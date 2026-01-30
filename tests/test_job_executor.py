"""Tests for job_monitor.job_executor module."""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from job_monitor.job_executor import JobExecutor
from job_monitor.models import JobStatus


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


class TestJobExecutorInit:
    """Tests for JobExecutor initialization."""

    def test_initialization(self, temp_dir):
        """Test JobExecutor initialization."""
        executor = JobExecutor(
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
        executor = JobExecutor(
            tasks_dir=str(temp_dir / "tasks"),
            results_dir=str(results_dir),
            project_root=str(temp_dir),
        )
        assert results_dir.exists()


class TestReadJobDocument:
    """Tests for _read_job_document method."""

    def test_read_existing_document(self, temp_dir):
        """Test reading an existing job document."""
        executor = JobExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        job_file = temp_dir / "test-job.md"
        job_file.write_text("# Test Job\n\nContent here")

        content = executor._read_job_document(job_file)
        assert content == "# Test Job\n\nContent here"

    def test_read_nonexistent_document(self, temp_dir):
        """Test reading a non-existent job document raises error."""
        executor = JobExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        with pytest.raises(FileNotFoundError, match="Job document not found"):
            executor._read_job_document(temp_dir / "nonexistent.md")


class TestSaveResult:
    """Tests for _save_result method."""

    def test_save_result(self, temp_dir, sample_job_result):
        """Test saving a job result."""
        executor = JobExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        executor._save_result(sample_job_result)

        result_file = temp_dir / "results" / "test-job-001.json"
        assert result_file.exists()

        import json
        with open(result_file) as f:
            data = json.load(f)

        assert data["job_id"] == "test-job-001"
        assert data["status"] == "completed"


class TestExecuteJob:
    """Tests for execute_job method."""

    @pytest.mark.asyncio
    async def test_execute_job_success(self, temp_dir):
        """Test successful job execution."""
        # Create a job file
        job_file = temp_dir / "test-job.md"
        job_file.write_text("# Test Job\n\nExecute this task")

        executor = JobExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock messages
        content_msg = Mock(spec=['content'])
        content_msg.content = [Mock(text="Processing...")]

        success_msg = Mock()
        success_msg.subtype = "success"
        success_msg.result = "Job completed successfully"
        success_msg.usage = {"total_tokens": 1000}
        success_msg.total_cost_usd = 0.05

        mock_query = AsyncIteratorMock([content_msg, success_msg])

        # Mock the query function
        with patch("job_monitor.job_executor.query", return_value=mock_query):
            result = await executor.execute_job("test-job.md")

            assert result.status == JobStatus.COMPLETED
            assert result.job_id == "test-job"
            assert result.duration_seconds is not None
            assert result.stdout is not None
            assert result.worker_output is not None

            # Verify result was saved
            result_file = temp_dir / "results" / "test-job.json"
            assert result_file.exists()

    @pytest.mark.asyncio
    async def test_execute_job_error(self, temp_dir):
        """Test job execution with error."""
        job_file = temp_dir / "failing-job.md"
        job_file.write_text("# Failing Job\n\nThis will fail")

        executor = JobExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock error message
        error_msg = Mock()
        error_msg.subtype = "error"
        error_msg.result = "Job execution failed"

        mock_query = AsyncIteratorMock([error_msg])

        with patch("job_monitor.job_executor.query", return_value=mock_query):
            result = await executor.execute_job("failing-job.md")

            assert result.status == JobStatus.FAILED
            assert result.error == "Job execution failed"
            assert result.stderr == "Job execution failed"

    @pytest.mark.asyncio
    async def test_execute_job_exception(self, temp_dir):
        """Test job execution with unexpected exception."""
        job_file = temp_dir / "exception-job.md"
        job_file.write_text("# Exception Job")

        executor = JobExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Mock query to raise an exception
        with patch("job_monitor.job_executor.query", side_effect=RuntimeError("Unexpected error")):
            result = await executor.execute_job("exception-job.md")

            assert result.status == JobStatus.FAILED
            assert "RuntimeError" in result.error
            assert "Unexpected error" in result.error

    @pytest.mark.asyncio
    async def test_execute_job_cancellation(self, temp_dir):
        """Test job execution with cancellation."""
        job_file = temp_dir / "cancel-job.md"
        job_file.write_text("# Cancel Job")

        executor = JobExecutor(
            tasks_dir=str(temp_dir),
            results_dir=str(temp_dir / "results"),
            project_root=str(temp_dir),
        )

        # Create mock that never completes (simulates long-running job)
        async def hanging_iterator():
            content_msg = Mock(spec=['content'])
            content_msg.content = [Mock(text="Working...")]
            yield content_msg
            await asyncio.sleep(100)  # This will be cancelled

        mock_query = hanging_iterator()

        with patch("job_monitor.job_executor.query", return_value=mock_query):
            # Create a task and cancel it
            task = asyncio.create_task(executor.execute_job("cancel-job.md"))
            await asyncio.sleep(0.01)  # Let it start
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_execute_job_with_usage_tracking(self, temp_dir):
        """Test job execution captures usage information."""
        job_file = temp_dir / "tracked-job.md"
        job_file.write_text("# Tracked Job")

        executor = JobExecutor(
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

        with patch("job_monitor.job_executor.query", return_value=mock_query):
            result = await executor.execute_job("tracked-job.md")

            assert result.status == JobStatus.COMPLETED
            assert result.worker_output is not None
            assert result.worker_output.get("usage") == {"total_tokens": 5000, "prompt_tokens": 3000, "completion_tokens": 2000}
            assert result.worker_output.get("cost_usd") == 0.15

    @pytest.mark.asyncio
    async def test_execute_job_collects_stdout(self, temp_dir):
        """Test job execution collects stdout from content messages."""
        job_file = temp_dir / "output-job.md"
        job_file.write_text("# Output Job")

        executor = JobExecutor(
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

        with patch("job_monitor.job_executor.query", return_value=mock_query):
            result = await executor.execute_job("output-job.md")

            assert result.status == JobStatus.COMPLETED
            assert "Line 1 output" in result.stdout
            assert "Line 2 output" in result.stdout
