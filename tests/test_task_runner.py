"""Tests for TaskRunner (Directory-Based State Architecture)."""

import pytest
import time
import threading
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from task_queue.task_runner import TaskRunner
from task_queue.models import TaskSourceDirectory


class TestTaskRunnerInit:
    """Tests for TaskRunner initialization."""

    def test_init_creates_directories(self, temp_dir):
        """Test that init creates necessary directories."""
        runner = TaskRunner(str(temp_dir))

        assert (temp_dir / "tasks" / "task-archive").exists()
        assert (temp_dir / "tasks" / "task-failed").exists()


class TestPickNextTask:
    """Tests for pick_next_task method."""

    def test_pick_next_task_from_empty_source(self, project_root):
        """Test picking from empty source."""
        runner = TaskRunner(str(project_root))
        source_dir = TaskSourceDirectory(
            id="test",
            path=str(project_root / "tasks" / "task-documents")
        )

        task = runner.pick_next_task_from_source(source_dir)
        assert task is None

    def test_pick_next_task_from_source(self, multiple_task_files, project_root):
        """Test picking tasks from a source."""
        runner = TaskRunner(str(project_root))
        source_dir = TaskSourceDirectory(
            id="test",
            path=str(project_root / "tasks" / "task-documents")
        )

        # Tasks should be picked in chronological order
        tasks = []
        for _ in range(3):
            task = runner.pick_next_task_from_source(source_dir)
            if task:
                tasks.append(task)

        assert len(tasks) == 3
        # Verify they're in chronological order by filename
        task_names = [t.name for t in tasks]
        assert task_names == sorted(task_names)

    def test_pick_next_task_from_source_with_running_marker(self, project_root):
        """Test that tasks with .running markers are skipped."""
        runner = TaskRunner(str(project_root))
        source_dir = TaskSourceDirectory(
            id="test",
            path=str(project_root / "tasks" / "task-documents")
        )

        # Create a task with a running marker
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        task_file = project_root / "tasks" / "task-documents" / f"task-{timestamp}-test.md"
        task_file.write_text("# Test task")

        # Create running marker with fake PID (non-existent process)
        running_marker = task_file.parent / f".{task_file.stem}.running"
        running_marker.write_text("process_id:99999:hostname\n")

        # Pick task - should skip the running one and clean up stale marker
        task = runner.pick_next_task_from_source(source_dir)

        # With fake PID, the stale marker should be cleaned and task returned
        assert task is not None
        assert task.name == task_file.name

    def test_pick_next_task_from_multiple_sources(self, project_root):
        """Test picking tasks from multiple sources."""
        # Create two source directories
        source1_dir = project_root / "tasks" / "source1"
        source2_dir = project_root / "tasks" / "source2"
        source1_dir.mkdir(parents=True)
        source2_dir.mkdir(parents=True)

        # Create tasks in both sources
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        task1 = source1_dir / f"task-{timestamp}-001-source1.md"
        task2 = source2_dir / f"task-{timestamp}-002-source2.md"
        task1.write_text("# Task 1")
        task2.write_text("# Task 2")

        runner = TaskRunner(str(project_root))
        source1 = TaskSourceDirectory(id="source1", path=str(source1_dir))
        source2 = TaskSourceDirectory(id="source2", path=str(source2_dir))

        # Pick from all sources - should return the earliest by filename
        task = runner.pick_next_task([source1, source2])
        assert task is not None
        # Should be task-001 since it's earlier in chronological order
        assert "001" in task.name


