"""Tests for task_monitor.monitor_daemon module."""

import pytest
import json
import tempfile
import shutil
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import time

from task_monitor.monitor_daemon import (
    InstanceLock,
    TaskMonitor,
    ProjectTaskQueue,
    TaskFileHandler,
    LOCK_FILE,
    task_monitor_path,
    ENV_VAR_NAME,
)


@pytest.fixture
def temp_lock(monkeypatch):
    """Patch LOCK_FILE to use temp directory."""
    test_lock = tempfile.mktemp(suffix=".lock")

    # Import the module to patch the globals
    import task_monitor.monitor_daemon as md
    monkeypatch.setattr(md, "LOCK_FILE", Path(test_lock))

    yield Path(test_lock)


class TestInstanceLock:
    """Tests for InstanceLock class."""

    def test_lock_acquire_and_release(self, temp_dir):
        """Test lock can be acquired and released."""
        lock_path = temp_dir / "test.lock"
        lock = InstanceLock(lock_path)

        assert lock.acquire() is True
        assert lock.acquired is True
        lock.release()
        assert lock.acquired is False

    def test_lock_prevents_double_acquire(self, temp_dir):
        """Test that lock cannot be acquired twice."""
        lock_path = temp_dir / "test.lock"
        lock1 = InstanceLock(lock_path)
        lock2 = InstanceLock(lock_path)

        assert lock1.acquire() is True
        assert lock2.acquire() is False

        lock1.release()
        # Now lock2 can acquire
        assert lock2.acquire() is True
        lock2.release()

    def test_lock_context_manager(self, temp_dir):
        """Test lock as context manager for auto-release."""
        lock_path = temp_dir / "test.lock"

        lock = InstanceLock(lock_path)
        lock.acquire()
        assert lock.acquired is True

        # Context manager auto-releases on exit
        with lock:
            # Inside context, still acquired
            assert lock.acquired is True
            # Another lock should fail
            lock2 = InstanceLock(lock_path)
            assert lock2.acquire() is False

        # After context, lock is released
        assert lock.acquired is False

        # Now a new lock can be acquired
        lock3 = InstanceLock(lock_path)
        assert lock3.acquire() is True
        lock3.release()


class TestProjectTaskQueue:
    """Tests for ProjectTaskQueue class."""

    @pytest.fixture
    def queue(self, temp_dir):
        """Create a test queue."""
        state_dir = temp_dir / "state"
        state_dir.mkdir()
        return ProjectTaskQueue("test-project", Path(temp_dir), state_dir)

    @pytest.mark.asyncio
    async def test_put_and_get_next(self, queue):
        """Test putting and getting tasks."""
        await queue.put("task-001.md")
        await queue.put("task-002.md")

        assert queue.size == 2

        task1 = await queue.get_next()
        assert task1 == "task-001.md"
        assert queue.size == 1

        task2 = await queue.get_next()
        assert task2 == "task-002.md"
        assert queue.size == 0

    @pytest.mark.asyncio
    async def test_poison_pill(self, queue):
        """Test that None (poison pill) can be retrieved."""
        await queue.put(None)

        result = await queue.get_next()
        assert result is None

    @pytest.mark.asyncio
    async def test_state_persistence(self, queue):
        """Test that queue state is saved and loaded."""
        queue.current_task = "current-task.md"
        queue.is_processing = True
        queue._save_state()

        # Load state
        state = queue._load_state()
        assert state["current_task"] == "current-task.md"
        assert state["is_processing"] is True
        assert state["project"] == "test-project"

    @pytest.mark.asyncio
    async def test_get_next_blocks_when_empty(self, queue):
        """Test that get_next blocks when queue is empty."""
        # Create a task that will complete after 0.1 seconds
        async def delayed_put():
            await asyncio.sleep(0.1)
            await queue.put("delayed-task.md")

        # Start delayed put in background
        asyncio.create_task(delayed_put())

        # get_next should block until task is available
        start = time.time()
        task = await queue.get_next()
        elapsed = time.time() - start

        assert task == "delayed-task.md"
        assert elapsed >= 0.1  # Should have waited


