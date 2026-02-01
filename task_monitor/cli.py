import argparse
import json
import subprocess
import os
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv


# Environment variable name for current project
ENV_VAR_NAME = "TASK_MONITOR_PROJECT"

# .env file location in source directory
ENV_FILE = Path(__file__).parent.parent / ".env"

# Task monitor path relative to project root (e.g., "tasks/task-monitor")
task_monitor_path = "tasks/task-monitor"


def get_current_project():
    """Get the current project path from .env file or environment variable."""
    # Try loading from .env file
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)

    path = os.environ.get(ENV_VAR_NAME)
    if path:
        return Path(path)
    return None


def use_project(path: str):
    """Set the current project path by updating .env file."""
    project_path = Path(path).expanduser().resolve()
    if not project_path.exists():
        print(f"Error: Project path does not exist: {project_path}")
        return False

    # Read existing content
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
    else:
        content = ""
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Remove old TASK_MONITOR_PROJECT line if exists
    lines = [line for line in content.split('\n')
             if not line.startswith(f'{ENV_VAR_NAME}=') and line.strip() != '']

    # Add new line in standard .env format (no "export")
    lines.append(f'{ENV_VAR_NAME}="{project_path}"')

    # Write back to .env file
    ENV_FILE.write_text('\n'.join(lines) + '\n')

    print(f"Current project set to: {project_path}")
    print(f"Updated {ENV_FILE}")
    return True


def show_current():
    """Show the current project."""
    path = get_current_project()
    if not path:
        print("No current project set.")
        print()
        print(f"Set a project with: task-monitor use <path>")
        return

    print(f"Current project: {path}")
    print(f"Source: {ENV_FILE}")


def get_project_root(project_path: str = None):
    """Get project root from argument or environment variable."""
    # 1. Explicit path takes priority
    if project_path:
        return Path(project_path).expanduser().resolve()

    # 2. Use current project from environment variable
    current_path = get_current_project()
    if current_path:
        return current_path

    # 3. No current project set
    print("Error: No current project set.")
    print()
    print(f"Set a project with: task-monitor use <path>")
    print("Or specify project path with: task-monitor -p <path> <command>")
    raise SystemExit(1)


def show_task_status(task_id: str, project_root: Path):
    """Show status of a specific task across all stages (waiting, processing, completed)."""

    # Normalize task_id - ensure it has .md extension if just the base name
    if not task_id.endswith('.md'):
        task_id = f"{task_id}.md"

    state_file = project_root / task_monitor_path / "state" / "queue_state.json"
    items_dir = project_root / task_monitor_path / "pending"
    results_dir = project_root / task_monitor_path / "results"

    # 1. Check if currently processing
    if state_file.exists():
        with open(state_file, 'r') as f:
            state = json.load(f)

        current_task = state.get('current_task')
        if current_task and task_id in current_task:
            print(f"Status: processing")
            print(f"Task: {task_id}")
            print(f"Started: {state.get('task_start_time', 'Unknown')}")
            return

    # 2. Check if waiting in queue
    task_file = items_dir / task_id
    if task_file.exists():
        stat = task_file.stat()
        created_time = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
        print(f"Status: waiting")
        print(f"Task: {task_id}")
        print(f"Created: {created_time}")
        print(f"Size: {stat.st_size} bytes")

        # Show position in queue if available
        if state_file.exists():
            with open(state_file, 'r') as f:
                state = json.load(f)
            queued_tasks = state.get('queued_tasks', [])
            if task_id in queued_tasks:
                position = queued_tasks.index(task_id) + 1
                print(f"Queue position: {position} of {len(queued_tasks)}")
        return

    # 3. Check if completed - try with .json extension for result file
    result_file = results_dir / task_id.replace('.md', '.json')
    if result_file.exists():
        with open(result_file) as f:
            data = json.load(f)

        # Show summary
        print(f"Status: {data.get('status', 'unknown')}")
        print(f"Task: {data.get('task_id', task_id)}")

        if 'duration_seconds' in data:
            print(f"Duration: {data['duration_seconds']:.2f} seconds")

        if 'worker_output' in data:
            worker_out = data['worker_output']
            if 'summary' in worker_out:
                print(f"\nSummary:")
                print(f"  {worker_out['summary']}")

            if 'usage' in worker_out:
                usage = worker_out['usage']
                print(f"\nUsage:")
                print(f"  Tokens: {usage.get('total_tokens', 'N/A')}")
                print(f"  Cost: ${usage.get('cost_usd', 0):.4f}")

        if 'error' in data:
            print(f"\nError: {data['error']}")
        return

    # 4. Not found anywhere
    print(f"Status: not_found")
    print(f"Task: {task_id}")
    print(f"\nThe task was not found in any of the following locations:")
    print(f"  - Currently processing")
    print(f"  - Waiting in queue ({items_dir})")
    print(f"  - Completed tasks ({results_dir})")


