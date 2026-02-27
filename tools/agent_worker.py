# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "todoist-api-python",
# ]
# ///
"""
Background agent worker — polls a Todoist project for tasks and dispatches them to Claude Code.

Each Todoist project is an employee. Start a worker per project.

Usage:
    uv run tools/agent_worker.py --project "LinkedIn Writer"
    uv run tools/agent_worker.py --project "LinkedIn Writer" --watch
    uv run tools/agent_worker.py --project "LinkedIn Writer" --watch --interval 60
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


# --- Todoist helpers ---

def find_project_id(api: TodoistAPI, name: str) -> str | None:
    """Find a Todoist project by name (case-insensitive)."""
    target = name.lower()
    for page in api.get_projects():
        for project in page:
            if project.name.lower() == target:
                return project.id
    return None


def comment(api: TodoistAPI, task_id: str, message: str):
    """Add a comment to a Todoist task."""
    try:
        api.add_comment(content=message, task_id=task_id)
    except Exception as e:
        print(f"  Warning: failed to add comment: {e}")


# --- Prompt + dispatch ---

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


def dispatch_task(title: str, description: str | None) -> tuple[bool, str]:
    """Invoke Claude Code with the task prompt. Returns (success, summary)."""
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
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)  # allow spawning claude from within a claude session
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=TASK_TIMEOUT,
            env=env,
        )
        if result.returncode == 0:
            cost = "?"
            result_text = ""
            try:
                output = json.loads(result.stdout)
                cost = output.get("cost_usd", "?")
                result_text = output.get("result", "")
            except json.JSONDecodeError:
                pass
            print(f"  Done. Cost: ${cost}")
            summary = f"Cost: ${cost}"
            if result_text:
                # Truncate to keep comment readable
                preview = result_text[:500]
                if len(result_text) > 500:
                    preview += "..."
                summary += f"\n\n{preview}"
            return True, summary
        else:
            error_msg = result.stderr[:500] if result.stderr else "Unknown error"
            print(f"  Failed (exit {result.returncode})")
            if result.stderr:
                print(f"  stderr: {error_msg}")
            return False, f"Failed (exit {result.returncode}): {error_msg}"
    except subprocess.TimeoutExpired:
        print(f"  Timed out after {TASK_TIMEOUT}s")
        return False, f"Timed out after {TASK_TIMEOUT}s"
    except FileNotFoundError:
        print("  Error: 'claude' not found. Is Claude Code installed?")
        return False, "'claude' command not found"


# --- Main loop ---

def run_once(api: TodoistAPI, project_id: str) -> int:
    """Process all pending tasks. Returns count processed."""
    tasks = []
    for page in api.get_tasks(project_id=project_id):
        tasks.extend(page)

    if not tasks:
        print("No pending tasks.")
        return 0

    processed = 0
    for task in tasks:
        print(f"\nTask: {task.content}")

        # Comment: picked up
        comment(api, task.id, "🤖 Agent picked up this task. Working on it now...")

        success, summary = dispatch_task(task.content, task.description)

        if success:
            # Comment: done
            comment(api, task.id, f"✅ Done.\n\n{summary}")
            api.complete_task(task_id=task.id)
            print(f"  Marked complete in Todoist.")
            processed += 1
        else:
            # Comment: failed
            comment(api, task.id, f"❌ Failed. Will retry next run.\n\n{summary}")
            print(f"  Skipped (will retry next run).")

    return processed


def main():
    parser = argparse.ArgumentParser(description="Background agent worker")
    parser.add_argument("--project", required=True, help="Todoist project name to watch (e.g. 'LinkedIn Writer')")
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

    project_id = find_project_id(api, args.project)
    if not project_id:
        print(f"Error: No '{args.project}' project found in Todoist. Create one first.", file=sys.stderr)
        sys.exit(1)

    print(f"Watching project: {args.project} (id: {project_id})")

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
