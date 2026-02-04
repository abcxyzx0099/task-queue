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
    find_task_file,
    show_result,
    show_history,
    show_logs,
    ENV_VAR_NAME,
    ENV_FILE,
    task_monitor_path,
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


class TestFindTaskFile:
    """Tests for find_task_file function."""

    @pytest.fixture
    def cli_project_root(self, temp_dir):
        """Create a project root with task directories for CLI tests."""
        task_monitor_dir = temp_dir / "tasks" / "task-monitor"
        task_monitor_dir.mkdir(parents=True)
        (task_monitor_dir / "pending").mkdir()
        (task_monitor_dir / "results").mkdir()
        return temp_dir

    def test_find_exact_match_in_results(self, cli_project_root):
        """Test finding exact match in results directory."""
        results_dir = cli_project_root / task_monitor_path / "results"
        result_file = results_dir / "task-20260202-030504-test.json"
        result_file.write_text('{"task_id": "test"}')

        found = find_task_file("task-20260202-030504-test", cli_project_root)
        assert found == result_file

    def test_find_exact_match_with_json_extension(self, cli_project_root):
        """Test finding exact match with .json extension."""
        results_dir = cli_project_root / task_monitor_path / "results"
        result_file = results_dir / "task-20260202-030504-test.json"
        result_file.write_text('{"task_id": "test"}')

        found = find_task_file("task-20260202-030504-test.json", cli_project_root)
        assert found == result_file

    def test_find_partial_match_in_results(self, cli_project_root):
        """Test finding partial match in results directory."""
        results_dir = cli_project_root / task_monitor_path / "results"
        result_file = results_dir / "task-20260202-030504-test.json"
        result_file.write_text('{"task_id": "test"}')

        found = find_task_file("task-20260202", cli_project_root)
        assert found == result_file

    def test_find_exact_match_in_pending(self, cli_project_root):
        """Test finding exact match in pending directory."""
        pending_dir = cli_project_root / task_monitor_path / "pending"
        task_file = pending_dir / "task-20260202-030504-test.md"
        task_file.write_text("# Test")

        found = find_task_file("task-20260202-030504-test", cli_project_root)
        assert found == task_file

    def test_find_partial_match_in_pending(self, cli_project_root):
        """Test finding partial match in pending directory."""
        pending_dir = cli_project_root / task_monitor_path / "pending"
        task_file = pending_dir / "task-20260202-030504-test.md"
        task_file.write_text("# Test")

        found = find_task_file("task-20260202", cli_project_root)
        assert found == task_file

    def test_find_task_not_found(self, cli_project_root):
        """Test when task is not found."""
        found = find_task_file("nonexistent-task", cli_project_root)
        assert found is None

    def test_find_task_with_md_extension(self, cli_project_root):
        """Test finding task with .md extension."""
        pending_dir = cli_project_root / task_monitor_path / "pending"
        task_file = pending_dir / "task-20260202-030504-test.md"
        task_file.write_text("# Test")

        found = find_task_file("task-20260202-030504-test.md", cli_project_root)
        assert found == task_file


