"""Tests for task_queue models."""

import pytest
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError

from task_queue.models import (
    TaskStatus, TaskSource, Task, TaskResult, QueueState,
    TaskSourceDirectory, QueueSettings, QueueConfig, SourceStatistics,
    SourceProcessingState, DiscoveredTask, SystemStatus, TaskSourceDirectoryStatus,
    SourceState, CoordinatorState, GlobalStatistics,
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
        assert TaskSource.WATCHDOG == "watchdog"
        assert TaskSource.RELOAD == "reload"


class TestTask:
    """Tests for Task model."""

    def test_create_task(self):
        """Test creating a Task."""
        task = Task(
            task_id="task-20250131-100000-test",
            task_doc_file="tasks/task-documents/task.md",
            task_doc_dir_id="main"
        )
        assert task.task_id == "task-20250131-100000-test"
        assert task.task_doc_file == "tasks/task-documents/task.md"
        assert task.task_doc_dir_id == "main"
        assert task.status == TaskStatus.PENDING
        assert task.source == TaskSource.LOAD
        assert task.attempts == 0
        assert task.last_modified is None

    def test_task_with_all_fields(self):
        """Test creating a Task with all fields."""
        task = Task(
            task_id="task-20250131-100000-test",
            task_doc_file="tasks/task-documents/task.md",
            task_doc_dir_id="main",
            status=TaskStatus.COMPLETED,
            source=TaskSource.MANUAL,
            started_at="2025-01-31T10:00:00",
            completed_at="2025-01-31T10:00:10",
            attempts=2,
            error="Test error",
            last_modified="2025-01-31T09:55:00"
        )
        assert task.status == TaskStatus.COMPLETED
        assert task.source == TaskSource.MANUAL
        assert task.attempts == 2
        assert task.error == "Test error"
        assert task.last_modified == "2025-01-31T09:55:00"


class TestTaskResult:
    """Tests for TaskResult model."""

    def test_create_task_result(self):
        """Test creating a TaskResult."""
        result = TaskResult(
            task_id="task-001",
            task_doc_file="tasks/task-documents/task.md",
            task_doc_dir_id="main",
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
            task_doc_file="tasks/task-documents/task.md",
            task_doc_dir_id="main",
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


class TestSourceState:
    """Tests for SourceState model (per-source queue)."""

    def test_create_empty_source_state(self):
        """Test creating an empty SourceState."""
        state = SourceState(
            id="main",
            path="/path/to/source"
        )
        assert state.id == "main"
        assert state.path == "/path/to/source"
        assert state.queue == []
        assert state.processing.is_processing is False
        assert state.get_pending_count() == 0
        assert state.get_running_count() == 0
        assert state.get_completed_count() == 0
        assert state.get_failed_count() == 0

    def test_source_state_counts(self):
        """Test SourceState count methods."""
        state = SourceState(
            id="main",
            path="/path/to/source",
            queue=[
                Task(task_id="t1", task_doc_file="t1.md", task_doc_dir_id="main", status=TaskStatus.PENDING),
                Task(task_id="t2", task_doc_file="t2.md", task_doc_dir_id="main", status=TaskStatus.PENDING),
                Task(task_id="t3", task_doc_file="t3.md", task_doc_dir_id="main", status=TaskStatus.RUNNING),
                Task(task_id="t4", task_doc_file="t4.md", task_doc_dir_id="main", status=TaskStatus.COMPLETED),
                Task(task_id="t5", task_doc_file="t5.md", task_doc_dir_id="main", status=TaskStatus.FAILED),
            ]
        )
        assert state.get_pending_count() == 2
        assert state.get_running_count() == 1
        assert state.get_completed_count() == 1
        assert state.get_failed_count() == 1

    def test_get_next_pending(self):
        """Test getting next pending task from source."""
        state = SourceState(
            id="main",
            path="/path/to/source",
            queue=[
                Task(task_id="t1", task_doc_file="t1.md", task_doc_dir_id="main", status=TaskStatus.PENDING),
                Task(task_id="t2", task_doc_file="t2.md", task_doc_dir_id="main", status=TaskStatus.RUNNING),
                Task(task_id="t3", task_doc_file="t3.md", task_doc_dir_id="main", status=TaskStatus.PENDING),
            ]
        )
        next_task = state.get_next_pending()
        assert next_task is not None
        assert next_task.task_id == "t1"


class TestQueueState:
    """Tests for QueueState model (v2.0 with per-source queues)."""

    def test_create_empty_queue_state(self):
        """Test creating an empty QueueState v2.0."""
        state = QueueState()
        assert state.version == "2.0"
        assert state.sources == {}
        assert state.get_total_pending_count() == 0
        assert state.get_total_running_count() == 0
        assert state.get_total_completed_count() == 0
        assert state.get_total_failed_count() == 0

    def test_queue_state_with_sources(self):
        """Test QueueState with multiple sources."""
        state = QueueState(
            sources={
                "main": SourceState(
                    id="main",
                    path="/path/to/main",
                    queue=[
                        Task(task_id="t1", task_doc_file="t1.md", task_doc_dir_id="main", status=TaskStatus.PENDING),
                        Task(task_id="t2", task_doc_file="t2.md", task_doc_dir_id="main", status=TaskStatus.COMPLETED),
                    ]
                ),
                "experimental": SourceState(
                    id="experimental",
                    path="/path/to/exp",
                    queue=[
                        Task(task_id="t3", task_doc_file="t3.md", task_doc_dir_id="experimental", status=TaskStatus.RUNNING),
                    ]
                )
            }
        )
        assert state.get_total_pending_count() == 1
        assert state.get_total_running_count() == 1
        assert state.get_total_completed_count() == 1
        assert state.get_total_failed_count() == 0


class TestTaskSourceDirectory:
    """Tests for TaskSourceDirectory model."""

    def test_create_task_source_directory(self, tmp_path):
        """Test creating a TaskSourceDirectory."""
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()

        doc = TaskSourceDirectory(
            id="main",
            path=str(doc_dir),
            description="Main task source directory"
        )
        assert doc.id == "main"
        assert doc.description == "Main task source directory"

    def test_task_source_directory_path_validation(self):
        """Test TaskSourceDirectory path validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskSourceDirectory(id="main", path="/nonexistent/path")
        assert "does not exist" in str(exc_info.value).lower()


class TestQueueConfig:
    """Tests for QueueConfig model."""

    def test_create_empty_config(self):
        """Test creating an empty QueueConfig."""
        config = QueueConfig()
        assert config.project_workspace is None
        assert config.task_source_directories == []
        assert config.settings.watch_enabled is True
        assert config.settings.watch_debounce_ms == 500

    def test_set_project_workspace(self, tmp_path):
        """Test setting project workspace."""
        config = QueueConfig()
        config.set_project_workspace(str(tmp_path))
        assert config.project_workspace == str(tmp_path.resolve())

    def test_set_project_workspace_validation(self):
        """Test project workspace validation."""
        config = QueueConfig()
        with pytest.raises(ValueError) as exc_info:
            config.set_project_workspace("/nonexistent/path")
        assert "does not exist" in str(exc_info.value).lower()

    def test_add_task_source_directory(self, tmp_path):
        """Test adding a task source directory."""
        config = QueueConfig()
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        source = config.add_task_source_directory(
            path=str(source_dir),
            id="main",
            description="Test sources"
        )
        assert source.id == "main"
        assert len(config.task_source_directories) == 1

    def test_add_duplicate_source_directory(self, tmp_path):
        """Test adding duplicate source directory."""
        config = QueueConfig()
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        config.add_task_source_directory(path=str(source_dir), id="main")

        with pytest.raises(ValueError) as exc_info:
            config.add_task_source_directory(path=str(source_dir), id="main")
        assert "already exists" in str(exc_info.value).lower()

    def test_remove_task_source_directory(self, tmp_path):
        """Test removing a source directory."""
        config = QueueConfig()
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        config.add_task_source_directory(path=str(source_dir), id="main")
        assert len(config.task_source_directories) == 1

        result = config.remove_task_source_directory("main")
        assert result is True
        assert len(config.task_source_directories) == 0

    def test_get_task_source_directory(self, tmp_path):
        """Test getting a source directory."""
        config = QueueConfig()
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        config.add_task_source_directory(path=str(source_dir), id="main")
        source = config.get_task_source_directory("main")
        assert source is not None
        assert source.id == "main"

        source = config.get_task_source_directory("nonexistent")
        assert source is None


class TestQueueSettings:
    """Tests for QueueSettings model."""

    def test_default_settings(self):
        """Test default QueueSettings."""
        settings = QueueSettings()
        assert settings.watch_enabled is True
        assert settings.watch_debounce_ms == 500
        assert settings.watch_patterns == ["task-*.md"]
        assert settings.watch_recursive is False
        assert settings.task_pattern == "task-*.md"
        assert settings.max_attempts == 3
        assert settings.enable_file_hash is True


class TestSourceStatistics:
    """Tests for SourceStatistics model."""

    def test_empty_statistics(self):
        """Test empty SourceStatistics."""
        stats = SourceStatistics()
        assert stats.total_queued == 0
        assert stats.total_completed == 0
        assert stats.total_failed == 0
        assert stats.last_processed_at is None
        assert stats.last_loaded_at is None

    def test_statistics_with_values(self):
        """Test SourceStatistics with values."""
        stats = SourceStatistics(
            total_queued=10,
            total_completed=5,
            total_failed=2,
            last_processed_at="2025-01-31T10:00:00",
            last_loaded_at="2025-01-31T09:00:00"
        )
        assert stats.total_queued == 10
        assert stats.total_completed == 5
        assert stats.total_failed == 2


class TestSourceProcessingState:
    """Tests for SourceProcessingState model."""

    def test_not_processing(self):
        """Test SourceProcessingState when not processing."""
        state = SourceProcessingState()
        assert state.is_processing is False
        assert state.current_task is None
        assert state.process_id is None
        assert state.started_at is None
        assert state.hostname is None

    def test_processing_state(self):
        """Test SourceProcessingState when processing."""
        state = SourceProcessingState(
            is_processing=True,
            current_task="task-001",
            process_id=12345,
            started_at="2025-01-31T10:00:00",
            hostname="localhost"
        )
        assert state.is_processing is True
        assert state.current_task == "task-001"
        assert state.process_id == 12345
        assert state.hostname == "localhost"


class TestCoordinatorState:
    """Tests for CoordinatorState model."""

    def test_empty_coordinator(self):
        """Test empty CoordinatorState."""
        state = CoordinatorState()
        assert state.current_source is None
        assert state.last_switch is None
        assert state.source_order == []

    def test_coordinator_with_order(self):
        """Test CoordinatorState with source order."""
        state = CoordinatorState(
            current_source="main",
            last_switch="2025-01-31T10:00:00",
            source_order=["main", "experimental", "test"]
        )
        assert state.current_source == "main"
        assert len(state.source_order) == 3
        assert state.source_order[0] == "main"


class TestGlobalStatistics:
    """Tests for GlobalStatistics model."""

    def test_empty_global_statistics(self):
        """Test empty GlobalStatistics."""
        stats = GlobalStatistics()
        assert stats.total_sources == 0
        assert stats.total_queued == 0
        assert stats.total_completed == 0
        assert stats.total_failed == 0
        assert stats.last_processed_at is None


class TestDiscoveredTask:
    """Tests for DiscoveredTask model."""

    def test_create_discovered_task(self, tmp_path):
        """Test creating a DiscoveredTask."""
        task_file = tmp_path / "task-001.md"
        task_file.write_text("# Test task")

        task = DiscoveredTask(
            task_id="task-001",
            task_doc_file=task_file,
            task_doc_dir_id="main",
            file_hash="abc123",
            file_size=100
        )
        assert task.task_id == "task-001"
        assert task.task_doc_dir_id == "main"
        assert task.file_hash == "abc123"
        assert task.file_size == 100


class TestSystemStatus:
    """Tests for SystemStatus model."""

    def test_empty_system_status(self):
        """Test empty SystemStatus."""
        status = SystemStatus()
        assert status.running is False
        assert status.uptime_seconds == 0.0
        assert status.load_count == 0
        assert status.project_workspace is None
        assert status.total_task_source_dirs == 0
        assert status.total_pending == 0
        assert status.total_completed == 0


class TestTaskSourceDirectoryStatus:
    """Tests for TaskSourceDirectoryStatus model."""

    def test_source_directory_status(self):
        """Test TaskSourceDirectoryStatus."""
        status = TaskSourceDirectoryStatus(
            id="main",
            path="/path/to/main",
            description="Main source",
            queue_stats={"pending": 5, "running": 1, "completed": 10}
        )
        assert status.id == "main"
        assert status.path == "/path/to/main"
        assert status.queue_stats["pending"] == 5
