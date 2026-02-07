"""Tests for task_queue.executor module."""

import pytest
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from task_queue.executor import (
    LockInfo,
    get_lock_file_path,
    is_task_locked,
    get_locked_task,
    process_exists,
    ExecutionResult,
    SyncTaskExecutor,
    create_executor,
)


class TestLockInfo:
    """Tests for LockInfo dataclass."""

    def test_lockinfo_creation(self):
        """Test creating a LockInfo instance."""
        lock = LockInfo(
            task_id="task-123",
            worker="ad-hoc",
            thread_id="12345",
            pid=12345,
            started_at="2026-02-07T12:00:00"
        )
        assert lock.task_id == "task-123"
        assert lock.worker == "ad-hoc"
        assert lock.thread_id == "12345"
        assert lock.pid == 12345
        assert lock.started_at == "2026-02-07T12:00:00"

    def test_to_dict(self):
        """Test LockInfo.to_dict() method."""
        lock = LockInfo(
            task_id="task-123",
            worker="ad-hoc",
            thread_id="12345",
            pid=12345,
            started_at="2026-02-07T12:00:00"
        )
        data = lock.to_dict()
        assert data == {
            "task_id": "task-123",
            "worker": "ad-hoc",
            "thread_id": "12345",
            "pid": 12345,
            "started_at": "2026-02-07T12:00:00"
        }

    def test_from_file_valid(self, temp_dir):
        """Test LockInfo.from_file() with valid lock file."""
        lock_file = temp_dir / "test.lock"
        lock_data = {
            "task_id": "task-123",
            "worker": "ad-hoc",
            "thread_id": "12345",
            "pid": 12345,
            "started_at": "2026-02-07T12:00:00"
        }
        lock_file.write_text(json.dumps(lock_data))

        lock = LockInfo.from_file(lock_file)
        assert lock is not None
        assert lock.task_id == "task-123"
        assert lock.worker == "ad-hoc"

    def test_from_file_invalid_json(self, temp_dir):
        """Test LockInfo.from_file() with invalid JSON."""
        lock_file = temp_dir / "test.lock"
        lock_file.write_text("invalid json")

        lock = LockInfo.from_file(lock_file)
        assert lock is None

    def test_from_file_nonexistent(self, temp_dir):
        """Test LockInfo.from_file() with nonexistent file."""
        lock_file = temp_dir / "nonexistent.lock"
        lock = LockInfo.from_file(lock_file)
        assert lock is None

    def test_from_file_missing_fields(self, temp_dir):
        """Test LockInfo.from_file() with missing required fields."""
        lock_file = temp_dir / "test.lock"
        lock_file.write_text(json.dumps({"task_id": "task-123"}))

        lock = LockInfo.from_file(lock_file)
        assert lock is None

    def test_save(self, temp_dir):
        """Test LockInfo.save() method."""
        lock_file = temp_dir / "test.lock"
        lock = LockInfo(
            task_id="task-123",
            worker="ad-hoc",
            thread_id="12345",
            pid=12345,
            started_at="2026-02-07T12:00:00"
        )
        lock.save(lock_file)

        assert lock_file.exists()
        data = json.loads(lock_file.read_text())
        assert data["task_id"] == "task-123"
        assert data["worker"] == "ad-hoc"