class TestShowResult:
    """Tests for show_result function."""

    @pytest.fixture
    def result_project_root(self, temp_dir):
        """Create a project root with a result file."""
        task_monitor_dir = temp_dir / "tasks" / "task-monitor"
        task_monitor_dir.mkdir(parents=True)
        results_dir = task_monitor_dir / "results"
        results_dir.mkdir()

        # Create a completed task result
        result_file = results_dir / "task-20260202-030504-completed.json"
        result_data = {
            "task_id": "task-20260202-030504-completed",
            "status": "completed",
            "created_at": "2026-02-02T03:05:04",
            "started_at": "2026-02-02T03:05:10",
            "completed_at": "2026-02-02T03:06:00",
            "duration_seconds": 50.0,
            "worker_output": {
                "summary": "Task completed successfully",
                "usage": {"total_tokens": 5000, "cost_usd": 0.025},
                "cost_usd": 0.025
            },
            "artifacts": ["output.txt", "report.pdf"],
            "stdout": "Processing complete\nAll steps finished",
            "stderr": None
        }
        result_file.write_text(json.dumps(result_data))

        # Create a failed task result
        failed_file = results_dir / "task-20260202-040505-failed.json"
        failed_data = {
            "task_id": "task-20260202-040505-failed",
            "status": "failed",
            "created_at": "2026-02-02T04:05:05",
            "started_at": "2026-02-02T04:05:10",
            "completed_at": "2026-02-02T04:05:25",
            "duration_seconds": 15.0,
            "error": "ValueError: Invalid input",
            "stderr": "Traceback (most recent call last):\nValueError: Invalid input"
        }
        failed_file.write_text(json.dumps(failed_data))

        return temp_dir

    def test_show_result_completed(self, result_project_root, capsys):
        """Test showing completed task result."""
        show_result("task-20260202-030504-completed", result_project_root)
        captured = capsys.readouterr()

        assert "Task ID: task-20260202-030504-completed" in captured.out
        assert "Status: completed" in captured.out
        assert "Duration: 50.00 seconds" in captured.out
        assert "Summary:" in captured.out
        assert "Task completed successfully" in captured.out
        assert "Tokens: 5000" in captured.out
        assert "Artifacts:" in captured.out
        assert "- output.txt" in captured.out
        assert "- report.pdf" in captured.out

    def test_show_result_failed(self, result_project_root, capsys):
        """Test showing failed task result."""
        show_result("task-20260202-040505-failed", result_project_root)
        captured = capsys.readouterr()

        assert "Task ID: task-20260202-040505-failed" in captured.out
        assert "Status: failed" in captured.out
        assert "Error: ValueError: Invalid input" in captured.out
        assert "Stderr:" in captured.out or "Traceback" in captured.out

    def test_show_result_partial_id(self, result_project_root, capsys):
        """Test showing result with partial task ID."""
        show_result("task-20260202-03", result_project_root)
        captured = capsys.readouterr()

        assert "Task ID: task-20260202-030504-completed" in captured.out

    def test_show_result_not_found(self, result_project_root, capsys):
        """Test showing result for non-existent task."""
        show_result("nonexistent-task", result_project_root)
        captured = capsys.readouterr()

        assert "Error: Task 'nonexistent-task' not found" in captured.out
        assert "Searched in:" in captured.out

    def test_show_result_invalid_json(self, result_project_root, capsys):
        """Test showing result with malformed JSON."""
        results_dir = result_project_root / task_monitor_path / "results"
        bad_file = results_dir / "task-bad.json"
        bad_file.write_text("{invalid json")

        show_result("task-bad", result_project_root)
        captured = capsys.readouterr()

        assert "Error: Failed to parse result file" in captured.out


class TestShowHistory:
    """Tests for show_history function."""

    @pytest.fixture
    def history_project_root(self, temp_dir):
        """Create a project root with multiple result files."""
        task_monitor_dir = temp_dir / "tasks" / "task-monitor"
        task_monitor_dir.mkdir(parents=True)
        results_dir = task_monitor_dir / "results"
        results_dir.mkdir()

        # Create multiple result files
        results = [
            {
                "file": "task-20260202-100001-oldest.json",
                "status": "completed",
                "completed_at": "2026-02-02T10:00:01"
            },
            {
                "file": "task-20260202-110002-middle.json",
                "status": "completed",
                "completed_at": "2026-02-02T11:00:02"
            },
            {
                "file": "task-20260202-120003-newest.json",
                "status": "completed",
                "completed_at": "2026-02-02T12:00:03"
            },
            {
                "file": "task-20260202-090004-failed.json",
                "status": "failed",
                "completed_at": "2026-02-02T09:00:04"
            },
        ]

        for result in results:
            result_file = results_dir / result["file"]
            data = {
                "task_id": result["file"].replace(".json", ""),
                "status": result["status"],
                "completed_at": result["completed_at"]
            }
            result_file.write_text(json.dumps(data))

        return temp_dir

    def test_show_history_all(self, history_project_root, capsys):
        """Test showing all history."""
        show_history(history_project_root)
        captured = capsys.readouterr()

        # Should show all 4 tasks
        assert "task-20260202-100001-oldest" in captured.out
        assert "task-20260202-110002-middle" in captured.out
        assert "task-20260202-120003-newest" in captured.out
        assert "task-20260202-090004-failed" in captured.out
        # Should show header
        assert "Task ID" in captured.out
        assert "Status" in captured.out
        assert "Completed" in captured.out

    def test_show_history_with_limit(self, history_project_root, capsys):
        """Test showing history with limit."""
        show_history(history_project_root, limit=2)
        captured = capsys.readouterr()

        lines = captured.out.strip().split('\n')
        # Count non-header lines
        task_lines = [l for l in lines if l and not l.startswith('-') and 'Task ID' not in l]
        assert len(task_lines) == 2

    def test_show_history_failed_only(self, history_project_root, capsys):
        """Test showing only failed tasks."""
        show_history(history_project_root, failed_only=True)
        captured = capsys.readouterr()

        assert "task-20260202-090004-failed" in captured.out
        # Should NOT show completed tasks
        assert "task-20260202-100001-oldest" not in captured.out
        assert "task-20260202-110002-middle" not in captured.out

    def test_show_history_no_results(self, temp_dir, capsys):
        """Test showing history when no results directory exists."""
        show_history(temp_dir)
        captured = capsys.readouterr()

        assert "No results directory found" in captured.out

    def test_show_history_empty_results(self, history_project_root, capsys):
        """Test showing history with empty results directory."""
        results_dir = history_project_root / task_monitor_path / "results"
        # Remove all files
        for f in results_dir.glob("*"):
            f.unlink()

        show_history(history_project_root)
        captured = capsys.readouterr()

        assert "No completed tasks found" in captured.out

    def test_show_history_no_failed_tasks(self, history_project_root, capsys):
        """Test showing failed history when no failed tasks exist after filter."""
        # Remove the failed file
        results_dir = history_project_root / task_monitor_path / "results"
        failed_file = results_dir / "task-20260202-090004-failed.json"
        if failed_file.exists():
            failed_file.unlink()

        show_history(history_project_root, failed_only=True)
        captured = capsys.readouterr()

        assert "No failed tasks found" in captured.out


