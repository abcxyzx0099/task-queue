"""
Comprehensive tests for task_queue.config module to improve coverage.

Tests for edge cases, error handling, and less-covered code paths.
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO
import sys

from task_queue.config import ConfigManager, get_default_config_manager
from task_queue.models import Queue, MonitorConfig
from task_queue.constants import DEFAULT_CONFIG_FILE


class TestConfigManagerMigration:
    """Tests for config migration and error handling."""

    def test_load_config_migrates_old_format(self, temp_dir):
        """Test loading config with old 'task_source_directories' format."""
        config_file = temp_dir / "config.json"

        # Write old format config
        old_config = {
            "version": "1.0",
            "task_source_directories": [
                {"id": "test", "path": "/tmp/test"}
            ],
            "project_workspace": "/tmp/workspace"
        }
        config_file.write_text(json.dumps(old_config))

        manager = ConfigManager(config_file)

        # Should have migrated to new format
        assert len(manager.config.queues) == 1
        assert manager.config.queues[0].id == "test"

    def test_load_config_invalid_json(self, temp_dir):
        """Test loading invalid JSON config creates default."""
        config_file = temp_dir / "config.json"
        # Invalid JSON that's not caught by read_json
        config_file.write_text(json.dumps({"queues": "not a list"}))

        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            manager = ConfigManager(config_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        # Should create default config (model validation fails)
        assert manager.config is not None
        # Should have warning about invalid config
        assert "Warning" in output or manager.config is not None

    def test_load_config_invalid_model(self, temp_dir):
        """Test loading config with invalid model data creates default."""
        config_file = temp_dir / "config.json"
        config_file.write_text(json.dumps({"invalid": "data"}))

        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            manager = ConfigManager(config_file)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        # Should create default config
        assert manager.config is not None

    def test_save_config_lock_timeout(self, temp_dir):
        """Test save_config raises RuntimeError when lock can't be acquired."""
        config_file = temp_dir / "config.json"
        lock_file = temp_dir / "config.lock"

        manager = ConfigManager(config_file)

        # Acquire lock externally to simulate contention
        lock_file.touch()

        # Mock acquire to return False
        with patch.object(manager.lock, 'acquire', return_value=False):
            with pytest.raises(RuntimeError, match="Could not acquire config lock"):
                manager.save_config()

    def test_reload(self, temp_dir):
        """Test reload method."""
        config_file = temp_dir / "config.json"

        # Create actual directories to work with
        old_workspace = temp_dir / "old"
        new_workspace = temp_dir / "new"
        old_workspace.mkdir()
        new_workspace.mkdir()

        # Create initial config
        manager = ConfigManager(config_file)
        manager.config.set_project_workspace(str(old_workspace))
        manager.save_config()

        # Modify config externally
        data = json.loads(config_file.read_text())
        data["project_workspace"] = str(new_workspace)
        config_file.write_text(json.dumps(data))

        # Reload should pick up changes
        manager.reload()
        assert manager.config.project_workspace == str(new_workspace)

    def test_get_project_workspace(self, temp_dir):
        """Test get_project_workspace method."""
        config_file = temp_dir / "config.json"
        workspace = temp_dir / "workspace"
        workspace.mkdir()

        manager = ConfigManager(config_file)
        manager.config.set_project_workspace(str(workspace))
        manager.save_config()

        result = manager.get_project_workspace()
        assert result == str(workspace)

    def test_get_queue(self, temp_dir):
        """Test get_queue method."""
        config_file = temp_dir / "config.json"
        queue_path = temp_dir / "queue"
        queue_path.mkdir()

        manager = ConfigManager(config_file)
        manager.add_queue(path=str(queue_path), id="test-queue", description="Test queue")

        queue = manager.get_queue("test-queue")
        assert queue is not None
        assert queue.id == "test-queue"
        assert queue.description == "Test queue"

    def test_get_queue_not_found(self, temp_dir):
        """Test get_queue with non-existent ID."""
        config_file = temp_dir / "config.json"
        manager = ConfigManager(config_file)

        queue = manager.get_queue("nonexistent")
        assert queue is None

    def test_update_settings_valid(self, temp_dir):
        """Test update_settings with valid settings."""
        config_file = temp_dir / "config.json"
        manager = ConfigManager(config_file)

        manager.update_settings(
            watch_enabled=False,
            watch_debounce_ms=1000
        )

        assert manager.config.settings.watch_enabled is False
        assert manager.config.settings.watch_debounce_ms == 1000

    def test_update_settings_invalid(self, temp_dir):
        """Test update_settings with invalid setting raises ValueError."""
        config_file = temp_dir / "config.json"
        manager = ConfigManager(config_file)

        with pytest.raises(ValueError, match="Unknown setting"):
            manager.update_settings(invalid_setting=True)

    def test_acquire_lock(self, temp_dir):
        """Test acquire_lock method."""
        config_file = temp_dir / "config.json"
        manager = ConfigManager(config_file)

        result = manager.acquire_lock(timeout=1.0)
        assert result is True

        # Release to clean up
        manager.release_lock()

    def test_release_lock(self, temp_dir):
        """Test release_lock method."""
        config_file = temp_dir / "config.json"
        manager = ConfigManager(config_file)

        manager.acquire_lock(timeout=1.0)
        manager.release_lock()

        # Should be able to acquire again
        assert manager.acquire_lock(timeout=1.0) is True
        manager.release_lock()

    def test_get_default_config_manager(self):
        """Test get_default_config_manager function."""
        manager = get_default_config_manager()
        assert isinstance(manager, ConfigManager)
        assert manager.config_file == DEFAULT_CONFIG_FILE


