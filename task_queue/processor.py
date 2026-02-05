"""
Task processor for per-source sequential execution.

Handles task queue and execution with per-source architecture:
- Each Task Source Directory has its own queue
- Tasks within same source execute sequentially (FIFO)
- Tasks from different sources can execute in parallel
- Source Coordinator provides round-robin scheduling
"""

import shutil
import socket
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from threading import Lock

from task_queue.models import (
    Task, TaskStatus, TaskSource,
    QueueState, SourceState, SourceProcessingState,
    SourceStatistics, DiscoveredTask, TaskSourceDirectory
)
from task_queue.atomic import AtomicFileWriter, FileLock
from task_queue.scanner import TaskScanner
from task_queue.executor import SyncTaskExecutor
from task_queue.coordinator import SourceCoordinator


class TaskProcessor:
    """
    Per-source task processor.

    Manages multiple task queues (one per Task Source Directory) with:
    - Sequential execution within each source
    - Parallel execution across sources
    - Round-robin coordinator for fair scheduling
    """

    def __init__(
        self,
        project_workspace: str,
        state_file: Path,
        scanner: Optional[TaskScanner] = None
    ):
        """
        Initialize task processor.

        Args:
            project_workspace: Path to project root (used as cwd for SDK execution)
            state_file: Path to queue state file
            scanner: Task scanner (optional, for auto-discovery)
        """
        self.project_workspace = Path(project_workspace).resolve()
        self.state_file = Path(state_file)
        self.scanner = scanner or TaskScanner()

        # Create directories
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Create archive directory
        self.archive_dir = self.project_workspace / "tasks" / "task-archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        # State file lock (for loading/saving state)
        self.state_lock = FileLock(self.state_file.with_suffix('.lock'))

        # Per-source locks (for thread-safe queue operations)
        self._source_locks: Dict[str, Lock] = {}

        # Load state
        self.state = self._load_state()

        # Create coordinator
        self.coordinator = SourceCoordinator(self.state)

        # Create executor
        self.executor = SyncTaskExecutor(self.project_workspace)

    def _get_source_lock(self, source_id: str) -> Lock:
        """
        Get or create lock for a specific source.

        Args:
            source_id: Source ID

        Returns:
            Lock for this source
        """
        if source_id not in self._source_locks:
            self._source_locks[source_id] = Lock()

        return self._source_locks[source_id]

    def _load_state(self) -> QueueState:
        """Load queue state from disk with migration support."""
        data = AtomicFileWriter.read_json(self.state_file)

        if data is None:
            return self._create_default_state()

        try:
            # Check version for migration
            version = data.get("version", "1.0")

            if version == "1.0":
                # Migrate from v1.0 to v2.0
                return self._migrate_state_v1_to_v2(data)

            return QueueState(**data)
        except Exception:
            return self._create_default_state()

    def _migrate_state_v1_to_v2(self, v1_data: dict) -> QueueState:
        """
        Migrate state from version 1.0 to 2.0.

        v1.0 had a single global queue. v2.0 has per-source queues.

        Args:
            v1_data: Version 1.0 state data

        Returns:
            Version 2.0 QueueState
        """
        # Get all tasks from v1.0 queue
        old_queue = v1_data.get("queue", [])
        old_statistics = v1_data.get("statistics", {})

        # Create v2.0 state
        v2_state = QueueState(version="2.0")

        # Group tasks by source
        source_tasks: Dict[str, List[Task]] = {}

        for task_data in old_queue:
            task = Task(**task_data)
            source_id = task.task_doc_dir_id

            if source_id not in source_tasks:
                source_tasks[source_id] = []

            source_tasks[source_id].append(task)

        # Create source states
        for source_id, tasks in source_tasks.items():
            source_state = SourceState(
                id=source_id,
                path=f"<migrated>",  # Unknown path from migration
                queue=tasks,
                statistics=SourceStatistics(
                    total_queued=len(tasks),
                    total_completed=old_statistics.get("total_completed", 0),
                    total_failed=old_statistics.get("total_failed", 0),
                )
            )

            v2_state.sources[source_id] = source_state

        # Initialize coordinator
        v2_state.coordinator.source_order = list(source_tasks.keys())

        return v2_state

    def _create_default_state(self) -> QueueState:
        """Create default queue state (v2.0)."""
        return QueueState(version="2.0")

    def _save_state(self) -> None:
        """Save queue state atomically."""
        self.state.updated_at = datetime.now().isoformat()
        AtomicFileWriter.write_json(self.state_file, self.state.model_dump(), indent=2)

    def load_tasks(
        self,
        source_dirs: List[TaskSourceDirectory],
        source: TaskSource = TaskSource.MANUAL
    ) -> int:
        """
        Scan Task Source Directories and add new tasks to their respective queues.

        Args:
            source_dirs: List of Task Source Directory configurations
            source: How the tasks were discovered (MANUAL, WATCHDOG, RELOAD)

        Returns:
            Number of new tasks discovered
        """
        # Scan all Task Source Directories
        discovered = self.scanner.scan_task_source_directories(source_dirs)

        new_count = 0

        for task in discovered:
            if self._add_to_queue(task, source=source):
                new_count += 1

        if new_count > 0:
            # Update global statistics
            self.state.global_statistics.last_load_at = datetime.now().isoformat()

            # Save state
            self._save_state()

            print(f"  📥 Loaded {new_count} new tasks")

        return new_count

    def _add_to_queue(
        self,
        discovered: DiscoveredTask,
        source: TaskSource = TaskSource.MANUAL
    ) -> bool:
        """
        Add a discovered task to the appropriate source queue.

        Args:
            discovered: Discovered task
            source: How the task was discovered

        Returns:
            True if added, False if already exists
        """
        source_id = discovered.task_doc_dir_id

        # Get or create source state
        if source_id not in self.state.sources:
            self.state.sources[source_id] = SourceState(
                id=source_id,
                path=str(discovered.task_doc_file.parent),
                queue=[],
                processing=SourceProcessingState(),
                statistics=SourceStatistics()
            )
            # Add to coordinator order
            self.coordinator.add_source(source_id)

        source_state = self.state.sources[source_id]
        source_lock = self._get_source_lock(source_id)

        # Get file modification time
        last_modified = self.scanner.get_file_modification_time(discovered.task_doc_file)

        # Check if task already exists in queue
        with source_lock:
            for task in source_state.queue:
                if task.task_id == discovered.task_id:
                    # Update file info if changed
                    if self.scanner.is_file_modified(
                        discovered.task_doc_file,
                        task.file_hash
                    ):
                        task.file_hash = discovered.file_hash
                        task.file_size = discovered.file_size
                        task.last_modified = last_modified

                        # Re-queue if was completed
                        if task.status == TaskStatus.COMPLETED:
                            task.status = TaskStatus.PENDING
                            task.started_at = None
                            task.completed_at = None
                            task.error = None
                            task.source = source
                            self._save_state()
                            return True
                    return False

            # Add new task to source queue
            task = Task(
                task_id=discovered.task_id,
                task_doc_file=str(discovered.task_doc_file),
                task_doc_dir_id=discovered.task_doc_dir_id,
                source=source,
                file_hash=discovered.file_hash,
                file_size=discovered.file_size,
                last_modified=last_modified
            )

            source_state.queue.append(task)
            source_state.statistics.total_queued += 1
            source_state.updated_at = datetime.now().isoformat()

            # Update global statistics
            self.state.global_statistics.total_queued += 1

            return True

    def load_single_task(
        self,
        task_doc_file: str,
        source_id: str,
        source: TaskSource = TaskSource.MANUAL
    ) -> bool:
        """
        Load a single Task Document into the queue.

        Args:
            task_doc_file: Path to Task Document file
            source_id: Task Source Directory ID
            source: How the task was discovered

        Returns:
            True if loaded, False if already exists
        """
        filepath = Path(task_doc_file)

        # Validate task ID
        task_id = filepath.stem
        if not self._is_valid_task_id(task_id):
            return False

        # Create discovered task
        file_size = 0
        file_hash = None

        try:
            file_size = filepath.stat().st_size
            if file_size > 0:
                file_hash = self.scanner.calculate_hash(filepath)
        except OSError:
            return False

        last_modified = self.scanner.get_file_modification_time(filepath)

        discovered = DiscoveredTask(
            task_id=task_id,
            task_doc_file=filepath,
            task_doc_dir_id=source_id,
            file_hash=file_hash,
            file_size=file_size,
            discovered_at=datetime.now().isoformat()
        )

        result = self._add_to_queue(discovered, source=source)

        if result:
            self.state.global_statistics.last_load_at = datetime.now().isoformat()
            self._save_state()

        return result

    def unload_source(self, source_id: str) -> int:
        """
        Remove ALL tasks from a Task Source Directory.

        Cancels all pending/running tasks from this source.

        Args:
            source_id: Task Source Directory ID

        Returns:
            Number of tasks removed
        """
        if source_id not in self.state.sources:
            return 0

        source_state = self.state.sources[source_id]
        source_lock = self._get_source_lock(source_id)

        with source_lock:
            removed_count = len(source_state.queue)

            # Remove from coordinator
            self.coordinator.remove_source(source_id)

            # Remove from state
            del self.state.sources[source_id]

            # Update global counts
            self.state.global_statistics.total_queued -= removed_count

            self._save_state()

            return removed_count

    def process_tasks(self, max_tasks: Optional[int] = None) -> dict:
        """
        Process pending tasks using round-robin across sources.

        Args:
            max_tasks: Maximum tasks to process (None = unlimited)

        Returns:
            Processing summary dict
        """
        # Reload state from disk to get latest changes
        self.state = self._load_state()
        self.coordinator = SourceCoordinator(self.state)

        # Try to acquire state lock
        if not self.state_lock.acquire(timeout=0.5):
            return {
                "status": "skipped",
                "reason": "locked"
            }

        try:
            # Check total pending tasks
            total_pending = self.state.get_total_pending_count()

            if total_pending == 0:
                return {
                    "status": "empty",
                    "processed": 0,
                    "failed": 0,
                    "remaining": 0
                }

            print(f"  🔧 Processing {total_pending} tasks across {len(self.state.sources)} sources")

            processed = 0
            failed = 0
            tasks_processed = 0

            # Process tasks using round-robin
            while tasks_processed < max_tasks if max_tasks else True:
                # Get next task using coordinator
                result = self.coordinator.get_next_pending_task()

                if result is None:
                    # No more pending tasks
                    break

                task, source_id = result

                # Process the task
                status = self._process_single_task(task, source_id)

                if status == TaskStatus.COMPLETED:
                    processed += 1
                else:
                    failed += 1

                tasks_processed += 1

                # Check if source is complete
                self.coordinator.mark_source_complete(source_id)

            remaining = self.state.get_total_pending_count()

            return {
                "status": "completed",
                "processed": processed,
                "failed": failed,
                "remaining": remaining
            }

        finally:
            self.state_lock.release()

    def _process_single_task(self, task: Task, source_id: str) -> TaskStatus:
        """
        Process a single task from a specific source.

        Args:
            task: Task to process
            source_id: Source ID for this task

        Returns:
            Final task status
        """
        source_state = self.state.sources[source_id]
        source_lock = self._get_source_lock(source_id)

        with source_lock:
            # Update task to running
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now().isoformat()
            task.attempts += 1

            # Update source processing state
            source_state.processing = SourceProcessingState(
                is_processing=True,
                current_task=task.task_id,
                process_id=None,
                started_at=task.started_at,
                hostname=socket.gethostname()
            )

            self._save_state()

        try:
            # Execute task
            result = self.executor.execute(task, project_root=self.project_workspace)

            with source_lock:
                # Update task with result
                task.status = result.status
                task.completed_at = result.completed_at
                task.error = result.error

                # Update source statistics
                if result.status == TaskStatus.COMPLETED:
                    source_state.statistics.total_completed += 1
                    self.state.global_statistics.total_completed += 1
                else:
                    source_state.statistics.total_failed += 1
                    self.state.global_statistics.total_failed += 1

                source_state.statistics.last_processed_at = result.completed_at

                # Archive completed task doc
                if result.status == TaskStatus.COMPLETED:
                    self._archive_task_doc(task)

        except Exception as e:
            with source_lock:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now().isoformat()
                task.error = str(e)
                source_state.statistics.total_failed += 1
                self.state.global_statistics.total_failed += 1

        finally:
            with source_lock:
                # Clear source processing state
                source_state.processing = SourceProcessingState()
                source_state.updated_at = datetime.now().isoformat()
                self._save_state()

        return task.status

    def _archive_task_doc(self, task: Task) -> None:
        """
        Move completed Task Document to archive.

        Args:
            task: Completed task
        """
        doc_file = Path(task.task_doc_file)

        if not doc_file.exists():
            return

        # Move file
        target = self.archive_dir / doc_file.name

        try:
            shutil.move(str(doc_file), str(target))
        except Exception as e:
            print(f"  ⚠️  Could not archive {doc_file.name}: {e}")

    def get_status(self) -> dict:
        """Get current status."""
        return {
            "project_workspace": str(self.project_workspace),
            "version": self.state.version,
            "total_sources": len(self.state.sources),
            "queue_stats": {
                "total": sum(len(s.queue) for s in self.state.sources.values()),
                "pending": self.state.get_total_pending_count(),
                "running": self.state.get_total_running_count(),
                "completed": self.state.get_total_completed_count(),
                "failed": self.state.get_total_failed_count(),
            },
            "global_statistics": self.state.global_statistics.model_dump(),
            "coordinator": self.coordinator.get_statistics(),
            "sources": self.coordinator.get_source_status(),
        }

    def get_source_state(self, source_id: str) -> Optional[SourceState]:
        """Get state for a specific source."""
        return self.state.sources.get(source_id)

    def get_all_source_states(self) -> Dict[str, SourceState]:
        """Get all source states."""
        return self.state.sources.copy()

    def _is_valid_task_id(self, task_id: str) -> bool:
        """
        Validate task ID format.

        Expected format: task-YYYYMMDD-HHMMSS-description

        Args:
            task_id: Task ID to validate

        Returns:
            True if valid format
        """
        if not task_id.startswith("task-"):
            return False

        # Remove "task-" prefix
        rest = task_id[5:]

        # Check for timestamp pattern (YYYYMMDD-HHMMSS)
        parts = rest.split("-", 2)

        if len(parts) < 2:
            return False

        date_part = parts[0]
        time_part = parts[1]

        # Validate date (8 digits)
        if len(date_part) != 8 or not date_part.isdigit():
            return False

        # Validate time (6 digits)
        if len(time_part) != 6 or not time_part.isdigit():
            return False

        return True
