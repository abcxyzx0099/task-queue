"""
Additional coverage tests for task_queue.cli module.

Tests error handling, edge cases, and the cmd_run command to improve
coverage from 50% to 70%+.
"""

import pytest
import tempfile
import subprocess
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from io import StringIO
import sys

from task_queue.cli import (
    cmd_status, cmd_register, cmd_list_sources, cmd_unregister,
    cmd_run, _restart_daemon, main
)
from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE


class TestRestartDaemon:
    """Tests for _restart_daemon helper function."""

    def test_restart_daemon_success(self):
        """Test successful daemon restart."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=""
            )

            result = _restart_daemon()

            assert result is True
            mock_run.assert_called_once_with(
                ["systemctl", "--user", "restart", "task-queue.service"],
                check=True,
                capture_output=True,
                text=True
            )

    def test_restart_daemon_called_process_error(self, capsys):
        """Test restart daemon handles CalledProcessError."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["systemctl", "--user", "restart", "task-queue.service"],
                stderr="Unit task-queue.service not found"
            )

            result = _restart_daemon()

            assert result is False

            captured = capsys.readouterr()
            assert "Failed to restart daemon" in captured.out

    def test_restart_daemon_generic_exception(self, capsys):
        """Test restart daemon handles generic exceptions."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = RuntimeError("Unexpected error")

            result = _restart_daemon()

            assert result is False

            captured = capsys.readouterr()
            assert "Failed to restart daemon" in captured.out


class TestCmdStatusEdgeCases:
    """Tests for cmd_status edge cases and error handling."""

    @pytest.fixture
    def mock_args(self):
        """Create mock args namespace."""
        return MagicMock(config=None)

    def test_cmd_status_config_load_error(self, mock_args, capsys):
        """Test cmd_status handles config loading errors."""
        # Use non-existent config path
        mock_args.config = "/nonexistent/config.json"

        result = cmd_status(mock_args)

        assert result == 1

        captured = capsys.readouterr()
        assert "Error loading configuration" in captured.err

    def test_cmd_status_no_project_workspace(self, temp_dir):
        """Test cmd_status with no project workspace set."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {
                    "watch_enabled": True,
                    "watch_debounce_ms": 500,
                    "watch_patterns": ["task-*.md"],
                    "watch_recursive": False,
                    "max_attempts": 3,
                    "enable_file_hash": True
                },
                "project_workspace": None,  # No workspace set
                "task_source_directories": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            # Capture output
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_status(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "No Project Workspace set" in output
            assert "Use 'task-queue register'" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_status_no_source_directories(self, temp_dir):
        """Test cmd_status with no source directories configured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "tasks").mkdir()

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                config = {
                    "version": "2.0",
                    "settings": {
                        "watch_enabled": True,
                        "watch_debounce_ms": 500,
                        "watch_patterns": ["task-*.md"],
                        "watch_recursive": False,
                        "max_attempts": 3,
                        "enable_file_hash": True
                    },
                    "project_workspace": str(workspace),
                    "task_source_directories": []  # No sources
                }
                json.dump(config, f)
                f.flush()
                config_path = f.name

            try:
                args = MagicMock(config=config_path)

                old_stdout = sys.stdout
                sys.stdout = StringIO()

                try:
                    result = cmd_status(args)
                    output = sys.stdout.getvalue()
                finally:
                    sys.stdout = old_stdout

                assert result == 0
                assert "No Task Source Directories configured" in output
            finally:
                Path(config_path).unlink(missing_ok=True)

    def test_cmd_status_with_tasks(self, temp_dir):
        """Test cmd_status shows task statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            task_dir = workspace / "tasks" / "task-documents"
            task_dir.mkdir(parents=True)

            # Create some task files
            (task_dir / "task-20260206-120000-pending.md").write_text("# Pending task")
            (task_dir / "task-20260206-120001-completed.md").write_text("# Completed task")

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                config = {
                    "version": "2.0",
                    "settings": {
                        "watch_enabled": True,
                        "watch_debounce_ms": 500,
                        "watch_patterns": ["task-*.md"],
                        "watch_recursive": False,
                        "max_attempts": 3,
                        "enable_file_hash": True
                    },
                    "project_workspace": str(workspace),
                    "task_source_directories": [
                        {
                            "id": "main",
                            "path": str(task_dir),
                            "description": "Main source"
                        }
                    ]
                }
                json.dump(config, f)
                f.flush()
                config_path = f.name

            try:
                args = MagicMock(config=config_path)

                old_stdout = sys.stdout
                sys.stdout = StringIO()

                try:
                    result = cmd_status(args)
                    output = sys.stdout.getvalue()
                finally:
                    sys.stdout = old_stdout

                assert result == 0
                assert "Overall Statistics" in output
                assert "Pending:" in output
                assert "Per-Source Details" in output
                assert "main" in output
            finally:
                Path(config_path).unlink(missing_ok=True)


class TestCmdListSourcesEdgeCases:
    """Tests for cmd_list_sources edge cases."""

    def test_cmd_list_sources_empty(self, temp_dir):
        """Test list-sources with no sources configured."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {
                    "watch_enabled": True,
                    "watch_debounce_ms": 500,
                    "watch_patterns": ["task-*.md"],
                    "watch_recursive": False
                },
                "project_workspace": None,
                "task_source_directories": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_list_sources(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "Task Source Directories:" in output
            assert "(none)" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_list_sources_config_error(self, capsys):
        """Test list-sources handles config errors."""
        args = MagicMock(config="/nonexistent/config.json")

        result = cmd_list_sources(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error loading configuration" in captured.err


class TestCmdRun:
    """Tests for cmd_run command."""

    @pytest.fixture
    def run_config(self, temp_dir):
        """Create a config for run command testing."""
        workspace = temp_dir / "workspace"
        task_dir = workspace / "tasks" / "task-documents"
        task_dir.mkdir(parents=True)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {
                    "watch_enabled": True,
                    "watch_debounce_ms": 500,
                    "watch_patterns": ["task-*.md"],
                    "watch_recursive": False
                },
                "project_workspace": str(workspace),
                "task_source_directories": [
                    {
                        "id": "main",
                        "path": str(task_dir),
                        "description": "Main source"
                    }
                ]
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        yield config_path, workspace, task_dir

        Path(config_path).unlink(missing_ok=True)

    def test_cmd_run_no_workspace(self):
        """Test cmd_run with no workspace configured."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": None,
                "task_source_directories": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_run(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 1
            assert "No Project Workspace set" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_run_no_pending_tasks(self, run_config):
        """Test cmd_run with no pending tasks."""
        config_path, workspace, task_dir = run_config

        args = MagicMock(config=config_path, cycles=1)

        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            result = cmd_run(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert result == 0
        assert "All tasks processed" in output

    def test_cmd_run_with_cycles(self, run_config):
        """Test cmd_run with specified cycle count."""
        config_path, workspace, task_dir = run_config

        # Create a task file
        (task_dir / "task-20260206-120000-test.md").write_text("# Test task")

        args = MagicMock(config=config_path, cycles=2)

        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            result = cmd_run(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert result == 0
        assert "Cycle 1" in output

    def test_cmd_run_zero_cycles(self, run_config):
        """Test cmd_run with cycles=0 (infinite mode, but stops when done)."""
        config_path, workspace, task_dir = run_config

        args = MagicMock(config=config_path, cycles=0)

        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            result = cmd_run(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        # Should exit when no tasks
        assert result == 0
        assert "All tasks processed" in output

    def test_cmd_run_keyboard_interrupt(self, run_config):
        """Test cmd_run handles KeyboardInterrupt."""
        config_path, workspace, task_dir = run_config

        # Create a task file
        (task_dir / "task-20260206-120000-test.md").write_text("# Test task")

        args = MagicMock(config=config_path, cycles=999)

        # Mock pick_next_task to raise KeyboardInterrupt after first call
        with patch('task_queue.cli.TaskRunner') as mock_runner_class:
            mock_runner = MagicMock()
            mock_runner_class.return_value = mock_runner

            # First call returns a task, second raises KeyboardInterrupt
            mock_task = MagicMock()
            mock_task.name = "task-20260206-120000-test.md"
            mock_runner.pick_next_task.side_effect = [mock_task, KeyboardInterrupt()]

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_run(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "Interrupted" in output

    def test_cmd_run_exception_handling(self, run_config):
        """Test cmd_run handles exceptions."""
        config_path, workspace, task_dir = run_config

        args = MagicMock(config=config_path, cycles=1)

        # Mock TaskRunner to raise exception
        with patch('task_queue.cli.TaskRunner') as mock_runner_class:
            mock_runner_class.side_effect = RuntimeError("Test error")

            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = StringIO()
            sys.stderr = StringIO()

            try:
                result = cmd_run(args)
                output = sys.stdout.getvalue()
                error_output = sys.stderr.getvalue()
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

            assert result == 1
            assert "Error:" in error_output

    def test_cmd_run_with_task_execution(self, run_config):
        """Test cmd_run executes a task."""
        config_path, workspace, task_dir = run_config

        # Create a task file
        task_file = task_dir / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        args = MagicMock(config=config_path, cycles=1)

        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            result = cmd_run(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert result == 0
        # Task should be executed and archived
        assert not task_file.exists()


class TestMainFunction:
    """Tests for main() function."""

    def test_main_no_command(self, capsys):
        """Test main() with no command (shows help)."""
        with patch('sys.argv', ['task-queue']):
            result = main()

            assert result == 1

    def test_main_with_config_arg(self):
        """Test main() with --config argument."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": None,
                "task_source_directories": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            with patch('sys.argv', ['task-queue', '--config', config_path, 'list-sources']):
                old_stdout = sys.stdout
                sys.stdout = StringIO()

                try:
                    result = main()
                finally:
                    sys.stdout = old_stdout

                assert result == 0
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_main_uses_default_config(self):
        """Test main() uses default config when not specified."""
        # Create default config file location
        default_config = Path.home() / ".config" / "task-queue" / "config.json"
        default_config.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(default_config, 'w') as f:
                json.dump({
                    "version": "2.0",
                    "settings": {},
                    "project_workspace": None,
                    "task_source_directories": []
                }, f)

            # Test without --config arg
            with patch('sys.argv', ['task-queue', 'list-sources']):
                old_stdout = sys.stdout
                sys.stdout = StringIO()

                try:
                    result = main()
                finally:
                    sys.stdout = old_stdout

                assert result == 0
        finally:
            default_config.unlink(missing_ok=True)


class TestCmdRegisterEdgeCases:
    """Additional tests for cmd_register error handling."""

    def test_cmd_register_exception_handling(self, temp_dir, capsys):
        """Test cmd_register handles exceptions."""
        # Use invalid workspace path
        args = MagicMock(
            config="/nonexistent/config.json",
            task_source_dir="/nonexistent/source",
            project_workspace="/nonexistent/workspace",
            source_id="test"
        )

        result = cmd_register(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err


class TestCmdUnregisterEdgeCases:
    """Additional tests for cmd_unregister error handling."""

    def test_cmd_unregister_exception_handling(self, capsys):
        """Test cmd_unregister handles exceptions."""
        args = MagicMock(
            config="/nonexistent/config.json",
            source_id="test"
        )

        result = cmd_unregister(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
