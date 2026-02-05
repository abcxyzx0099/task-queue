"""
Command-line interface for task-queue (Directory-Based State).

Simplified CLI - no state file operations.
"""

import sys
import argparse
from pathlib import Path

from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.task_runner import TaskRunner


def cmd_init(args):
    """Initialize configuration."""
    import json

    config_file = Path(args.config) if args.config else DEFAULT_CONFIG_FILE
    config_file.parent.mkdir(parents=True, exist_ok=True)

    if config_file.exists():
        print("⚠️  Configuration file already exists")
        response = input("Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Aborted")
            return 1

    # Create default config
    from task_queue.models import QueueConfig
    config = QueueConfig()

    # Save config
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode='w',
        dir=config_file.parent,
        prefix=f".{config_file.name}.",
        suffix='.tmp',
        delete=False
    ) as tmp_file:
        json.dump(config.model_dump(), tmp_file, indent=2)
        tmp_file.flush()

    import os
    os.replace(tmp_file.name, config_file)

    print(f"✅ Configuration created: {config_file}")
    print()
    print("Next steps:")
    print("  1. Set project workspace:")
    print(f"     task-queue init --config {config_file}")
    print(f"     task-queue load --task-source-dir tasks/task-documents --project-workspace /path/to/project --source-id main")
    return 0


def cmd_status(args):
    """Show system status."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("📊 Task Queue Status")
    print("=" * 60)

    # Configuration info
    print(f"\nConfiguration: {args.config}")
    print(f"Project Workspace: {config.project_workspace or 'Not set'}")

    # Create task runner to get status
    if not config.project_workspace:
        print("\n⚠️  No Project Workspace set")
        print("Use 'task-queue load' to set up the workspace")
        return 0

    task_runner = TaskRunner(
        project_workspace=config.project_workspace
    )

    source_dirs = config.task_source_directories

    if not source_dirs:
        print("\n⚠️  No Task Source Directories configured")
        print("Use 'task-queue load' to add a source directory")
        return 0

    print(f"\nTask Source Directories: {len(source_dirs)}")

    # Get status by scanning directories
    status = task_runner.get_status(source_dirs)

    print(f"\n📋 Overall Statistics:")
    print(f"   Pending:   {status['pending']}")
    print(f"   Running:   {status['running']}")
    print(f"   Completed: {status['completed']}")
    print(f"   Failed:    {status['failed']}")

    # Per-source breakdown
    print(f"\n📁 Per-Source Details:")
    for source_id, source_stats in status['sources'].items():
        source_dir = config.get_task_source_directory(source_id)
        print(f"\n  📁 {source_id}")
        if source_dir:
            print(f"      Path: {source_dir.path}")
            print(f"      Description: {source_dir.description}")
        print(f"      Pending: {source_stats['pending']}, Running: {source_stats['running']}, "
              f"Completed: {source_stats['completed']}, Failed: {source_stats['failed']}")

    return 0


def cmd_load(args):
    """Load tasks from source directory."""
    try:
        config_manager = ConfigManager(args.config)

        # Set project workspace if not set
        if not config_manager.config.project_workspace:
            config_manager.set_project_workspace(args.project_workspace)

        # Add source directory
        source_dir = config_manager.add_task_source_directory(
            path=args.task_source_dir,
            id=args.source_id
        )

        # Save config
        config_manager.save_config()

        print(f"\n✅ Registered Task Source Directory '{args.source_id}'")
        print(f"   Path: {args.task_source_dir}")
        print(f"   Workspace: {args.project_workspace}")

        # Count existing tasks
        from pathlib import Path
        source_path = Path(args.task_source_dir)
        task_files = list(source_path.glob("task-*.md"))

        if task_files:
            print(f"\n📋 Found {len(task_files)} task documents in directory")
            print("   Daemon will process them automatically")
        else:
            print(f"\n📭 No task documents found yet")
            print("   Create task-*.md files and the daemon will process them")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_list_sources(args):
    """List Task Source Directories."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    print("\n📂 Task Source Directories:")

    if not config.task_source_directories:
        print("  (none)")
        return 0

    for source_dir in config.task_source_directories:
        print(f"\n  📁 {source_dir.id}")
        print(f"      Path: {source_dir.path}")
        print(f"      Description: {source_dir.description or '(no description)'}")
        print(f"      Added: {source_dir.added_at}")

    return 0


