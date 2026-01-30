import argparse
import json
from pathlib import Path
from datetime import datetime


# Default project root - can be overridden by --project-path argument
DEFAULT_PROJECT_ROOT = Path("/home/admin/workspaces/datachat")


def show_job_status(job_id: str, project_root: Path = DEFAULT_PROJECT_ROOT):
    """Show status of a specific job across all stages (waiting, processing, completed)."""

    # Normalize job_id - ensure it has .md extension if just the base name
    if not job_id.endswith('.md'):
        job_id = f"{job_id}.md"

    state_file = project_root / "jobs" / "state" / "queue_state.json"
    items_dir = project_root / "jobs" / "items"
    results_dir = project_root / "jobs" / "results"

    # 1. Check if currently processing
    if state_file.exists():
        with open(state_file, 'r') as f:
            state = json.load(f)

        current_task = state.get('current_task')
        if current_task and job_id in current_task:
            print(f"Status: processing")
            print(f"Job: {job_id}")
            print(f"Started: {state.get('task_start_time', 'Unknown')}")
            return

    # 2. Check if waiting in queue
    job_file = items_dir / job_id
    if job_file.exists():
        stat = job_file.stat()
        created_time = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
        print(f"Status: waiting")
        print(f"Job: {job_id}")
        print(f"Created: {created_time}")
        print(f"Size: {stat.st_size} bytes")

        # Show position in queue if available
        if state_file.exists():
            with open(state_file, 'r') as f:
                state = json.load(f)
            queued_tasks = state.get('queued_tasks', [])
            if job_id in queued_tasks:
                position = queued_tasks.index(job_id) + 1
                print(f"Queue position: {position} of {len(queued_tasks)}")
        return

    # 3. Check if completed - try with .json extension for result file
    result_file = results_dir / job_id.replace('.md', '.json')
    if result_file.exists():
        with open(result_file) as f:
            data = json.load(f)

        # Show summary
        print(f"Status: {data.get('status', 'unknown')}")
        print(f"Job: {data.get('job_id', job_id)}")

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
    print(f"Job: {job_id}")
    print(f"\nThe job was not found in any of the following locations:")
    print(f"  - Currently processing")
    print(f"  - Waiting in queue ({items_dir})")
    print(f"  - Completed jobs ({results_dir})")


def show_status(job_id: str = None, project_root: Path = DEFAULT_PROJECT_ROOT):
    """Show job status (legacy - redirects to show_job_status for specific job)."""
    if job_id:
        show_job_status(job_id, project_root)
    else:
        # List all completed jobs
        results_dir = project_root / "jobs" / "results"
        print("Completed jobs:")
        for result_file in sorted(results_dir.glob("*.json"), reverse=True):
            with open(result_file) as f:
                data = json.load(f)
            status_symbol = "✓" if data.get('status') == 'completed' else "✗"
            print(f"  {status_symbol} {data['job_id']}: {data['status']}")


def show_queue(project_root: Path = DEFAULT_PROJECT_ROOT):
    """Show current queue state."""
    state_file = project_root / "jobs" / "state" / "queue_state.json"
    if state_file.exists():
        with open(state_file, 'r') as f:
            state = json.load(f)
        print(f"Queue size: {state['queue_size']}")
        print(f"Processing: {state.get('current_task', 'None')}")
        if state.get('queued_tasks'):
            print("Queued jobs:")
            for i, job in enumerate(state['queued_tasks'], 1):
                print(f"  {i}. {job}")
    else:
        print("Queue state not available (monitor may not be running)")


def main():
    """CLI entry point - called by setuptools entry point."""
    parser = argparse.ArgumentParser(description="Job Monitor CLI")
    parser.add_argument("--project-path", "-p", type=str, help="Project root path")
    parser.add_argument("command", nargs="?", default="status", help="Command: status, queue, or job_id")
    args = parser.parse_args()

    # Project root - where jobs/items, jobs/results, jobs/state directories are located
    project_root = Path(args.project_path) if args.project_path else DEFAULT_PROJECT_ROOT

    if args.command == "queue":
        show_queue(project_root)
    else:
        show_status(args.command, project_root)


if __name__ == "__main__":
    main()
