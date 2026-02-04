"""Tests for task_queue models."""

import pytest
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError

from task_queue.models import (
    TaskStatus, TaskSource, Task, TaskResult, QueueState,
    SpecDirectory, QueueSettings, QueueConfig, Statistics,
    ProcessingState, DiscoveredTask, SystemStatus, SpecDirectoryStatus
)


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_status_values(self):
        """Test TaskStatus enum values."""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"


class TestTaskSource:
    """Tests for TaskSource enum."""

    def test_source_values(self):
        """Test TaskSource enum values."""
        assert TaskSource.LOAD == "load"
        assert TaskSource.MANUAL == "manual"
        assert TaskSource.API == "api"


class TestTask:
    """Tests for Task model."""

    def test_create_task(self):
        """Test creating a Task."""
        task = Task(
            task_id="task-20250131-100000-test",
            spec_file="tasks/task-documents/task.md",
            spec_dir_id="main"
        )
        assert task.task_id == "task-20250131-100000-test"
        assert task.spec_file == "tasks/task-documents/task.md"
        assert task.spec_dir_id == "main"
        assert task.status == TaskStatus.PENDING
        assert task.source == TaskSource.LOAD
        assert task.attempts == 0

    def test_task_with_all_fields(self):
        """Test creating a Task with all fields."""
        task = Task(
            task_id="task-20250131-100000-test",
            spec_file="tasks/task-documents/task.md",
            spec_dir_id="main",
            status=TaskStatus.COMPLETED,
            source=TaskSource.MANUAL,
            started_at="2025-01-31T10:00:00",
            completed_at="2025-01-31T10:00:10",
            attempts=2,
            error="Test error"
        )
        assert task.status == TaskStatus.COMPLETED
        assert task.source == TaskSource.MANUAL
        assert task.attempts == 2
        assert task.error == "Test error"


class TestTaskResult:
    """Tests for TaskResult model."""

    def test_create_task_result(self):
        """Test creating a TaskResult."""
        result = TaskResult(
            task_id="task-001",
            spec_file="tasks/task-documents/task.md",
            spec_dir_id="main",
            status=TaskStatus.COMPLETED,
            started_at="2025-01-31T10:00:00",
            completed_at="2025-01-31T10:00:10",
            duration_seconds=10.0
        )
        assert result.task_id == "task-001"
        assert result.status == TaskStatus.COMPLETED
        assert result.duration_seconds == 10.0
        assert result.cost_usd == 0.0

    def test_task_result_with_output(self):
        """Test TaskResult with output."""
        result = TaskResult(
            task_id="task-001",
            spec_file="tasks/task-documents/task.md",
            spec_dir_id="main",
            status=TaskStatus.FAILED,
            started_at="2025-01-31T10:00:00",
            duration_seconds=5.0,
            stdout="Some output",
            stderr="Error occurred",
            error="Task failed"
        )
        assert result.stdout == "Some output"
        assert result.stderr == "Error occurred"
        assert result.error == "Task failed"


class TestQueueState:
    """Tests for QueueState model."""

    def test_create_empty_queue_state(self):
        """Test creating an empty QueueState."""
        state = QueueState()
        assert state.queue == []
        assert state.processing.is_processing is False
        assert state.get_pending_count() == 0
        assert state.get_running_count() == 0
        assert state.get_completed_count() == 0
        assert state.get_failed_count() == 0

    def test_queue_state_counts(self):
        """Test QueueState count methods."""
        state = QueueState(queue=[
            Task(task_id="t1", spec_file="t1.md", spec_dir_id="main", status=TaskStatus.PENDING),
            Task(task_id="t2", spec_file="t2.md", spec_dir_id="main", status=TaskStatus.PENDING),
            Task(task_id="t3", spec_file="t3.md", spec_dir_id="main", status=TaskStatus.RUNNING),
            Task(task_id="t4", spec_file="t4.md", spec_dir_id="main", status=TaskStatus.COMPLETED),
            Task(task_id="t5", spec_file="t5.md", spec_dir_id="main", status=TaskStatus.FAILED),
        ])
        assert state.get_pending_count() == 2
        assert state.get_running_count() == 1
        assert state.get_completed_count() == 1
        assert state.get_failed_count() == 1

    def test_get_next_pending(self):
        """Test getting next pending task."""
        state = QueueState(queue=[
            Task(task_id="t1", spec_file="t1.md", spec_dir_id="main", status=TaskStatus.PENDING),
            Task(task_id="t2", spec_file="t2.md", spec_dir_id="main", status=TaskStatus.RUNNING),
            Task(task_id="t3", spec_file="t3.md", spec_dir_id="main", status=TaskStatus.PENDING),
        ])
        next_task = state.get_next_pending()
        assert next_task is not None
        assert next_task.task_id == "t1"