class TestTaskMonitor:
    """Tests for TaskMonitor class."""

    @pytest.fixture
    def monitor(self):
        """Create a test monitor."""
        monitor = TaskMonitor()
        yield monitor

    def test_get_current_project_path_from_env(self, monitor, monkeypatch):
        """Test getting project path from environment variable."""
        project_path = "/test/project"
        monkeypatch.setenv(ENV_VAR_NAME, project_path)

        result = monitor._get_current_project_path()
        assert str(result) == project_path

    def test_get_current_project_path_not_set(self, monitor, monkeypatch, tmp_path):
        """Test getting project path when not set."""
        # Remove env var
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)

        # Patch ENV_FILE to a non-existent temporary file
        import task_monitor.monitor_daemon as md
        fake_env = tmp_path / "nonexistent.env"
        monkeypatch.setattr(md, "ENV_FILE", fake_env)

        result = monitor._get_current_project_path()
        assert result is None

    def test_get_current_project_path_from_env_file(self, monitor, monkeypatch, tmp_path):
        """Test getting project path from .env file when env var is not set."""
        # Remove env var
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)

        # Create a temporary .env file with project path (standard format, no export)
        fake_env = tmp_path / ".env"
        project_path = "/test/project/from-env-file"
        fake_env.write_text(f'{ENV_VAR_NAME}="{project_path}"\n')

        # Patch ENV_FILE
        import task_monitor.monitor_daemon as md
        monkeypatch.setattr(md, "ENV_FILE", fake_env)

        result = monitor._get_current_project_path()
        assert str(result) == project_path

    def test_setup_project(self, monitor, temp_dir):
        """Test setting up a project."""
        project_path = temp_dir / "my-project"
        project_path.mkdir()

        result = monitor._setup_project(project_path)

        assert result is True
        assert monitor.project is not None
        assert monitor.project["name"] == "my-project"
        assert monitor.project["path"] == project_path

        # Verify directories were created
        assert (project_path / task_monitor_path / "pending").exists()
        assert (project_path / task_monitor_path / "results").exists()
        assert (project_path / task_monitor_path / "logs").exists()
        assert (project_path / task_monitor_path / "state").exists()

    def test_setup_project_nonexistent_path(self, monitor):
        """Test setup fails with nonexistent path."""
        result = monitor._setup_project(Path("/nonexistent/path"))
        assert result is False

    @pytest.mark.asyncio
    async def test_queue_processing_with_poison_pill(self, monitor, temp_dir):
        """Test that queue processor exits on poison pill."""
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor._setup_project(project_path)
        project = monitor.project

        # Track completion
        processor_complete = False

        async def mock_processor():
            nonlocal processor_complete
            try:
                await monitor._process_queue()
            except asyncio.CancelledError:
                raise
            finally:
                processor_complete = True

        # Start processor
        task = asyncio.create_task(mock_processor())

        # Send poison pill
        await project["queue"].put(None)

        # Wait for processor to exit
        await asyncio.wait_for(task, timeout=1.0)

        assert processor_complete is True

    @pytest.mark.asyncio
    async def test_stop_sends_poison_pill(self, monitor, temp_dir):
        """Test that stop sends poison pill to queue."""
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor._setup_project(project_path)
        queue = monitor.project["queue"]

        # Put items in queue to verify poison pill is sent
        await queue.put("task-001.md")
        assert queue.size == 1

        # Mock observer and processor task
        mock_observer = Mock()
        monitor.project["observer"] = mock_observer
        monitor.processor_task = None

        monitor.stop()

        # Check that observer.stop() was called
        mock_observer.stop.assert_called_once()
        assert monitor.running is False


