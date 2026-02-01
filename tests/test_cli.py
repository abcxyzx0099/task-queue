"""Tests for task_monitor.cli module."""

import pytest
import json
import os
from pathlib import Path
from datetime import datetime
from io import StringIO
import sys
import tempfile

from task_monitor.cli import (
    show_task_status,
    show_status,
    show_queue,
    load_pending_tasks,
    use_project,
    get_current_project,
    ENV_VAR_NAME,
    ENV_FILE,
)


class TestShowTaskStatus:
    """Tests for show_task_status function."""

    def test_processing_job(self, project_root, queue_state_file, capsys):
        """Test status display for a currently processing job."""
        # The current task is "current-job.md"
        show_task_status("current-job", project_root)

        captured = capsys.readouterr()
        assert "Status: processing" in captured.out
        assert "current-job.md" in captured.out
        assert "Started:" in captured.out

    def test_queued_job(self, project_root, queued_job_file, queue_state_file, capsys):
        """Test status display for a queued job."""
        show_task_status("queued-job", project_root)

        captured = capsys.readouterr()
        assert "Status: waiting" in captured.out
        assert "queued-job.md" in captured.out
        assert "Created:" in captured.out
        assert "Queue position:" in captured.out
        assert "1 of 2" in captured.out

    def test_completed_job(self, project_root, completed_job_result, capsys):
        """Test status display for a completed job."""
        show_task_status("completed-job", project_root)

        captured = capsys.readouterr()
        assert "Status: completed" in captured.out
        assert "completed-job" in captured.out
        assert "Duration:" in captured.out
        assert "Summary:" in captured.out
        assert "Tokens:" in captured.out

    def test_job_id_auto_extension(self, project_root, queued_job_file, capsys):
        """Test that .md extension is auto-added if not provided."""
        show_task_status("queued-job", project_root)

        captured = capsys.readouterr()
        assert "Status: waiting" in captured.out

    def test_not_found_job(self, project_root, capsys):
        """Test status display for a non-existent job."""
        show_task_status("nonexistent-job", project_root)

        captured = capsys.readouterr()
        assert "Status: not_found" in captured.out
        assert "not found in any of the following locations" in captured.out

    def test_completed_job_with_error(self, project_root, capsys):
        """Test status display for a failed job."""
        result_file = project_root / "tasks" / "task-monitor" / "results" / "failed-job.json"
        result_data = {
            "task_id": "failed-job",
            "status": "failed",
            "error": "Connection timeout",
            "duration_seconds": 5.0,
        }
        result_file.write_text(json.dumps(result_data))

        show_task_status("failed-job", project_root)

        captured = capsys.readouterr()
        assert "Status: failed" in captured.out
        assert "Error: Connection timeout" in captured.out


class TestShowStatus:
    """Tests for show_status function."""

    def test_show_status_all_completed(self, project_root, completed_job_result, capsys):
        """Test showing all completed tasks when no task_id is provided."""
        # Create multiple completed tasks
        for i in range(3):
            result_file = project_root / "tasks" / "task-monitor" / "results" / f"task-{i}.json"
            result_data = {
                "task_id": f"task-{i}",
                "status": "completed" if i < 2 else "failed",
            }
            result_file.write_text(json.dumps(result_data))

        show_status(task_id=None, project_root=project_root)

        captured = capsys.readouterr()
        assert "Running" in captured.out or "Stopped" in captured.out

    def test_show_status_redirects_to_show_task_status(self, project_root, completed_job_result, capsys):
        """Test that show_status with task_id redirects to show_task_status."""
        show_status(task_id="completed-job", project_root=project_root)

        captured = capsys.readouterr()
        assert "Status: completed" in captured.out


class TestShowQueue:
    """Tests for show_queue function."""

    def test_show_queue_with_state(self, project_root, queue_state_file, capsys):
        """Test showing queue when state file exists."""
        show_queue(project_root)

        captured = capsys.readouterr()
        assert "Queue size: 2" in captured.out
        assert "Processing: current-job.md" in captured.out
        assert "Queued tasks:" in captured.out
        assert "queued-job.md" in captured.out
        assert "pending-job.md" in captured.out

    def test_show_queue_no_state(self, project_root, capsys):
        """Test showing queue when state file doesn't exist."""
        show_queue(project_root)

        captured = capsys.readouterr()
        assert "Queue state not available" in captured.out
        assert "monitor may not be running" in captured.out

    def test_show_queue_empty(self, project_root, capsys):
        """Test showing empty queue."""
        state_file = project_root / "tasks" / "task-monitor" / "state" / "queue_state.json"
        state_data = {
            "queue_size": 0,
            "current_task": None,
            "is_processing": False,
            "queued_tasks": [],
        }
        state_file.write_text(json.dumps(state_data))

        show_queue(project_root)

        captured = capsys.readouterr()
        assert "Queue size: 0" in captured.out
        assert "Processing: None" in captured.out