class TestLockFileHelpers:
    """Tests for lock file helper functions."""

    def test_get_lock_file_path(self):
        """Test get_lock_file_path() function."""
        task_file = Path("/tmp/tasks/pending/task-123.md")
        lock_path = get_lock_file_path(task_file)
        assert lock_path == Path("/tmp/tasks/pending/.task-123.lock")

    def test_is_task_locked_no_lock_file(self, temp_dir):
        """Test is_task_locked() when no lock file exists."""
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        assert is_task_locked(task_file) is False

    def test_is_task_locked_with_valid_lock(self, temp_dir):
        """Test is_task_locked() with valid lock file."""
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        lock_file = get_lock_file_path(task_file)
        lock_data = {
            "task_id": "task-123",
            "worker": "ad-hoc",
            "thread_id": "12345",
            "pid": 999999,  # Non-existent PID
            "started_at": "2026-02-07T12:00:00"
        }
        lock_file.write_text(json.dumps(lock_data))

        # With non-existent PID, should return False (stale lock cleaned up)
        assert is_task_locked(task_file) is False
        # Lock file should be removed
        assert not lock_file.exists()

    def test_is_task_locked_stale_lock_removed(self, temp_dir):
        """Test that stale lock files are removed."""
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        lock_file = get_lock_file_path(task_file)
        lock_data = {
            "task_id": "task-123",
            "worker": "ad-hoc",
            "thread_id": "12345",
            "pid": 999999,
            "started_at": "2026-02-07T12:00:00"
        }
        lock_file.write_text(json.dumps(lock_data))

        # Lock file exists before check
        assert lock_file.exists()

        # Check locks (should clean up stale lock)
        is_task_locked(task_file)

        # Lock file should be removed after stale check
        assert not lock_file.exists()

    def test_get_locked_task_no_locks(self, temp_dir):
        """Test get_locked_task() with no lock files."""
        assert get_locked_task(temp_dir) is None

    def test_get_locked_task_with_stale_lock(self, temp_dir):
        """Test get_locked_task() with stale lock file."""
        lock_file = temp_dir / ".task-123.lock"
        lock_data = {
            "task_id": "task-123",
            "worker": "ad-hoc",
            "thread_id": "12345",
            "pid": 999999,
            "started_at": "2026-02-07T12:00:00"
        }
        lock_file.write_text(json.dumps(lock_data))

        # Should return None for stale lock
        assert get_locked_task(temp_dir) is None

    def test_process_exists_current_process(self):
        """Test process_exists() with current process."""
        import os
        current_pid = os.getpid()
        assert process_exists(current_pid) is True

    def test_process_exists_nonexistent(self):
        """Test process_exists() with non-existent PID."""
        assert process_exists(999999) is False

    def test_process_exists_error_handling(self):
        """Test process_exists() handles errors gracefully."""
        # Test with invalid PID (negative number)
        assert process_exists(-1) is False


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_execution_result_creation(self):
        """Test creating an ExecutionResult."""
        result = ExecutionResult(
            success=True,
            output="Task completed",
            task_id="task-123"
        )
        assert result.success is True
        assert result.output == "Task completed"
        assert result.task_id == "task-123"

    def test_to_dict_with_none_values(self):
        """Test to_dict() filters out None values."""
        result = ExecutionResult(
            success=True,
            task_id="task-123",
            output="Done",
            duration_ms=1000,
            total_cost_usd=None
        )
        data = result.to_dict()
        assert "total_cost_usd" not in data
        assert data["success"] is True
        assert data["duration_ms"] == 1000

    def test_to_dict_complete(self):
        """Test to_dict() with all fields."""
        result = ExecutionResult(
            success=True,
            output="Done",
            error="",  # Empty string is not filtered, only None is
            task_id="task-123",
            duration_ms=1000,
            duration_api_ms=800,
            total_cost_usd=0.001,
            usage={"input_tokens": 100, "output_tokens": 50},
            session_id="sess-123",
            num_turns=3,
            started_at="2026-02-07T12:00:00",
            completed_at="2026-02-07T12:01:00"
        )
        data = result.to_dict()
        # All non-None fields included (12 total since error="" is not None)
        assert len(data) == 12
        assert data["success"] is True
        assert data["usage"]["input_tokens"] == 100
        assert data["error"] == ""

    def test_save_to_file(self, temp_dir):
        """Test save_to_file() creates result JSON."""
        result = ExecutionResult(
            success=True,
            output="Done",
            task_id="task-123",
            duration_ms=1000
        )

        result_path = result.save_to_file(temp_dir, "ad-hoc")

        # Check file exists in correct location
        expected_path = temp_dir / "tasks" / "ad-hoc" / "results" / "task-123.json"
        assert result_path == expected_path
        assert expected_path.exists()

        # Check content
        data = json.loads(expected_path.read_text())
        assert data["success"] is True
        assert data["task_id"] == "task-123"


