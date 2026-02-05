"""
Task queue monitor for per-source processing.

Orchestrates task loading and execution with watchdog support.
"""

import time
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from task_queue.models import (
    QueueConfig, SystemStatus, TaskSourceDirectory,
    TaskSourceDirectoryStatus, TaskSource
)
from task_queue.config import ConfigManager
from task_queue.scanner import TaskScanner
from task_queue.processor import TaskProcessor


class TaskQueue:
    """
    Task queue for per-source processing.

    Manages task loading from multiple Task Source Directories
    with per-source queues and round-robin execution.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None
    ):
        """
        Initialize task queue.

        Args:
            config_manager: Configuration manager (creates default if None)
        """
        self.config_manager = config_manager or ConfigManager()
        self.scanner = TaskScanner()

        # Processor (created when needed)
        self._processor: Optional[TaskProcessor] = None

        # State
        self._running = False
        self._start_time: Optional[datetime] = None
        self._load_count = 0
        self._last_load: Optional[datetime] = None

    def get_processor(self) -> Optional[TaskProcessor]:
        """Get or create task processor."""
        project_workspace = self.config_manager.config.project_workspace

        if not project_workspace:
            return None

        if self._processor is None:
            # Define paths (in ~/.config/task-queue/)
            config_dir = self.config_manager.config_file.parent
            state_dir = config_dir / "state"

            state_dir.mkdir(parents=True, exist_ok=True)

            state_file = state_dir / "queue_state.json"

            self._processor = TaskProcessor(
                project_workspace=project_workspace,
                state_file=state_file,
                scanner=self.scanner
            )

        return self._processor

    def load_tasks(self) -> Dict[str, int]:
        """
        Load tasks from configured Task Source Directories.

        Returns:
            Dict mapping source_id to new task count
        """
        processor = self.get_processor()

        if not processor:
            print("⚠️  No Project Workspace set. Use 'task-queue load <task-source-dir> <project-workspace>'")
            return {}

        source_dirs = self.config_manager.config.task_source_directories

        if not source_dirs:
            print("⚠️  No Task Source Directories configured")
            return {}

        print(f"\n📂 Scanning Task Source Directories...")

        for source_dir in source_dirs:
            print(f"  - {source_dir.id}: {source_dir.path}")

        print()

        # Load tasks (processor scans all Task Source Directories)
        new_count = processor.load_tasks(source_dirs, source=TaskSource.LOAD)

        self._load_count += 1
        self._last_load = datetime.now()

        return {"total": new_count}

    def load_single_task(
        self,
        task_doc_file: str,
        task_source_dir: str,
        project_workspace: str
    ) -> bool:
        """
        Load a single Task Document.

        Args:
            task_doc_file: Path to Task Document file
            task_source_dir: Task Source Directory ID
            project_workspace: Project Workspace path

        Returns:
            True if loaded successfully
        """
        # Set project workspace if provided
        if project_workspace:
            try:
                self.config_manager.set_project_workspace(project_workspace)
            except Exception as e:
                print(f"❌ Error setting Project Workspace: {e}")
                return False

        processor = self.get_processor()

        if not processor:
            print("⚠️  No Project Workspace set")
            return False

        # Register source directory if needed
        source_dir = self.config_manager.get_task_source_directory(task_source_dir)
        if not source_dir:
            # Auto-register source directory
            source_path = str(Path(task_doc_file).parent)
            try:
                source_dir = self.config_manager.add_task_source_directory(
                    path=source_path,
                    id=task_source_dir,
                    description=f"Auto-registered for {task_doc_file}"
                )
                print(f"✅ Registered Task Source Directory '{task_source_dir}': {source_path}")
            except Exception as e:
                print(f"❌ Error registering source directory: {e}")
                return False

        # Load single task
        result = processor.load_single_task(
            task_doc_file=task_doc_file,
            source_id=task_source_dir,
            source=TaskSource.MANUAL
        )

        if result:
            self._load_count += 1
            self._last_load = datetime.now()

        return result

    def reload_source(
        self,
        task_source_dir: str,
        project_workspace: str
    ) -> int:
        """
        Force re-scan a Task Source Directory.

        Args:
            task_source_dir: Task Source Directory ID or path
            project_workspace: Project Workspace path

        Returns:
            Number of tasks (re)loaded
        """
        # Set project workspace
        try:
            self.config_manager.set_project_workspace(project_workspace)
        except Exception as e:
            print(f"❌ Error setting Project Workspace: {e}")
            return 0

        processor = self.get_processor()

        if not processor:
            print("⚠️  No Project Workspace set")
            return 0

        # Get source directory
        source_dir = self.config_manager.get_task_source_directory(task_source_dir)

        if not source_dir:
            # Try path as a directory
            source_path = Path(task_source_dir)
            if not source_path.exists():
                print(f"❌ Task Source Directory not found: {task_source_dir}")
                return 0

            # Create temporary source for scanning
            source_dir = TaskSourceDirectory(
                id="<temp>",
                path=str(source_path)
            )

        print(f"\n📂 Reloading tasks from: {source_dir.path}")

        # Scan and load
        discovered = self.scanner.scan_task_source_directory(source_dir)

        loaded_count = 0
        for task in discovered:
            if processor.load_single_task(
                str(task.task_doc_file),
                task_source_dir,
                source=TaskSource.RELOAD
            ):
                loaded_count += 1

        if loaded_count > 0:
            self._load_count += 1
            self._last_load = datetime.now()
            print(f"✅ Reloaded {loaded_count} tasks")
        else:
            print(f"📭 No tasks found")

        return loaded_count

    def unload_source(self, task_source_dir: str) -> int:
        """
        Remove ALL tasks from a Task Source Directory.

        Args:
            task_source_dir: Task Source Directory ID

        Returns:
            Number of tasks removed
        """
        processor = self.get_processor()

        if not processor:
            print("⚠️  No processor available")
            return 0

        removed_count = processor.unload_source(task_source_dir)

        if removed_count > 0:
            print(f"✅ Removed {removed_count} tasks from '{task_source_dir}'")
        else:
            print(f"⚠️  No tasks found for '{task_source_dir}'")

        return removed_count

    def process_tasks(self, max_tasks: Optional[int] = None) -> dict:
        """
        Process pending tasks.

        Args:
            max_tasks: Maximum tasks to process

        Returns:
            Processing result
        """
        processor = self.get_processor()

        if not processor:
            return {
                "status": "error",
                "error": "No Project Workspace configured"
            }

        print(f"\n🔧 Processing tasks...")

        result = processor.process_tasks(max_tasks=max_tasks)

        status = result.get("status", "unknown")

        if status == "completed":
            processed = result.get("processed", 0)
            failed = result.get("failed", 0)
            remaining = result.get("remaining", 0)
            print(f"  ✅ Processed: {processed} completed, {failed} failed")
            if remaining > 0:
                print(f"  📋 Remaining: {remaining} tasks")

        elif status == "empty":
            print(f"  ⏭️  No pending tasks")

        elif status == "skipped":
            reason = result.get("reason", "unknown")
            print(f"  ⏸️  Skipped ({reason})")

        return result

    def run_single_cycle(self) -> Dict[str, dict]:
        """
        Run a single monitoring cycle.

        This is for manual processing - daemon uses process_tasks directly.

        Returns:
            Processing results
        """
        print(f"\n{'='*60}")
        print(f"🔄 Task Queue Cycle")
        print(f"{'='*60}")

        # Process only (no auto-loading)
        result = self.process_tasks()

        print()

        return {"process": result}

    def run(self, cycles: Optional[int] = None) -> None:
        """
        Run the task queue loop.

        Args:
            cycles: Number of cycles to run (None = infinite)
        """
        self._running = True
        self._start_time = datetime.now()

        print(f"\n🎯 Task Queue Started")
        print(f"   Project Workspace: {self.config_manager.config.project_workspace}")
        print(f"   Task Source Directories: {len(self.config_manager.config.task_source_directories)}")
        print(f"   Cycles: {'infinite' if cycles is None else cycles}")

        cycle = 0

        try:
            while self._running:
                if cycles is not None and cycle >= cycles:
                    break

                cycle += 1

                # Process tasks (no auto-scanning)
                self.process_tasks()

                # Check if we should continue
                if cycles is not None and cycle >= cycles:
                    break

                # Check if there are more tasks
                processor = self.get_processor()
                if processor and processor.state.get_total_pending_count() == 0:
                    print(f"\n📭 No more pending tasks")
                    break

        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")

        finally:
            self._running = False
            print(f"\n🛑 Task Queue Stopped")

    def stop(self) -> None:
        """Stop the task queue."""
        self._running = False

    def get_status(self) -> SystemStatus:
        """Get overall system status."""
        status = SystemStatus()

        status.running = self._running

        if self._start_time and self._running:
            status.uptime_seconds = (datetime.now() - self._start_time).total_seconds()

        status.load_count = self._load_count
        status.last_load_at = self._last_load.isoformat() if self._last_load else None

        # Project info
        status.project_workspace = self.config_manager.config.project_workspace

        # Task Source Directories
        source_dirs = self.config_manager.config.task_source_directories
        status.total_task_source_dirs = len(source_dirs)
        status.active_task_source_dirs = len(source_dirs)

        # Queue stats
        processor = self.get_processor()
        if processor:
            proc_status = processor.get_status()
            stats = proc_status.get("queue_stats", {})

            status.total_pending = stats.get("pending", 0)
            status.total_running = stats.get("running", 0)
            status.total_completed = stats.get("completed", 0)
            status.total_failed = stats.get("failed", 0)

        return status

    def get_task_source_directory_status(self) -> List[TaskSourceDirectoryStatus]:
        """Get status for all Task Source Directories."""
        statuses = []

        processor = self.get_processor()

        for source_dir in self.config_manager.config.task_source_directories:
            queue_stats = {}

            # Count tasks from this Task Source Directory
            if processor:
                source_state = processor.get_source_state(source_dir.id)
                if source_state:
                    queue_stats = {
                        "pending": source_state.get_pending_count(),
                        "running": source_state.get_running_count(),
                        "completed": source_state.get_completed_count(),
                        "failed": source_state.get_failed_count(),
                    }

            statuses.append(TaskSourceDirectoryStatus(
                id=source_dir.id,
                path=source_dir.path,
                description=source_dir.description,
                queue_stats=queue_stats
            ))

        return statuses


def create_queue(
    config_file: Optional[Path] = None
) -> TaskQueue:
    """
    Create a configured task queue.

    Args:
        config_file: Path to configuration file

    Returns:
        Configured TaskQueue
    """
    config_manager = ConfigManager(config_file)

    return TaskQueue(config_manager=config_manager)
