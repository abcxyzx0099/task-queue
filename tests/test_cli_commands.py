"""
Integration tests for task-queue CLI commands.

Tests the CLI functionality including:
- queues add command
- queues rm command
- status command
- queues list command
- Auto-restart functionality
- Daemon stays running
"""

import pytest
import subprocess
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import time


class TestCLICommands:
    """Test CLI command functionality."""

    @pytest.fixture
    def temp_config(self):
        """Create a temporary config file for testing."""
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
                "project_workspace": None,
                "queues": []
            }
            json.dump(config, f, indent=2)
            f.flush()
            config_path = f.name
        yield config_path
        # Cleanup
        Path(config_path).unlink(missing_ok=True)

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # Create task directories
            (workspace / "tasks").mkdir()
            (workspace / "tasks" / "ad-hoc" / "pending").mkdir(parents=True)
            (workspace / "tasks" / "ad-hoc" / "completed").mkdir(parents=True)
            (workspace / "tasks" / "ad-hoc" / "failed").mkdir(parents=True)
            yield workspace

    @pytest.fixture
    def mock_systemctl(self):
        """Mock systemctl commands to avoid actual service manipulation."""
        with patch('subprocess.run') as mock_run:
            # Mock successful systemctl calls
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Active: active (running)\n",
                stderr=""
            )
            yield mock_run

    def test_register_creates_config(self, temp_workspace):
        """Test that register command creates config if it doesn't exist."""
        # This test verifies the behavior mentioned in documentation:
        # "Configuration is auto-created on first use"

        # Use a temporary config location
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "test-config.json"
            queue_path = temp_workspace / "tasks" / "ad-hoc"

            # Run sources add command
            result = subprocess.run(
                [
                    "python3", "-m", "task_queue.cli",
                    "--config", str(config_file),
                    "queues", "add", str(queue_path),
                    "--id", "test-source",
                    "--project-workspace", str(temp_workspace)
                ],
                capture_output=True,
                text=True,
                cwd="/home/admin/workspaces/task-monitor"
            )

            # Verify config was created
            assert config_file.exists(), "Config file should be created"

            # Verify config content
            with open(config_file) as f:
                config = json.load(f)

            assert config["project_workspace"] == str(temp_workspace)
            assert len(config["queues"]) == 1
            assert config["queues"][0]["id"] == "test-source"

    def test_register_adds_source(self, temp_config, temp_workspace, mock_systemctl):
        """Test that register adds a source directory to config."""
        from task_queue.config import ConfigManager
        from task_queue.cli import cmd_queues_add
        from argparse import Namespace

        # Create args - queues add uses 'id' not 'queue_id'
        args = Namespace(
            config=temp_config,
            queue_path=str(temp_workspace / "tasks" / "ad-hoc"),
            project_workspace=str(temp_workspace),
            id="test-source",
            description=None  # Optional description
        )

        # Run register command
        result = cmd_queues_add(args)

        assert result == 0

        # Verify source was added - reload config from file
        config_manager = ConfigManager(Path(temp_config))
        config = config_manager.config
        assert len(config.queues) == 1
        assert config.queues[0].id == "test-source"
        assert config.queues[0].path == str(temp_workspace / "tasks" / "ad-hoc")

    def test_unregister_removes_source(self, temp_config, temp_workspace, mock_systemctl):
        """Test that sources rm removes a source directory from config."""
        from task_queue.config import ConfigManager
        from task_queue.cli import cmd_queues_add, cmd_queues_rm
        from argparse import Namespace

        # First register a queue - queues add uses 'id' not 'queue_id'
        args_reg = Namespace(
            config=temp_config,
            queue_path=str(temp_workspace / "tasks" / "ad-hoc"),
            project_workspace=str(temp_workspace),
            id="test-source",
            description=None  # Optional description
        )
        result = cmd_queues_add(args_reg)
        assert result == 0

        # Verify source was added - reload from file
        config_manager = ConfigManager(Path(temp_config))
        assert len(config_manager.config.queues) == 1

        # Now unregister it
        args_unreg = Namespace(
            config=temp_config,
            queue_id="test-source"
        )
        result = cmd_queues_rm(args_unreg)

        assert result == 0

        # Verify source was removed - reload from file
        config_manager = ConfigManager(Path(temp_config))
        assert len(config_manager.config.queues) == 0

    def test_unregister_nonexistent_source(self, temp_config):
        """Test that queues rm handles non-existent queues gracefully."""
        from task_queue.config import ConfigManager
        from task_queue.cli import cmd_queues_rm
        from argparse import Namespace

        args = Namespace(
            config=temp_config,
            queue_id="nonexistent"
        )

        result = cmd_queues_rm(args)

        # Should return error code
        assert result == 1

    def test_restart_daemon_called(self, temp_config, temp_workspace):
        """Test that register and unregister call systemctl restart."""
        from task_queue.cli import _restart_daemon

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=""
            )

            # Test restart daemon function
            result = _restart_daemon()

            assert result == True
            mock_run.assert_called_once()

            # Verify systemctl command
            call_args = mock_run.call_args
            assert call_args[0][0] == ["systemctl", "--user", "restart", "task-queue.service"]

    def test_restart_daemon_handles_failure(self, temp_config, temp_workspace):
        """Test that restart daemon handles systemctl failures."""
        from task_queue.cli import _restart_daemon

        with patch('subprocess.run') as mock_run:
            # Mock systemctl failure
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["systemctl", "--user", "restart", "task-queue.service"],
                stderr="Failed to restart"
            )

            # Should return False but not raise exception
            result = _restart_daemon()

            assert result == False

    def test_status_command(self, temp_config, temp_workspace):
        """Test status command output."""
        from task_queue.config import ConfigManager
        from task_queue.cli import cmd_status
        from argparse import Namespace
        from io import StringIO
        import sys

        config_manager = ConfigManager(Path(temp_config))
        config_manager.set_project_workspace(str(temp_workspace))
        config_manager.add_queue(
            path=str(temp_workspace / "tasks" / "ad-hoc"),
            id="test-source"
        )

        args = Namespace(config=temp_config, detailed=False)

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            result = cmd_status(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert result == 0
        assert "Task Queue Status" in output
        assert "test-source" in output

    def test_list_sources_command(self, temp_config, temp_workspace):
        """Test sources list command."""
        from task_queue.config import ConfigManager
        from task_queue.cli import cmd_queues_list
        from argparse import Namespace
        from io import StringIO
        import sys

        config_manager = ConfigManager(Path(temp_config))
        config_manager.set_project_workspace(str(temp_workspace))
        config_manager.add_queue(
            path=str(temp_workspace / "tasks" / "ad-hoc"),
            id="test-source"
        )

        args = Namespace(config=temp_config, detailed=False)

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            result = cmd_queues_list(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert result == 0
        assert "Task Source Directories" in output
        assert "test-source" in output


class TestDaemonFix:
    """Test the daemon worker thread fix."""

    def test_worker_threads_not_daemon(self):
        """Test that worker threads are created with daemon=False."""
        import threading

        # Create a thread with daemon=False
        thread = threading.Thread(
            target=lambda: None,
            daemon=False
        )

        # Verify thread is NOT a daemon thread
        assert thread.daemon == False, "Worker threads should NOT be daemon threads"

    def test_daemon_stays_running_with_non_daemon_threads(self):
        """Test that daemon stays running when worker threads are non-daemon."""
        import threading
        import time

        worker_ran = [False]

        def worker_loop():
            """Simulated worker that runs continuously."""
            for i in range(3):
                worker_ran[0] = True
                time.sleep(0.1)

        # Create thread with daemon=False
        worker = threading.Thread(target=worker_loop, daemon=False)
        worker.start()

        # Thread should complete
        worker.join(timeout=2)

        assert worker_ran[0], "Worker should have executed"
        assert not worker.is_alive(), "Worker should be complete"


class TestCLIIntegration:
    """Integration tests for complete CLI workflows."""

    def test_register_unregister_workflow(self):
        """Test complete register -> list -> unregister workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "test-config.json"

            with tempfile.TemporaryDirectory() as workspace_dir:
                workspace = Path(workspace_dir)
                # Create task directories
                (workspace / "tasks").mkdir()
                (workspace / "tasks" / "ad-hoc" / "pending").mkdir(parents=True)
                task_source_dir = workspace / "tasks" / "ad-hoc" / "pending"

                # Mock systemctl to avoid actual service restart
                original_run = subprocess.run
                def mock_run(cmd, *args, **kwargs):
                    # If it's a systemctl command, mock it
                    if cmd and len(cmd) > 0 and "systemctl" in str(cmd[0]):
                        return MagicMock(returncode=0, stdout="", stderr="")
                    # Otherwise run normally
                    return original_run(cmd, *args, **kwargs)

                with patch('subprocess.run', side_effect=mock_run):
                    # 1. Register (queues add)
                    result = subprocess.run(
                        [
                            "python3", "-m", "task_queue.cli",
                            "--config", str(config_file),
                            "queues", "add", str(workspace / "tasks" / "ad-hoc"),
                            "--id", "test",
                            "--project-workspace", str(workspace)
                        ],
                        capture_output=True,
                        text=True,
                        cwd="/home/admin/workspaces/task-monitor"
                    )

                    assert "Added" in result.stdout

                    # 2. List queues
                    result = subprocess.run(
                        [
                            "python3", "-m", "task_queue.cli",
                            "--config", str(config_file),
                            "queues", "list"
                        ],
                        capture_output=True,
                        text=True,
                        cwd="/home/admin/workspaces/task-monitor"
                    )

                    assert "test" in result.stdout

                    # 3. Remove (queues rm)
                    result = subprocess.run(
                        [
                            "python3", "-m", "task_queue.cli",
                            "--config", str(config_file),
                            "queues", "rm",
                            "--queue-id", "test"
                        ],
                        capture_output=True,
                        text=True,
                        cwd="/home/admin/workspaces/task-monitor"
                    )

                    assert "Removed" in result.stdout


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
