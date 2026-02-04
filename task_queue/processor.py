"""
Task processor for sequential execution.

Handles task queue and execution for a single project path.
"""

import shutil
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from task_queue.models import (
    Task, TaskStatus, QueueState, Statistics,
    DiscoveredTask, ProcessingState
)
from task_queue.atomic import AtomicFileWriter, FileLock
from task_queue.scanner import TaskScanner
from task_queue.executor import SyncTaskExecutor


class TaskProcessor:
    """
    Sequential task processor.

    Manages a FIFO queue of tasks and executes them one at a time
    using the Claude Agent SDK.
    """

    def __init__(
        self,
        project_path: str,
        state_file: Path,
        scanner: Optional[TaskScanner] = None
    ):
        """
        Initialize task processor.

        Args:
            project_path: Path to project root (used as cwd)
            state_file: Path to queue state file
            scanner: Task scanner (optional, for auto-discovery)
        """
        self.project_path = Path(project_path).resolve()
        self.state_file = Path(state_file)
        self.scanner = scanner or TaskScanner()

        # Create directories
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Create archive directory
        self.archive_dir = self.project_path / "tasks" / "task-archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        # Lock
        self.lock = FileLock(self.state_file.with_suffix('.lock'))

        # Load state
        self.state = self._load_state()

        # Create executor
        self.executor = SyncTaskExecutor(self.project_path)

    def _load_state(self) -> QueueState:
        """Load queue state from disk."""
        data = AtomicFileWriter.read_json(self.state_file)

        if data is None:
            return self._create_default_state()

        try:
            return QueueState(**data)
        except Exception:
            return self._create_default_state()

    def _create_default_state(self) -> QueueState:
        """Create default queue state."""
        return QueueState(version="1.0")

    def _save_state(self) -> None:
        """Save queue state atomically."""
        self.state.updated_at = datetime.now().isoformat()
        AtomicFileWriter.write_json(self.state_file, self.state.model_dump(), indent=2)

    def load_tasks(self, spec_dirs: List) -> int:
        """
        Scan spec directories and add new tasks to queue.

        Args:
            spec_dirs: List of SpecDirectory configurations

        Returns:
            Number of new tasks discovered
        """
        # Scan all spec directories
        discovered = self.scanner.scan_spec_directories(spec_dirs)

        new_count = 0

        for task in discovered:
            if self._add_to_queue(task):
                new_count += 1

        if new_count > 0:
            self.state.statistics.last_load_at = datetime.now().isoformat()
            self._save_state()
            print(f"  📥 Loaded {new_count} new tasks")

        return new_count

    def _add_to_queue(self, discovered: DiscoveredTask) -> bool:
        """
        Add a discovered task to the queue.

        Args:
            discovered: Discovered task

        Returns:
            True if added, False if already exists
        """
        # Check if task already exists in queue
        for task in self.state.queue:
            if task.task_id == discovered.task_id:
                # Update file hash if changed
                if self.scanner.is_file_modified(
                    discovered.spec_file,
                    task.file_hash
                ):
                    task.file_hash = discovered.file_hash
                    task.file_size = discovered.file_size
                    # Re-queue if was completed
                    if task.status == TaskStatus.COMPLETED:
                        task.status = TaskStatus.PENDING
                        task.started_at = None
                        task.completed_at = None
                        task.error = None
                        self._save_state()
                        return True
                return False

        # Add new task to queue
        task = Task(
            task_id=discovered.task_id,
            spec_file=str(discovered.spec_file),
            spec_dir_id=discovered.spec_dir_id,
            source="load",
            file_hash=discovered.file_hash,
            file_size=discovered.file_size
        )

        self.state.queue.append(task)
        self.state.statistics.total_queued += 1

        return True

    def process_tasks(self, max_tasks: Optional[int] = None) -> dict:
        """
        Process pending tasks sequentially.

        Args:
            max_tasks: Maximum tasks to process (None = unlimited)

        Returns:
            Processing summary dict
        """
        # Reload state from disk to get latest changes
        self.state = self._load_state()

        # Try to acquire lock
        if not self.lock.acquire(timeout=0.5):
            return {
                "status": "skipped",
                "reason": "locked"
            }

        try:
            # Get pending tasks
            pending = [t for t in self.state.queue if t.status == TaskStatus.PENDING]

            if not pending:
                return {
                    "status": "empty",
                    "processed": 0,
                    "failed": 0,
                    "remaining": 0
                }

            # Limit batch size
            if max_tasks:
                pending = pending[:max_tasks]

            print(f"  🔧 Processing {len(pending)} tasks")

            processed = 0
            failed = 0

            for task in pending:
                if max_tasks and processed >= max_tasks:
                    break

                result = self._process_single_task(task)

                if result == TaskStatus.COMPLETED:
                    processed += 1
                else:
                    failed += 1

            remaining = len([t for t in self.state.queue if t.status == TaskStatus.PENDING])

            return {
                "status": "completed",
                "processed": processed,
                "failed": failed,
                "remaining": remaining
            }

        finally:
            self.lock.release()

    def _process_single_task(self, task: Task) -> TaskStatus:
        """
        Process a single task.

        Args:
            task: Task to process

        Returns:
            Final task status
        """
        # Update state to running
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()
        task.attempts += 1

        # Update processing state
        self.state.processing = ProcessingState(
            is_processing=True,
            current_task=task.task_id,
            process_id=None,
            started_at=task.started_at,
            hostname=None
        )

        self._save_state()

        try:
            # Execute task
            result = self.executor.execute(task, project_root=self.project_path)

            # Update task with result
            task.status = result.status
            task.completed_at = result.completed_at
            task.error = result.error

            # Update statistics
            if result.status == TaskStatus.COMPLETED:
                self.state.statistics.total_completed += 1
            else:
                self.state.statistics.total_failed += 1

            self.state.statistics.last_processed_at = result.completed_at

            # Archive completed task spec
            if result.status == TaskStatus.COMPLETED:
                self._archive_task_spec(task)

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now().isoformat()
            task.error = str(e)
            self.state.statistics.total_failed += 1

        finally:
            # Clear processing state
            self.state.processing = ProcessingState()
            self._save_state()

        return task.status

    def _archive_task_spec(self, task: Task) -> None:
        """
        Move completed task spec to archive.

        Args:
            task: Completed task
        """
        spec_file = Path(task.spec_file)

        if not spec_file.exists():
            return

        # Move file
        target = self.archive_dir / spec_file.name

        try:
            shutil.move(str(spec_file), str(target))
        except Exception as e:
            print(f"  ⚠️  Could not archive {spec_file.name}: {e}")

    def get_status(self) -> dict:
        """Get current status."""
        return {
            "project_path": str(self.project_path),
            "queue_stats": {
                "total": len(self.state.queue),
                "pending": self.state.get_pending_count(),
                "running": self.state.get_running_count(),
                "completed": self.state.get_completed_count(),
                "failed": self.state.get_failed_count()
            },
            "is_processing": self.state.processing.is_processing,
            "current_task": self.state.processing.current_task,
            "statistics": self.state.statistics.model_dump()
        }

    def get_queue(self) -> List[Task]:
        """Get all tasks in queue."""
        return self.state.queue.copy()

    def clear_completed(self, older_than_days: int = 7) -> int:
        """
        Remove completed tasks from queue.

        Args:
            older_than_days: Only remove tasks completed more than this many days ago

        Returns:
            Number of tasks removed
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=older_than_days)
        removed = 0

        new_queue = []

        for task in self.state.queue:
            if task.status == TaskStatus.COMPLETED:
                if task.completed_at:
                    completed_dt = datetime.fromisoformat(task.completed_at)
                    if completed_dt < cutoff:
                        removed += 1
                        continue

            new_queue.append(task)

        self.state.queue = new_queue
        self._save_state()

        return removed