def check_daemon_running() -> bool:
    """Check if the monitor daemon process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "monitor_daemon"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        # Fallback: use ps and grep
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True
            )
            return "monitor_daemon" in result.stdout and "grep -v grep" not in result.stdout
        except Exception:
            return False


def show_status(task_id: str = None, project_root: Path = None):
    """Show daemon status - simple check if service is running."""
    if task_id:
        show_task_status(task_id, project_root)
    else:
        daemon_running = check_daemon_running()
        print(f"{'Running' if daemon_running else 'Stopped'}")


def show_queue(project_root: Path):
    """Show current queue state."""
    state_file = project_root / task_monitor_path / "state" / "queue_state.json"
    if state_file.exists():
        with open(state_file, 'r') as f:
            state = json.load(f)
        print(f"Project: {project_root}")
        print(f"Queue size: {state['queue_size']}")
        print(f"Processing: {state.get('current_task', 'None')}")
        if state.get('queued_tasks'):
            print("Queued tasks:")
            for i, task in enumerate(state['queued_tasks'], 1):
                print(f"  {i}. {task}")
    else:
        print(f"Project: {project_root}")
        print("Queue state not available (monitor may not be running)")


def load_pending_tasks(project_root: Path):
    """Load existing task files from pending directory by triggering watchdog events.

    This scans the pending directory for existing task files matching the pattern
    and triggers the watchdog by renaming them to force queueing.
    """
    pending_dir = project_root / task_monitor_path / "pending"

    if not pending_dir.exists():
        print(f"Error: Pending directory does not exist: {pending_dir}")
        return False

    # Find all task files matching the pattern
    task_pattern = re.compile(r"^task-\d{8}-\d{6}-.*\.md$")
    task_files = [f for f in pending_dir.iterdir() if f.is_file() and task_pattern.match(f.name)]

    if not task_files:
        print(f"No task files found in {pending_dir}")
        print("Task files must match pattern: task-YYYYMMDD-HHMMSS-*.md")
        return True

    print(f"Found {len(task_files)} task file(s) in {pending_dir}")
    print()

    # Check if daemon is running
    if not check_daemon_running():
        print("Warning: Monitor daemon does not appear to be running.")
        print("Tasks will be loaded but won't be processed until the daemon starts.")
        print()
        print("Start the daemon with:")
        print("  systemctl --user start task-monitor")
        print()

    # Trigger watchdog by renaming each file (temporarily add prefix, then remove it)
    loaded_count = 0
    for task_file in sorted(task_files):
        temp_name = task_file.parent / f".loading_{task_file.name}"
        try:
            # Rename to temp name (triggers on_moved)
            task_file.rename(temp_name)
            # Rename back to original (triggers on_moved again)
            temp_name.rename(task_file)
            print(f"  Loaded: {task_file.name}")
            loaded_count += 1
        except Exception as e:
            print(f"  Failed to load {task_file.name}: {e}")

    print()
    print(f"Successfully loaded {loaded_count} task file(s)")
    print("Use 'task-monitor queue' to check the queue status")
    return True


def main():
    """CLI entry point - called by setuptools entry point."""
    parser = argparse.ArgumentParser(description="Task Monitor CLI")
    parser.add_argument("--project-path", "-p", type=str, help="Project root path (overrides current)")

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status command
    subparsers.add_parser("status", help="Show daemon status")

    # Queue command
    subparsers.add_parser("queue", help="Show queue state")

    # Current command - show current project
    subparsers.add_parser("current", help="Show current project")

    # Use command - set current project
    use_parser = subparsers.add_parser("use", help="Set current project")
    use_parser.add_argument("path", help="Project path")

    # Load command - load existing tasks
    subparsers.add_parser("load", help="Load existing task files from pending directory")

    args = parser.parse_args()

    # Handle commands that don't need project root
    if args.command == "use":
        use_project(args.path)
        return
    elif args.command == "current":
        show_current()
        return

    # Get project root from argument or environment
    try:
        project_root = get_project_root(args.project_path)
    except SystemExit:
        return

    # Handle commands that need project root
    if args.command == "queue":
        show_queue(project_root)
    elif args.command == "load":
        load_pending_tasks(project_root)
    elif args.command == "status":
        show_status(None, project_root)
    elif args.command is None:
        # Default: show status
        show_status(None, project_root)
    else:
        # Treat as task ID
        show_status(args.command, project_root)


if __name__ == "__main__":
    main()
