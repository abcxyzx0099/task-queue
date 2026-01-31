"""Tests for task_monitor.task_executor module."""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from task_monitor.task_executor import TaskExecutor
from task_monitor.models import TaskStatus


class AsyncIteratorMock:
    """Helper class to create async iterator mocks."""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        result = self.items[self.index]
        self.index += 1
        return result


class TestTaskExecutorInit:
    """Tests for TaskExecutor initialization."""

    def test_initialization(self, temp_dir):
        """Test TaskExecutor initialization."""
        executor = TaskExecutor(
            tasks_dir=str(temp_dir / "tasks"),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )
        assert executor.tasks_dir == temp_dir / "tasks"
        assert executor.results_dir == temp_dir / "results"
        assert executor.project_root == temp_dir.resolve()

    def test_results_dir_created(self, temp_dir):
        """Test that results directory is created."""
        results_dir = temp_dir / "results"
        executor = TaskExecutor(
            tasks_dir=str(temp_dir / "tasks"),
            results_dir=str(results_dir),
            project_root=str(temp_dir),
        )
        assert results_dir.exists()


class TestReadJobDocument:
    """Tests for _read_task_document method."""

    def test_read_existing_document(self, temp_dir):
        """Test reading an existing task document."""
        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        task_file = temp_dir / "test-task.md"
        task_file.write_text("# Test Job\n\nContent here")

        content = executor._read_task_document(task_file)
        assert content == "# Test Job\n\nContent here"

    def test_read_nonexistent_document(self, temp_dir):
        """Test reading a non-existent task document raises error."""
        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        with pytest.raises(FileNotFoundError, match="Task document not found"):
            executor._read_task_document(temp_dir / "nonexistent.md")


class TestSaveResult:
    """Tests for _save_result method."""

    def test_save_result(self, temp_dir, sample_task_result):
        """Test saving a task result."""
        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        executor._save_result(sample_task_result)

        result_file = temp_dir / "results" / "test-task-001.json"
        assert result_file.exists()

        import json
        with open(result_file) as f:
            data = json.load(f)

        assert data["task_id"] == "test-task-001"
        assert data["status"] == "completed"


class TestExecuteJob:
    """Tests for execute_task method."""

    @pytest.mark.asyncio
    async def test_execute_task_success(self, temp_dir):
        """Test successful task execution."""
        # Create a task file
        task_file = temp_dir / "test-task.md"
        task_file.write_text("# Test Job\n\nExecute this task")

        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock messages
        content_msg = Mock(spec=['content'])
        content_msg.content = [Mock(text="Processing...")]

        success_msg = Mock()
        success_msg.subtype = "success"
        success_msg.result = "Task completed successfully"
        success_msg.usage = {"total_tokens": 1000}
        success_msg.total_cost_usd = 0.05

        mock_query = AsyncIteratorMock([content_msg, success_msg])

        # Mock the query function
        with patch("task_monitor.task_executor.query", return_value=mock_query):
            result = await executor.execute_task("test-task.md")

            assert result.status == TaskStatus.COMPLETED
            assert result.task_id == "test-task"
            assert result.duration_seconds is not None
            assert result.stdout is not None
            assert result.worker_output is not None

            # Verify result was saved
            result_file = temp_dir / "results" / "test-task.json"
            assert result_file.exists()

    @pytest.mark.asyncio
    async def test_execute_task_error(self, temp_dir):
        """Test task execution with error."""
        task_file = temp_dir / "failing-task.md"
        task_file.write_text("# Failing Job\n\nThis will fail")

        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock error message
        error_msg = Mock()
        error_msg.subtype = "error"
        error_msg.result = "Job execution failed"

        mock_query = AsyncIteratorMock([error_msg])

        with patch("task_monitor.task_executor.query", return_value=mock_query):
            result = await executor.execute_task("failing-task.md")

            assert result.status == TaskStatus.FAILED
            assert result.error == "Job execution failed"
            assert result.stderr == "Job execution failed"

    @pytest.mark.asyncio
    async def test_execute_task_exception(self, temp_dir):
        """Test task execution with unexpected exception."""
        task_file = temp_dir / "exception-task.md"
        task_file.write_text("# Exception Job")

        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Mock query to raise an exception
        with patch("task_monitor.task_executor.query", side_effect=RuntimeError("Unexpected error")):
            result = await executor.execute_task("exception-task.md")

            assert result.status == TaskStatus.FAILED
            assert "RuntimeError" in result.error
            assert "Unexpected error" in result.error

    @pytest.mark.asyncio
    async def test_execute_task_cancellation(self, temp_dir):
        """Test task execution with cancellation."""
        task_file = temp_dir / "cancel-task.md"
        task_file.write_text("# Cancel Job")

        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock that never completes (simulates long-running task)
        async def hanging_iterator():
            content_msg = Mock(spec=['content'])
            content_msg.content = [Mock(text="Working...")]
            yield content_msg
            await asyncio.sleep(100)  # This will be cancelled

        mock_query = hanging_iterator()

        with patch("task_monitor.task_executor.query", return_value=mock_query):
            # Create a task and cancel it
            task = asyncio.create_task(executor.execute_task("cancel-task.md"))
            await asyncio.sleep(0.01)  # Let it start
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_execute_task_with_usage_tracking(self, temp_dir):
        """Test task execution captures usage information."""
        task_file = temp_dir / "tracked-task.md"
        task_file.write_text("# Tracked Job")

        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock with usage data
        success_msg = Mock()
        success_msg.subtype = "success"
        success_msg.result = "Job done"
        success_msg.usage = {"total_tokens": 5000, "prompt_tokens": 3000, "completion_tokens": 2000}
        success_msg.total_cost_usd = 0.15

        mock_query = AsyncIteratorMock([success_msg])

        with patch("task_monitor.task_executor.query", return_value=mock_query):
            result = await executor.execute_task("tracked-task.md")

            assert result.status == TaskStatus.COMPLETED
            assert result.worker_output is not None
            assert result.worker_output.get("usage") == {"total_tokens": 5000, "prompt_tokens": 3000, "completion_tokens": 2000}
            assert result.worker_output.get("cost_usd") == 0.15

    @pytest.mark.asyncio
    async def test_execute_task_collects_stdout(self, temp_dir):
        """Test task execution collects stdout from content messages."""
        task_file = temp_dir / "output-task.md"
        task_file.write_text("# Output Job")

        executor = TaskExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock with multiple content messages
        # Need to explicitly set subtype to None since Mock returns True for hasattr
        content_msg1 = Mock(spec=['content'])
        content_msg1.content = [Mock(text="Line 1 output")]

        content_msg2 = Mock(spec=['content'])
        content_msg2.content = [Mock(text="Line 2 output")]

        success_msg = Mock()
        success_msg.subtype = "success"
        success_msg.result = "Complete"

        mock_query = AsyncIteratorMock([content_msg1, content_msg2, success_msg])

        with patch("task_monitor.task_executor.query", return_value=mock_query):
            result = await executor.execute_task("output-task.md")

            assert result.status == TaskStatus.COMPLETED
            assert "Line 1 output" in result.stdout
            assert "Line 2 output" in result.stdout
