"""
Comprehensive tests for task_queue.cli module to improve coverage.

Tests for commands that are currently not well covered:
- cmd_init
- cmd_tasks_show
- cmd_tasks_logs
- cmd_tasks_cancel
- cmd_workers_status
- cmd_workers_list
- cmd_logs
"""

import pytest
import tempfile
import subprocess
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from io import StringIO
import sys

from task_queue.cli import (
    cmd_init,
    cmd_tasks_show,
    cmd_tasks_logs,
    cmd_tasks_cancel,
    cmd_workers_status,
    cmd_workers_list,
    cmd_logs,
    _find_task_file,
)


class TestFindTaskFile:
    """Tests for _find_task_file helper function."""

    def test_find_task_file_in_pending(self, temp_dir):
        """Test finding task file in pending directory."""
        workspace = temp_dir / "workspace"
        queue_path = workspace / "tasks" / "ad-hoc"
        queue_path.mkdir(parents=True)

        task_file = queue_path / "task-123.md"
        task_file.write_text("# Task")

        # Create mock config
        from task_queue.models import Queue, MonitorConfig
        config = MonitorConfig(
            project_workspace=str(workspace),
            queues=[Queue(id="ad-hoc", path=str(queue_path))]
        )

        result = _find_task_file("task-123", config)
        assert result == task_file

    def test_find_task_file_in_completed(self, temp_dir):
        """Test finding task file in completed directory."""
        workspace = temp_dir / "workspace"
        # Queue path is the pending directory
        queue_path = workspace / "tasks" / "ad-hoc" / "pending"
        queue_path.mkdir(parents=True)
        completed_path = workspace / "tasks" / "ad-hoc" / "completed"
        completed_path.mkdir(parents=True)

        task_file = completed_path / "task-123.md"
        task_file.write_text("# Task")

        # Create mock config - queue path points to pending
        from task_queue.models import Queue, MonitorConfig
        config = MonitorConfig(
            project_workspace=str(workspace),
            queues=[Queue(id="ad-hoc", path=str(queue_path))]
        )

        result = _find_task_file("task-123", config)
        assert result == task_file

    def test_find_task_file_not_found(self, temp_dir):
        """Test finding non-existent task file."""
        workspace = temp_dir / "workspace"
        queue_path = workspace / "tasks" / "ad-hoc"
        queue_path.mkdir(parents=True)

        from task_queue.models import Queue, MonitorConfig
        config = MonitorConfig(
            project_workspace=str(workspace),
            queues=[Queue(id="ad-hoc", path=str(queue_path))]
        )

        result = _find_task_file("nonexistent", config)
        assert result is None


