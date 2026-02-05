"""Integration tests for task-queue watchdog and per-source architecture."""

import pytest
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from task_queue.models import (
    Task, TaskStatus, TaskSource, QueueState,
    SourceState, SourceStatistics, SourceProcessingState,
    CoordinatorState, GlobalStatistics, TaskSourceDirectory,
    DiscoveredTask
)
from task_queue.config import ConfigManager
from task_queue.processor import TaskProcessor
from task_queue.coordinator import SourceCoordinator
from task_queue.watchdog import WatchdogManager, DebounceTracker
from task_queue.scanner import TaskScanner


class TestStateMigration:
    """Tests for v1.0 to v2.0 state migration."""

    def test_migrate_v1_to_v2_empty_queue(self, tmp_path):
        """Test migrating empty v1.0 state to v2.0."""
        state_file = tmp_path / "queue_state.json"

        # Create v1.0 state file
        v1_data = {
            "version": "1.0",
            "queue": [],
            "processing": {
                "is_processing": False,
                "current_task": None,
                "process_id": None,
                "started_at": None,
                "hostname": None
            },
            "statistics": {
                "total_queued": 0,
                "total_completed": 0,
                "total_failed": 0,
                "last_processed_at": None,
                "last_load_at": None
            }
        }
        state_file.write_text(json.dumps(v1_data))

        # Create processor - should migrate automatically
        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Check migrated state
        assert processor.state.version == "2.0"
        assert isinstance(processor.state.sources, dict)
        assert len(processor.state.sources) == 0
        assert isinstance(processor.state.coordinator, CoordinatorState)

    def test_migrate_v1_to_v2_with_tasks(self, tmp_path):
        """Test migrating v1.0 state with tasks to v2.0."""
        state_file = tmp_path / "queue_state.json"

        # Create v1.0 state with tasks
        v1_data = {
            "version": "1.0",
            "queue": [
                {
                    "task_id": "task-20250131-100000-test1",
                    "task_doc_file": "/path/to/task1.md",
                    "task_doc_dir_id": "main",
                    "status": "pending",
                    "source": "load",
                    "attempts": 0
                },
                {
                    "task_id": "task-20250131-100000-test2",
                    "task_doc_file": "/path/to/task2.md",
                    "task_doc_dir_id": "experimental",
                    "status": "completed",
                    "source": "load",
                    "attempts": 1
                }
            ],
            "processing": {
                "is_processing": False,
                "current_task": None,
                "process_id": None,
                "started_at": None,
                "hostname": None
            },
            "statistics": {
                "total_queued": 2,
                "total_completed": 1,
                "total_failed": 0,
                "last_processed_at": None,
                "last_load_at": None
            }
        }
        state_file.write_text(json.dumps(v1_data))

        # Create processor - should migrate automatically
        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Check migrated state
        assert processor.state.version == "2.0"
        assert len(processor.state.sources) == 2

        # Check main source
        main_source = processor.state.sources.get("main")
        assert main_source is not None
        assert main_source.id == "main"
        assert len(main_source.queue) == 1
        assert main_source.queue[0].task_id == "task-20250131-100000-test1"
        # Note: Statistics are migrated from v1.0 stats
        assert main_source.statistics.total_queued == 1

        # Check experimental source
        exp_source = processor.state.sources.get("experimental")
        assert exp_source is not None
        assert exp_source.queue[0].task_id == "task-20250131-100000-test2"
        assert exp_source.queue[0].status == TaskStatus.COMPLETED

        # Note: Global statistics default to 0 after migration
        # They get updated when tasks are actually processed


