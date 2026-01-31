"""Test fixtures for task-monitor tests."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json
import asyncio

from task_monitor.models import TaskStatus, TaskResult, QueueState, TaskInfo


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


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def project_root(temp_dir):
    """Create a mock project root with task directories."""
    tasks_dir = temp_dir / "tasks"
    tasks_dir.mkdir()

    # Create subdirectories
    (tasks_dir / "pending").mkdir()
    (tasks_dir / "results").mkdir()
    (tasks_dir / "state").mkdir()

    return temp_dir


@pytest.fixture
def sample_task_result():
    """Create a sample TaskResult for testing."""
    return TaskResult(
        task_id="test-task-001",
        status=TaskStatus.COMPLETED,
        created_at=datetime(2025, 1, 31, 10, 0, 0),
        started_at=datetime(2025, 1, 31, 10, 0, 5),
        completed_at=datetime(2025, 1, 31, 10, 0, 15),
        queue_position=1,
        worker_output={"summary": "Test task completed successfully"},
        audit_score=95,
        audit_notes="Excellent work",
        artifacts=["output.txt", "report.pdf"],
        duration_seconds=10.5,
        stdout="Processing complete",
        stderr=None,
        retry_count=0,
    )


@pytest.fixture
def sample_queue_state():
    """Create a sample QueueState for testing."""
    return QueueState(
        queue_size=3,
        current_task="task-001.md",
        is_processing=True,
        queued_tasks=["task-002.md", "task-003.md", "task-004.md"],
    )


@pytest.fixture
def sample_task_info():
    """Create a sample TaskInfo for testing."""
    return TaskInfo(
        task_id="test-task-001",
        status=TaskStatus.QUEUED,
        created_at=datetime(2025, 1, 31, 10, 0, 0),
        queue_position=1,
    )


@pytest.fixture
def mock_query():
    """Create a mock Claude SDK query object."""
    # Create mock messages
    success_msg = Mock()
    success_msg.subtype = "success"
    success_msg.result = "Task completed successfully"
    success_msg.usage = {"total_tokens": 1000}
    success_msg.total_cost_usd = 0.05

    # Use spec to limit attributes so hasattr returns False for 'subtype'
    content_msg = Mock(spec=['content'])
    content_msg.content = [Mock(text="Processing...")]

    # Return an async iterator mock
    return AsyncIteratorMock([content_msg, success_msg])


@pytest.fixture
def queued_task_file(project_root):
    """Create a queued task file in the pending directory."""
    task_file = project_root / "tasks" / "pending" / "queued-task.md"
    task_file.write_text("# Test Job\n\nThis is a test task.")
    return task_file


@pytest.fixture
def completed_task_result(project_root):
    """Create a completed task result file."""
    result_file = project_root / "tasks" / "results" / "completed-task.json"
    result_data = {
        "task_id": "completed-task",
        "status": "completed",
        "created_at": "2025-01-31T10:00:00",
        "started_at": "2025-01-31T10:00:05",
        "completed_at": "2025-01-31T10:00:15",
        "duration_seconds": 10.5,
        "stdout": "Job output",
        "worker_output": {
            "summary": "Task completed",
            "usage": {"total_tokens": 1000, "cost_usd": 0.05}
        }
    }
    result_file.write_text(json.dumps(result_data))
    return result_file


@pytest.fixture
def queue_state_file(project_root):
    """Create a queue state file."""
    state_file = project_root / "tasks" / "state" / "queue_state.json"
    state_data = {
        "queue_size": 2,
        "current_task": "current-task.md",
        "is_processing": True,
        "task_start_time": "2025-01-31T10:00:00",
        "queued_tasks": ["queued-task.md", "pending-task.md"]
    }
    state_file.write_text(json.dumps(state_data))
    return state_file