class TestProjectManagement:
    """Tests for project management commands (use, current)."""

    def test_use_project_updates_env_file(self, project_root, monkeypatch, tmp_path):
        """Test that use_project updates .env file."""
        # Mock ENV_FILE to use temp directory
        temp_env = tmp_path / ".env"
        monkeypatch.setattr("task_monitor.cli.ENV_FILE", temp_env)

        use_project(str(project_root))

        # Verify .env file was created/updated
        content = temp_env.read_text()
        assert f'{ENV_VAR_NAME}="{project_root}"' in content

    def test_use_project_validates_path_exists(self, monkeypatch, tmp_path, capsys):
        """Test that use_project validates path exists."""
        temp_env = tmp_path / ".env"
        monkeypatch.setattr("task_monitor.cli.ENV_FILE", temp_env)

        # Use non-existent path
        result = use_project("/nonexistent/path")

        assert result is False
        captured = capsys.readouterr()
        assert "does not exist" in captured.out

    def test_get_current_project_from_env(self, project_root, monkeypatch):
        """Test that get_current_project reads from environment variable."""
        monkeypatch.setenv(ENV_VAR_NAME, str(project_root))

        result = get_current_project()
        assert result == project_root

    def test_get_current_project_returns_none_when_not_set(self, monkeypatch, tmp_path):
        """Test that get_current_project returns None when env var is not set and .env doesn't exist."""
        # Remove env var
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)

        # Mock ENV_FILE to a non-existent temporary file
        fake_env = tmp_path / "nonexistent.env"
        monkeypatch.setattr("task_monitor.cli.ENV_FILE", fake_env)

        result = get_current_project()
        assert result is None


class TestMain:
    """Tests for main CLI entry point."""

    def test_main_queue_command(self, project_root, queue_state_file, monkeypatch, capsys):
        """Test main function with queue command."""
        # Set environment variable
        monkeypatch.setenv(ENV_VAR_NAME, str(project_root))

        # Mock sys.argv
        monkeypatch.setattr(sys, "argv", ["task-monitor", "queue"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        assert "Queue size:" in captured.out

    def test_main_with_project_path(self, project_root, queue_state_file, monkeypatch, capsys):
        """Test main function with custom project path."""
        monkeypatch.setattr(sys, "argv", ["task-monitor", "--project-path", str(project_root), "queue"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        assert "Queue size:" in captured.out

    def test_main_with_project_path_override(self, project_root, completed_job_result, monkeypatch, capsys):
        """Test main function with project path override using -p."""
        monkeypatch.setattr(sys, "argv", ["task-monitor", "--project-path", str(project_root), "status"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        # Status command should show running or stopped
        assert "Running" in captured.out or "Stopped" in captured.out

    def test_main_use_command(self, project_root, monkeypatch, capsys, tmp_path):
        """Test main function with use command."""
        # Mock ENV_FILE to use temp directory
        temp_env = tmp_path / ".env"
        monkeypatch.setattr("task_monitor.cli.ENV_FILE", temp_env)

        monkeypatch.setattr(sys, "argv", ["task-monitor", "use", str(project_root)])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        assert "Current project set to:" in captured.out
        assert str(project_root) in captured.out

    def test_main_current_command(self, project_root, monkeypatch, capsys):
        """Test main function with current command."""
        # Set environment variable
        monkeypatch.setenv(ENV_VAR_NAME, str(project_root))

        monkeypatch.setattr(sys, "argv", ["task-monitor", "current"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        assert "Current project:" in captured.out
        assert str(project_root) in captured.out

    def test_main_load_command(self, project_root, monkeypatch, capsys):
        """Test main function with load command."""
        monkeypatch.setenv(ENV_VAR_NAME, str(project_root))

        monkeypatch.setattr(sys, "argv", ["task-monitor", "load"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        # Should show found/loaded message or no files message
        assert "Found" in captured.out or "No task files found" in captured.out


class TestLoadPendingTasks:
    """Tests for load_pending_tasks function."""

    def test_load_no_tasks(self, project_root, capsys):
        """Test loading when pending directory is empty."""
        load_pending_tasks(project_root)

        captured = capsys.readouterr()
        assert "No task files found" in captured.out

    def test_load_with_tasks(self, project_root, capsys):
        """Test loading existing task files."""
        pending_dir = project_root / "tasks" / "task-monitor" / "pending"

        # Create test task files
        (pending_dir / "task-20260101-120000-test-1.md").write_text("# Test Task 1")
        (pending_dir / "task-20260101-130000-test-2.md").write_text("# Test Task 2")
        (pending_dir / "task-20260101-140000-test-3.md").write_text("# Test Task 3")

        load_pending_tasks(project_root)

        captured = capsys.readouterr()
        assert "Found 3 task file(s)" in captured.out
        assert "Successfully loaded 3 task file(s)" in captured.out
        assert "task-20260101-120000-test-1.md" in captured.out
        assert "task-20260101-130000-test-2.md" in captured.out
        assert "task-20260101-140000-test-3.md" in captured.out

    def test_load_filters_invalid_names(self, project_root, capsys):
        """Test that load only processes files matching the task pattern."""
        pending_dir = project_root / "tasks" / "task-monitor" / "pending"

        # Create valid and invalid files
        (pending_dir / "task-20260101-120000-valid.md").write_text("# Valid")
        (pending_dir / "invalid-name.txt").write_text("# Invalid")
        (pending_dir / "readme.md").write_text("# Invalid")

        load_pending_tasks(project_root)

        captured = capsys.readouterr()
        assert "Found 1 task file(s)" in captured.out
        assert "task-20260101-120000-valid.md" in captured.out

    def test_load_nonexistent_directory(self, tmp_path, capsys):
        """Test loading when pending directory doesn't exist."""
        nonexistent_path = tmp_path / "nonexistent"
        load_pending_tasks(nonexistent_path)

        captured = capsys.readouterr()
        assert "does not exist" in captured.out