def cmd_unload(args):
    """Remove a Task Source Directory."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config

        # Check if source exists
        source_dir = config.get_task_source_directory(args.source_id)
        if not source_dir:
            print(f"❌ Task Source Directory '{args.source_id}' not found")
            return 1

        # Remove it
        if config.remove_task_source_directory(args.source_id):
            config_manager.save_config()
            print(f"✅ Removed Task Source Directory '{args.source_id}'")
            return 0
        else:
            print(f"❌ Failed to remove Task Source Directory '{args.source_id}'")
            return 1

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_run(args):
    """Run task queue interactively (for testing)."""
    import time

    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config

        if not config.project_workspace:
            print("❌ No Project Workspace set")
            return 1

        task_runner = TaskRunner(
            project_workspace=config.project_workspace
        )

        source_dirs = config.task_source_directories

        print("=" * 60)
        print("🔄 Running Task Queue (Interactive Mode)")
        print("=" * 60)
        print(f"Configuration: {args.config}")
        print(f"Task Source Directories: {len(source_dirs)}")
        print()

        cycles = args.cycles if args.cycles > 0 else 999999

        for cycle in range(cycles):
            print(f"\n--- Cycle {cycle + 1} ---")

            # Pick next task
            task_file = task_runner.pick_next_task(source_dirs)

            if task_file:
                print(f"Found task: {task_file.name}")
                result = task_runner.execute_task(task_file)
                print(f"Status: {result['status']}")
                if result.get("error"):
                    print(f"Error: {result['error']}")
            else:
                print("No pending tasks")

            # Check if any tasks exist
            status = task_runner.get_status(source_dirs)
            if status['pending'] == 0 and status['running'] == 0:
                print("\n✅ All tasks processed")
                break

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1

    return 0


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Task Queue CLI (Directory-Based State)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize configuration
  task-queue init

  # Load a task source directory
  task-queue load \\
    --task-source-dir tasks/task-documents \\
    --project-workspace /path/to/project \\
    --source-id main

  # Check status
  task-queue status

  # Run interactively
  task-queue run --cycles 5

  # List source directories
  task-queue list-sources

  # Unload a source directory
  task-unload --source-id main
        """
    )

    # Global arguments
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to configuration file"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize configuration")
    init_parser.set_defaults(func=cmd_init)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show system status")
    status_parser.set_defaults(func=cmd_status)

    # Load command
    load_parser = subparsers.add_parser("load", help="Load Task Source Directory")
    load_parser.add_argument(
        "--task-source-dir",
        required=True,
        help="Path to Task Source Directory"
    )
    load_parser.add_argument(
        "--project-workspace",
        required=True,
        help="Path to Project Workspace"
    )
    load_parser.add_argument(
        "--source-id",
        required=True,
        help="Unique ID for this source"
    )
    load_parser.set_defaults(func=cmd_load)

    # List sources command
    list_sources_parser = subparsers.add_parser("list-sources", help="List Task Source Directories")
    list_sources_parser.set_defaults(func=cmd_list_sources)

    # Unload command
    unload_parser = subparsers.add_parser("unload", help="Remove Task Source Directory")
    unload_parser.add_argument(
        "--source-id",
        required=True,
        help="Task Source Directory ID to remove"
    )
    unload_parser.set_defaults(func=cmd_unload)

    # Run command
    run_parser = subparsers.add_parser("run", help="Run task queue interactively")
    run_parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of cycles (0 = infinite)"
    )
    run_parser.set_defaults(func=cmd_run)

    # Parse arguments
    args = parser.parse_args()

    # Set default config file if not specified
    if not args.config:
        args.config = DEFAULT_CONFIG_FILE

    # Execute command
    if hasattr(args, 'func'):
        return args.func(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
