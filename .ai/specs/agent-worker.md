# Spec: Agent Worker

## Purpose

A single Python script (`agent_worker.py`) that bridges a Todoist project and Claude Code. The worker polls for tasks, dispatches each one to the agent, and reports results back to Todoist. Tasks stay open for human review.

## Architecture

```
Todoist project          agent_worker.py          claude -p
(control plane)    --->  (poll + dispatch)   --->  (does work)
                   <---  (comment + label)         (saves output)
```

The worker is a dumb bridge. It passes the task title and description verbatim to Claude Code. The agent reads `CLAUDE.md` to decide which skill to use.

## Task Lifecycle

1. Poll project for open tasks (skip `agent-done` and `agent-failed` labels)
2. Comment "working on it" on the task
3. Dispatch to Claude Code via `claude -p` in a subprocess
4. On success: comment summary, add `agent-done` label
5. On failure: increment retry count via labels, retry next poll (up to 3 attempts)
6. On permanent failure: add `agent-failed` label
7. Human reviews output, closes task when satisfied

## Requirements

### Functional

- Poll a named Todoist project for tasks
- Pass task content to Claude Code as-is (no prompt engineering in the worker)
- Comment status updates on Todoist tasks (working, done, failed)
- Track retries via task labels (`agent-retry-N`), give up after N failures
- Support continuous polling (`--watch`) and single-run modes
- Stream tool-use progress to terminal in verbose mode
- Configurable per-task timeout, poll interval, and max retries

### Non-functional

- Single file, no `pyproject.toml` — runs via `uv run agent_worker.py`
- Inline PEP 723 script metadata for dependencies
- Tasks processed sequentially (one at a time per worker). Scale by running one worker per project.
- Graceful shutdown on Ctrl+C (kill child process group)
- Exponential backoff on Todoist API errors in watch mode
- Rotating log file in watch mode (10 MB cap)

## Security Model

Each task runs in a child subprocess with:

- `ANTHROPIC_API_KEY` stripped (agent uses Claude Code subscription, not API credits)
- `CLAUDECODE` stripped (prevents nested session conflicts)
- `start_new_session=True` (clean process group for signal handling)

No `--allowedTools` flags. The security boundary is process isolation, not framework-level permissions.

## CLI

```
uv run agent_worker.py --project "LinkedIn Writer"
uv run agent_worker.py --project "LinkedIn Writer" --watch --verbose
uv run agent_worker.py --project "LinkedIn Writer" --timeout 600
```

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | required | Todoist project name |
| `--watch` | off | Poll continuously |
| `--interval` | 30s | Poll interval |
| `--verbose` | off | Stream tool-use progress to terminal |
| `--timeout` | 300s | Per-task timeout |
| `--max-retries` | 3 | Attempts before giving up |

## Dependencies

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "todoist-api-python",
#     "python-dotenv",
# ]
# ///
```

## Configuration

`TODOIST_API_TOKEN` loaded via `python-dotenv` from `.env` at repo root, or from the environment directly.

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| No token | Log error, exit 1 |
| Project not found | Log error, exit 1 |
| `claude` not installed | Return failure, task stays open |
| Agent fails (non-zero exit) | Increment retry, comment error |
| Agent times out | Kill process group, increment retry |
| Todoist API error (watch mode) | Log, exponential backoff, continue |
| Comment API fails | Log warning, continue (non-fatal) |
