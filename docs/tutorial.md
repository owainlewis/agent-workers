# Background Agents: The Pattern

You don't need a framework to run AI agents in the background. You need three things: a task queue, a worker, and an agent. This tutorial walks through the pattern and a working implementation in ~100 lines of Python.

## The Problem

Most AI agent demos are interactive. You sit in a chat window, type a prompt, wait for the response.

That's fine for exploration. But real work happens in the background. You want to add a task to a list and have it done by the time you check back. The same way you'd delegate to an employee.

The automation tools that solve this (Zapier, Make, n8n) are designed for deterministic workflows. Step 1 triggers Step 2 triggers Step 3. They weren't built for work that requires judgement — writing, reviewing, researching, coding.

AI agents can do that kind of work. The missing piece is the control plane — how you assign tasks, how the agent picks them up, and how the output gets delivered somewhere useful.

## The Pattern

Three components. That's it.

```mermaid
graph LR
    A[Task Queue] -->|poll| B[Worker]
    B -->|dispatch| C[AI Agent]
    C -->|output| D[Delivery Target]
    B -->|"comment + tag"| A
```

**Task Queue** — Where you add tasks. This is the control plane. It's how you tell agents what to do without sitting in a chat window.

**Worker** — A small script that polls the task queue, builds a prompt from each task, dispatches it to the agent, and reports back with comments. Tasks stay open for human review.

**AI Agent** — The thing that actually does the work. In our case, Claude Code running with skill files that tell it how to write, review, and format content.

The worker is the glue. It's the only code you write. The task queue and the agent are off-the-shelf.

## Why a Task Queue?

You could trigger agents from a cron job, a webhook, or a Slack message. A task queue is better because:

1. **Visibility** — You can see what's pending, what's in progress, what's done. Open your phone, check the list. The agent comments on tasks as it works, so you always know the status.
2. **Human review** — Completed tasks stay open with an `agent-done` label. You review the output and close the task yourself. The agent does the work, you make the call.
3. **Retry** — Failed tasks stay open without the label. The worker picks them up on the next run.
4. **Prioritisation** — Reorder tasks, add due dates, flag urgent work.
5. **Input from anywhere** — Add tasks from your phone, a browser extension, an API, or voice.
6. **Familiar interface** — You already know how to use a to-do app.

Any task management tool works. Todoist, Linear, Asana, GitHub Issues, a database table. The pattern is the same.

## The Mental Model: Projects as Employees

Think of each project in your task queue as an employee with a specific job.

```mermaid
graph TD
    subgraph Todoist
        P1["LinkedIn Writer"]
        P2["Newsletter Writer"]
        P3["Code Reviewer"]
    end

    P1 -->|worker| A1["Claude Code<br/>(linkedin skill)"]
    P2 -->|worker| A2["Claude Code<br/>(newsletter skill)"]
    P3 -->|worker| A3["Claude Code<br/>(review skill)"]
```

Each project has its own worker process. Each worker dispatches to Claude Code with different skill files and permissions. The projects are independent — you can run one or all of them.

Adding a task is like walking up to an employee's desk and putting a sticky note on their monitor. The worker is the employee checking their desk for new notes.

## Implementation

This repo uses Todoist as the task queue and Claude Code as the agent. Here's how each piece works.

### 1. The Worker (~100 lines)

`tools/agent_worker.py` is the entire backend. It does four things:

```mermaid
sequenceDiagram
    participant T as Todoist
    participant W as Worker
    participant C as Claude Code
    participant O as Output

    W->>T: Get open tasks (skip agent-done)
    T-->>W: Task list

    loop Each task
        W->>T: Comment "working on it"
        W->>C: claude -p "prompt" --allowedTools [...]
        C->>C: Read skills, write content, self-review
        C->>O: Save to workspace/ + push to Airtable
        C-->>W: Exit code 0
        W->>T: Comment "done" + add agent-done label
    end

    Note over T: Human reviews and closes tasks
```

The worker doesn't know anything about LinkedIn posts, content strategy, or Airtable schemas. It just:

1. **Polls** — Fetches open tasks from a Todoist project (skips tasks labeled `agent-done`)
2. **Comments** — Posts "working on it" so you can see progress in Todoist
3. **Dispatches** — Runs `claude -p` with the prompt and scoped permissions
4. **Reports back** — Comments "done" with a summary, adds `agent-done` label
5. **Leaves the task open** — You review the output and close it when you're satisfied

That's the entire responsibility of the worker. The agent handles the actual work. You handle the final call.

### 2. The Agent (Claude Code + Skills)

Claude Code runs headless via `claude -p`. It receives:

- A prompt telling it what to do
- `--allowedTools` restricting what it can access
- `--model sonnet` for cost efficiency
- A working directory containing skill files and reference docs

