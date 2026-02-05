"""Test fixtures for task-queue tests (Directory-Based State Architecture)."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock

from task_queue.models import (
    QueueConfig, TaskSourceDirectory, QueueSettings, DiscoveredTask
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def project_root(temp_dir):
    """Create a mock project root with task directories."""
    task_spec_dir = temp_dir / "tasks" / "task-documents"
    task_archive_dir = temp_dir / "tasks" / "task-archive"
    task_failed_dir = temp_dir / "tasks" / "task-failed"

    task_spec_dir.mkdir(parents=True)
    task_archive_dir.mkdir(parents=True)
    task_failed_dir.mkdir(parents=True)

    return temp_dir


@pytest.fixture
def task_source_dir(project_root):
    """Get the task source directory."""
    return project_root / "tasks" / "task-documents"


@pytest.fixture
def task_archive_dir(project_root):
    """Get the task archive directory."""
    return project_root / "tasks" / "task-archive"


@pytest.fixture
def task_failed_dir(project_root):
    """Get the task failed directory."""
    return project_root / "tasks" / "task-failed"


@pytest.fixture
def sample_task_source_dir(temp_dir):
    """Create a sample TaskSourceDirectory."""
    source_path = temp_dir / "tasks" / "task-documents"
    source_path.mkdir(parents=True)

    return TaskSourceDirectory(
        id="test-source",
        path=str(source_path),
        description="Test source directory"
    )


@pytest.fixture
def sample_config(temp_dir):
    """Create a sample QueueConfig."""
    source_path = temp_dir / "tasks" / "task-documents"
    source_path.mkdir(parents=True)

    return QueueConfig(
        project_workspace=str(temp_dir),
        task_source_directories=[
            TaskSourceDirectory(
                id="test-source",
                path=str(source_path),
                description="Test source directory"
            )
        ]
    )


@pytest.fixture
def sample_settings():
    """Create sample QueueSettings."""
    return QueueSettings(
        watch_enabled=True,
        watch_debounce_ms=500,
        watch_patterns=["task-*.md"],
        watch_recursive=False
    )


@pytest.fixture
def task_spec_file(task_source_dir):
    """Create a sample task specification file."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    task_file = task_source_dir / f"task-{timestamp}-test-task.md"
    task_file.write_text("""# Task: Test Task

Test task description
""")
    return task_file


@pytest.fixture
def multiple_task_files(task_source_dir):
    """Create multiple task specification files."""
    tasks = []
    for i in range(3):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        task_file = task_source_dir / f"task-{timestamp}-test-{i:02d}.md"
        task_file.write_text(f"# Task: Test Task {i}\n\nTest description\n")
        tasks.append(task_file)
    return tasks