class TestPerSourceArchitecture:
    """Tests for per-source queue architecture."""

    def test_add_tasks_to_different_sources(self, tmp_path):
        """Test adding tasks to different sources creates separate queues."""
        state_file = tmp_path / "queue_state.json"

        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Add task to main source
        task1 = DiscoveredTask(
            task_id="task-001",
            task_doc_file=tmp_path / "main" / "task1.md",
            task_doc_dir_id="main"
        )
        processor._add_to_queue(task1)

        # Add task to experimental source
        task2 = DiscoveredTask(
            task_id="task-002",
            task_doc_file=tmp_path / "exp" / "task2.md",
            task_doc_dir_id="experimental"
        )
        processor._add_to_queue(task2)

        # Check separate sources
        assert len(processor.state.sources) == 2
        assert "main" in processor.state.sources
        assert "experimental" in processor.state.sources

        # Check queues are separate
        main_source = processor.state.sources["main"]
        exp_source = processor.state.sources["experimental"]

        assert len(main_source.queue) == 1
        assert len(exp_source.queue) == 1
        assert main_source.queue[0].task_id == "task-001"
        assert exp_source.queue[0].task_id == "task-002"

    def test_each_source_has_own_lock(self, tmp_path):
        """Test that each source has its own lock."""
        state_file = tmp_path / "queue_state.json"

        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Add tasks to two sources
        for i in range(3):
            task = DiscoveredTask(
                task_id=f"task-main-{i}",
                task_doc_file=tmp_path / "main" / f"task{i}.md",
                task_doc_dir_id="main"
            )
            processor._add_to_queue(task)

        task = DiscoveredTask(
            task_id="task-exp-1",
            task_doc_file=tmp_path / "exp" / "task1.md",
            task_doc_dir_id="experimental"
        )
        processor._add_to_queue(task)

        # Check each source has its own lock
        main_lock = processor._get_source_lock("main")
        exp_lock = processor._get_source_lock("experimental")

        assert main_lock is not exp_lock
        assert isinstance(main_lock, type(exp_lock))

    def test_source_state_counts(self, tmp_path):
        """Test SourceState count methods."""
        state_file = tmp_path / "queue_state.json"

        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Add tasks with different statuses to main source
        for i in range(2):
            task = DiscoveredTask(
                task_id=f"task-pending-{i}",
                task_doc_file=tmp_path / "main" / f"task{i}.md",
                task_doc_dir_id="main"
            )
            processor._add_to_queue(task)

        # Manually set one to running
        processor.state.sources["main"].queue[0].status = TaskStatus.RUNNING

        # Check counts
        main_source = processor.state.sources["main"]
        assert main_source.get_pending_count() == 1
        assert main_source.get_running_count() == 1
        assert main_source.get_completed_count() == 0
        assert main_source.get_failed_count() == 0

    def test_unload_source_removes_all_tasks(self, tmp_path):
        """Test unloading a source removes all its tasks."""
        state_file = tmp_path / "queue_state.json"

        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Add tasks to two sources
        for i in range(3):
            task = DiscoveredTask(
                task_id=f"task-main-{i}",
                task_doc_file=tmp_path / "main" / f"task{i}.md",
                task_doc_dir_id="main"
            )
            processor._add_to_queue(task)

        task = DiscoveredTask(
            task_id="task-exp-1",
            task_doc_file=tmp_path / "exp" / "task1.md",
            task_doc_dir_id="experimental"
        )
        processor._add_to_queue(task)

        # Unload main source
        removed = processor.unload_source("main")

        assert removed == 3
        assert "main" not in processor.state.sources
        assert "experimental" in processor.state.sources
        assert len(processor.state.sources["experimental"].queue) == 1

    def test_global_statistics_aggregation(self, tmp_path):
        """Test that global statistics aggregate across all sources."""
        state_file = tmp_path / "queue_state.json"

        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Add tasks to multiple sources
        for i in range(2):
            task = DiscoveredTask(
                task_id=f"task-main-{i}",
                task_doc_file=tmp_path / "main" / f"task{i}.md",
                task_doc_dir_id="main"
            )
            processor._add_to_queue(task)

        for i in range(3):
            task = DiscoveredTask(
                task_id=f"task-exp-{i}",
                task_doc_file=tmp_path / "exp" / f"task{i}.md",
                task_doc_dir_id="experimental"
            )
            processor._add_to_queue(task)

        # Check global counts
        assert processor.state.get_total_pending_count() == 5
        assert processor.state.global_statistics.total_queued == 5
        assert len(processor.state.sources) == 2


