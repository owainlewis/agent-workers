# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "todoist-api-python",
# ]
# ///
"""
Background agent worker — polls a Todoist project for tasks and dispatches them to Claude Code.

Each Todoist project is an employee. Start a worker per project.
The worker knows nothing about what the agent does. It passes the ticket
as-is and lets Claude Code decide how to handle it using its skills and CLAUDE.md.

Usage:
    uv run tools/agent_worker.py --project "LinkedIn Writer"
    uv run tools/agent_worker.py --project "LinkedIn Writer" --watch --verbose
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from todoist_api_python.api import TodoistAPI

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_TIMEOUT = 300  # 5 minutes per task
MAX_RETRIES = 3  # give up after this many failures
RETRY_PREFIX = "agent-retry-"  # labels: agent-retry-1, agent-retry-2, etc.


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


def _describe_tool_use(name: str, input_data: dict) -> str | None:
    """Turn a tool_use event into a short human-readable status line, or None to skip."""
    if name == "Read":
        path = input_data.get("file_path", "")
        short = path.replace(str(REPO_ROOT) + "/", "")
        if "skill" in short.lower() or "SKILL" in short:
            return f"📖 Reading skill: {short}"
        if "reference" in short.lower():
            return f"📖 Reading reference: {short}"
        return f"📖 Reading {short}"
    if name == "Write":
        path = input_data.get("file_path", "")
        short = path.replace(str(REPO_ROOT) + "/", "")
        return f"✍️ Writing {short}"
    if name == "Bash":
        cmd = input_data.get("command", "")
        if "airtable" in cmd.lower():
            return "📤 Pushing to Airtable"
        if "youtube" in cmd.lower():
            return "🎬 Fetching YouTube transcript"
        return f"🔧 Running command"
    if name == "Glob":
        return f"🔍 Searching files"
    if name == "Grep":
        return f"🔍 Searching content"
    return None


def dispatch(title: str, description: str | None, *,
             verbose: bool = False, api: TodoistAPI | None = None,
             task_id: str | None = None) -> tuple[bool, str]:
    """Pass the ticket to Claude Code. Returns (success, summary)."""
    prompt = title
    if description:
        prompt += f"\n\n{description}"

    output_format = "stream-json" if verbose else "json"
    cmd = ["claude", "-p", prompt, "--model", "sonnet", "--output-format", output_format]
    if verbose:
        cmd.append("--verbose")

    print("  Dispatching to Claude Code...")
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("ANTHROPIC_API_KEY", None)  # use subscription plan, not API credits

    # Use Popen for both modes so we can kill the child on Ctrl+C
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, start_new_session=True,
        )
    except FileNotFoundError:
        return False, "'claude' command not found"

    seen = set()  # deduplicate verbose output
    result_text = ""

    def _kill_child():
        """Kill the child process group."""
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass

    try:
        if verbose:
            # Stream events to terminal only (not Todoist)
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_use":
                            desc = _describe_tool_use(block["name"], block.get("input", {}))
                            if desc and desc not in seen:
                                seen.add(desc)
                                print(f"  {desc}")

                if event.get("type") == "result":
                    result_text = event.get("result", "")

        proc.wait(timeout=TASK_TIMEOUT)

        if not verbose:
            stdout = proc.stdout.read()
            try:
                output = json.loads(stdout)
                result_text = output.get("result", "")
            except (json.JSONDecodeError, ValueError):
                pass

    except KeyboardInterrupt:
        print("\n  Interrupted — killing agent...")
        _kill_child()
        raise
    except subprocess.TimeoutExpired:
        _kill_child()
        return False, f"Timed out after {TASK_TIMEOUT}s"

    stderr_text = proc.stderr.read() if proc.stderr else ""

    if proc.returncode == 0:
        print("  Done.")
        summary = result_text[:500] + ("..." if len(result_text) > 500 else "") if result_text else "Completed."
        return True, summary
    else:
        # Build a useful error message from everything we have
        error_parts = [f"Exit code {proc.returncode}"]
        if stderr_text.strip():
            error_parts.append(f"stderr: {stderr_text.strip()[:500]}")
        if result_text:
            error_parts.append(f"output: {result_text[:500]}")

        error_msg = "\n".join(error_parts)
        print(f"  Failed:\n  {error_msg.replace(chr(10), chr(10) + '  ')}")
        return False, error_msg


def _get_retry_count(labels: list[str]) -> int:
    """Extract retry count from task labels."""
    for label in labels:
        if label.startswith(RETRY_PREFIX):
            try:
                return int(label[len(RETRY_PREFIX):])
            except ValueError:
                pass
    return 0


def _set_retry_label(api: TodoistAPI, task_id: str, labels: list[str], count: int):
    """Update task labels with new retry count."""
    # Remove old retry labels
    new_labels = [l for l in labels if not l.startswith(RETRY_PREFIX)]
    new_labels.append(f"{RETRY_PREFIX}{count}")
    api.update_task(task_id=task_id, labels=new_labels)


def run_once(api: TodoistAPI, project_id: str, *, verbose: bool = False,
             max_retries: int = MAX_RETRIES) -> int:
    """Process all pending tasks. Returns count processed."""
    tasks = []
    for page in api.get_tasks(project_id=project_id):
        tasks.extend(page)

    if not tasks:
        print("No pending tasks.")
        return 0

    processed = 0
    for task in tasks:
        labels = task.labels or []

        if "agent-done" in labels or "agent-failed" in labels:
            continue

        retries = _get_retry_count(labels)
        if retries >= max_retries:
            continue  # already gave up, skip silently

        retry_info = f" (attempt {retries + 1}/{max_retries})" if retries > 0 else ""
        print(f"\nTask: {task.content}{retry_info}")
        comment(api, task.id, f"Working on it...{retry_info}")

        success, summary = dispatch(
            task.content, task.description,
            verbose=verbose, api=api, task_id=task.id,
        )

        if success:
            comment(api, task.id, f"Done. Ready for review.\n\n{summary}")
            # Clean up retry labels and mark done
            done_labels = [l for l in labels if not l.startswith(RETRY_PREFIX)]
            done_labels.append("agent-done")
            api.update_task(task_id=task.id, labels=done_labels)
            print("  Done. Left open for review.")
            processed += 1
        else:
            retries += 1
            if retries >= max_retries:
                comment(api, task.id, f"Failed after {max_retries} attempts. Giving up.\n\n{summary}")
                failed_labels = [l for l in labels if not l.startswith(RETRY_PREFIX)]
                failed_labels.append("agent-failed")
                api.update_task(task_id=task.id, labels=failed_labels)
                print(f"  Failed permanently after {max_retries} attempts.")
            else:
                comment(api, task.id, f"Failed (attempt {retries}/{max_retries}). Will retry.\n\n{summary}")
                _set_retry_label(api, task.id, labels, retries)
                print(f"  Failed (attempt {retries}/{max_retries}). Will retry next run.")

    return processed


def main():
    parser = argparse.ArgumentParser(description="Background agent worker")
    parser.add_argument("--project", required=True, help="Todoist project name to watch")
    parser.add_argument("--watch", action="store_true", help="Poll continuously")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    parser.add_argument("--verbose", action="store_true",
                        help="Stream agent progress to terminal")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                        help=f"Give up after N failures (default {MAX_RETRIES})")
    args = parser.parse_args()

    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        env_path = REPO_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.strip().startswith("TODOIST_API_TOKEN="):
                    token = line.strip().split("=", 1)[1].strip().strip("'\"")
                    break

    if not token:
        print("Error: TODOIST_API_TOKEN not set. Add it to .env or export it.", file=sys.stderr)
        sys.exit(1)

    api = TodoistAPI(token)
    project_id = find_project_id(api, args.project)
    if not project_id:
        print(f"Error: No '{args.project}' project found in Todoist.", file=sys.stderr)
        sys.exit(1)

    print(f"Watching project: {args.project} (id: {project_id})")
    if args.verbose:
        print("Verbose mode: streaming agent progress to terminal")

    max_retries = args.max_retries

    try:
        if args.watch:
            print(f"Polling every {args.interval}s. Ctrl+C to stop.\n")
            while True:
                run_once(api, project_id, verbose=args.verbose, max_retries=max_retries)
                time.sleep(args.interval)
        else:
            run_once(api, project_id, verbose=args.verbose, max_retries=max_retries)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
