# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "todoist-api-python",
#     "python-dotenv",
# ]
# ///
"""
Background agent worker — polls a Todoist project for tasks and dispatches them to Claude Code.

Each Todoist project is an employee. Start a worker per project.
The worker knows nothing about what the agent does. It passes the ticket
as-is and lets Claude Code decide how to handle it using its skills and CLAUDE.md.

Usage:
    uv run agent_worker.py --project "LinkedIn Writer"
    uv run agent_worker.py --project "LinkedIn Writer" --watch --verbose
    uv run agent_worker.py --project "LinkedIn Writer" --watch --timeout 600
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_TIMEOUT = 300  # 5 minutes per task
MAX_RETRIES = 3  # give up after this many failures

log = logging.getLogger("agent_worker")
log.propagate = False  # prevent third-party DEBUG noise via root logger


def setup_logging(watch: bool = False, verbose: bool = False):
    """Configure logging — console always, rotating file handler in --watch mode."""
    log.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(console)

    if watch:
        fh = RotatingFileHandler(
            REPO_ROOT / "agent_worker.log", maxBytes=10 * 1024 * 1024, backupCount=3,
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
        log.addHandler(fh)


class TodoistQueue:
    """Wraps all Todoist API calls for the worker."""

    RETRY_PREFIX = "agent-retry-"

    def __init__(self, token: str):
        self.api = TodoistAPI(token)

    def find_project_id(self, name: str) -> str | None:
        """Find a Todoist project by name (case-insensitive)."""
        target = name.lower()
        for page in self.api.get_projects():
            for project in page:
                if project.name.lower() == target:
                    return project.id
        return None

    def get_tasks(self, project_id: str) -> list:
        """Fetch all tasks for a project."""
        tasks = []
        for page in self.api.get_tasks(project_id=project_id):
            tasks.extend(page)
        return tasks

    def comment(self, task_id: str, message: str):
        """Add a comment to a Todoist task."""
        try:
            self.api.add_comment(content=message, task_id=task_id)
        except Exception as e:
            log.warning("Failed to add comment: %s", e)

    def mark_done(self, task_id: str, labels: list[str]):
        """Remove retry labels and add agent-done label."""
        done_labels = [l for l in labels if not l.startswith(self.RETRY_PREFIX)]
        done_labels.append("agent-done")
        self.api.update_task(task_id=task_id, labels=done_labels)

    def mark_failed(self, task_id: str, labels: list[str]):
        """Remove retry labels and add agent-failed label."""
        failed_labels = [l for l in labels if not l.startswith(self.RETRY_PREFIX)]
        failed_labels.append("agent-failed")
        self.api.update_task(task_id=task_id, labels=failed_labels)

    def get_retry_count(self, labels: list[str]) -> int:
        """Extract retry count from task labels."""
        for label in labels:
            if label.startswith(self.RETRY_PREFIX):
                try:
                    return int(label[len(self.RETRY_PREFIX):])
                except ValueError:
                    pass
        return 0

    def set_retry(self, task_id: str, labels: list[str], count: int):
        """Update task labels with new retry count."""
        new_labels = [l for l in labels if not l.startswith(self.RETRY_PREFIX)]
        new_labels.append(f"{self.RETRY_PREFIX}{count}")
        self.api.update_task(task_id=task_id, labels=new_labels)


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
        return "🔧 Running command"
    if name == "Glob":
        return "🔍 Searching files"
    if name == "Grep":
        return "🔍 Searching content"
    return None


def dispatch(title: str, description: str | None, *,
             verbose: bool = False, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Pass the ticket to Claude Code. Returns (success, summary)."""
    prompt = title
    if description:
        prompt += f"\n\n{description}"

    output_format = "stream-json" if verbose else "json"
    cmd = ["claude", "-p", prompt, "--model", "sonnet", "--output-format", output_format]
    if verbose:
        cmd.append("--verbose")

    log.info("  Dispatching to Claude Code...")
    # Subprocess isolation: strip sensitive env vars so the agent uses the
    # Claude Code subscription plan and can't access API keys or session state.
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("ANTHROPIC_API_KEY", None)

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

    # Watchdog timer — ensures timeout fires even when the stdout stream blocks
    timed_out = threading.Event()

    def _on_timeout():
        timed_out.set()
        _kill_child()

    timer = threading.Timer(timeout, _on_timeout)
    timer.start()

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
                                log.info("  %s", desc)

                if event.get("type") == "result":
                    result_text = event.get("result", "")

        proc.wait()

        if not verbose:
            stdout = proc.stdout.read()
            try:
                output = json.loads(stdout)
                result_text = output.get("result", "")
            except (json.JSONDecodeError, ValueError):
                pass

    except KeyboardInterrupt:
        log.info("\n  Interrupted — killing agent...")
        _kill_child()
        raise
    finally:
        timer.cancel()

    if timed_out.is_set():
        return False, f"Timed out after {timeout}s"

    stderr_text = proc.stderr.read() if proc.stderr else ""

    if proc.returncode == 0:
        log.info("  Done.")
        summary = result_text[:500] + ("..." if len(result_text) > 500 else "") if result_text else "Completed."
        return True, summary
    else:
        error_parts = [f"Exit code {proc.returncode}"]
        if stderr_text.strip():
            error_parts.append(f"stderr: {stderr_text.strip()[:500]}")
        if result_text:
            error_parts.append(f"output: {result_text[:500]}")

        error_msg = "\n".join(error_parts)
        log.error("  Failed:\n  %s", error_msg.replace("\n", "\n  "))
        return False, error_msg