class TestSourceCoordinator:
    """Tests for SourceCoordinator round-robin behavior."""

    def test_coordinator_initial_state(self):
        """Test coordinator starts with no current source."""
        state = QueueState()
        coordinator = SourceCoordinator(state)

        assert coordinator.coordinator_state.current_source is None
        assert coordinator.coordinator_state.source_order == []

    def test_coordinator_add_source(self):
        """Test adding sources to coordinator."""
        state = QueueState()
        coordinator = SourceCoordinator(state)

        coordinator.add_source("main")
        coordinator.add_source("experimental")

        assert "main" in coordinator.coordinator_state.source_order
        assert "experimental" in coordinator.coordinator_state.source_order
        assert coordinator.coordinator_state.source_order == ["main", "experimental"]

    def test_coordinator_get_next_source(self, tmp_path):
        """Test getting next source with pending tasks."""
        state = QueueState()

        # Add sources with pending tasks
        state.sources["main"] = SourceState(
            id="main",
            path="/path/main",
            queue=[
                Task(task_id="t1", task_doc_file="t1.md", task_doc_dir_id="main", status=TaskStatus.PENDING),
                Task(task_id="t2", task_doc_file="t2.md", task_doc_dir_id="main", status=TaskStatus.PENDING),
            ]
        )
        state.sources["experimental"] = SourceState(
            id="experimental",
            path="/path/exp",
            queue=[
                Task(task_id="t3", task_doc_file="t3.md", task_doc_dir_id="experimental", status=TaskStatus.PENDING),
            ]
        )

        coordinator = SourceCoordinator(state)
        coordinator.add_source("main")
        coordinator.add_source("experimental")

        # First call should return main
        next_source = coordinator.get_next_source()
        assert next_source == "main"

        # After marking main complete, should return experimental
        coordinator.switch_to_source("main")
        # Simulate main completing by clearing its pending tasks
        state.sources["main"].queue[0].status = TaskStatus.COMPLETED
        state.sources["main"].queue[1].status = TaskStatus.COMPLETED

        next_source = coordinator.get_next_source()
        assert next_source == "experimental"

    def test_coordinator_round_robin(self, tmp_path):
        """Test round-robin cycling through sources."""
        state = QueueState()

        # Add three sources with pending tasks
        for source_id in ["main", "experimental", "test"]:
            state.sources[source_id] = SourceState(
                id=source_id,
                path=f"/path/{source_id}",
                queue=[
                    Task(task_id=f"{source_id}-t1", task_doc_file="t1.md", task_doc_dir_id=source_id, status=TaskStatus.PENDING),
                ]
            )

        coordinator = SourceCoordinator(state)

        # Add in specific order
        coordinator.add_source("main")
        coordinator.add_source("experimental")
        coordinator.add_source("test")

        # Cycle through sources
        order = []
        for _ in range(4):
            next_source = coordinator.get_next_source()
            if next_source:
                order.append(next_source)
                # Mark as having no more pending tasks
                state.sources[next_source].queue = []

        # Should cycle through all three
        assert order == ["main", "experimental", "test"]

    def test_coordinator_no_pending_returns_none(self, tmp_path):
        """Test coordinator returns None when no pending tasks."""
        state = QueueState()
        state.sources["main"] = SourceState(
            id="main",
            path="/path/main",
            queue=[
                Task(task_id="t1", task_doc_file="t1.md", task_doc_dir_id="main", status=TaskStatus.COMPLETED),
            ]
        )

        coordinator = SourceCoordinator(state)
        coordinator.add_source("main")

        next_source = coordinator.get_next_source()
        assert next_source is None