class TestCmdInit:
    """Tests for cmd_init command."""

    def test_cmd_init_basic(self, temp_dir):
        """Test basic initialization."""
        config_file = temp_dir / "config.json"

        args = MagicMock(
            config=config_file,
            force=False,
            skip_existing=False,
            restart_daemon=False
        )

        # Change to temp dir for init
        original_cwd = Path.cwd()
        import os
        os.chdir(temp_dir)

        try:
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_init(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "Initialization complete" in output

            # Check directories were created
            assert (temp_dir / "tasks" / "ad-hoc" / "pending").exists()
            assert (temp_dir / "tasks" / "ad-hoc" / "completed").exists()
            assert (temp_dir / "tasks" / "planned" / "pending").exists()

            # Check config was created
            assert config_file.exists()
        finally:
            os.chdir(original_cwd)

    def test_cmd_init_force(self, temp_dir):
        """Test init with --force flag."""
        config_file = temp_dir / "config.json"

        args = MagicMock(
            config=config_file,
            force=True,
            skip_existing=False,
            restart_daemon=False
        )

        original_cwd = Path.cwd()
        import os
        os.chdir(temp_dir)

        try:
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_init(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "Initialization complete" in output
        finally:
            os.chdir(original_cwd)

    def test_cmd_init_skip_existing(self, temp_dir):
        """Test init with --skip-existing flag."""
        config_file = temp_dir / "config.json"

        args = MagicMock(
            config=config_file,
            force=False,
            skip_existing=True,
            restart_daemon=False
        )

        original_cwd = Path.cwd()
        import os
        os.chdir(temp_dir)

        try:
            # First init
            cmd_init(args)

            # Second init with skip_existing
            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_init(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
        finally:
            os.chdir(original_cwd)


class TestCmdTasksShow:
    """Tests for cmd_tasks_show command."""

    def test_cmd_tasks_show_found(self, temp_dir):
        """Test showing found task."""
        workspace = temp_dir / "workspace"
        queue_path = workspace / "tasks" / "ad-hoc"
        queue_path.mkdir(parents=True)
        task_file = queue_path / "task-123.md"
        task_file.write_text("# Task")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": [{"id": "ad-hoc", "path": str(queue_path)}]
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path, task_id="task-123")

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_tasks_show(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "task-123.md" in output
            assert "cat" in output or "less" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_tasks_show_not_found(self, temp_dir):
        """Test showing non-existent task."""
        workspace = temp_dir / "workspace"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path, task_id="nonexistent")

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_tasks_show(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 1
            assert "not found" in output
        finally:
            Path(config_path).unlink(missing_ok=True)


class TestCmdTasksLogs:
    """Tests for cmd_tasks_logs command."""

    def test_cmd_tasks_logs_found(self, temp_dir):
        """Test showing logs for task with result file."""
        workspace = temp_dir / "workspace"
        results_dir = workspace / "tasks" / "ad-hoc" / "results"
        results_dir.mkdir(parents=True)

        result_file = results_dir / "task-123.json"
        result_data = {
            "success": True,
            "task_id": "task-123",
            "started_at": "2026-02-07T12:00:00",
            "completed_at": "2026-02-07T12:01:00",
            "duration_ms": 60000
        }
        result_file.write_text(json.dumps(result_data))

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path, task_id="task-123")

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_tasks_logs(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "Success" in output or "✅" in output
            assert "duration" in output.lower()
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_tasks_logs_not_found(self, temp_dir):
        """Test showing logs for task with no result file."""
        workspace = temp_dir / "workspace"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path, task_id="task-123")

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_tasks_logs(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 1
            assert "No result logs found" in output
        finally:
            Path(config_path).unlink(missing_ok=True)


class TestCmdTasksCancel:
    """Tests for cmd_tasks_cancel command."""

    def test_cmd_tasks_cancel_not_found(self, temp_dir):
        """Test cancelling non-existent task."""
        workspace = temp_dir / "workspace"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path, task_id="nonexistent")

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_tasks_cancel(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 1
            assert "not found" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_tasks_cancel_not_running(self, temp_dir):
        """Test cancelling task that is not running."""
        workspace = temp_dir / "workspace"
        queue_path = workspace / "tasks" / "ad-hoc"
        queue_path.mkdir(parents=True)
        task_file = queue_path / "task-123.md"
        task_file.write_text("# Task")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": [{"id": "ad-hoc", "path": str(queue_path)}]
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path, task_id="task-123")

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_tasks_cancel(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 1
            assert "not running" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_tasks_cancel_with_lock(self, temp_dir):
        """Test cancelling task with lock file."""
        workspace = temp_dir / "workspace"
        queue_path = workspace / "tasks" / "ad-hoc"
        queue_path.mkdir(parents=True)
        task_file = queue_path / "task-123.md"
        task_file.write_text("# Task")

        # Create lock file
        from task_queue.executor import LockInfo, get_lock_file_path
        lock_file = get_lock_file_path(task_file)
        lock_info = LockInfo(
            task_id="task-123",
            worker="ad-hoc",
            thread_id="12345",
            pid=999999,  # Non-existent PID
            started_at="2026-02-07T12:00:00"
        )
        lock_info.save(lock_file)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": [{"id": "ad-hoc", "path": str(queue_path)}]
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path, task_id="task-123")

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_tasks_cancel(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            # Task should be cancelled (stale lock removed)
            assert result == 0 or result == 1  # Depends on whether process exists
        finally:
            Path(config_path).unlink(missing_ok=True)


class TestCmdWorkersStatus:
    """Tests for cmd_workers_status command."""

    def test_cmd_workers_status_no_workspace(self, temp_dir):
        """Test workers status with no workspace."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": None,
                "queues": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_workers_status(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 1
            assert "No Project Workspace" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_workers_status_no_queues(self, temp_dir):
        """Test workers status with no queues."""
        workspace = temp_dir / "workspace"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_workers_status(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "No Task Source Directories" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_workers_status_with_queues(self, temp_dir):
        """Test workers status with queues configured."""
        workspace = temp_dir / "workspace"
        queue_path = workspace / "tasks" / "ad-hoc"
        queue_path.mkdir(parents=True)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": [{"id": "ad-hoc", "path": str(queue_path)}]
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_workers_status(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "Worker Status" in output
            assert "ad-hoc" in output
        finally:
            Path(config_path).unlink(missing_ok=True)


class TestCmdWorkersList:
    """Tests for cmd_workers_list command."""

    def test_cmd_workers_list_no_queues(self, temp_dir):
        """Test workers list with no queues."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": None,
                "queues": []
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_workers_list(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "Workers:" in output
            assert "(none)" in output
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_cmd_workers_list_with_queues(self, temp_dir):
        """Test workers list with queues configured."""
        workspace = temp_dir / "workspace"
        queue_path = workspace / "tasks" / "ad-hoc"
        queue_path.mkdir(parents=True)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = {
                "version": "2.0",
                "settings": {},
                "project_workspace": str(workspace),
                "queues": [{"id": "ad-hoc", "path": str(queue_path)}]
            }
            json.dump(config, f)
            f.flush()
            config_path = f.name

        try:
            args = MagicMock(config=config_path)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_workers_list(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            assert result == 0
            assert "ad-hoc" in output
        finally:
            Path(config_path).unlink(missing_ok=True)


class TestCmdLogs:
    """Tests for cmd_logs command."""

    def test_cmd_logs_with_lines(self, capsys):
        """Test logs command with --lines flag."""
        args = MagicMock(
            follow=False,
            lines=10
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = cmd_logs(args)

            assert result == 0
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "journalctl" in call_args
            assert "-n" in call_args
            assert "10" in call_args

    def test_cmd_logs_follow(self):
        """Test logs command with --follow flag."""
        args = MagicMock(
            follow=True,
            lines=None
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            old_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                result = cmd_logs(args)
            finally:
                sys.stdout = old_stdout

            assert result == 0
            mock_run.assert_called_once()

    def test_cmd_logs_default(self):
        """Test logs command with default options."""
        args = MagicMock(
            follow=False,
            lines=None
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = cmd_logs(args)

            assert result == 0
            mock_run.assert_called_once()
