"""Test fixtures for task-queue tests."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, AsyncMock
import json

from task_queue.models import (
    TaskStatus, TaskResult, QueueState, Task,
    TaskSource, QueueConfig, TaskDocDirectory, QueueSettings
)


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
    task_queue_dir = temp_dir / "tasks" / "task-queue"
    task_spec_dir = temp_dir / "tasks" / "task-documents"
    task_queue_dir.mkdir(parents=True)
    task_spec_dir.mkdir(parents=True)

    # Create subdirectories
    (task_queue_dir / "state").mkdir()
    (task_queue_dir / "results").mkdir()
    (task_queue_dir / "logs").mkdir()
    (task_spec_dir / "archive").mkdir(parents=True)

    return temp_dir


@pytest.fixture
def task_spec_dir(project_root):
    """Get the task specifications directory."""
    return project_root / "tasks" / "task-documents"


@pytest.fixture
def task_queue_dir(project_root):
    """Get the task queue directory."""
    return project_root / "tasks" / "task-queue"


@pytest.fixture
def sample_task():
    """Create a sample Task for testing."""
    return Task(
        task_id="task-20250131-100000-test-task",
        task_doc_file="tasks/task-documents/task-20250131-100000-test-task.md",
        task_doc_dir_id="main",
        status=TaskStatus.PENDING,
        source=TaskSource.LOAD,
    )


@pytest.fixture
def sample_task_result():
    """Create a sample TaskResult for testing."""
    return TaskResult(
        task_id="test-task-001",
        task_doc_file="tasks/task-documents/test-task.md",
        task_doc_dir_id="main",
        status=TaskStatus.COMPLETED,
        started_at="2025-01-31T10:00:05",
        completed_at="2025-01-31T10:00:15",
        duration_seconds=10.5,
        cost_usd=0.05,
        stdout="Processing complete",
        stderr=None,
        attempts=1,
    )


@pytest.fixture
def sample_queue_state():
    """Create a sample QueueState for testing."""
    return QueueState(
        queue=[
            Task(
                task_id="task-001.md",
                task_doc_file="tasks/task-documents/task-001.md",
                task_doc_dir_id="main",
                status=TaskStatus.PENDING,
            ),
            Task(
                task_id="task-002.md",
                task_doc_file="tasks/task-documents/task-002.md",
                task_doc_dir_id="main",
                status=TaskStatus.COMPLETED,
            ),
        ],
    )


@pytest.fixture
def sample_config():
    """Create a sample QueueConfig for testing."""
    return QueueConfig(
        project_path="/tmp/test-project",
        task_doc_directories=[
            TaskDocDirectory(
                id="main",
                path="/tmp/test-project/tasks/task-documents",
                description="Main task doc directory"
            )
        ]
    )


@pytest.fixture
def mock_query():
    """Create a mock Claude SDK query object."""
    success_msg = Mock()
    success_msg.subtype = "success"
    success_msg.result = "Task completed successfully"
    success_msg.usage = {"total_tokens": 1000}
    success_msg.total_cost_usd = 0.05

    content_msg = Mock(spec=['content'])
    content_msg.content = [Mock(text="Processing...")]

    return AsyncIteratorMock([content_msg, success_msg])


@pytest.fixture
def task_spec_file(task_spec_dir):
    """Create a sample task specification file."""
    task_file = task_spec_dir / "task-20250131-100000-test-task.md"
    task_file.write_text("""# Task: Test Task

**Status**: pending

---

## Task
Test task description

## Context
Test context

## Requirements
1. Test requirement
""")
    return task_file


@pytest.fixture
def queue_state_file(task_queue_dir):
    """Create a queue state file."""
    state_file = task_queue_dir / "state" / "queue_state.json"
    state_data = {
        "version": "1.0",
        "queue": [
            {
                "task_id": "task-001.md",
                "task_doc_file": "tasks/task-documents/task-001.md",
                "task_doc_dir_id": "main",
                "status": "pending",
                "source": "load",
                "added_at": "2025-01-31T10:00:00",
                "attempts": 0
            }
        ],
        "processing": {
            "is_processing": False,
            "current_task": None
        },
        "statistics": {
            "total_queued": 1,
            "total_completed": 0,
            "total_failed": 0
        },
        "updated_at": "2025-01-31T10:00:00"
    }
    state_file.write_text(json.dumps(state_data))
    return state_file