def run_once(queue: TodoistQueue, project_id: str, *, verbose: bool = False,
             timeout: int = DEFAULT_TIMEOUT, max_retries: int = MAX_RETRIES) -> int:
    """Process all pending tasks. Returns count processed."""
    tasks = queue.get_tasks(project_id)

    if not tasks:
        log.info("No pending tasks.")
        return 0

    processed = 0
    for task in tasks:
        labels = task.labels or []

        if "agent-done" in labels or "agent-failed" in labels:
            continue

        retries = queue.get_retry_count(labels)
        if retries >= max_retries:
            continue  # already gave up, skip silently

        retry_info = f" (attempt {retries + 1}/{max_retries})" if retries > 0 else ""
        log.info("\nTask: %s%s", task.content, retry_info)
        queue.comment(task.id, f"Working on it...{retry_info}")

        success, summary = dispatch(
            task.content, task.description,
            verbose=verbose, timeout=timeout,
        )

        if success:
            queue.comment(task.id, f"Done. Ready for review.\n\n{summary}")
            queue.mark_done(task.id, labels)
            log.info("  Done. Left open for review.")
            processed += 1
        else:
            retries += 1
            if retries >= max_retries:
                queue.comment(task.id, f"Failed after {max_retries} attempts. Giving up.\n\n{summary}")
                queue.mark_failed(task.id, labels)
                log.error("  Failed permanently after %d attempts.", max_retries)
            else:
                queue.comment(task.id, f"Failed (attempt {retries}/{max_retries}). Will retry.\n\n{summary}")
                queue.set_retry(task.id, labels, retries)
                log.warning("  Failed (attempt %d/%d). Will retry next run.", retries, max_retries)

    return processed


def main():
    parser = argparse.ArgumentParser(description="Background agent worker")
    parser.add_argument("--project", required=True, help="Todoist project name to watch")
    parser.add_argument("--watch", action="store_true", help="Poll continuously")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    parser.add_argument("--verbose", action="store_true",
                        help="Stream agent progress to terminal")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Per-task timeout in seconds (default {DEFAULT_TIMEOUT})")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                        help=f"Give up after N failures (default {MAX_RETRIES})")
    args = parser.parse_args()

    setup_logging(watch=args.watch, verbose=args.verbose)

    load_dotenv(REPO_ROOT / ".env")

    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        log.error("TODOIST_API_TOKEN not set. Add it to .env or export it.")
        sys.exit(1)

    queue = TodoistQueue(token)
    project_id = queue.find_project_id(args.project)
    if not project_id:
        log.error("No '%s' project found in Todoist.", args.project)
        sys.exit(1)

    log.info("Watching project: %s (id: %s)", args.project, project_id)
    if args.verbose:
        log.info("Verbose mode: streaming agent progress to terminal")

    try:
        if args.watch:
            log.info("Polling every %ds. Ctrl+C to stop.\n", args.interval)
            consecutive_errors = 0
            while True:
                try:
                    run_once(queue, project_id, verbose=args.verbose,
                             timeout=args.timeout, max_retries=args.max_retries)
                    consecutive_errors = 0
                except KeyboardInterrupt:
                    raise
                except Exception:
                    consecutive_errors += 1
                    backoff = min(args.interval * (2 ** consecutive_errors), 600)
                    log.exception("Poll failed, retrying in %ds", backoff)
                    time.sleep(backoff)
                    continue
                time.sleep(args.interval)
        else:
            run_once(queue, project_id, verbose=args.verbose,
                     timeout=args.timeout, max_retries=args.max_retries)
    except KeyboardInterrupt:
        log.info("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