class TestWatchdogManager:
    """Tests for watchdog event handling."""

    def test_debounce_tracker(self):
        """Test debounce tracker coalesces rapid events."""
        tracker = DebounceTracker(debounce_ms=100)

        file_path = "/path/to/file.md"

        # First event should process
        assert tracker.should_process(file_path) is True

        # Immediate second event should be debounced
        assert tracker.should_process(file_path) is False

        # Wait for debounce period
        time.sleep(0.15)

        # Now should process again
        assert tracker.should_process(file_path) is True

    def test_debounce_tracker_cleanup(self):
        """Test debounce tracker cleanup of old events."""
        tracker = DebounceTracker(debounce_ms=100)

        file_path = "/path/to/file.md"

        # Add some events
        tracker.should_process(file_path)

        # Cleanup should remove old events
        tracker.cleanup_old_events(max_age_seconds=0.01)

        # Wait a tiny bit
        time.sleep(0.02)

        # Cleanup again
        tracker.cleanup_old_events(max_age_seconds=0.01)

        # Event should be cleaned up
        assert file_path not in tracker._pending_events

    def test_watchdog_manager_load_callback(self, tmp_path):
        """Test WatchdogManager uses the provided load callback."""
        loaded_tasks = []

        def mock_load_callback(task_doc_file, source_id):
            loaded_tasks.append((task_doc_file, source_id))

        manager = WatchdogManager(mock_load_callback)

        # The callback is passed to individual TaskDocumentWatcher instances
        # Test that the manager stores the callback
        assert manager.load_callback == mock_load_callback

        # Create a mock source directory
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        source = TaskSourceDirectory(
            id="test",
            path=str(source_dir)
        )

        # Add source to manager - this creates a watcher with the callback
        manager.add_source(source)

        # Verify the watcher was created
        assert "test" in manager._watchers
        watcher = manager._watchers["test"]
        # The watcher should have the callback
        assert watcher.load_callback == mock_load_callback

    def test_watchdog_manager_multiple_sources(self, tmp_path):
        """Test managing multiple source watchers."""
        loaded_tasks = []

        def mock_load_callback(task_doc_file, source_id):
            loaded_tasks.append((task_doc_file, source_id))

        manager = WatchdogManager(mock_load_callback)

        # Create mock source directories
        for source_id in ["main", "experimental", "test"]:
            source_dir = tmp_path / source_id
            source_dir.mkdir()

            source = TaskSourceDirectory(id=source_id, path=str(source_dir))
            manager._watchers[source_id] = MagicMock()
            manager._watchers[source_id].is_running.return_value = False

        # Check all sources are tracked
        watched = manager.get_watched_sources()
        # All watchers are marked as not running, so no sources tracked
        assert len(watched) == 0

        # Mark one as running
        manager._watchers["main"].is_running.return_value = True
        watched = manager.get_watched_sources()
        assert "main" in watched
        assert len(watched) == 1


class TestWatchdogIntegration:
    """Integration tests for watchdog with file system events."""

    def test_task_pattern_validation(self):
        """Test task pattern validation in scanner."""
        scanner = TaskScanner()

        # Valid task IDs (date + time is enough, description is optional)
        assert scanner._is_valid_task_id("task-20250131-100000-test") is True
        assert scanner._is_valid_task_id("task-20250131-100000-test-description") is True
        assert scanner._is_valid_task_id("task-20250131-100000") is True  # No description is valid

        # Invalid task IDs
        assert scanner._is_valid_task_id("invalid") is False
        assert scanner._is_valid_task_id("task-123") is False
        assert scanner._is_valid_task_id("TASK-20250131-100000-test") is False

    def test_scanner_finds_task_files(self, tmp_path):
        """Test scanner finds task files matching pattern."""
        scanner = TaskScanner()

        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        # Create task files
        (source_dir / "task-20250131-100000-test1.md").write_text("# Test 1")
        (source_dir / "task-20250131-100001-test2.md").write_text("# Test 2")

        # Create non-task files
        (source_dir / "README.md").write_text("# Readme")
        (source_dir / "other.txt").write_text("Other")

        source = TaskSourceDirectory(id="test", path=str(source_dir))
        discovered = scanner.scan_task_source_directory(source)

        # Should find only task files
        assert len(discovered) == 2
        task_ids = [t.task_id for t in discovered]
        assert "task-20250131-100000-test1" in task_ids
        assert "task-20250131-100001-test2" in task_ids