class TestShowLogs:
    """Tests for show_logs function."""

    @pytest.fixture
    def logs_project_root(self, temp_dir):
        """Create a project root with task results containing logs."""
        task_monitor_dir = temp_dir / "tasks" / "task-monitor"
        task_monitor_dir.mkdir(parents=True)
        results_dir = task_monitor_dir / "results"
        results_dir.mkdir()

        # Create a task with stdout and stderr
        task_file = results_dir / "task-with-logs.json"
        log_data = {
            "task_id": "task-with-logs",
            "status": "completed",
            "stdout": "Line 1\nLine 2\nLine 3\nLine 4\nLine 5",
            "stderr": "Warning: minor issue"
        }
        task_file.write_text(json.dumps(log_data))

        # Create a task without stdout
        no_stdout_file = results_dir / "task-no-stdout.json"
        no_stdout_data = {
            "task_id": "task-no-stdout",
            "status": "completed",
            "stdout": None,
            "stderr": None
        }
        no_stdout_file.write_text(json.dumps(no_stdout_data))

        # Create a failed task with stderr
        failed_file = results_dir / "task-failed.json"
        failed_data = {
            "task_id": "task-failed",
            "status": "failed",
            "error": "Something went wrong",
            "stdout": "Starting...\n",
            "stderr": "Error: Critical failure"
        }
        failed_file.write_text(json.dumps(failed_data))

        return temp_dir

    def test_show_logs_with_stdout(self, logs_project_root, capsys):
        """Test showing logs with stdout."""
        show_logs("task-with-logs", logs_project_root)
        captured = capsys.readouterr()

        assert "Logs for: task-with-logs" in captured.out
        assert "Status: completed" in captured.out
        assert "STDOUT:" in captured.out
        assert "Line 1" in captured.out
        assert "Line 5" in captured.out
        assert "STDERR:" in captured.out
        assert "Warning: minor issue" in captured.out

    def test_show_logs_with_tail(self, logs_project_root, capsys):
        """Test showing logs with tail option."""
        show_logs("task-with-logs", logs_project_root, tail=2)
        captured = capsys.readouterr()

        assert "showing last 2 lines" in captured.out
        assert "Line 4" in captured.out
        assert "Line 5" in captured.out
        # Earlier lines should not appear
        assert "Line 1" not in captured.out
        assert "Line 2" not in captured.out

    def test_show_logs_no_stdout(self, logs_project_root, capsys):
        """Test showing logs when no stdout available."""
        show_logs("task-no-stdout", logs_project_root)
        captured = capsys.readouterr()

        assert "Logs for: task-no-stdout" in captured.out
        assert "No stdout available" in captured.out
        assert "No stderr" in captured.out

    def test_show_logs_failed_task(self, logs_project_root, capsys):
        """Test showing logs for failed task."""
        show_logs("task-failed", logs_project_root)
        captured = capsys.readouterr()

        assert "Logs for: task-failed" in captured.out
        assert "Status: failed" in captured.out
        assert "STDERR:" in captured.out
        assert "Error: Critical failure" in captured.out

    def test_show_logs_task_not_found(self, logs_project_root, capsys):
        """Test showing logs for non-existent task."""
        show_logs("nonexistent-task", logs_project_root)
        captured = capsys.readouterr()

        assert "Error: Task 'nonexistent-task' not found" in captured.out

    def test_show_logs_partial_id(self, logs_project_root, capsys):
        """Test showing logs with partial task ID."""
        show_logs("task-with", logs_project_root)
        captured = capsys.readouterr()

        assert "Logs for: task-with-logs" in captured.out
        assert "Line 1" in captured.out

    def test_show_logs_tail_zero(self, logs_project_root, capsys):
        """Test that tail=0 shows all lines (default behavior)."""
        show_logs("task-with-logs", logs_project_root, tail=0)
        captured = capsys.readouterr()

        # tail=0 shows all lines (no tail limit applied)
        assert "Line 1" in captured.out
        assert "Line 5" in captured.out
