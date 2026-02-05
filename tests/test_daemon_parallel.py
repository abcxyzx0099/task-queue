"""Tests for daemon parallel execution feature."""

import pytest
import time
import threading
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from task_queue.daemon import TaskQueueDaemon
from task_queue.models import TaskSourceDirectory


class TestParallelWorkerSetup:
    """Tests for parallel worker initialization."""

    def test_daemon_creates_per_source_events(self, temp_dir):
        """Test that daemon creates events for each source."""
        # Create two source directories
        source1_dir = temp_dir / "source1"
        source2_dir = temp_dir / "source2"
        source1_dir.mkdir(parents=True)
        source2_dir.mkdir(parents=True)

        # Create a config file for this test
        config_file = temp_dir / "config.json"
        import json
        config_data = {
            "version": "2.0",
            "project_workspace": str(temp_dir),
            "task_source_directories": [
                {
                    "id": "source1",
                    "path": str(source1_dir),
                    "description": "Source 1"
                },
                {
                    "id": "source2",
                    "path": str(source2_dir),
                    "description": "Source 2"
                }
            ],
            "settings": {
                "watch_enabled": True  # Enable watchdog so events are created
            }
        }
        config_file.write_text(json.dumps(config_data))

        daemon = TaskQueueDaemon(config_file=config_file)

        # Setup config and task runner manually
        from task_queue.config import ConfigManager
        config_manager = ConfigManager(config_file)
        daemon.task_runner = Mock()

        # Call _setup_watchdog which creates the events
        daemon._setup_watchdog()

        # Check that events were created
        assert "source1" in daemon._source_events
        assert "source2" in daemon._source_events


class TestWorkerLoop:
    """Tests for the worker loop method."""

    def test_worker_loop_processes_single_source(self, temp_dir):
        """Test that worker loop processes tasks from one source."""
        # Create source directory with tasks
        source_dir = temp_dir / "tasks" / "task-documents"
        source_dir.mkdir(parents=True)

        # Create test tasks
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for i in range(2):
            task = source_dir / f"task-{timestamp}-{i:02d}.md"
            task.write_text(f"# Task {i}")

        daemon = TaskQueueDaemon()
        daemon.running = True
        daemon.shutdown_requested = False

        # Create task runner
        from task_queue.task_runner import TaskRunner
        daemon.task_runner = TaskRunner(str(temp_dir))

        # Create source
        source = TaskSourceDirectory(id="test", path=str(source_dir))

        # Create event for this source
        daemon._source_events["test"] = threading.Event()

        # Mock execute to return success and move to archive
        def mock_execute(task_file, project_root=None):
            # Move to archive
            archive_dir = Path(project_root) / "tasks" / "task-archive"
            shutil.move(str(task_file), str(archive_dir / task_file.name))
            from task_queue.executor import ExecutionResult
            return ExecutionResult(success=True, task_id=task_file.stem)

        daemon.task_runner.executor.execute = mock_execute

        # Run worker loop for one iteration
        def stop_after_one():
            time.sleep(0.1)
            daemon.shutdown_requested = True
            daemon._source_events["test"].set()

        stopper = threading.Thread(target=stop_after_one)
        stopper.start()

        daemon._worker_loop(source)

        stopper.join()

        # Tasks should have been processed
        archive_dir = temp_dir / "tasks" / "task-archive"
        assert len(list(archive_dir.glob("task-*.md"))) >= 1


class TestParallelExecutionSimulation:
    """Tests simulating parallel execution across sources."""

    def test_parallel_workers_dont_conflict(self, temp_dir):
        """Test that parallel workers don't conflict with each other."""
        # Create two source directories
        source1_dir = temp_dir / "source1"
        source2_dir = temp_dir / "source2"
        source1_dir.mkdir(parents=True)
        source2_dir.mkdir(parents=True)

        # Create tasks in both sources
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for i in range(3):
            (source1_dir / f"task-{timestamp}-{i:02d}-s1.md").write_text(f"# S1 Task {i}")
            (source2_dir / f"task-{timestamp}-{i:02d}-s2.md").write_text(f"# S2 Task {i}")

        from task_queue.task_runner import TaskRunner
        runner = TaskRunner(str(temp_dir))

        source1 = TaskSourceDirectory(id="source1", path=str(source1_dir))
        source2 = TaskSourceDirectory(id="source2", path=str(source2_dir))

        # Track which worker processed which tasks
        processed = {"worker1": [], "worker2": []}
        lock = threading.Lock()

        def worker1():
            """Simulate worker 1 processing source1."""
            for i in range(3):
                task = runner.pick_next_task_from_source(source1)
                if task:
                    with lock:
                        processed["worker1"].append(task.name)
                    time.sleep(0.05)  # Simulate work
                    shutil.move(str(task), str(temp_dir / "tasks" / "task-archive" / task.name))

        def worker2():
            """Simulate worker 2 processing source2."""
            for i in range(3):
                task = runner.pick_next_task_from_source(source2)
                if task:
                    with lock:
                        processed["worker2"].append(task.name)
                    time.sleep(0.05)  # Simulate work
                    shutil.move(str(task), str(temp_dir / "tasks" / "task-archive" / task.name))

        # Run workers in parallel
        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)

        start_time = time.time()
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        elapsed = time.time() - start_time

        # Both workers should have processed their tasks
        assert len(processed["worker1"]) == 3
        assert len(processed["worker2"]) == 3

        # Check that each worker only processed its own source
        for task in processed["worker1"]:
            assert "s1" in task
        for task in processed["worker2"]:
            assert "s2" in task

        # Parallel execution should be faster than sequential
        # Sequential: 6 * 0.05 = 0.3 seconds
        # Parallel: ~3 * 0.05 = 0.15 seconds
        assert elapsed < 0.25  # Should be significantly faster


class TestWatchdogEventSignaling:
    """Tests for per-source watchdog event signaling."""

    def test_watchdog_signals_correct_source(self, temp_dir):
        """Test that watchdog events signal the correct source event."""
        daemon = TaskQueueDaemon()

        # Create events for two sources
        daemon._source_events["source1"] = threading.Event()
        daemon._source_events["source2"] = threading.Event()

        # Simulate watchdog event for source1
        daemon._on_watchdog_event("/tmp/task-test.md", "source1")

        # Only source1 event should be set
        assert daemon._source_events["source1"].is_set()
        assert not daemon._source_events["source2"].is_set()

    def test_watchdog_unknown_source(self, temp_dir):
        """Test watchdog event for unknown source (should not crash)."""
        daemon = TaskQueueDaemon()

        # Create event for one source
        daemon._source_events["source1"] = threading.Event()

        # Simulate watchdog event for unknown source (should not crash)
        daemon._on_watchdog_event("/tmp/task-test.md", "unknown_source")

        # Should not crash, source1 should not be set
        assert not daemon._source_events["source1"].is_set()


class TestGracefulShutdown:
    """Tests for graceful shutdown with multiple workers."""

    def test_shutdown_wakes_all_workers(self, temp_dir):
        """Test that shutdown wakes all waiting workers."""
        daemon = TaskQueueDaemon()

        # Create events for multiple sources
        for i in range(3):
            daemon._source_events[f"source{i}"] = threading.Event()

        # Set shutdown flag
        daemon.shutdown_requested = True

        # Call signal handler
        daemon._signal_handler(15, None)

        # All events should be set to wake up workers
        for event in daemon._source_events.values():
            assert event.is_set()
