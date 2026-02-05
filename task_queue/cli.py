"""
Command-line interface for task queue.

Provides CLI commands for managing the task queue system with watchdog support.
"""

import sys
import argparse
from pathlib import Path
from typing import Optional

from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.monitor import create_queue
from task_queue.models import SystemStatus


def cmd_status(args, config: ConfigManager) -> int:
    """Show system status."""
    try:
        monitor = create_queue(config_file=config.config_file)
        status = monitor.get_status()

        print(f"\n{'='*60}")
        print(f"📊 Task Queue Status")
        print(f"{'='*60}")

        # Running state
        running = "🟢 Running" if status.running else "🔴 Stopped"
        print(f"\nStatus: {running}")

        if status.uptime_seconds > 0:
            uptime_mins = int(status.uptime_seconds / 60)
            print(f"Uptime: {uptime_mins} minutes")

        # Load info
        if status.load_count > 0:
            print(f"Loads: {status.load_count}")
            if status.last_load_at:
                print(f"Last load: {status.last_load_at}")

        # Project
        print(f"\nProject Workspace: {status.project_workspace or 'Not set'}")

        # Task Source Directories
        print(f"\nTask Source Directories: {status.active_task_source_dirs}/{status.total_task_source_dirs} active")

        # Queue stats
        print(f"\n📋 Queue Statistics:")
        print(f"   Pending:   {status.total_pending}")
        print(f"   Running:   {status.total_running}")
        print(f"   Completed: {status.total_completed}")
        print(f"   Failed:    {status.total_failed}")

        # Source details
        if args.verbose:
            print(f"\n{'='*60}")
            print(f"📂 Task Source Directory Details")
            print(f"{'='*60}")

            for source_status in monitor.get_task_source_directory_status():
                print(f"\n{source_status.id}:")
                print(f"   Path: {source_status.path}")
                if source_status.description:
                    print(f"   Description: {source_status.description}")

                queue = source_status.queue_stats
                if queue:
                    print(f"   Queue: {queue}")

        print()

        return 0

    except Exception as e:
        print(f"❌ Error getting status: {e}", file=sys.stderr)
        return 1


def cmd_queue(args, config: ConfigManager) -> int:
    """Show queue status."""
    try:
        monitor = create_queue(config_file=config.config_file)
        status = monitor.get_status()

        print(f"\nProject Workspace: {status.project_workspace or 'Not set'}")
        print(f"Task Source Directories: {status.active_task_source_dirs}/{status.total_task_source_dirs} active")

        print(f"\n📋 Queue Statistics:")
        print(f"   Pending:   {status.total_pending}")
        print(f"   Running:   {status.total_running}")
        print(f"   Completed: {status.total_completed}")
        print(f"   Failed:    {status.total_failed}")

        # Show source breakdown
        for source_status in monitor.get_task_source_directory_status():
            queue = source_status.queue_stats
            pending = queue.get("pending", 0)
            running = queue.get("running", 0)
            completed = queue.get("completed", 0)
            failed = queue.get("failed", 0)

            if pending + running + completed + failed > 0:
                print(f"\n{source_status.id}:")
                print(f"   Pending: {pending}, Running: {running}, Completed: {completed}, Failed: {failed}")

        print()

        return 0

    except Exception as e:
        print(f"❌ Error getting queue: {e}", file=sys.stderr)
        return 1


def cmd_load(args, config: ConfigManager) -> int:
    """
    Load tasks from Task Source Directory.

    Both parameters are required.
    """
    if not args.task_source_dir or not args.project_workspace:
        print(f"❌ Error: Both --task-source-dir and --project-workspace are required", file=sys.stderr)
        return 1

    try:
        monitor = create_queue(config_file=config.config_file)

        print(f"\n📂 Loading tasks...")

        # Check if it's a single file or directory
        source_path = Path(args.task_source_dir)

        if source_path.is_file():
            # Single task file
            print(f"Loading single task: {source_path.name}")

            # Generate source ID from parent directory
            source_id = source_path.parent.name

            result = monitor.load_single_task(
                task_doc_file=str(source_path),
                task_source_dir=source_id,
                project_workspace=args.project_workspace
            )

            if result:
                print(f"✅ Loaded task: {source_path.name}")
            else:
                print(f"⚠️  Task already exists: {source_path.name}")

        else:
            # Directory - set project workspace and load all configured sources
            config.set_project_workspace(args.project_workspace)

            # Add source directory if not configured
            existing = config.get_task_source_directory(args.source_id)
            if not existing:
                config.add_task_source_directory(
                    path=args.task_source_dir,
                    id=args.source_id,
                    description=f"Added via load command"
                )
                print(f"✅ Registered Task Source Directory '{args.source_id}': {args.task_source_dir}")

            # Load tasks
            results = monitor.load_tasks()

            total = results.get("total", 0)
            if total > 0:
                print(f"\n✅ Loaded {total} new tasks")
            else:
                print(f"\n📭 No new tasks found")

        return 0

    except Exception as e:
        print(f"❌ Error loading tasks: {e}", file=sys.stderr)
        return 1


def cmd_reload(args, config: ConfigManager) -> int:
    """Force re-scan Task Source Directory."""
    try:
        monitor = create_queue(config_file=config.config_file)

        count = monitor.reload_source(
            task_source_dir=args.task_source_dir,
            project_workspace=args.project_workspace
        )

        return 0

    except Exception as e:
        print(f"❌ Error reloading: {e}", file=sys.stderr)
        return 1


