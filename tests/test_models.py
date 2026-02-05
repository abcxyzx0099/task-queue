"""Tests for task_queue models (Directory-Based State Architecture)."""

import pytest
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError
import tempfile
import shutil

from task_queue.models import (
    TaskSourceDirectory, QueueSettings, QueueConfig, DiscoveredTask
)


class TestTaskSourceDirectory:
    """Tests for TaskSourceDirectory model."""

    def test_create_task_source_directory(self):
        """Test creating a TaskSourceDirectory."""
        source_dir = TaskSourceDirectory(
            id="test-source",
            path="/tmp/test/tasks",
            description="Test directory"
        )
        assert source_dir.id == "test-source"
        assert source_dir.path == "/tmp/test/tasks"
        assert source_dir.description == "Test directory"
        assert source_dir.added_at is not None

    def test_task_source_directory_defaults(self):
        """Test TaskSourceDirectory default values."""
        source_dir = TaskSourceDirectory(
            id="test",
            path="/tmp/test"
        )
        assert source_dir.description == ""
        assert source_dir.added_at is not None


class TestQueueSettings:
    """Tests for QueueSettings model."""

    def test_create_queue_settings(self):
        """Test creating QueueSettings."""
        settings = QueueSettings(
            watch_enabled=True,
            watch_debounce_ms=500,
            watch_patterns=["task-*.md"],
            watch_recursive=False,
            max_attempts=3,
            enable_file_hash=True
        )
        assert settings.watch_enabled is True
        assert settings.watch_debounce_ms == 500
        assert settings.watch_patterns == ["task-*.md"]
        assert settings.watch_recursive is False
        assert settings.max_attempts == 3
        assert settings.enable_file_hash is True

    def test_queue_settings_defaults(self):
        """Test QueueSettings default values."""
        settings = QueueSettings()
        assert settings.watch_enabled is True
        assert settings.watch_debounce_ms == 500
        assert settings.watch_patterns == ["task-*.md"]
        assert settings.watch_recursive is False
        assert settings.max_attempts == 3
        assert settings.enable_file_hash is True


class TestQueueConfig:
    """Tests for QueueConfig model."""

    def test_create_queue_config(self):
        """Test creating QueueConfig."""
        config = QueueConfig(
            project_workspace="/tmp/test",
            task_source_directories=[
                TaskSourceDirectory(
                    id="test",
                    path="/tmp/test/tasks"
                )
            ]
        )
        assert config.version == "2.0"
        assert config.project_workspace == "/tmp/test"
        assert len(config.task_source_directories) == 1
        assert isinstance(config.settings, QueueSettings)

    def test_queue_config_defaults(self):
        """Test QueueConfig default values."""
        config = QueueConfig()
        assert config.version == "2.0"
        assert config.project_workspace is None
        assert config.task_source_directories == []
        assert isinstance(config.settings, QueueSettings)

    def test_get_task_source_directory(self, sample_config):
        """Test getting a TaskSourceDirectory by ID."""
        source_dir = sample_config.get_task_source_directory("test-source")
        assert source_dir is not None
        assert source_dir.id == "test-source"

    def test_get_task_source_directory_not_found(self, sample_config):
        """Test getting a non-existent TaskSourceDirectory."""
        source_dir = sample_config.get_task_source_directory("non-existent")
        assert source_dir is None

    def test_add_task_source_directory(self, temp_dir):
        """Test adding a TaskSourceDirectory."""
        config = QueueConfig(project_workspace=str(temp_dir))

        source_path = temp_dir / "tasks"
        source_path.mkdir(parents=True)

        source_dir = config.add_task_source_directory(
            path=str(source_path),
            id="new-source",
            description="New source"
        )

        assert source_dir.id == "new-source"
        assert len(config.task_source_directories) == 1
        assert config.task_source_directories[0].id == "new-source"

    def test_add_task_source_directory_duplicate_id(self, temp_dir):
        """Test adding a TaskSourceDirectory with duplicate ID."""
        config = QueueConfig(project_workspace=str(temp_dir))

        source_path = temp_dir / "tasks"
        source_path.mkdir(parents=True)

        config.add_task_source_directory(
            path=str(source_path),
            id="test-source"
        )

        with pytest.raises(ValueError, match="already exists"):
            config.add_task_source_directory(
                path=str(source_path),
                id="test-source"
            )

    def test_add_task_source_directory_invalid_path(self, temp_dir):
        """Test adding a TaskSourceDirectory with invalid path."""
        config = QueueConfig(project_workspace=str(temp_dir))

        with pytest.raises(ValueError, match="does not exist"):
            config.add_task_source_directory(
                path="/nonexistent/path",
                id="test"
            )

    def test_remove_task_source_directory(self, sample_config):
        """Test removing a TaskSourceDirectory."""
        result = sample_config.remove_task_source_directory("test-source")
        assert result is True
        assert len(sample_config.task_source_directories) == 0

    def test_remove_task_source_directory_not_found(self, sample_config):
        """Test removing a non-existent TaskSourceDirectory."""
        result = sample_config.remove_task_source_directory("non-existent")
        assert result is False



class TestDiscoveredTask:
    """Tests for DiscoveredTask model."""

    def test_create_discovered_task(self):
        """Test creating a DiscoveredTask."""
        task = DiscoveredTask(
            task_id="task-20250131-100000-test",
            task_doc_file=Path("/tmp/test.md"),
            task_doc_dir_id="main",
            file_hash="abc123",
            file_size=1024,
            discovered_at="2025-01-31T10:00:00"
        )
        assert task.task_id == "task-20250131-100000-test"
        assert task.task_doc_file == Path("/tmp/test.md")
        assert task.task_doc_dir_id == "main"
        assert task.file_hash == "abc123"
        assert task.file_size == 1024

    def test_discovered_task_defaults(self):
        """Test DiscoveredTask default values."""
        task = DiscoveredTask(
            task_id="task-test",
            task_doc_file=Path("/tmp/test.md"),
            task_doc_dir_id="main",
            discovered_at="2025-01-31T10:00:00"
        )
        assert task.file_hash is None
        assert task.file_size == 0