class TestSourceStatistics:
    """Tests for per-source statistics."""

    def test_source_statistics_tracking(self, tmp_path):
        """Test that each source tracks its own statistics."""
        state_file = tmp_path / "queue_state.json"

        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Add tasks to main source
        for i in range(5):
            task = DiscoveredTask(
                task_id=f"main-{i}",
                task_doc_file=tmp_path / "main" / f"task{i}.md",
                task_doc_dir_id="main"
            )
            processor._add_to_queue(task)

        # Add tasks to experimental source
        for i in range(2):
            task = DiscoveredTask(
                task_id=f"exp-{i}",
                task_doc_file=tmp_path / "exp" / f"task{i}.md",
                task_doc_dir_id="experimental"
            )
            processor._add_to_queue(task)

        # Check statistics are separate
        main_stats = processor.state.sources["main"].statistics
        exp_stats = processor.state.sources["experimental"].statistics

        assert main_stats.total_queued == 5
        assert exp_stats.total_queued == 2

        # Global statistics aggregate correctly
        global_stats = processor.state.global_statistics
        assert global_stats.total_queued == 7
        # Note: total_sources tracks active sources from config, not sources with queues
        # The migration and queue building don't automatically update this


class TestTaskSourceEnum:
    """Tests for new TaskSource enum values."""

    def test_task_source_watchdog(self):
        """Test WATCHDOG source value."""
        assert TaskSource.WATCHDOG == "watchdog"

    def test_task_source_reload(self):
        """Test RELOAD source value."""
        assert TaskSource.RELOAD == "reload"

    def test_all_task_sources(self):
        """Test all expected source values exist."""
        expected = ["load", "manual", "api", "watchdog", "reload"]
        actual = [source.value for source in TaskSource]

        for expected_value in expected:
            assert expected_value in actual


class TestSourceProcessingState:
    """Tests for per-source processing state."""

    def test_processing_state_per_source(self, tmp_path):
        """Test each source has its own processing state."""
        state_file = tmp_path / "queue_state.json"

        processor = TaskProcessor(
            project_workspace=str(tmp_path),
            state_file=state_file
        )

        # Add two sources
        for source_id in ["main", "experimental"]:
            task = DiscoveredTask(
                task_id=f"{source_id}-1",
                task_doc_file=tmp_path / source_id / "task1.md",
                task_doc_dir_id=source_id
            )
            processor._add_to_queue(task)

        # Each source should have its own processing state
        main_processing = processor.state.sources["main"].processing
        exp_processing = processor.state.sources["experimental"].processing

        assert main_processing.is_processing is False
        assert exp_processing.is_processing is False
        assert main_processing.current_task is None
        assert exp_processing.current_task is None


class TestConfigWithWatchdogSettings:
    """Tests for watchdog configuration settings."""

    def test_default_watchdog_settings(self):
        """Test default watchdog settings."""
        from task_queue.models import QueueSettings

        settings = QueueSettings()

        assert settings.watch_enabled is True
        assert settings.watch_debounce_ms == 500
        assert settings.watch_patterns == ["task-*.md"]
        assert settings.watch_recursive is False

    def test_watchdog_settings_validation(self):
        """Test watchdog settings can be configured."""
        from task_queue.models import QueueSettings

        settings = QueueSettings(
            watch_enabled=False,
            watch_debounce_ms=1000,
            watch_patterns=["*.md"],
            watch_recursive=True
        )

        assert settings.watch_enabled is False
        assert settings.watch_debounce_ms == 1000
        assert settings.watch_patterns == ["*.md"]
        assert settings.watch_recursive is True
