"""
Task monitor for processing.

Orchestrates task loading and execution.
"""

import time
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from task_queue.models import (
    QueueConfig, SystemStatus, SpecDirectoryStatus
)
from task_queue.config import ConfigManager
from task_queue.scanner import TaskScanner
from task_queue.processor import TaskProcessor
from task_queue.atomic import FileLock


class TaskQueue:
    """
    Task monitor for single project path.

    Manages task loading from multiple spec directories
    and sequential execution.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None
    ):
        """
        Initialize monitor.

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
        project_path = self.config_manager.config.project_path

        if not project_path:
            return None

        if self._processor is None:
            # Define paths (in ~/.config/task-monitor/)
            config_dir = self.config_manager.config_file.parent
            state_dir = config_dir / "state"
            results_dir = config_dir / "results"

            state_dir.mkdir(parents=True, exist_ok=True)
            results_dir.mkdir(parents=True, exist_ok=True)

            state_file = state_dir / "queue_state.json"

            self._processor = TaskProcessor(
                project_path=project_path,
                state_file=state_file,
                results_dir=results_dir,
                scanner=self.scanner
            )

        return self._processor

    def load_tasks(self) -> Dict[str, int]:
        """
        Load tasks from configured spec directories.

        Returns:
            Dict mapping spec_dir_id to new task count
        """
        processor = self.get_processor()

        if not processor:
            print("⚠️  No project path set. Use 'task-queue' set-project <path>'")
            return {}

        print(f"\n📂 Scanning spec directories...")

        spec_dirs = self.config_manager.config.spec_directories

        if not spec_dirs:
            print("⚠️  No spec directories configured. Use 'task-queue' add-spec <path>'")
            return {}

        for spec_dir in spec_dirs:
            print(f"  - {spec_dir.id}: {spec_dir.path}")

        print()

        # Load tasks (processor scans all spec directories)
        new_count = processor.load_tasks(spec_dirs)

        self._load_count += 1
        self._last_load = datetime.now()

        return {"total": new_count}

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
                "error": "No project path configured"
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
        Run the monitor loop.

        Args:
            cycles: Number of cycles to run (None = infinite)
        """
        self._running = True
        self._start_time = datetime.now()

        processing_interval = self.config_manager.config.settings.processing_interval

        print(f"\n🎯 Task Queue Started")
        print(f"   Project: {self.config_manager.config.project_path}")
        print(f"   Spec directories: {len(self.config_manager.config.spec_directories)}")
        print(f"   Interval: {processing_interval}s")
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

                # Wait for next cycle
                print(f"\n⏱️  Waiting {processing_interval}s...")
                time.sleep(processing_interval)

        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")

        finally:
            self._running = False
            print(f"\n🛑 Task Queue Stopped")

    def stop(self) -> None:
        """Stop the monitor."""
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
        status.project_path = self.config_manager.config.project_path

        # Spec directories
        status.total_spec_dirs = len(self.config_manager.config.spec_directories)
        status.active_spec_dirs = len(self.config_manager.config.spec_directories)

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

    def get_spec_directory_status(self) -> List[SpecDirectoryStatus]:
        """Get status for all spec directories."""
        statuses = []

        for spec_dir in self.config_manager.config.spec_directories:
            queue_stats = {}

            # Count tasks from this spec directory
            processor = self.get_processor()
            if processor:
                for task in processor.state.queue:
                    if task.spec_dir_id == spec_dir.id:
                        st = task.status.value
                        queue_stats[st] = queue_stats.get(st, 0) + 1

            statuses.append(SpecDirectoryStatus(
                id=spec_dir.id,
                path=spec_dir.path,
                description=spec_dir.description,
                queue_stats=queue_stats
            ))

        return statuses


def create_queue(
    config_file: Optional[Path] = None
) -> TaskQueue:
    """
    Create a configured monitor.

    Args:
        config_file: Path to configuration file

    Returns:
        Configured TaskQueue
    """
    config_manager = ConfigManager(config_file)

    return TaskQueue(config_manager=config_manager)
