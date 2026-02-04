"""Tests for task_queue CLI module."""

import pytest
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

from task_queue.cli import main
from task_queue.config import ConfigManager
from task_queue.models import QueueConfig


class TestCLICommands:
    """Tests for CLI commands."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a mock configuration."""
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        config = QueueConfig(
            project_path=str(tmp_path),
            task_doc_directories=[]
        )
        return config, tmp_path

    def test_cmd_set_project(self, mock_config):
        """Test set-project command."""
        config, project_path = mock_config

        with patch('task_queue.cli.ConfigManager') as MockConfigManager:
            mock_instance = MagicMock()
            mock_instance.config = config
            mock_instance.get_project_path.return_value = None
            mock_instance.set_project_path.return_value = None
            MockConfigManager.return_value = mock_instance

            from task_queue.cli import cmd_set_project
            args = MagicMock(path=str(project_path))

            result = cmd_set_project(args, mock_instance)
            assert result == 0

    def test_cmd_clear_project(self, mock_config):
        """Test clear-project command."""
        config, _ = mock_config

        with patch('task_queue.cli.ConfigManager') as MockConfigManager:
            mock_instance = MagicMock()
            mock_instance.config = config
            mock_instance.get_project_path.return_value = str(mock_config[1])
            mock_instance.clear_project_path.return_value = None
            MockConfigManager.return_value = mock_instance

            from task_queue.cli import cmd_clear_project
            args = MagicMock()

            result = cmd_clear_project(args, mock_instance)
            assert result == 0

    def test_cmd_show_project(self, mock_config):
        """Test show-project command."""
        config, project_path = mock_config

        with patch('task_queue.cli.ConfigManager') as MockConfigManager:
            mock_instance = MagicMock()
            mock_instance.config = config
            mock_instance.get_project_path.return_value = str(project_path)
            MockConfigManager.return_value = mock_instance

            from task_queue.cli import cmd_show_project
            args = MagicMock()

            # Capture stdout
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            result = cmd_show_project(args, mock_instance)

            output = sys.stdout.getvalue()
            sys.stdout = old_stdout

            assert result == 0
            assert str(project_path) in output

    def test_cmd_add_doc(self, mock_config):
        """Test add-spec command."""
        config, project_path = mock_config
        spec_dir = project_path / "specs"
        spec_dir.mkdir(exist_ok=True)

        with patch('task_queue.cli.ConfigManager') as MockConfigManager:
            mock_instance = MagicMock()
            mock_instance.config = config
            mock_instance.add_task_doc_directory.return_value = MagicMock(
                id="main",
                path=str(spec_dir),
                description=""
            )
            MockConfigManager.return_value = mock_instance

            from task_queue.cli import cmd_add_doc
            args = MagicMock(path=str(spec_dir), id="main", description="")

            result = cmd_add_doc(args, mock_instance)
            assert result == 0

    def test_cmd_remove_doc(self):
        """Test remove-spec command."""
        with patch('task_queue.cli.ConfigManager') as MockConfigManager:
            mock_instance = MagicMock()
            mock_instance.remove_task_doc_directory.return_value = True
            MockConfigManager.return_value = mock_instance

            from task_queue.cli import cmd_remove_doc
            args = MagicMock(id="main")

            result = cmd_remove_doc(args, mock_instance)
            assert result == 0

    def test_cmd_list_docs_empty(self):
        """Test list-docs command with no docs."""
        with patch('task_queue.cli.ConfigManager') as MockConfigManager:
            mock_instance = MagicMock()
            mock_instance.list_task_doc_directories.return_value = []
            MockConfigManager.return_value = mock_instance

            from task_queue.cli import cmd_list_docs
            args = MagicMock()

            # Capture stdout
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            result = cmd_list_docs(args, mock_instance)

            output = sys.stdout.getvalue()
            sys.stdout = old_stdout

            assert result == 0
            assert "No task doc directories" in output

    def test_cmd_list_docs_with_docs(self):
        """Test list-docs command with task docs."""
        with patch('task_queue.cli.ConfigManager') as MockConfigManager:
            mock_spec = MagicMock(id="main", path="/path/to/specs", description="Test")
            mock_instance = MagicMock()
            mock_instance.list_task_doc_directories.return_value = [mock_spec]
            MockConfigManager.return_value = mock_instance

            from task_queue.cli import cmd_list_docs
            args = MagicMock()

            # Capture stdout
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            result = cmd_list_docs(args, mock_instance)

            output = sys.stdout.getvalue()
            sys.stdout = old_stdout

            assert result == 0
            assert "main" in output


class TestMain:
    """Tests for main CLI entry point."""

    def test_main_help(self):
        """Test main with --help."""
        with patch('sys.argv', ['task-queue', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
