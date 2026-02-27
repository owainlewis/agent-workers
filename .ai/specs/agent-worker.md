# Spec: Agent Worker

## What it does

A single Python script (`tools/agent_worker.py`) that polls a Todoist project for tasks and dispatches each one to Claude Code for execution. The worker handles the Todoist lifecycle (poll, comment, dispatch, label). Claude Code handles the actual work. Tasks stay open for human review.

## Architecture

```
Todoist project (e.g. "LinkedIn Writer")
        │
        ▼
┌─────────────────┐    subprocess.run     ┌─────────────────┐
│  agent_worker.py │ ──────────────────▶  │   claude -p      │
│  (Python, ~100L) │                      │   (does work)    │
└─────────────────┘                      └─────────────────┘
        │                                         │
        ▼                                         ▼
  comment + label                         saves output to
  (task stays open)                      workspace/ + Airtable
```

## Task Lifecycle

1. Worker polls project for open tasks without the `agent-done` label
2. For each task: comment "working on it"
3. Dispatch to Claude Code via `claude -p`
4. On success: comment "done" with summary, add `agent-done` label, leave task open
5. On failure: comment "failed", leave task open without label (will retry next poll)
6. Human reviews output, closes task when satisfied

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

## SDK Gotchas

### Pagination

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

### Method names

- Use `complete_task(task_id=...)` not `close_task` (doesn't exist)
- Use `add_comment(content=..., task_id=...)` for task comments
- Use `update_task(task_id=..., labels=[...])` to add labels

### Nested sessions

When running from within a Claude Code session, the `CLAUDECODE` env var must be unset before spawning `claude -p`, or it will refuse to start. Strip it from the subprocess environment:

```python
env = os.environ.copy()
env.pop("CLAUDECODE", None)
```

## Functions

### `find_project_id(api, name) -> str | None`

Iterates all Todoist projects (paginated). Returns the `id` of the first project matching `name` (case-insensitive). Returns `None` if not found.

### `comment(api, task_id, message)`

Adds a comment to a Todoist task. Wraps `api.add_comment()` with a try/except so comment failures don't crash the worker.

### `build_prompt(title, description) -> str`

Constructs the prompt string sent to Claude Code. Takes the Todoist task title and optional description. The prompt tells Claude to:

1. Read the LinkedIn skill file and follow Autonomous Mode
2. Read brand/pillars/offers reference files
3. Generate hooks, pick the best, write full post, self-review
4. Save draft to `workspace/linkedin/`
5. Push to Airtable if credentials exist in `.env`

The prompt is a plain f-string. No templating library needed.

### `dispatch_task(title, description) -> tuple[bool, str]`

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
- `--output-format json` — stdout is JSON with `cost_usd` and `result` fields on success
- Strips `CLAUDECODE` env var to allow nested sessions
- Returns `(True, summary)` on exit code 0, `(False, error_msg)` on failure or timeout

**Allowed tools (security scope):**
- `Read`, `Write`, `Glob`, `Grep` — file operations only
- `Bash(uv run:*)` — only uv commands (for the Airtable CLI script)

No unrestricted Bash. Claude cannot run arbitrary shell commands.

### `run_once(api, project_id) -> int`

Fetches all open tasks in the project (paginated). For each task:

1. Skip if `agent-done` label is present (already processed, waiting for human review)
2. Comment "working on it"
3. Call `dispatch_task(task.content, task.description)`
4. On success: comment "done" with summary, add `agent-done` label via `update_task`
5. On failure: comment "failed" with error, leave task open without label (retry next run)

Returns count of successfully processed tasks.

### `main()`

Entry point. Handles:

1. **Token loading** — check `TODOIST_API_TOKEN` env var, fallback to `.env` file
2. **Project lookup** — call `find_project_id(api, args.project)`, exit with error if not found
3. **CLI args** via argparse:
   - `--project NAME` (required): Todoist project name to watch
   - `--watch`: loop `run_once` with `time.sleep(interval)`, catch `KeyboardInterrupt`
   - `--interval N`: poll interval in seconds (default 30)

## CLI Interface

```
usage: agent_worker.py [-h] --project PROJECT [--watch] [--interval INTERVAL]

  --project PROJECT    Todoist project name to watch (e.g. 'LinkedIn Writer')
  --watch              Poll continuously
  --interval INTERVAL  Poll interval in seconds (default: 30)
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No token | Print error to stderr, exit 1 |
| Project not found | Print error to stderr, exit 1 |
| Claude Code not installed | Comment "failed" on task, return `False` (task stays open) |
| Claude Code fails (non-zero exit) | Comment "failed" with stderr, return `False` |
| Claude Code times out | Comment "failed" with timeout message, return `False` |
| No pending tasks | Print "No pending tasks.", return 0 |
| Comment API fails | Print warning, continue (non-fatal) |

Failed tasks stay open without the `agent-done` label — the worker retries them on the next poll.

## Output

The worker prints to stdout:

```
Watching project: LinkedIn Writer (id: 6g5RpvCw9fVxJGPw)
No pending tasks.
```

Or when processing:

```
Watching project: LinkedIn Writer (id: 6g5RpvCw9fVxJGPw)

Task: Why background agents beat chatbots
  Dispatching to Claude Code...
  Done. Cost: $0.12
  Done. Left open for review.
```