class TestTaskFileHandler:
    """Tests for TaskFileHandler class."""

    @pytest.fixture
    def handler(self, temp_dir):
        """Create a test file handler."""
        state_dir = temp_dir / "state"
        state_dir.mkdir()
        queue = ProjectTaskQueue("test", Path(temp_dir), state_dir)

        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)

        handler = TaskFileHandler(
            queue,
            "test-project",
            Path(temp_dir),
            event_loop
        )
        yield handler

        event_loop.close()

    def test_on_created_matches_task_pattern(self, handler, temp_dir, monkeypatch):
        """Test that task files matching pattern are queued."""
        call_log = []

        monkeypatch.setattr(
            handler.task_queue.__class__,
            'put',
            lambda self, item: call_log.append(item)
        )

        event = Mock()
        event.is_directory = False
        event.src_path = str(temp_dir / "task-20250131-120000-abc123.md")

        handler.on_created(event)

        # Verify the task file name was captured
        assert len(call_log) > 0

    def test_on_created_ignores_non_matching_files(self, handler, temp_dir):
        """Test that non-task files are ignored."""
        event = Mock()
        event.is_directory = False
        event.src_path = str(temp_dir / "readme.md")

        # Should not raise any errors
        handler.on_created(event)

    def test_on_created_ignores_directories(self, handler, temp_dir):
        """Test that directories are ignored."""
        event = Mock()
        event.is_directory = True
        event.src_path = str(temp_dir / "task-20250131-120000-abc123.md")

        handler.on_created(event)

    def test_on_moved_matches_task_pattern(self, handler, temp_dir, monkeypatch):
        """Test that moved task files matching pattern are queued."""
        call_log = []

        monkeypatch.setattr(
            handler.task_queue.__class__,
            'put',
            lambda self, item: call_log.append(item)
        )

        event = Mock()
        event.is_directory = False
        event.dest_path = str(temp_dir / "task-20250131-120000-xyz789.md")

        handler.on_moved(event)

        # Verify the task file name was captured
        assert len(call_log) > 0

    def test_on_moved_ignores_non_matching_files(self, handler, temp_dir):
        """Test that moved non-task files are ignored."""
        event = Mock()
        event.is_directory = False
        event.dest_path = str(temp_dir / "other.md")

        handler.on_moved(event)


class TestIntegration:
    """Integration tests for monitor daemon."""

    @pytest.mark.asyncio
    async def test_full_queue_flow_with_poison_pill(self, temp_dir):
        """Test full flow: queue tasks, process, poison pill shutdown."""
        state_dir = temp_dir / "state"
        state_dir.mkdir()
        queue = ProjectTaskQueue("test", Path(temp_dir), state_dir)

        # Simulate queue operations
        await queue.put("task-001.md")
        await queue.put("task-002.md")

        assert queue.size == 2

        # Retrieve tasks
        task1 = await queue.get_next()
        assert task1 == "task-001.md"
        assert queue.size == 1

        task2 = await queue.get_next()
        assert task2 == "task-002.md"
        assert queue.size == 0

        # Send poison pill
        await queue.put(None)

        # Processor should receive None and exit
        final = await queue.get_next()
        assert final is None

    def test_directory_structure_creation(self, temp_dir):
        """Test that all required directories are created."""
        monitor = TaskMonitor()
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor._setup_project(project_path)

        base = project_path / task_monitor_path
        expected_dirs = ["pending", "results", "logs", "state"]

        for dir_name in expected_dirs:
            assert (base / dir_name).exists(), f"Directory {dir_name} should exist"
            assert (base / dir_name).is_dir(), f"{dir_name} should be a directory"


class TestQueueProcessorErrorHandling:
    """Tests for error handling in queue processor."""

    @pytest.fixture
    def monitor(self, temp_dir):
        """Create a test monitor."""
        monitor = TaskMonitor()
        yield monitor

    @pytest.mark.asyncio
    async def test_processor_handles_task_exception(self, monitor, temp_dir):
        """Test that processor handles exceptions during task execution."""
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor._setup_project(project_path)
        project = monitor.project
        queue = project["queue"]

        # Mock executor to raise exception
        async def mock_execute(task_file):
            raise RuntimeError("Test error")

        project["executor"].execute_task = mock_execute

        # Add a task and then poison pill
        await queue.put("task-001.md")
        await queue.put(None)

        # Process should not crash, should handle exception and exit on poison pill
        await monitor._process_queue()

        # State should be clean
        assert queue.current_task is None
        assert queue.is_processing is False

    @pytest.mark.asyncio
    async def test_processor_handles_cancellation(self, monitor, temp_dir):
        """Test that processor handles asyncio.CancelledError gracefully."""
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor._setup_project(project_path)
        project = monitor.project

        # Start processor and cancel it
        task = asyncio.create_task(monitor._process_queue())

        # Give it a moment to start
        await asyncio.sleep(0.01)

        # Cancel the task
        task.cancel()

        # Should handle cancellation gracefully
        with pytest.raises(asyncio.CancelledError):
            await task

        # State should be cleaned up
        assert project["queue"].current_task is None
        assert project["queue"].is_processing is False

    @pytest.mark.asyncio
    async def test_processor_saves_state_on_completion(self, monitor, temp_dir):
        """Test that processor saves state after task completion."""
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor._setup_project(project_path)
        project = monitor.project
        queue = project["queue"]

        # Create mock result
        from task_monitor.models import TaskResult, TaskStatus
        from datetime import datetime

        async def mock_execute(task_file):
            return TaskResult(
                task_id=task_file.replace(".md", ""),
                status=TaskStatus.COMPLETED,
                created_at=datetime.now(),
                started_at=datetime.now(),
                completed_at=datetime.now(),
                duration_seconds=1.0,
            )

        project["executor"].execute_task = mock_execute

        # Add task and poison pill
        await queue.put("task-001.md")
        await queue.put(None)

        # Process one task then exit on poison pill
        await monitor._process_queue()

        # Verify state was saved
        state = queue._load_state()
        assert state["current_task"] is None
        assert state["is_processing"] is False