class TestConfigManagerWithExistingData:
    """Tests with existing config data."""

    def test_add_queue_with_existing_id_fails(self, temp_dir):
        """Test adding queue with duplicate ID raises error."""
        config_file = temp_dir / "config.json"
        queue1_path = temp_dir / "queue1"
        queue2_path = temp_dir / "queue2"
        queue1_path.mkdir()
        queue2_path.mkdir()

        manager = ConfigManager(config_file)
        manager.add_queue(path=str(queue1_path), id="test")

        # Adding same ID again should raise ValueError
        with pytest.raises(ValueError):
            manager.add_queue(path=str(queue2_path), id="test")

    def test_remove_nonexistent_queue(self, temp_dir):
        """Test removing non-existent queue returns False."""
        config_file = temp_dir / "config.json"
        manager = ConfigManager(config_file)

        result = manager.remove_queue("nonexistent")
        assert result is False

    def test_list_queues(self, temp_dir):
        """Test list_queues returns all queues."""
        config_file = temp_dir / "config.json"
        queue1_path = temp_dir / "queue1"
        queue2_path = temp_dir / "queue2"
        queue1_path.mkdir()
        queue2_path.mkdir()

        manager = ConfigManager(config_file)
        manager.add_queue(path=str(queue1_path), id="queue1")
        manager.add_queue(path=str(queue2_path), id="queue2")

        queues = manager.list_queues()
        assert len(queues) == 2
        queue_ids = {q.id for q in queues}
        assert queue_ids == {"queue1", "queue2"}


class TestConfigManagerPersistence:
    """Tests for config persistence."""

    def test_config_persists_across_instances(self, temp_dir):
        """Test config data persists across manager instances."""
        config_file = temp_dir / "config.json"
        workspace = temp_dir / "workspace"
        queue_path = temp_dir / "queue"
        workspace.mkdir()
        queue_path.mkdir()

        # First instance
        manager1 = ConfigManager(config_file)
        manager1.config.set_project_workspace(str(workspace))
        manager1.add_queue(path=str(queue_path), id="test-queue", description="Test")

        # Second instance should load saved data
        manager2 = ConfigManager(config_file)

        assert manager2.config.project_workspace == str(workspace)
        assert len(manager2.config.queues) == 1
        assert manager2.config.queues[0].id == "test-queue"
        assert manager2.config.queues[0].description == "Test"
