# Background Agents

Replace complex automation tools with ~100 lines of Python and Claude Code.

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌───────────┐
│   Todoist    │────▶│ agent_worker │────▶│ Claude Code │────▶│ Airtable  │
│ (add task)   │     │  (polls)     │     │  (does work) │     │ (output)  │
└─────────────┘     └──────────────┘     └─────────────┘     └───────────┘
```

**Pattern**: Todoist is the control plane. The Python worker polls for tasks. Claude Code does the actual work. Output lands in Airtable.

**First demo**: Add a Todoist task → worker picks it up → Claude Code writes a LinkedIn post → pushes draft to Airtable → marks task complete.

## Setup

1. Clone and configure:
```bash
git clone <repo-url>
cd background-agents
cp .env.example .env
# Fill in your tokens
```

2. Create an "Agent" project in Todoist (the worker looks for this by name).

3. Required tokens in `.env`:
- `TODOIST_API_TOKEN` — [Get one here](https://todoist.com/prefs/integrations)
- `AIRTABLE_API_KEY` — [Create a PAT](https://airtable.com/create/tokens)
- `AIRTABLE_BASE_ID` — Find in your Airtable base URL

## Usage

### Run once (process pending tasks and exit)
```bash
uv run tools/agent_worker.py
```

### Watch mode (poll every 30s)
```bash
uv run tools/agent_worker.py --watch
```

### Custom interval
```bash
uv run tools/agent_worker.py --watch --interval 60
```

## How It Works

1. Worker polls the "Agent" project in Todoist for open tasks
2. For each task, it builds a prompt and invokes `claude -p` with scoped `--allowedTools`
3. Claude Code reads the LinkedIn skill files, writes a post, self-reviews, saves to `workspace/linkedin/`
4. If Airtable credentials exist, Claude pushes the draft as a record
5. Worker marks the Todoist task complete

## Architecture

- **`tools/agent_worker.py`** — The ~100 line Python worker. Uses `todoist-api-python` SDK. Dispatches to Claude Code via `subprocess.run`.
- **`.claude/skills/linkedin-post/`** — LinkedIn post writing skill with autonomous mode support.
- **`.claude/skills/airtable/`** — Airtable CLI for pushing content records.
- **`.claude/agents/`** — Agent definitions (writer + reviewer).
- **`reference/`** — Brand voice, content pillars, offers.

## Security Model

Each dispatched task runs with scoped `--allowedTools`:
- `Read`, `Write`, `Glob`, `Grep` — file operations
- `Bash(uv run:*)` — only uv commands (for Airtable CLI)

No unrestricted shell access. No network access beyond Airtable API calls through the CLI.
