"""Tests for task_queue config module."""

import pytest
import json
from pathlib import Path

from task_queue.config import ConfigManager
from task_queue.models import QueueConfig, TaskDocDirectory


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
        assert default_config_manager.config.project_path is None
        assert len(default_config_manager.config.task_doc_directories) == 0

    def test_load_existing_config(self, config_file, tmp_path):
        """Test loading existing configuration."""
        # Create a config file
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        config_data = {
            "version": "1.0",
            "project_path": str(tmp_path),
            "task_doc_directories": [
                {
                    "id": "main",
                    "path": str(spec_dir),
                    "description": "Main specs"
                }
            ],
            "settings": {
                "processing_interval": 5,
                "batch_size": 10
            }
        }
        config_file.write_text(json.dumps(config_data))

        # Load config
        manager = ConfigManager(config_file)
        assert manager.config.project_path == str(tmp_path)
        assert len(manager.config.task_doc_directories) == 1
        assert manager.config.task_doc_directories[0].id == "main"

    def test_set_project_path(self, default_config_manager, tmp_path):
        """Test setting project path."""
        default_config_manager.set_project_path(str(tmp_path))
        assert default_config_manager.config.project_path == str(tmp_path.resolve())

    def test_add_task_doc_directory(self, default_config_manager, tmp_path):
        """Test adding a spec directory."""
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        spec = default_config_manager.add_task_doc_directory(
            path=str(spec_dir),
            id="main",
            description="Test specs"
        )
        assert spec.id == "main"
        assert len(default_config_manager.config.task_doc_directories) == 1

    def test_remove_task_doc_directory(self, default_config_manager, tmp_path):
        """Test removing a spec directory."""
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        default_config_manager.add_task_doc_directory(path=str(spec_dir), id="main")
        assert len(default_config_manager.config.task_doc_directories) == 1

        result = default_config_manager.remove_task_doc_directory("main")
        assert result is True
        assert len(default_config_manager.config.task_doc_directories) == 0

    def test_list_task_doc_directories(self, default_config_manager, tmp_path):
        """Test listing spec directories."""
        spec_dir1 = tmp_path / "specs1"
        spec_dir2 = tmp_path / "specs2"
        spec_dir1.mkdir()
        spec_dir2.mkdir()

        default_config_manager.add_task_doc_directory(path=str(spec_dir1), id="specs1")
        default_config_manager.add_task_doc_directory(path=str(spec_dir2), id="specs2")

        specs = default_config_manager.list_task_doc_directories()
        assert len(specs) == 2
        assert specs[0].id == "specs1"
        assert specs[1].id == "specs2"

    def test_save_and_reload_config(self, default_config_manager, tmp_path):
        """Test saving and reloading configuration."""
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        # Modify config
        default_config_manager.set_project_path(str(tmp_path))
        default_config_manager.add_task_doc_directory(path=str(spec_dir), id="main")

        # Save
        default_config_manager.save_config()

        # Reload in a new manager
        new_manager = ConfigManager(default_config_manager.config_file)
        assert new_manager.config.project_path == str(tmp_path.resolve())
        assert len(new_manager.config.task_doc_directories) == 1
