"""Tests for task_monitor.cli module."""

import pytest
import json
from pathlib import Path
from datetime import datetime
from io import StringIO
import sys

from task_monitor.cli import (
    show_task_status,
    show_status,
    show_queue,
    DEFAULT_PROJECT_ROOT,
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


class TestMain:
    """Tests for main CLI entry point."""

    def test_main_queue_command(self, project_root, queue_state_file, monkeypatch, capsys):
        """Test main function with queue command."""
        import task_monitor.cli

        # Mock the project root
        monkeypatch.setattr(task_monitor.cli, "DEFAULT_PROJECT_ROOT", project_root)

        # Mock sys.argv
        monkeypatch.setattr(sys, "argv", ["task-monitor", "queue"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        assert "Queue size:" in captured.out

    def test_main_with_project_path(self, project_root, queue_state_file, monkeypatch, capsys):
        """Test main function with custom project path."""
        import task_monitor.cli

        monkeypatch.setattr(sys, "argv", ["task-monitor", "--project-path", str(project_root), "queue"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        assert "Queue size:" in captured.out

    def test_main_default_status_command(self, project_root, completed_job_result, monkeypatch, capsys):
        """Test main function with default status command."""
        import task_monitor.cli

        monkeypatch.setattr(task_monitor.cli, "DEFAULT_PROJECT_ROOT", project_root)
        monkeypatch.setattr(sys, "argv", ["task-monitor", "completed-job"])

        from task_monitor.cli import main
        main()

        captured = capsys.readouterr()
        assert "Status: completed" in captured.out
