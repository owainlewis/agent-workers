# Background Agents

A secure, reliable alternative to OpenClaw in ~100 lines of Python.

You assign tasks from your phone. Agents do the work in the background. You review the results when you're ready.

## Three Levels of Working With AI

Most people are stuck at level one. This repo gets you to level two.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Level 1: Micromanaging                                         │
│  You sit in a chat window prompting back and forth.             │
│  You're there the whole time. Like standing over someone's      │
│  shoulder telling them what to do line by line.                  │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Level 2: Delegating  ◄── this repo                             │
│  You hand off a task and walk away. The agent does the work     │
│  in the background, reports back, and you review the result.    │
│  Like giving a brief to a team member.                          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Level 3: Running a Team                                        │
│  Multiple agents collaborating — one researches, another        │
│  writes, another reviews. The frontier.                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

```
┌─────────────────┐        poll         ┌──────────────────┐       invoke       ┌─────────────┐
│   CONTROL PLANE │  ◄────────────────  │   AGENT WORKER   │  ───────────────►  │ CLAUDE CODE │
│   (Todoist)     │   Todoist SDK       │   (Python script) │   claude -p        │ (does work) │
│                 │                     │                   │                    │             │
│  You add tasks  │  ──────────────────►│  Polls for tasks  │  ◄───────────────  │ Runs skills │
│  from anywhere  │   comment + label   │  Dispatches work  │   returns results  │ Saves output│
└─────────────────┘                     └──────────────────┘                    └─────────────┘
       ▲                                                                              │
       │                            ┌──────────────┐                                  │
       └────── you review ────────  │   RESULTS    │  ◄──────── pushes output ────────┘
                                    │  (Airtable)  │
                                    └──────────────┘
```

Three components:

1. **Control plane (Todoist)** — You add tasks from your phone, laptop, anywhere. Each task is a job for the agent.
2. **Worker (Python script)** — Polls Todoist for new tasks. When it finds one, it passes the task straight to Claude Code. The polling is plain Python — zero tokens, zero cost. The agent only spins up when there's real work.
3. **Agent (Claude Code)** — Receives the task, does the work, saves output. The worker comments "done" on the ticket and tags it. The task stays open for you to review.

The worker is a dumb bridge. It doesn't decide what to do — it just passes your task to the agent. Claude Code reads its `CLAUDE.md` to figure out which skill to use. The intelligence lives in the agent, not the worker.

## OpenClaw vs This Approach

|  | OpenClaw | This repo |
|--|----------|-----------|
| **Control plane** | Custom Telegram bot | Todoist — battle-tested UI on every device |
| **Task queue** | Internal database / Redis | Todoist project — visual and auditable |
| **Worker** | Dockerised orchestration | Python script (~100 lines) |
| **Security** | Framework-level permissions | OS-level `--allowedTools` per task |
| **Cost model** | Always running | Polls with plain code, agent only when needed |

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/owainlewis/agent-workers.git
cd agent-workers
cp .env.example .env
# Add TODOIST_API_TOKEN (required), AIRTABLE_API_KEY + AIRTABLE_BASE_ID (optional)

# 2. Add a task to Todoist
# Create a project called "Agent" in Todoist, then add a task via the app or CLI

# 3. Run the worker
uv run tools/agent_worker.py --project "Agent"
```

The worker finds the task, comments "working on it", dispatches to Claude Code, then comments "done" and adds the `agent-done` label. The task stays open — you review the output and close it yourself.

### Continuous polling

```bash
uv run tools/agent_worker.py --project "Agent" --watch
```

### Verbose mode (real-time progress on tickets)

```bash
uv run tools/agent_worker.py --project "Agent" --watch --verbose
```

In verbose mode, the worker posts live progress updates to the Todoist task as the agent works — reading files, writing drafts, pushing to Airtable.

## Multiple Agents

Each Todoist project is an employee. Run one worker per project:

```bash
uv run tools/agent_worker.py --project "LinkedIn Writer" --watch
uv run tools/agent_worker.py --project "Code Reviewer" --watch
uv run tools/agent_worker.py --project "Research" --watch
```

Your task manager becomes a dispatch centre for a team of agents.

## The Security Model

Every task runs with scoped permissions via `--allowedTools`:

```
--allowedTools Read Write Glob Grep "Bash(uv run:*)"
```

The agent can read and write files, search the codebase, and run `uv run` commands (for the Airtable CLI). No unrestricted shell, no network access, no `rm`. OpenClaw gives the agent access to everything. We give it access to exactly what the task needs.

## Trust and Verification

The agent drafts. You approve. The agent never publishes, merges, or sends anything directly. Output lands in `workspace/` and Airtable as a draft. You review and ship.

Start with low-stakes tasks — content drafts, research summaries, code review flags. Expand scope as you build confidence.

## Repo Structure

```
tools/agent_worker.py          # The worker (~100 lines)
tools/youtube.py               # YouTube transcript tool
CLAUDE.md                      # Agent instructions + skill routing
.claude/skills/linkedin-post/  # LinkedIn writing skill + references
.claude/skills/airtable/       # Airtable CLI skill
.claude/agents/                # Agent definitions
reference/                     # Brand voice, pillars, offers
workspace/                     # Agent output lands here
docs/tutorial.md               # Full tutorial
```

## Read More

**[Full tutorial →](docs/tutorial.md)** — Deep dive into the pattern, the worker design, adapting to different task queues and agents.
