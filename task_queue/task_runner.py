"""
Task Runner for directory-based state architecture.

No state file - directory structure is the source of truth:
- tasks/task-documents/  - pending tasks
- tasks/task-archive/    - completed tasks
- tasks/task-failed/    - failed tasks
- .task-XXX.running     - marker file for running tasks
"""

import os
import shutil
import socket
import uuid
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

from task_queue.models import TaskSourceDirectory
from task_queue.executor import SyncTaskExecutor


class TaskRunner:
    """
    Simplified task runner using directory-based state.

    No state file - the directory structure tells us everything.
    """

    def __init__(
        self,
        project_workspace: str
    ):
        """
        Initialize task runner.

        Args:
            project_workspace: Path to project root (used as cwd for SDK execution)
        """
        self.project_workspace = Path(project_workspace).resolve()

        # Create necessary directories
        self.archive_dir = self.project_workspace / "tasks" / "task-archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        self.failed_dir = self.project_workspace / "tasks" / "task-failed"
        self.failed_dir.mkdir(parents=True, exist_ok=True)

        # Executor for running tasks
        self.executor = SyncTaskExecutor()

    def pick_next_task(
        self,
        source_dirs: List[TaskSourceDirectory]
    ) -> Optional[Path]:
        """
        Pick the next task to execute from all source directories.

        Scans directories, sorts by filename (chronological order),
        and returns the first available (not currently running) task.

        Args:
            source_dirs: List of source directories to scan

        Returns:
            Path to task document, or None if no pending tasks
        """
        all_tasks = []

        # Scan all source directories
        for source_dir in source_dirs:
            source_path = Path(source_dir.path)
            if not source_path.exists():
                continue

            # Find all task-*.md files
            for task_file in source_path.glob("task-*.md"):
                if task_file.is_file():
                    all_tasks.append(task_file)

        # Sort by filename (chronological: task-YYYYMMDD-HHMMSS-*)
        all_tasks.sort(key=lambda p: p.name)

        # Pick first task that's not currently running
        for task_file in all_tasks:
            task_id = task_file.stem

            # Check if currently running (has .running marker)
            running_marker = task_file.parent / f".{task_id}.running"
            if running_marker.exists():
                # Verify it's actually running (check process)
                if self._is_task_actually_running(task_id):
                    continue  # Skip, still running
                else:
                    # Stale marker - clean it up
                    try:
                        running_marker.unlink()
                    except OSError:
                        pass

            return task_file

        return None

    def pick_next_task_from_source(
        self,
        source_dir: TaskSourceDirectory
    ) -> Optional[Path]:
        """
        Pick the next task to execute from a SINGLE source directory.

        For parallel execution: each worker thread calls this for its own source.
        Tasks are picked in chronological order (by filename).

        Args:
            source_dir: Single source directory to scan

        Returns:
            Path to task document, or None if no pending tasks in this source
        """
        source_path = Path(source_dir.path)
        if not source_path.exists():
            return None

        # Find all task-*.md files
        all_tasks = []
        for task_file in source_path.glob("task-*.md"):
            if task_file.is_file():
                all_tasks.append(task_file)

        # Sort by filename (chronological: task-YYYYMMDD-HHMMSS-*)
        all_tasks.sort(key=lambda p: p.name)

        # Pick first task that's not currently running
        for task_file in all_tasks:
            task_id = task_file.stem

            # Check if currently running (has .running marker)
            running_marker = task_file.parent / f".{task_id}.running"
            if running_marker.exists():
                # Verify it's actually running (check process)
                if self._is_task_actually_running(task_id):
                    continue  # Skip, still running
                else:
                    # Stale marker - clean it up
                    try:
                        running_marker.unlink()
                    except OSError:
                        pass

            return task_file

        return None

    def _is_task_actually_running(self, task_id: str) -> bool:
        """
        Check if a task is actually running (not just has a marker).

        Uses the process ID stored in the marker file.

        Args:
            task_id: Task ID to check

        Returns:
            True if task is running, False otherwise
        """
        running_marker = self.project_workspace / "tasks" / "task-documents" / f".{task_id}.running"

        if not running_marker.exists():
            return False

        try:
            content = running_marker.read_text()
            # Format: "process_id:hostname\n"
            if ":" in content:
                process_id_str = content.split(":")[0]
                try:
                    process_id = int(process_id_str)
                    # Check if process is still alive
                    import os
                    try:
                        os.kill(process_id, 0)  # Send signal 0 (no effect)
                        return True  # Process exists
                    except OSError:
                        return False  # Process dead
                except ValueError:
                    pass
        except (OSError, IOError):
            pass

        return False

    def execute_task(self, task_file: Path) -> Dict:
        """
        Execute a task.

        Creates .running marker, executes task, moves to archive/failed.

        Args:
            task_file: Path to task document

        Returns:
            Result dict with status and error info
        """
        task_id = task_file.stem
        running_marker = task_file.parent / f".{task_id}.running"

        # Check if already running
        if running_marker.exists():
            return {
                "status": "skipped",
                "reason": "Task already running",
                "task_id": task_id
            }

        # Create running marker with process info
        try:
            running_marker.write_text(
                f"process_id:{os.getpid()}:{socket.gethostname()}\n"
                f"started_at:{datetime.now().isoformat()}\n"
            )
        except OSError as e:
            return {
                "status": "error",
                "error": f"Failed to create running marker: {e}",
                "task_id": task_id
            }

        try:
            # Execute task
            result = self.executor.execute(
                task_file,
                project_root=self.project_workspace
            )

            # Task completed - handle result
            if result.success:
                # Move to archive
                try:
                    shutil.move(str(task_file), str(self.archive_dir / task_file.name))
                except OSError as e:
                    return {
                        "status": "warning",
                        "error": f"Task completed but failed to archive: {e}",
                        "task_id": task_id
                    }
            else:
                # Move to failed directory
                try:
                    failed_file = self.failed_dir / task_file.name
                    shutil.move(str(task_file), str(failed_file))

                    # Add error info to task document
                    error_file = failed_file.with_suffix(f".error.{uuid.uuid4().hex[:8]}")
                    error_file.write_text(f"Error: {result.error}\n")
                except OSError as e:
                    return {
                        "status": "warning",
                        "error": f"Task failed but failed to move: {e}",
                        "task_id": task_id
                    }

            return {
                "status": "success" if result.success else "failed",
                "task_id": task_id,
                "output": result.output,
                "error": result.error
            }

        except Exception as e:
            # Exception during execution
            try:
                # Move to failed directory
                failed_file = self.failed_dir / task_file.name
                shutil.move(str(task_file), str(failed_file))
            except OSError:
                pass

            return {
                "status": "error",
                "error": str(e),
                "task_id": task_id
            }

        finally:
            # Always remove running marker
            try:
                running_marker.unlink()
            except OSError:
                pass

    def get_status(
        self,
        source_dirs: List[TaskSourceDirectory]
    ) -> Dict:
        """
        Get current status by scanning directories.

        Args:
            source_dirs: List of source directories to scan

        Returns:
            Status dict with statistics
        """
        stats = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "sources": {}
        }

        for source_dir in source_dirs:
            source_path = Path(source_dir.path)
            if not source_path.exists():
                continue

            source_stats = {
                "pending": 0,
                "running": 0,
                "completed": 0,
                "failed": 0
            }

            # Count pending tasks (task-*.md files, not .running markers)
            for task_file in source_path.glob("task-*.md"):
                if task_file.is_file():
                    running_marker = task_file.parent / f".{task_file.stem}.running"
                    if running_marker.exists():
                        source_stats["running"] += 1
                    else:
                        source_stats["pending"] += 1

            # Count completed in archive
            if self.archive_dir.exists():
                source_stats["completed"] = len(list(self.archive_dir.glob("task-*.md")))

            # Count failed
            if self.failed_dir.exists():
                source_stats["failed"] = len(list(self.failed_dir.glob("task-*.md")))

            stats["sources"][source_dir.id] = source_stats
            stats["pending"] += source_stats["pending"]
            stats["running"] += source_stats["running"]
            stats["completed"] += source_stats["completed"]
            stats["failed"] += source_stats["failed"]

        return stats