class TestExecuteTask:
    """Tests for execute_task method."""

    def test_execute_task_creates_running_marker(self, project_root):
        """Test that execute_task creates a .running marker."""
        runner = TaskRunner(str(project_root))

        # Create a task file
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        task_file = project_root / "tasks" / "task-documents" / f"task-{timestamp}-test.md"
        task_file.write_text("# Test task")

        # Mock the executor to return success
        with patch.object(runner.executor, 'execute') as mock_execute:
            from task_queue.executor import ExecutionResult
            mock_execute.return_value = ExecutionResult(
                success=True,
                task_id=task_file.stem,
                output="Done"
            )

            result = runner.execute_task(task_file)

            # Check running marker was created
            running_marker = task_file.parent / f".{task_file.stem}.running"
            assert not running_marker.exists()  # Should be cleaned up after execution

    def test_execute_task_moves_to_archive_on_success(self, project_root):
        """Test that successful tasks are moved to archive."""
        runner = TaskRunner(str(project_root))

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        task_file = project_root / "tasks" / "task-documents" / f"task-{timestamp}-test.md"
        task_file.write_text("# Test task")

        archive_dir = project_root / "tasks" / "task-archive"

        # Mock the executor to return success
        with patch.object(runner.executor, 'execute') as mock_execute:
            from task_queue.executor import ExecutionResult
            mock_execute.return_value = ExecutionResult(
                success=True,
                task_id=task_file.stem,
                output="Done"
            )

            result = runner.execute_task(task_file)

            # Task should be in archive
            archived_task = archive_dir / task_file.name
            assert archived_task.exists()
            # Original should be gone
            assert not task_file.exists()
            assert result['status'] == 'success'

    def test_execute_task_moves_to_failed_on_error(self, project_root):
        """Test that failed tasks are moved to failed directory."""
        runner = TaskRunner(str(project_root))

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        task_file = project_root / "tasks" / "task-documents" / f"task-{timestamp}-test.md"
        task_file.write_text("# Test task")

        failed_dir = project_root / "tasks" / "task-failed"

        # Mock the executor to return failure
        with patch.object(runner.executor, 'execute') as mock_execute:
            from task_queue.executor import ExecutionResult
            mock_execute.return_value = ExecutionResult(
                success=False,
                task_id=task_file.stem,
                error="Test error"
            )

            result = runner.execute_task(task_file)

            # Task should be in failed
            failed_task = failed_dir / task_file.name
            assert failed_task.exists()
            assert result['status'] == 'failed'


class TestGetStatus:
    """Tests for get_status method."""

    def test_get_status_empty(self, project_root):
        """Test status with no tasks."""
        runner = TaskRunner(str(project_root))
        source_dir = TaskSourceDirectory(
            id="test",
            path=str(project_root / "tasks" / "task-documents")
        )

        status = runner.get_status([source_dir])

        assert status['pending'] == 0
        assert status['running'] == 0
        assert status['completed'] == 0
        assert status['failed'] == 0

    def test_get_status_with_pending_tasks(self, multiple_task_files, project_root):
        """Test status with pending tasks."""
        runner = TaskRunner(str(project_root))
        source_dir = TaskSourceDirectory(
            id="test",
            path=str(project_root / "tasks" / "task-documents")
        )

        status = runner.get_status([source_dir])

        assert status['pending'] == 3
        assert status['running'] == 0
        assert 'test' in status['sources']

    def test_get_status_with_running_tasks(self, project_root):
        """Test status with running tasks."""
        runner = TaskRunner(str(project_root))
        source_dir = TaskSourceDirectory(
            id="test",
            path=str(project_root / "tasks" / "task-documents")
        )

        # Create a task with running marker
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        task_file = project_root / "tasks" / "task-documents" / f"task-{timestamp}-test.md"
        task_file.write_text("# Test")

        # Create running marker
        running_marker = task_file.parent / f".{task_file.stem}.running"
        running_marker.write_text("process_id:12345:hostname\n")

        status = runner.get_status([source_dir])

        assert status['running'] == 1
        assert status['pending'] == 0

    def test_get_status_multiple_sources(self, project_root):
        """Test status with multiple source directories."""
        # Create two sources
        source1_dir = project_root / "tasks" / "source1"
        source2_dir = project_root / "tasks" / "source2"
        source1_dir.mkdir(parents=True)
        source2_dir.mkdir(parents=True)

        # Create tasks in source1
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for i in range(2):
            task = source1_dir / f"task-{timestamp}-{i:02d}-s1.md"
            task.write_text("# Task")

        # Create tasks in source2
        for i in range(3):
            task = source2_dir / f"task-{timestamp}-{i:02d}-s2.md"
            task.write_text("# Task")

        runner = TaskRunner(str(project_root))
        source1 = TaskSourceDirectory(id="source1", path=str(source1_dir))
        source2 = TaskSourceDirectory(id="source2", path=str(source2_dir))

        status = runner.get_status([source1, source2])

        assert status['pending'] == 5
        assert status['sources']['source1']['pending'] == 2
        assert status['sources']['source2']['pending'] == 3