The skill files (`.claude/skills/linkedin-post/SKILL.md`) are the real instructions. They define:

- How to write hooks, structure posts, match voice
- Reference files for brand, content strategy, examples
- An "autonomous mode" section — pick the best hook, skip waiting for input, self-review

The agent reads these files, follows the process, and saves output to `workspace/`.

### 3. The Security Model

Each dispatched task runs in a sandbox. The `--allowedTools` flag controls exactly what Claude Code can do:

```
--allowedTools Read Write Glob Grep "Bash(uv run:*)"
```

This means:
- **Read/Write/Glob/Grep** — File operations within the repo
- **Bash(uv run:\*)** — Only `uv run` commands (used for the Airtable CLI)

No unrestricted shell. No `rm`. No `curl`. No network access except through the Airtable CLI script. If the agent tries to run something outside this scope, it gets blocked.

This is important. You're running an AI agent unsupervised. Scoping its permissions is how you keep it safe.

### 4. The Delivery Target

After the agent finishes, output lands in two places:

- **`workspace/linkedin/`** — The draft file, saved locally
- **Airtable** — A record in the Content table with title, body, status, and platform

The Airtable push uses a CLI script (`.claude/skills/airtable/scripts/airtable.py`) that wraps the Airtable API. Claude Code calls it via `uv run`. No SDK, no API keys in the prompt — credentials live in `.env` and the script reads them.

## Running It

### Setup

```bash
# Clone the repo
git clone <repo-url>
cd background-agents

# Add your tokens
cp .env.example .env
# Edit .env with your TODOIST_API_TOKEN, AIRTABLE_API_KEY, AIRTABLE_BASE_ID

# Install the Todoist CLI (for adding tasks)
npm install -g @doist/todoist-cli
td auth login
```

### Create a project (your first "employee")

```bash
td project create --name "LinkedIn Writer"
```

### Add a task

```bash
td task add "Why background agents beat chatbots for real work" --project "LinkedIn Writer"
```

### Start the worker

```bash
# Process once and exit
uv run tools/agent_worker.py --project "LinkedIn Writer"

# Or watch continuously
uv run tools/agent_worker.py --project "LinkedIn Writer" --watch
```

The worker finds the task, comments "working on it", dispatches to Claude Code, then comments "done" and adds the `agent-done` label. The task stays open — check Todoist for the status comments and `workspace/linkedin/` for the draft. Close the task yourself once you've reviewed it.

### Multiple employees

Run multiple workers in separate terminals:

```bash
# Terminal 1
uv run tools/agent_worker.py --project "LinkedIn Writer" --watch

# Terminal 2
uv run tools/agent_worker.py --project "Newsletter Writer" --watch
```

Each one watches its own project, dispatches with its own skills and permissions.

## Adapting the Pattern

### Different task queues

The pattern works with anything that has an API:

| Queue | How to poll | How to mark done |
|-------|-------------|-----------------|
| Todoist | `todoist-api-python` SDK | Add label + comment |
| Linear | GraphQL API | Move to "Review" status |
| GitHub Issues | `gh` CLI or REST API | Add label + comment |
| Airtable | Filter by status field | Update status to "review" |
| PostgreSQL | `SELECT WHERE status = 'pending'` | `UPDATE SET status = 'review'` |

Replace the `TodoistAPI` calls in the worker and the rest stays the same.

### Different agents

Claude Code is one option. The dispatch function just needs to run a subprocess:

```python
subprocess.run(["claude", "-p", prompt, ...])
```

You could swap in any agent that accepts a prompt via CLI:
- `codex` (OpenAI)
- A custom script that calls an API
- Another Claude Code instance with different skills

### Different outputs

The delivery target is whatever the agent's skill files tell it to do. Change the skill instructions and the output changes:

- Write to a database instead of Airtable
- Post directly to LinkedIn via API
- Create a PR on GitHub
- Send a Slack message

The worker doesn't care. It just dispatches and reports back.

## Why This Works

The key insight is **separation of concerns**:

- **You** decide what needs doing (add a task) and what ships (review + close)
- **The worker** handles lifecycle (poll, dispatch, comment, label)
- **The agent** handles judgement (writing, reviewing, deciding)
- **Skill files** encode your standards (voice, structure, quality)

The human stays in the loop where it matters — at the review step. The agent does the work. You make the final call. This is important: you're not removing yourself from the process, you're removing yourself from the generation step.

No framework. No orchestration platform. No YAML configs. A to-do app, a Python script, and an AI agent with good instructions.

The to-do app is the control plane you already use. The Python script is ~100 lines you can read in 5 minutes. The skill files are markdown documents that encode how you want work done. Everything is visible, editable, and debuggable.

That's the whole system.
