"""
Command-line interface for task-monitor (Directory-Based State).

Grouped command structure:
- queues: list, add, rm
- tasks: show, logs, cancel
- workers: status, list
"""

import sys
import os
import argparse
import subprocess
import threading
from pathlib import Path

from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.task_runner import TaskRunner
from task_queue.executor import get_lock_file_path, LockInfo, get_locked_task


def _restart_daemon() -> bool:
    """Restart the task-queue daemon service."""
    try:
        print("🔄 Restarting daemon to apply changes...")
        result = subprocess.run(
            ["systemctl", "--user", "restart", "task-queue.service"],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Daemon restarted successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to restart daemon: {e}")
        if e.stderr:
            print(f"   Error output: {e.stderr.strip()}")
        print("   Please restart manually: systemctl --user restart task-queue.service")
        return False
    except Exception as e:
        print(f"⚠️  Failed to restart daemon: {e}")
        print("   Please restart manually: systemctl --user restart task-queue.service")
        return False


# =============================================================================
# INIT COMMAND
# =============================================================================

def cmd_init(args):
    """Initialize task system from current directory."""
    from datetime import datetime

    project_workspace = Path.cwd()
    print("=" * 60)
    print("🚀 Task System Initialization")
    print("=" * 60)
    print(f"\n📁 Project Workspace: {project_workspace}")

    queues = [
        {
            "id": "ad-hoc",
            "path": project_workspace / "tasks" / "ad-hoc" / "pending",
            "description": "Quick, spontaneous tasks from conversation",
            "subdirs": ["staging", "pending", "completed", "failed", "results", "reports", "planning"]
        },
        {
            "id": "planned",
            "path": project_workspace / "tasks" / "planned" / "pending",
            "description": "Organized, sequential tasks from planning docs",
            "subdirs": ["staging", "pending", "completed", "failed", "results", "reports", "planning"]
        }
    ]

    config_manager = ConfigManager(args.config)

    existing_sources = [s.id for s in config_manager.config.queues]
    already_initialized = "ad-hoc" in existing_sources or "planned" in existing_sources

    if already_initialized and not args.force and not args.skip_existing:
        print("\n⚠️  Task system appears to be already initialized.")
        print("   Found sources:", ", ".join(existing_sources))
        print("\nUse --force to re-initialize or --skip-existing to add missing queues only.")
        return 0

    print("\n📂 Creating directory structure...")
    for queue in queues:
        queue_base = queue["path"].parent
        for subdir in queue["subdirs"]:
            subdir_path = queue_base / subdir
            try:
                subdir_path.mkdir(parents=True, exist_ok=True)
                print(f"   ✅ Created: {subdir_path.relative_to(project_workspace)}")
            except Exception as e:
                print(f"   ❌ Failed to create {subdir_path}: {e}")
                return 1

    print("\n📋 Registering Task Source Directories...")

    if not config_manager.config.project_workspace:
        config_manager.set_project_workspace(str(project_workspace))
        print(f"   ✅ Set Project Workspace: {project_workspace}")

    for queue in queues:
        source_id = queue["id"]
        task_queue = str(queue["path"])

        if args.skip_existing and config_manager.config.get_queue(source_id):
            print(f"   ⏭️  Skipped existing: {source_id}")
            continue

        try:
            if args.force and config_manager.config.get_queue(source_id):
                config_manager.config.remove_queue(source_id)
                print(f"   🔄 Removed existing: {source_id}")

            config_manager.add_queue(
                path=task_queue,
                id=source_id,
                description=queue["description"]
            )
            print(f"   ✅ Registered: {source_id}")
            print(f"      Path: {task_queue}")
        except Exception as e:
            print(f"   ❌ Failed to register {source_id}: {e}")
            return 1

    try:
        config_manager.save_config()
        print("\n💾 Configuration saved")
    except Exception as e:
        print(f"\n❌ Failed to save configuration: {e}")
        return 1

    config_manager = ConfigManager(args.config)
    registered = config_manager.config.queues

    print(f"\n✅ Initialization complete!")
    print(f"\n📊 Summary:")
    print(f"   Project Workspace: {project_workspace}")
    print(f"   Registered Queues: {len(registered)}")

    for source in registered:
        print(f"\n   📁 {source.id}")
        print(f"      Path: {source.path}")
        if source.description:
            print(f"      Description: {source.description}")

    if args.restart_daemon:
        _restart_daemon()

    return 0


# =============================================================================
# STATUS COMMAND
# =============================================================================

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

    print(f"\nConfiguration: {args.config}")
    print(f"Project Workspace: {config.project_workspace or 'Not set'}")

    if not config.project_workspace:
        print("\n⚠️  No Project Workspace set")
        print("Use 'task-queue init' or 'task-queue sources add' to set up the workspace")
        return 0

    task_runner = TaskRunner(project_workspace=config.project_workspace)
    queues = config.queues

    if not queues:
        print("\n⚠️  No Task Source Directories configured")
        print("Use 'task-queue sources add' to add a source directory")
        return 0

    # Get status by scanning directories
    status = task_runner.get_status(queues)

    if args.detailed:
        _print_detailed_status(config, task_runner, queues)
    else:
        _print_overview_status(config, status)

    return 0


def _print_overview_status(config, status):
    """Print overview status (summary counts)."""
    print(f"\nTask Source Directories: {len(status['sources'])}")

    print(f"\n📋 Overall Statistics:")
    print(f"   Pending:   {status['pending']}")
    print(f"   Completed: {status['completed']}")
    print(f"   Failed:    {status['failed']}")

    print(f"\n📁 Per-Source Summary:")
    for source_id, source_stats in status['sources'].items():
        queue = config.get_queue(source_id)
        running = get_locked_task(Path(queue.path))
        status_indicator = "🔄 Running" if running else "✅ Idle"
        print(f"\n  📁 {source_id} ({status_indicator})")
        if queue:
            print(f"      Path: {queue.path}")
        if running:
            print(f"      Running: {running}")
        print(f"      Pending: {source_stats['pending']}, "
              f"Completed: {source_stats['completed']}, Failed: {source_stats['failed']}")


def _print_detailed_status(config, task_runner, queues):
    """Print detailed status with task lists."""
    print(f"\nTask Source Directories: {len(queues)}")

    for queue in queues:
        queue_path = Path(queue.path)
        print(f"\n{'=' * 60}")
        print(f"📁 Source: {queue.id}")
        print(f"{'=' * 60}")
        print(f"Path: {queue.path}")
        if queue.description:
            print(f"Description: {queue.description}")

        # Check for running task
        running_task = get_locked_task(queue_path)
        if running_task:
            lock_file = queue_path / f".{running_task}.lock"
            lock_info = LockInfo.from_file(lock_file)
            print(f"\n🔄 Running Task:")
            print(f"   Task ID: {running_task}")
            if lock_info:
                print(f"   Worker: {lock_info.worker}")
                print(f"   Started: {lock_info.started_at}")
        else:
            print(f"\n✅ Idle (no running tasks)")

        # List pending tasks
        pending_tasks = sorted(queue_path.glob("task-*.md"))
        if pending_tasks:
            print(f"\n📋 Pending Tasks ({len(pending_tasks)}):")
            for task in pending_tasks[:10]:  # Show first 10
                print(f"   - {task.name}")
            if len(pending_tasks) > 10:
                print(f"   ... and {len(pending_tasks) - 10} more")
        else:
            print(f"\n📭 No pending tasks")

        # Count completed and failed
        # Get base directory from source path (parent of pending/)
        base = queue_path.parent

        completed = list((base / "completed").glob("task-*.md")) if (base / "completed").exists() else []
        failed = list((base / "failed").glob("task-*.md")) if (base / "failed").exists() else []

        print(f"\n📊 Statistics:")
        print(f"   Completed: {len(completed)}")
        print(f"   Failed: {len(failed)}")

        if completed:
            print(f"\n✅ Recently Completed:")
            for task in sorted(completed, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                mtime = p.stat().st_mtime
                from datetime import datetime
                print(f"   - {task.name} ({datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')})")


# =============================================================================
# SOURCES COMMANDS
# =============================================================================

def cmd_queues_list(args):
    """List Task Source Directories."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    print("\n📂 Task Source Directories:")

    if not config.queues:
        print("  (none)")
        return 0

    for queue in config.queues:
        running = get_locked_task(Path(queue.path))
        status_indicator = "🔄" if running else "✅"
        print(f"\n  {status_indicator} {queue.id}")
        print(f"      Path: {queue.path}")
        print(f"      Description: {queue.description or '(no description)'}")
        if running:
            print(f"      Running: {running}")
        print(f"      Added: {queue.added_at}")

    return 0


def cmd_queues_add(args):
    """Add a Queue."""
    try:
        config_manager = ConfigManager(args.config)

        if not config_manager.config.project_workspace:
            config_manager.set_project_workspace(args.project_workspace)

        queue = config_manager.add_queue(
            path=args.queue_path,
            id=args.id,  # Fixed: was args.queue_id, but argument is --id
            description=args.description or ""
        )

        config_manager.save_config()

        print(f"\n✅ Added Queue '{args.id}'")  # Fixed: was args.queue_id
        print(f"   Path: {args.queue_path}")
        print(f"   Workspace: {args.project_workspace}")

        # Count existing tasks
        queue_path = Path(args.queue_path)
        if queue_path.exists():
            task_files = list(queue_path.glob("task-*.md"))
            if task_files:
                print(f"\n📋 Found {len(task_files)} task documents in directory")
            else:
                print(f"\n📭 No task documents found yet")

        _restart_daemon()

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_queues_rm(args):
    """Remove a Queue."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config

        queue = config.get_queue(args.queue_id)
        if not queue:
            print(f"❌ Queue '{args.queue_id}' not found")
            return 1

        if config.remove_queue(args.queue_id):
            config_manager.save_config()
            print(f"✅ Removed Queue '{args.queue_id}'")
            _restart_daemon()
            return 0
        else:
            print(f"❌ Failed to remove Queue '{args.queue_id}'")
            return 1

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


# =============================================================================
# TASKS COMMANDS
# =============================================================================

def _find_task_file(task_id: str, config) -> Path:
    """Find a task file by ID in any source directory."""
    for queue in config.queues:
        queue_path = Path(queue.path)
        # Check in task-documents
        task_file = queue_path / f"{task_id}.md"
        if task_file.exists():
            return task_file
        # Check in archive
        # Get base directory from source path (parent of pending/)
        base = queue_path.parent
        for subdir in ["completed", "failed"]:
            task_file = base / subdir / f"{task_id}.md"
            if task_file.exists():
                return task_file
    return None


def cmd_tasks_show(args):
    """Show task document path (simple output with reminder)."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    task_file = _find_task_file(args.task_id, config)

    if not task_file:
        print(f"❌ Task '{args.task_id}' not found")
        return 1

    print(f"\n📄 Task document: {task_file}")
    print(f"\n💡 Use 'cat {task_file}' or 'less {task_file}' to view full details")

    return 0


def cmd_tasks_logs(args):
    """Show task result log path (simple output with reminder)."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    workspace = Path(config.project_workspace)

    # Try to find result JSON file
    result_dirs = [
        workspace / "tasks" / "ad-hoc" / "results",
        workspace / "tasks" / "planned" / "results",
        workspace / "tasks" / "results",
    ]

    result_file = None
    for result_dir in result_dirs:
        potential = result_dir / f"{args.task_id}.json"
        if potential.exists():
            result_file = potential
            break

    if not result_file:
        print(f"❌ No result logs found for task '{args.task_id}'")
        print(f"   Task may not have been executed yet")
        return 1

    # Read basic info from result
    try:
        import json
        with open(result_file, 'r') as f:
            result_data = json.load(f)

        print(f"\n📋 Task: {args.task_id}")
        print(f"Status: {'✅ Success' if result_data.get('success') else '❌ Failed'}")
        if result_data.get('started_at'):
            print(f"Started: {result_data['started_at']}")
        if result_data.get('completed_at'):
            print(f"Completed: {result_data['completed_at']}")
        if result_data.get('duration_ms'):
            print(f"Duration: {result_data['duration_ms'] / 1000:.1f} seconds")
    except Exception:
        pass  # Just show path if we can't read the file

    print(f"\n💾 Full result logs: {result_file}")
    print(f"\n💡 Use 'cat {result_file}' or 'jq . {result_file}' to view full details")

    return 0


def cmd_tasks_cancel(args):
    """Cancel a running task."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    # Find the task
    task_file = _find_task_file(args.task_id, config)

    if not task_file:
        print(f"❌ Task '{args.task_id}' not found")
        return 1

    # Check if task has a lock file
    lock_file = get_lock_file_path(task_file)

    if not lock_file.exists():
        print(f"❌ Task '{args.task_id}' is not running")
        print(f"   Only running tasks can be cancelled")
        return 1

    # Read lock info
    lock_info = LockInfo.from_file(lock_file)
    if not lock_info:
        print(f"❌ Invalid lock file")
        return 1

    # Check if process is still running
    if os.path.exists(f"/proc/{lock_info.pid}"):
        print(f"\n🛑 Cancelling task: {args.task_id}")
        print(f"   Worker: {lock_info.worker}")
        print(f"   PID: {lock_info.pid}")

        # We can't actually cancel the SDK task, but we can mark it as cancelled
        # by moving it to failed and removing the lock
        try:
            lock_file.unlink()
            print(f"✅ Lock file removed")

            # Move task to failed directory
            # Get base directory from task file's parent directory
            failed_dir = task_file.parent.parent / "failed"

            failed_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.move(str(task_file), str(failed_dir / task_file.name))

            print(f"✅ Task moved to failed directory")
            print(f"   Reason: User cancelled")
            return 0
        except Exception as e:
            print(f"❌ Failed to cancel task: {e}")
            return 1
    else:
        # Stale lock - clean it up
        print(f"⚠️  Task has stale lock (process no longer running)")
        print(f"   Cleaning up stale lock...")
        try:
            lock_file.unlink()
            print(f"✅ Stale lock removed")
        except Exception as e:
            print(f"❌ Failed to remove stale lock: {e}")
        return 1


# =============================================================================
# WORKERS COMMANDS
# =============================================================================

def cmd_workers_status(args):
    """Show worker activity status."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    if not config.project_workspace:
        print("❌ No Project Workspace set")
        return 1

    print("=" * 60)
    print("👷 Worker Status")
    print("=" * 60)

    print(f"\nProject Workspace: {config.project_workspace}")

    queues = config.queues
    if not queues:
        print("\n⚠️  No Task Source Directories configured")
        return 0

    print(f"\nActive Workers: {len(queues)}")

    for queue in queues:
        queue_path = Path(queue.path)
        running_task = get_locked_task(queue_path)

        print(f"\n┌─────────────────────────────────────────────────────────────┐")
        print(f"│ Worker: {queue.id}")
        print(f"├─────────────────────────────────────────────────────────────┤")

        if running_task:
            lock_file = queue_path / f".{running_task}.lock"
            lock_info = LockInfo.from_file(lock_file)

            print(f"│ State: 🔄 RUNNING (Executing task)")
            if lock_info:
                print(f"│ Thread ID: {lock_info.thread_id}")
                from datetime import datetime
                started = datetime.fromisoformat(lock_info.started_at)
                elapsed = (datetime.now() - started).total_seconds()
                print(f"│ Current Task: {running_task}")
                print(f"│ Started: {lock_info.started_at}")
                print(f"│ Elapsed: {int(elapsed // 60)}m {int(elapsed % 60)}s")
        else:
            print(f"│ State: ✅ IDLE (Waiting for tasks)")

        # Count tasks in this source
        pending = len(list(queue_path.glob("task-*.md")))

        # Get base directory from source path (parent of pending/)
        base = queue_path.parent

        archive = base / "completed"
        failed = base / "failed"

        completed = len(list(archive.glob("task-*.md"))) if archive.exists() else 0
        failed_count = len(list(failed.glob("task-*.md"))) if failed.exists() else 0

        print(f"│")
        print(f"│ Tasks Processed: {completed + failed_count}")
        print(f"│ Pending: {pending} | Completed: {completed} | Failed: {failed_count}")

        print(f"└─────────────────────────────────────────────────────────────┘")

    # Summary
    running_count = sum(1 for sd in queues if get_locked_task(Path(sd.path)))
    idle_count = len(queues) - running_count

    print(f"\nSummary:")
    print(f"   Total Workers: {len(queues)}")
    print(f"   Running: {running_count}")
    print(f"   Idle: {idle_count}")

    return 0


def cmd_workers_list(args):
    """List all workers."""
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config
    except Exception as e:
        print(f"❌ Error loading configuration: {e}", file=sys.stderr)
        return 1

    print("\n👷 Workers:")

    queues = config.queues
    if not queues:
        print("  (none)")
        return 0

    for queue in queues:
        running_task = get_locked_task(Path(queue.path))
        status = "🔄 Running" if running_task else "✅ Idle"
        print(f"\n  {status} {queue.id}")
        print(f"      Path: {queue.path}")
        if running_task:
            print(f"      Current Task: {running_task}")

    return 0


# =============================================================================
# LOGS COMMAND
# =============================================================================

def cmd_logs(args):
    """Show daemon logs."""
    import subprocess

    follow = "--follow" if args.follow else ""

    if args.lines:
        result = subprocess.run(
            ["journalctl", "--user", "-u", "task-queue.service", "-n", str(args.lines), "--no-pager"],
            capture_output=False
        )
    else:
        if follow:
            print("Showing live logs (Ctrl+C to exit)...")
        subprocess.run(
            f"journalctl --user -u task-queue.service {follow} --no-pager",
            shell=True,
            capture_output=False
        )

    return 0


# =============================================================================
# RUN COMMAND (testing)
# =============================================================================

def cmd_run(args):
    """Run task queue interactively (for testing)."""
    import time

    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.config

        if not config.project_workspace:
            print("❌ No Project Workspace set")
            return 1

        task_runner = TaskRunner(project_workspace=config.project_workspace)
        queues = config.queues

        print("=" * 60)
        print("🔄 Running Task Queue (Interactive Mode)")
        print("=" * 60)
        print(f"Configuration: {args.config}")
        print(f"Task Source Directories: {len(queues)}")
        print()

        cycles = args.cycles if args.cycles > 0 else 999999

        for cycle in range(cycles):
            print(f"\n--- Cycle {cycle + 1} ---")

            task_file = task_runner.pick_next_task(queues)

            if task_file:
                print(f"Found task: {task_file.name}")

                # Determine worker from task path
                rel_path = task_file.relative_to(config.project_workspace)
                worker = "ad-hoc" if "ad-hoc" in str(rel_path) else "planned"

                result = task_runner.execute_task(task_file, worker=worker)
                print(f"Status: {result['status']}")
                if result.get("error"):
                    print(f"Error: {result['error']}")
            else:
                print("No pending tasks")

            status = task_runner.get_status(queues)
            if status['pending'] == 0:
                print("\n✅ All tasks processed")
                break

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1

    return 0


# =============================================================================
# MAIN
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Task Queue CLI (Directory-Based State)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize task system
  task-queue init

  # Show status
  task-queue status
  task-queue status --detailed

  # Manage sources
  task-queue sources list
  task-queue sources add /path/to/tasks --id my-queue
  task-queue sources rm my-queue

  # Task operations
  task-queue tasks show task-20260207-123456
  task-queue tasks logs task-20260207-123456
  task-queue tasks cancel task-20260207-123456

  # Worker operations
  task-queue workers status
  task-queue workers list

  # View logs
  task-queue logs
  task-queue logs --follow

  # Run interactively
  task-queue run --cycles 5
        """
    )

    parser.add_argument("--config", type=Path, default=None, help="Path to configuration file")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize task system")
    init_parser.add_argument("--force", action="store_true", help="Re-initialize completely")
    init_parser.add_argument("--skip-existing", action="store_true", help="Skip existing queues")
    init_parser.add_argument("--restart-daemon", action="store_true", help="Restart daemon after init")
    init_parser.set_defaults(func=cmd_init)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show system status")
    status_parser.add_argument("--detailed", action="store_true", help="Show detailed task lists")
    status_parser.set_defaults(func=cmd_status)

    # Queues subcommands
    queues_parser = subparsers.add_parser("queues", help="Manage task queues")
    queues_subparsers = queues_parser.add_subparsers(dest="queues_command", help="Queues commands")

    queues_list_parser = queues_subparsers.add_parser("list", help="List queues")
    queues_list_parser.set_defaults(func=cmd_queues_list)

    queues_add_parser = queues_subparsers.add_parser("add", help="Add a queue")
    queues_add_parser.add_argument("queue_path", help="Path to queue directory")
    queues_add_parser.add_argument("--id", required=True, help="Unique ID for this queue")
    queues_add_parser.add_argument("--project-workspace", help="Path to project workspace")
    queues_add_parser.add_argument("--description", help="Description of this queue")
    queues_add_parser.set_defaults(func=cmd_queues_add)

    queues_rm_parser = queues_subparsers.add_parser("rm", help="Remove a queue")
    queues_rm_parser.add_argument("--queue-id", required=True, help="Queue ID to remove")
    queues_rm_parser.set_defaults(func=cmd_queues_rm)

    # Tasks subcommands
    tasks_parser = subparsers.add_parser("tasks", help="Manage tasks")
    tasks_subparsers = tasks_parser.add_subparsers(dest="tasks_command", help="Tasks commands")

    tasks_show_parser = tasks_subparsers.add_parser("show", help="Show task document path")
    tasks_show_parser.add_argument("task_id", help="Task ID")
    tasks_show_parser.set_defaults(func=cmd_tasks_show)

    tasks_logs_parser = tasks_subparsers.add_parser("logs", help="Show task result logs")
    tasks_logs_parser.add_argument("task_id", help="Task ID")
    tasks_logs_parser.set_defaults(func=cmd_tasks_logs)

    tasks_cancel_parser = tasks_subparsers.add_parser("cancel", help="Cancel a running task")
    tasks_cancel_parser.add_argument("task_id", help="Task ID to cancel")
    tasks_cancel_parser.set_defaults(func=cmd_tasks_cancel)

    # Workers subcommands
    workers_parser = subparsers.add_parser("workers", help="Manage workers")
    workers_subparsers = workers_parser.add_subparsers(dest="workers_command", help="Workers commands")

    workers_status_parser = workers_subparsers.add_parser("status", help="Show worker status")
    workers_status_parser.set_defaults(func=cmd_workers_status)

    workers_list_parser = workers_subparsers.add_parser("list", help="List workers")
    workers_list_parser.set_defaults(func=cmd_workers_list)

    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Show daemon logs")
    logs_parser.add_argument("--follow", "-f", action="store_true", help="Follow log output")
    logs_parser.add_argument("--lines", "-n", type=int, help="Number of lines to show")
    logs_parser.set_defaults(func=cmd_logs)

    # Run command
    run_parser = subparsers.add_parser("run", help="Run interactively (testing)")
    run_parser.add_argument("--cycles", type=int, default=0, help="Number of cycles")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()

    if not args.config:
        args.config = DEFAULT_CONFIG_FILE

    if hasattr(args, 'func'):
        return args.func(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
