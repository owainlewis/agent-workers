# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "todoist-api-python",
# ]
# ///
"""
Background agent worker — polls Todoist for tasks and dispatches them to Claude Code.

Usage:
    uv run tools/agent_worker.py              # process once and exit
    uv run tools/agent_worker.py --watch      # poll every 30s
    uv run tools/agent_worker.py --watch --interval 60
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from todoist_api_python.api import TodoistAPI

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_TIMEOUT = 300  # 5 minutes per task


def get_agent_project_id(api: TodoistAPI) -> str | None:
    """Find the 'Agent' project in Todoist."""
    for project in api.get_projects():
        if project.name.lower() == "agent":
            return project.id
    return None


def build_prompt(title: str, description: str | None) -> str:
    """Build the prompt that Claude Code will execute."""
    topic = title
    if description:
        topic += f"\n\nContext: {description}"

    return f"""Write a LinkedIn post about this topic using the linkedin-post skill.

Topic: {topic}

Instructions:
1. Read .claude/skills/linkedin-post/SKILL.md and follow the Autonomous Mode instructions.
2. Read reference/brand.md, reference/pillars.md, reference/offers.md for voice and positioning.
3. Generate 3 hooks, pick the strongest, write the full post, self-review.
4. Save the final draft to workspace/linkedin/ with a descriptive filename.
5. Push the draft to Airtable using .claude/skills/airtable/scripts/airtable.py if .env has credentials.
   Create a record in the "Content" table with fields: Title, Body, Status="draft", Platform="LinkedIn".
"""


def dispatch_task(title: str, description: str | None) -> bool:
    """Invoke Claude Code with the task prompt. Returns True on success."""
    prompt = build_prompt(title, description)

    allowed_tools = [
        "Read",
        "Write",
        "Glob",
        "Grep",
        "Bash(uv run:*)",
    ]

    cmd = [
        "claude",
        "-p", prompt,
        "--model", "sonnet",
        "--output-format", "json",
    ]
    for tool in allowed_tools:
        cmd.extend(["--allowedTools", tool])

    print(f"  Dispatching to Claude Code...")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=TASK_TIMEOUT,
        )
        if result.returncode == 0:
            try:
                output = json.loads(result.stdout)
                print(f"  Done. Cost: ${output.get('cost_usd', '?')}")
            except json.JSONDecodeError:
                print(f"  Done.")
            return True
        else:
            print(f"  Failed (exit {result.returncode})")
            if result.stderr:
                print(f"  stderr: {result.stderr[:500]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  Timed out after {TASK_TIMEOUT}s")
        return False
    except FileNotFoundError:
        print("  Error: 'claude' not found. Is Claude Code installed?")
        return False


def run_once(api: TodoistAPI, project_id: str) -> int:
    """Process all pending tasks in the Agent project. Returns count processed."""
    tasks = api.get_tasks(project_id=project_id)

    if not tasks:
        print("No pending tasks.")
        return 0

    processed = 0
    for task in tasks:
        print(f"\nTask: {task.content}")
        success = dispatch_task(task.content, task.description)
        if success:
            api.close_task(task_id=task.id)
            print(f"  Marked complete in Todoist.")
            processed += 1
        else:
            print(f"  Skipped (will retry next run).")

    return processed


def main():
    parser = argparse.ArgumentParser(description="Background agent worker")
    parser.add_argument("--watch", action="store_true", help="Poll continuously")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")
    args = parser.parse_args()

    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        env_path = REPO_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("TODOIST_API_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip("'\"")
                    break

    if not token:
        print("Error: TODOIST_API_TOKEN not set. Add it to .env or export it.", file=sys.stderr)
        sys.exit(1)

    api = TodoistAPI(token)

    project_id = get_agent_project_id(api)
    if not project_id:
        print("Error: No 'Agent' project found in Todoist. Create one first.", file=sys.stderr)
        sys.exit(1)

    print(f"Agent project found (id: {project_id})")

    if args.watch:
        print(f"Watching every {args.interval}s. Ctrl+C to stop.\n")
        while True:
            try:
                run_once(api, project_id)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
    else:
        run_once(api, project_id)


if __name__ == "__main__":
    main()