class TestSpecDirectory:
    """Tests for SpecDirectory model."""

    def test_create_spec_directory(self, tmp_path):
        """Test creating a SpecDirectory."""
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        spec = SpecDirectory(
            id="main",
            path=str(spec_dir),
            description="Main spec directory"
        )
        assert spec.id == "main"
        assert spec.description == "Main spec directory"

    def test_spec_directory_path_validation(self):
        """Test SpecDirectory path validation."""
        with pytest.raises(ValidationError) as exc_info:
            SpecDirectory(id="main", path="/nonexistent/path")
        assert "does not exist" in str(exc_info.value).lower()


class TestQueueConfig:
    """Tests for QueueConfig model."""

    def test_create_empty_config(self):
        """Test creating an empty QueueConfig."""
        config = QueueConfig()
        assert config.project_path is None
        assert config.spec_directories == []
        assert config.settings.processing_interval == 10

    def test_set_project_path(self, tmp_path):
        """Test setting project path."""
        config = QueueConfig()
        config.set_project_path(str(tmp_path))
        assert config.project_path == str(tmp_path.resolve())

    def test_set_project_path_validation(self):
        """Test project path validation."""
        config = QueueConfig()
        with pytest.raises(ValueError) as exc_info:
            config.set_project_path("/nonexistent/path")
        assert "does not exist" in str(exc_info.value).lower()

    def test_add_spec_directory(self, tmp_path):
        """Test adding a spec directory."""
        config = QueueConfig()
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        spec = config.add_spec_directory(
            path=str(spec_dir),
            id="main",
            description="Test specs"
        )
        assert spec.id == "main"
        assert len(config.spec_directories) == 1

    def test_add_duplicate_spec_directory(self, tmp_path):
        """Test adding duplicate spec directory."""
        config = QueueConfig()
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        config.add_spec_directory(path=str(spec_dir), id="main")

        with pytest.raises(ValueError) as exc_info:
            config.add_spec_directory(path=str(spec_dir), id="main")
        assert "already exists" in str(exc_info.value).lower()

    def test_remove_spec_directory(self, tmp_path):
        """Test removing a spec directory."""
        config = QueueConfig()
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        config.add_spec_directory(path=str(spec_dir), id="main")
        assert len(config.spec_directories) == 1

        result = config.remove_spec_directory("main")
        assert result is True
        assert len(config.spec_directories) == 0

    def test_get_spec_directory(self, tmp_path):
        """Test getting a spec directory."""
        config = QueueConfig()
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        config.add_spec_directory(path=str(spec_dir), id="main")
        spec = config.get_spec_directory("main")
        assert spec is not None
        assert spec.id == "main"

        spec = config.get_spec_directory("nonexistent")
        assert spec is None


class TestQueueSettings:
    """Tests for QueueSettings model."""

    def test_default_settings(self):
        """Test default QueueSettings."""
        settings = QueueSettings()
        assert settings.processing_interval == 10
        assert settings.batch_size == 10
        assert settings.task_spec_pattern == "task-*.md"
        assert settings.max_attempts == 3
        assert settings.enable_file_hash is True