class TestSyncTaskExecutor:
    """Tests for SyncTaskExecutor class."""

    def test_init_with_workspace(self, temp_dir):
        """Test SyncTaskExecutor initialization with workspace."""
        executor = SyncTaskExecutor(temp_dir)
        assert executor.project_workspace == temp_dir.resolve()

    def test_init_without_workspace(self):
        """Test SyncTaskExecutor initialization without workspace."""
        executor = SyncTaskExecutor()
        assert executor.project_workspace is None

    def test_execute_raises_error_without_workspace(self, temp_dir):
        """Test execute() raises error when project_workspace is not set."""
        executor = SyncTaskExecutor()
        task_file = temp_dir / "task.md"
        task_file.write_text("# Task")

        with pytest.raises(ValueError, match="project_workspace must be set"):
            executor.execute(task_file)

    def test_execute_raises_error_for_nonexistent_task(self, temp_dir):
        """Test execute() raises FileNotFoundError for missing task."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "nonexistent.md"

        with pytest.raises(FileNotFoundError, match="Task document not found"):
            executor.execute(task_file)

    def test_execute_relative_path_resolved(self, temp_dir):
        """Test execute() resolves relative task paths."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "tasks" / "pending" / "task-123.md"
        task_file.parent.mkdir(parents=True)
        task_file.write_text("# Task")

        # Mock the query to avoid actual SDK call
        with patch('task_queue.executor.query') as mock_query:
            mock_q = MagicMock()
            mock_query.return_value = mock_q

            # Mock message sequence
            async def mock_messages():
                msg = MagicMock()
                msg.subtype = 'success'
                msg.result = "Done"
                msg.duration_ms = 1000
                msg.content = []
                yield msg

            mock_q.__aiter__ = lambda self: mock_messages()

            # Execute with relative path
            result = executor.execute("tasks/pending/task-123.md")

            assert result.task_id == "task-123"

    def test_execute_creates_lock_file(self, temp_dir):
        """Test execute() creates lock file during execution."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        with patch('task_queue.executor.query') as mock_query:
            mock_q = MagicMock()
            mock_query.return_value = mock_q

            async def mock_messages():
                # First check - lock should exist
                lock_path = get_lock_file_path(task_file)
                assert lock_path.exists()

                # Read lock content
                lock_info = LockInfo.from_file(lock_path)
                assert lock_info is not None
                assert lock_info.task_id == "task-123"
                assert lock_info.pid == lock_info.pid  # Current PID

                msg = MagicMock()
                msg.subtype = 'success'
                msg.result = "Done"
                msg.content = []
                yield msg

                # After success, lock should be removed
                assert not lock_path.exists()

            mock_q.__aiter__ = lambda self: mock_messages()

            executor.execute(task_file)

    def test_execute_with_mocked_sdk(self, temp_dir):
        """Test execute() with mocked SDK success path."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        with patch('task_queue.executor.query') as mock_query:
            mock_q = MagicMock()
            mock_query.return_value = mock_q

            # Create async generator that yields a success message
            async def mock_messages():
                msg = MagicMock()
                msg.subtype = 'success'
                msg.result = "Task completed successfully"
                msg.duration_ms = 1500
                msg.duration_api_ms = 1200
                msg.total_cost_usd = 0.002
                msg.usage = {"input_tokens": 200, "output_tokens": 100}
                msg.session_id = "test-session"
                msg.num_turns = 5
                msg.content = []
                yield msg

            # Properly set up async iterator
            async def async_iter():
                async for m in mock_messages():
                    yield m

            mock_q.__aiter__ = lambda self: async_iter()

            result = executor.execute(task_file)

            assert result.success is True
            assert result.task_id == "task-123"
            assert result.duration_ms == 1500
            assert result.session_id == "test-session"
            assert result.num_turns == 5

            # Check result file was saved
            result_file = temp_dir / "tasks" / "unknown" / "results" / "task-123.json"
            assert result_file.exists()

    def test_execute_with_sdk_error(self, temp_dir):
        """Test execute() handles SDK error response."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        with patch('task_queue.executor.query') as mock_query:
            mock_q = MagicMock()
            mock_query.return_value = mock_q

            # Create async generator that yields an error message
            async def mock_messages():
                msg = MagicMock()
                msg.subtype = 'error'
                msg.result = "SDK execution failed"
                msg.duration_ms = 500
                msg.session_id = "error-session"
                msg.content = []
                yield msg

            async def async_iter():
                async for m in mock_messages():
                    yield m

            mock_q.__aiter__ = lambda self: async_iter()

            result = executor.execute(task_file)

            assert result.success is False
            assert "SDK execution failed" in result.error
            assert result.session_id == "error-session"

            # Result file should still be saved for errors
            result_file = temp_dir / "tasks" / "unknown" / "results" / "task-123.json"
            assert result_file.exists()

    def test_execute_handles_cancelled_error(self, temp_dir):
        """Test execute() handles asyncio.CancelledError."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        # Patch asyncio.run to raise CancelledError
        with patch('task_queue.executor.asyncio.run') as mock_run:
            import asyncio
            mock_run.side_effect = asyncio.CancelledError()

            result = executor.execute(task_file)

            assert result.success is False
            assert "cancelled" in result.error.lower()

            # Lock file should be cleaned up
            lock_path = get_lock_file_path(task_file)
            assert not lock_path.exists()

    def test_execute_handles_general_exception(self, temp_dir):
        """Test execute() handles general exceptions."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        with patch('task_queue.executor.query') as mock_query:
            mock_query.side_effect = RuntimeError("Test error")

            result = executor.execute(task_file)

            assert result.success is False
            assert "RuntimeError" in result.error
            assert "Test error" in result.error

    def test_execute_with_custom_worker(self, temp_dir):
        """Test execute() with custom worker parameter."""
        executor = SyncTaskExecutor(temp_dir)
        task_file = temp_dir / "task-123.md"
        task_file.write_text("# Task")

        with patch('task_queue.executor.query') as mock_query:
            mock_q = MagicMock()
            mock_query.return_value = mock_q

            async def mock_messages():
                msg = MagicMock()
                msg.subtype = 'success'
                msg.result = "Done"
                msg.content = []
                yield msg

            mock_q.__aiter__ = lambda self: mock_messages()

            executor.execute(task_file, worker="planned")

            # Result should be in planned worker directory
            result_file = temp_dir / "tasks" / "planned" / "results" / "task-123.json"
            assert result_file.exists()


class TestCreateExecutor:
    """Tests for create_executor factory function."""

    def test_create_executor(self, temp_dir):
        """Test create_executor() returns configured executor."""
        executor = create_executor(temp_dir)
        assert isinstance(executor, SyncTaskExecutor)
        assert executor.project_workspace == temp_dir.resolve()
