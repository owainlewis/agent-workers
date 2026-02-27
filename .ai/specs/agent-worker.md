# Spec: Agent Worker

## What it does

A single Python script (`tools/agent_worker.py`) that polls a Todoist project for tasks and dispatches each one to Claude Code for execution. The worker handles the Todoist lifecycle (poll, dispatch, close). Claude Code handles the actual work.

## Architecture

```
Todoist "Agent" project
        │
        ▼
┌─────────────────┐    subprocess.run     ┌─────────────────┐
│  agent_worker.py │ ──────────────────▶  │   claude -p      │
│  (Python, ~100L) │                      │   (does work)    │
└─────────────────┘                      └─────────────────┘
        │                                         │
        ▼                                         ▼
  close task in                           saves output to
    Todoist                              workspace/ + Airtable
```

## Dependencies

Single inline dependency via uv script metadata:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "todoist-api-python",
# ]
# ///
```

No `pyproject.toml` needed. Run with `uv run tools/agent_worker.py`.

## Configuration

Token loaded from environment variable `TODOIST_API_TOKEN`. Fallback: parse `.env` file at repo root.

```
TODOIST_API_TOKEN=84223eff0b...
```

## SDK Gotcha

`todoist-api-python` returns a `ResultsPaginator` from `get_projects()` and `get_tasks()`. This yields **pages** (lists of objects), not individual items. You must iterate two levels:

```python
for page in api.get_projects():
    for project in page:
        # project.name, project.id
```

Same pattern for `get_tasks(project_id=...)`:

```python
tasks = []
for page in api.get_tasks(project_id=project_id):
    tasks.extend(page)
```

## Functions

### `get_agent_project_id(api) -> str | None`

Iterates all Todoist projects (paginated). Returns the `id` of the first project where `name.lower() == "agent"`. Returns `None` if not found.

### `build_prompt(title, description) -> str`

Constructs the prompt string sent to Claude Code. Takes the Todoist task title and optional description. The prompt tells Claude to:

1. Read the LinkedIn skill file and follow Autonomous Mode
2. Read brand/pillars/offers reference files
3. Generate hooks, pick the best, write full post, self-review
4. Save draft to `workspace/linkedin/`
5. Push to Airtable if credentials exist in `.env`

The prompt is a plain f-string. No templating library needed.

### `dispatch_task(title, description) -> bool`

Builds the prompt via `build_prompt`, then runs Claude Code as a subprocess:

```python
cmd = [
    "claude",
    "-p", prompt,
    "--model", "sonnet",
    "--output-format", "json",
]
for tool in allowed_tools:
    cmd.extend(["--allowedTools", tool])
```

**Key details:**
- `subprocess.run` with `cwd` set to repo root so skill paths resolve
- `capture_output=True, text=True` — capture stdout/stderr as strings
- `timeout=300` (5 minutes per task)
- `--output-format json` — stdout is JSON with `cost_usd` field on success
- Returns `True` on exit code 0, `False` on failure or timeout

**Allowed tools (security scope):**
- `Read`, `Write`, `Glob`, `Grep` — file operations only
- `Bash(uv run:*)` — only uv commands (for the Airtable CLI script)

No unrestricted Bash. Claude cannot run arbitrary shell commands.

### `run_once(api, project_id) -> int`

Fetches all open tasks in the Agent project (paginated). For each task:

1. Print task title
2. Call `dispatch_task(task.content, task.description)`
3. On success: `api.close_task(task_id=task.id)` and increment counter
4. On failure: skip (task stays open for next run)

Returns count of successfully processed tasks.

### `main()`

Entry point. Handles:

1. **Token loading** — check `TODOIST_API_TOKEN` env var, fallback to `.env` file
2. **Project lookup** — call `get_agent_project_id`, exit with error if not found
3. **CLI args** via argparse:
   - No flags: run `run_once` and exit
   - `--watch`: loop `run_once` with `time.sleep(interval)`, catch `KeyboardInterrupt`
   - `--interval N`: poll interval in seconds (default 30)

## CLI Interface

```
usage: agent_worker.py [-h] [--watch] [--interval INTERVAL]

  --watch              Poll continuously
  --interval INTERVAL  Poll interval in seconds (default: 30)
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No token | Print error to stderr, exit 1 |
| No "Agent" project | Print error to stderr, exit 1 |
| Claude Code not installed | Print error, return `False` (task stays open) |
| Claude Code fails (non-zero exit) | Print exit code + first 500 chars of stderr, return `False` |
| Claude Code times out | Print timeout message, return `False` |
| No pending tasks | Print "No pending tasks.", return 0 |

Failed tasks are never closed in Todoist — they stay open for the next run.

## Output

The worker prints to stdout:

```
Agent project found (id: 6g5RpvCw9fVxJGPw)
No pending tasks.
```

Or when processing:

```
Agent project found (id: 6g5RpvCw9fVxJGPw)

Task: LinkedIn post: why background agents beat chatbots
  Dispatching to Claude Code...
  Done. Cost: $0.12
  Marked complete in Todoist.
```