def cmd_unload(args, config: ConfigManager) -> int:
    """Remove ALL tasks from a Task Source Directory."""
    try:
        monitor = create_queue(config_file=config.config_file)

        count = monitor.unload_source(args.source_id)

        return 0

    except Exception as e:
        print(f"❌ Error unloading: {e}", file=sys.stderr)
        return 1


def cmd_list_sources(args, config: ConfigManager) -> int:
    """List Task Source Directories."""
    source_dirs = config.list_task_source_directories()

    if not source_dirs:
        print("⚠️  No Task Source Directories configured")
        return 0

    print(f"\n📂 Task Source Directories:")
    print()

    for source_dir in source_dirs:
        print(f"  📁 {source_dir.id}")
        print(f"      Path: {source_dir.path}")
        if source_dir.description:
            print(f"      Description: {source_dir.description}")

        # Get current status if available
        try:
            monitor = create_queue(config_file=config.config_file)
            source_statuses = monitor.get_task_source_directory_status()

            for source_status in source_statuses:
                if source_status.id == source_dir.id:
                    queue = source_status.queue_stats
                    if queue:
                        print(f"      Queue: {queue}")
                    break
        except Exception:
            pass

        print()

    return 0


def cmd_process(args, config: ConfigManager) -> int:
    """Trigger immediate processing."""
    try:
        monitor = create_queue(config_file=config.config_file)

        result = monitor.process_tasks(max_tasks=args.max_tasks)

        status = result.get("status", "unknown")

        print()

        if status == "completed":
            processed = result.get("processed", 0)
            failed = result.get("failed", 0)
            remaining = result.get("remaining", 0)

            print(f"📊 Processing Summary:")
            print(f"   ✅ Completed: {processed}")
            print(f"   ❌ Failed: {failed}")
            print(f"   📋 Remaining: {remaining}")

        elif status == "empty":
            print(f"📭 No pending tasks to process")

        elif status == "skipped":
            reason = result.get("reason", "unknown")
            print(f"⏸️  Skipped: {reason}")

        print()

        return 0

    except Exception as e:
        print(f"❌ Error processing: {e}", file=sys.stderr)
        return 1


def cmd_run(args, config: ConfigManager) -> int:
    """Run task queue interactively."""
    try:
        monitor = create_queue(config_file=config.config_file)

        cycles = args.cycles if args.cycles > 0 else None

        monitor.run(cycles=cycles)

        return 0

    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="task-queue",
        description="Task queue system with watchdog support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load tasks from a Task Source Directory
  task-queue load --task-source-dir tasks/task-documents --project-workspace /home/admin/workspaces/datachat --source-id main

  # Load a single Task Document
  task-queue load --task-source-dir tasks/task-documents/task-001.md --project-workspace /home/admin/workspaces/datachat --source-id main

  # Reload a Task Source Directory
  task-queue reload --task-source-dir main --project-workspace /home/admin/workspaces/datachat

  # Unload all tasks from a source
  task-queue unload --source-id main

  # List Task Source Directories
  task-queue list-sources

  # Show status
  task-queue status

  # Process tasks
  task-queue process
        """
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to configuration file"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Status and queue
    status_parser = subparsers.add_parser("status", help="Show system status")
    status_parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed status")

    subparsers.add_parser("queue", help="Show queue status")

    # List sources
    list_sources_parser = subparsers.add_parser("list-sources", help="List Task Source Directories")

    # Load command
    load_parser = subparsers.add_parser("load", help="Load tasks from Task Source Directory")
    load_parser.add_argument("--task-source-dir", required=True, help="Path to Task Source Directory or single Task Document")
    load_parser.add_argument("--project-workspace", required=True, help="Path to Project Workspace")
    load_parser.add_argument("--source-id", default="main", help="Source ID for the directory (default: main)")

    # Reload command
    reload_parser = subparsers.add_parser("reload", help="Force re-scan Task Source Directory")
    reload_parser.add_argument("--task-source-dir", required=True, help="Task Source Directory ID or path")
    reload_parser.add_argument("--project-workspace", required=True, help="Path to Project Workspace")

    # Unload command
    unload_parser = subparsers.add_parser("unload", help="Remove all tasks from Task Source Directory")
    unload_parser.add_argument("--source-id", required=True, help="Task Source Directory ID")

    # Process
    process_parser = subparsers.add_parser("process", help="Process pending tasks")
    process_parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Max tasks to process"
    )

    # Run
    run_parser = subparsers.add_parser("run", help="Run task queue interactively")
    run_parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of cycles (0 = infinite)"
    )

    return parser


def main() -> int:
    """CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Load config
    config = ConfigManager(args.config)

    # Dispatch command
    handlers = {
        ("status",): cmd_status,
        ("queue",): cmd_queue,
        ("load",): cmd_load,
        ("reload",): cmd_reload,
        ("unload",): cmd_unload,
        ("list-sources",): cmd_list_sources,
        ("process",): cmd_process,
        ("run",): cmd_run,
    }

    key = (args.command,)

    handler = handlers.get(key)

    if handler:
        return handler(args, config)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
