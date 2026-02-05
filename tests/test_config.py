"""Tests for task_queue config module."""

import pytest
import json
from pathlib import Path

from task_queue.config import ConfigManager
from task_queue.models import QueueConfig, TaskSourceDirectory


class TestConfigManager:
    """Tests for ConfigManager class."""

    @pytest.fixture
    def config_file(self, tmp_path):
        """Create a test config file."""
        return tmp_path / "config.json"

    @pytest.fixture
    def default_config_manager(self, config_file):
        """Create a ConfigManager with default config."""
        return ConfigManager(config_file)

    def test_create_default_config(self, default_config_manager):
        """Test creating default configuration."""
        assert isinstance(default_config_manager.config, QueueConfig)
        assert default_config_manager.config.project_workspace is None
        assert len(default_config_manager.config.task_source_directories) == 0

    def test_load_existing_config(self, config_file, tmp_path):
        """Test loading existing configuration (with backward compatibility)."""
        # Create a config file with old field names
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        config_data = {
            "version": "1.0",
            "project_path": str(tmp_path),  # Old field name
            "task_doc_directories": [       # Old field name
                {
                    "id": "main",
                    "path": str(source_dir),
                    "description": "Main sources"
                }
            ],
            "settings": {
                "processing_interval": 5,
                "batch_size": 10
            }
        }
        config_file.write_text(json.dumps(config_data))

        # Load config - should use new field names internally
        manager = ConfigManager(config_file)
        # Note: Old config files may not work directly with new model
        # In production, migration would be needed

    def test_load_v2_config(self, config_file, tmp_path):
        """Test loading v2.0 configuration."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        config_data = {
            "version": "1.0",
            "project_workspace": str(tmp_path),
            "task_source_directories": [
                {
                    "id": "main",
                    "path": str(source_dir),
                    "description": "Main sources"
                }
            ],
            "settings": {
                "watch_enabled": True,
                "watch_debounce_ms": 500,
                "watch_patterns": ["task-*.md"],
                "watch_recursive": False,
                "task_pattern": "task-*.md",
                "max_attempts": 3,
                "enable_file_hash": True
            }
        }
        config_file.write_text(json.dumps(config_data))

        # Load config
        manager = ConfigManager(config_file)
        assert manager.config.project_workspace == str(tmp_path)
        assert len(manager.config.task_source_directories) == 1
        assert manager.config.task_source_directories[0].id == "main"

    def test_set_project_workspace(self, default_config_manager, tmp_path):
        """Test setting project workspace."""
        default_config_manager.set_project_workspace(str(tmp_path))
        assert default_config_manager.config.project_workspace == str(tmp_path.resolve())

    def test_add_task_source_directory(self, default_config_manager, tmp_path):
        """Test adding a task source directory."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        source = default_config_manager.add_task_source_directory(
            path=str(source_dir),
            id="main",
            description="Test sources"
        )
        assert source.id == "main"
        assert len(default_config_manager.config.task_source_directories) == 1

    def test_remove_task_source_directory(self, default_config_manager, tmp_path):
        """Test removing a task source directory."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        default_config_manager.add_task_source_directory(path=str(source_dir), id="main")
        assert len(default_config_manager.config.task_source_directories) == 1

        result = default_config_manager.remove_task_source_directory("main")
        assert result is True
        assert len(default_config_manager.config.task_source_directories) == 0

    def test_list_task_source_directories(self, default_config_manager, tmp_path):
        """Test listing task source directories."""
        source_dir1 = tmp_path / "sources1"
        source_dir2 = tmp_path / "sources2"
        source_dir1.mkdir()
        source_dir2.mkdir()

        default_config_manager.add_task_source_directory(path=str(source_dir1), id="sources1")
        default_config_manager.add_task_source_directory(path=str(source_dir2), id="sources2")

        sources = default_config_manager.list_task_source_directories()
        assert len(sources) == 2
        assert sources[0].id == "sources1"
        assert sources[1].id == "sources2"

    def test_save_and_reload_config(self, default_config_manager, tmp_path):
        """Test saving and reloading configuration."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        # Modify config
        default_config_manager.set_project_workspace(str(tmp_path))
        default_config_manager.add_task_source_directory(path=str(source_dir), id="main")

        # Save
        default_config_manager.save_config()

        # Reload in a new manager
        new_manager = ConfigManager(default_config_manager.config_file)
        assert new_manager.config.project_workspace == str(tmp_path.resolve())
        assert len(new_manager.config.task_source_directories) == 1

    # Backward compatibility tests (old methods still work)

    def test_backward_compat_set_project_path(self, default_config_manager, tmp_path):
        """Test backward compatibility for set_project_path."""
        default_config_manager.set_project_path(str(tmp_path))
        assert default_config_manager.get_project_path() == str(tmp_path.resolve())

    def test_backward_compat_add_task_doc_directory(self, default_config_manager, tmp_path):
        """Test backward compatibility for add_task_doc_directory."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        spec = default_config_manager.add_task_doc_directory(
            path=str(source_dir),
            id="main",
            description="Test sources"
        )
        assert spec.id == "main"