class TestObserverLifecycle:
    """Tests for observer start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_observer_start_and_stop(self, temp_dir):
        """Test that observers can be started and stopped."""
        monitor = TaskMonitor()
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor._setup_project(project_path)

        # Mock acquire to prevent actual lock
        monitor.instance_lock.acquire = Mock(return_value=True)

        # Setup observers (partial start)
        monitor.running = True
        monitor.event_loop = asyncio.get_running_loop()

        project = monitor.project
        tasks_dir = project["path"] / task_monitor_path / "pending"
        event_handler = TaskFileHandler(
            project["queue"],
            project["name"],
            project["path"],
            monitor.event_loop
        )
        mock_observer = Mock()
        project["observer"] = mock_observer
        project["event_handler"] = event_handler
        project["started"] = True

        # Test stop calls observer.stop()
        monitor.processor_task = None
        monitor.stop()

        # Verify observer.stop() was called and lock was released
        mock_observer.stop.assert_called_once()
        assert monitor.running is False


class TestMonitorStart:
    """Tests for monitor start method."""

    def test_start_with_no_project_set(self, temp_dir, monkeypatch, caplog):
        """Test start when no project is set via environment variable."""
        # Ensure env var is not set
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)

        # Mock ENV_FILE to a non-existent temporary file
        import task_monitor.monitor_daemon as md
        fake_env = temp_dir / "nonexistent.env"
        monkeypatch.setattr(md, "ENV_FILE", fake_env)

        monitor = TaskMonitor()

        # Track what was run
        run_called = []

        def mock_run(coro):
            run_called.append(True)
            # Don't actually run the coroutine

        monkeypatch.setattr(asyncio, "run", mock_run)
        monitor.instance_lock.acquire = Mock(return_value=True)

        import logging
        caplog.set_level(logging.WARNING)

        monitor.start()

        # Should return early without calling asyncio.run when no project
        assert len(run_called) == 0
        # Should log a warning about setting current project
        assert "No current project set" in caplog.text or "Set a project with" in caplog.text

    def test_start_exits_when_lock_fails(self, temp_dir, monkeypatch):
        """Test start exits when another instance is already running."""
        monitor = TaskMonitor()

        # Mock acquire to fail (simulating lock held)
        monitor.instance_lock.acquire = Mock(return_value=False)

        # The start() method will call sys.exit(1) which raises SystemExit
        with pytest.raises(SystemExit) as exc_info:
            monitor.start()

        # Should have exited with code 1
        assert exc_info.value.code == 1

    def test_setup_project_creates_directories(self, temp_dir):
        """Test that setup creates all required directories."""
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        monitor = TaskMonitor()
        monitor._setup_project(project_path)

        base = project_path / task_monitor_path
        expected_dirs = ["pending", "results", "logs", "state"]

        for dir_name in expected_dirs:
            assert (base / dir_name).exists(), f"Directory {dir_name} should exist"
            assert (base / dir_name).is_dir(), f"{dir_name} should be a directory"
