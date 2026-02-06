"""
Coverage tests for task_queue.scanner module.

Tests the TaskScanner class and its methods to improve coverage from 22% to 60%+.
"""

import pytest
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, Mock

from task_queue.scanner import TaskScanner
from task_queue.models import TaskSourceDirectory, DiscoveredTask


class TestTaskScannerInit:
    """Tests for TaskScanner initialization."""

    def test_init_with_file_hash_enabled(self):
        """Test scanner initialization with file hash enabled."""
        scanner = TaskScanner(enable_file_hash=True)
        assert scanner.enable_file_hash is True

    def test_init_with_file_hash_disabled(self):
        """Test scanner initialization with file hash disabled."""
        scanner = TaskScanner(enable_file_hash=False)
        assert scanner.enable_file_hash is False

    def test_init_default(self):
        """Test scanner initialization with default parameters."""
        scanner = TaskScanner()
        assert scanner.enable_file_hash is True


class TestScanTaskSourceDirectory:
    """Tests for scan_task_source_directory method."""

    def test_scan_nonexistent_directory(self, sample_task_source_dir):
        """Test scanning a directory that does not exist."""
        scanner = TaskScanner()

        # Create a source dir pointing to non-existent path
        nonexistent_dir = TaskSourceDirectory(
            id="nonexistent",
            path="/nonexistent/path/that/does/not/exist",
            description="Nonexistent source"
        )

        result = scanner.scan_task_source_directory(nonexistent_dir)

        assert result == []

    def test_scan_empty_directory(self, sample_task_source_dir):
        """Test scanning an empty directory."""
        scanner = TaskScanner()
        result = scanner.scan_task_source_directory(sample_task_source_dir)

        assert result == []

    def test_scan_with_valid_task_files(self, temp_dir):
        """Test scanning directory with valid task files."""
        # Create source directory
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        # Create valid task files
        task1 = source_path / "task-20260206-120000-first-task.md"
        task2 = source_path / "task-20260206-120001-second-task.md"
        task1.write_text("# Task 1\nContent")
        task2.write_text("# Task 2\nContent")

        source_dir = TaskSourceDirectory(
            id="test-source",
            path=str(source_path),
            description="Test source"
        )

        scanner = TaskScanner()
        result = scanner.scan_task_source_directory(source_dir)

        assert len(result) == 2
        assert result[0].task_id == "task-20260206-120000-first-task"
        assert result[1].task_id == "task-20260206-120001-second-task"

    def test_scan_ignores_invalid_task_files(self, temp_dir):
        """Test that scanner ignores files with invalid task ID format."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        # Create invalid task files
        (source_path / "invalid-name.md").write_text("Invalid")
        (source_path / "task-123.md").write_text("Invalid format")
        (source_path / "task-20260206-12.md").write_text("Invalid format")

        source_dir = TaskSourceDirectory(
            id="test-source",
            path=str(source_path),
            description="Test source"
        )

        scanner = TaskScanner()
        result = scanner.scan_task_source_directory(source_dir)

        assert len(result) == 0

    def test_scan_sorts_by_filename(self, temp_dir):
        """Test that scan results are sorted by filename (chronological)."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        # Create task files in non-chronological order
        task3 = source_path / "task-20260206-120003-third.md"
        task1 = source_path / "task-20260206-120001-first.md"
        task2 = source_path / "task-20260206-120002-second.md"

        task3.write_text("# Task 3")
        task1.write_text("# Task 1")
        task2.write_text("# Task 2")

        source_dir = TaskSourceDirectory(
            id="test-source",
            path=str(source_path),
            description="Test source"
        )

        scanner = TaskScanner()
        result = scanner.scan_task_source_directory(source_dir)

        # Should be sorted chronologically by filename
        assert result[0].task_id == "task-20260206-120001-first"
        assert result[1].task_id == "task-20260206-120002-second"
        assert result[2].task_id == "task-20260206-120003-third"

    def test_scan_with_file_hash_disabled(self, temp_dir):
        """Test scanning with file hash calculation disabled."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        source_dir = TaskSourceDirectory(
            id="test-source",
            path=str(source_path),
            description="Test source"
        )

        scanner = TaskScanner(enable_file_hash=False)
        result = scanner.scan_task_source_directory(source_dir)

        assert len(result) == 1
        assert result[0].file_hash is None

    def test_scan_with_file_hash_enabled(self, temp_dir):
        """Test scanning with file hash calculation enabled."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        content = "# Test task"
        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text(content)

        source_dir = TaskSourceDirectory(
            id="test-source",
            path=str(source_path),
            description="Test source"
        )

        scanner = TaskScanner(enable_file_hash=True)
        result = scanner.scan_task_source_directory(source_dir)

        assert len(result) == 1
        assert result[0].file_hash is not None

        # Verify hash matches MD5 of content
        expected_hash = hashlib.md5(content.encode()).hexdigest()
        assert result[0].file_hash == expected_hash

    def test_scan_handles_oserror_on_file_stat(self, temp_dir):
        """Test scanning handles OSError when reading file stats."""
        # This test verifies OSError handling in _create_discovered_task
        # We'll test the _create_discovered_task method directly
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner()

        # Mock stat() to raise OSError for the specific file
        original_stat = Path.stat

        def mock_stat(*args, **kwargs):
            # Check if we're trying to stat our test file
            if args and len(args) > 0:
                path_str = str(args[0]) if hasattr(args[0], '__str__') else str(args)
                if "task-20260206-120000-test.md" in path_str:
                    raise OSError("Mock error")
            # Call original stat for other files
            return original_stat(*args, **kwargs)

        with patch.object(Path, 'stat', mock_stat):
            # Call _create_discovered_task directly to test error handling
            result = scanner._create_discovered_task(task_file, "test-source")

        # Should handle error and return None
        assert result is None

    def test_scan_includes_file_size(self, temp_dir):
        """Test that scan includes file size in discovered tasks."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        content = "# Test task\nSome content here"
        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text(content)

        source_dir = TaskSourceDirectory(
            id="test-source",
            path=str(source_path),
            description="Test source"
        )

        scanner = TaskScanner()
        result = scanner.scan_task_source_directory(source_dir)

        assert len(result) == 1
        assert result[0].file_size == len(content.encode())

    def test_scan_sets_discovered_at_timestamp(self, temp_dir):
        """Test that scan includes discovery timestamp."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        before_scan = datetime.now()
        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        source_dir = TaskSourceDirectory(
            id="test-source",
            path=str(source_path),
            description="Test source"
        )

        scanner = TaskScanner()
        result = scanner.scan_task_source_directory(source_dir)

        after_scan = datetime.now()

        assert len(result) == 1
        discovered_at = datetime.fromisoformat(result[0].discovered_at)
        assert before_scan <= discovered_at <= after_scan


class TestScanTaskSourceDirectories:
    """Tests for scan_task_source_directories method."""

    def test_scan_multiple_sources(self, temp_dir):
        """Test scanning multiple source directories."""
        # Create two source directories
        source1_path = temp_dir / "source1"
        source2_path = temp_dir / "source2"
        source1_path.mkdir(parents=True)
        source2_path.mkdir(parents=True)

        # Add tasks to each
        (source1_path / "task-20260206-120000-source1-task.md").write_text("# Source 1 Task")
        (source2_path / "task-20260206-120001-source2-task.md").write_text("# Source 2 Task")

        source_dirs = [
            TaskSourceDirectory(id="source1", path=str(source1_path), description="Source 1"),
            TaskSourceDirectory(id="source2", path=str(source2_path), description="Source 2"),
        ]

        scanner = TaskScanner()
        result = scanner.scan_task_source_directories(source_dirs)

        assert len(result) == 2
        assert result[0].task_doc_dir_id == "source1"
        assert result[1].task_doc_dir_id == "source2"

    def test_scan_empty_source_list(self):
        """Test scanning with empty source list."""
        scanner = TaskScanner()
        result = scanner.scan_task_source_directories([])

        assert result == []

    def test_scan_multiple_sources_sorts_chronologically(self, temp_dir):
        """Test that scanning multiple sources sorts all tasks chronologically."""
        source1_path = temp_dir / "source1"
        source2_path = temp_dir / "source2"
        source1_path.mkdir(parents=True)
        source2_path.mkdir(parents=True)

        # Add tasks in reverse chronological order across sources
        (source1_path / "task-20260206-120003-later-source1.md").write_text("# Task 3")
        (source2_path / "task-20260206-120001-early-source2.md").write_text("# Task 1")
        (source1_path / "task-20260206-120002-middle-source1.md").write_text("# Task 2")

        source_dirs = [
            TaskSourceDirectory(id="source1", path=str(source1_path)),
            TaskSourceDirectory(id="source2", path=str(source2_path)),
        ]

        scanner = TaskScanner()
        result = scanner.scan_task_source_directories(source_dirs)

        # All tasks should be sorted chronologically regardless of source
        assert result[0].task_id == "task-20260206-120001-early-source2"
        assert result[1].task_id == "task-20260206-120002-middle-source1"
        assert result[2].task_id == "task-20260206-120003-later-source1"


class TestIsFileModified:
    """Tests for is_file_modified method."""

    def test_is_modified_with_unknown_hash(self, temp_dir):
        """Test modification check with unknown (None) hash."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner()

        # None hash should be considered modified
        result = scanner.is_file_modified(task_file, None)
        assert result is True

    def test_is_modified_with_different_hash(self, temp_dir):
        """Test modification check with different hash."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner()
        known_hash = "abc123def456"

        result = scanner.is_file_modified(task_file, known_hash)
        assert result is True

    def test_is_not_modified_with_same_hash(self, temp_dir):
        """Test modification check with same hash."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        content = "# Test task"
        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text(content)

        scanner = TaskScanner(enable_file_hash=True)

        # Get the actual hash
        actual_hash = scanner.calculate_hash(task_file)

        # Check with same hash
        result = scanner.is_file_modified(task_file, actual_hash)
        assert result is False

    def test_is_modified_when_hash_disabled(self, temp_dir):
        """Test modification check when hash is disabled."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner(enable_file_hash=False)

        # Should return False when hash disabled
        result = scanner.is_file_modified(task_file, None)
        assert result is False


class TestGetFileModificationTime:
    """Tests for get_file_modification_time method."""

    def test_get_modification_time_existing_file(self, temp_dir):
        """Test getting modification time for existing file."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner()
        result = scanner.get_file_modification_time(task_file)

        assert result is not None
        # Should be valid ISO format
        datetime.fromisoformat(result)

    def test_get_modification_time_nonexistent_file(self):
        """Test getting modification time for non-existent file."""
        scanner = TaskScanner()
        result = scanner.get_file_modification_time(Path("/nonexistent/file.md"))

        assert result is None

    def test_get_modification_time_handles_oserror(self, temp_dir):
        """Test getting modification time handles OSError."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner()

        # Mock stat() to raise OSError
        with patch.object(Path, 'stat', side_effect=OSError("Mock error")):
            result = scanner.get_file_modification_time(task_file)

        assert result is None


class TestCalculateHash:
    """Tests for calculate_hash (public) and _calculate_hash (private) methods."""

    def test_calculate_hash_public_method(self, temp_dir):
        """Test public calculate_hash method."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        content = "# Test task content"
        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text(content)

        scanner = TaskScanner()
        result = scanner.calculate_hash(task_file)

        # Should match MD5 of content
        expected_hash = hashlib.md5(content.encode()).hexdigest()
        assert result == expected_hash

    def test_calculate_hash_empty_file(self, temp_dir):
        """Test hash calculation for empty file."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("")

        scanner = TaskScanner()
        result = scanner.calculate_hash(task_file)

        # MD5 of empty string
        assert result == "d41d8cd98f00b204e9800998ecf8427e"

    def test_calculate_hash_large_file(self, temp_dir):
        """Test hash calculation for large file (tests chunked reading)."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        # Create a file larger than one chunk (4096 bytes)
        large_content = "x" * 10000
        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text(large_content)

        scanner = TaskScanner()
        result = scanner.calculate_hash(task_file)

        expected_hash = hashlib.md5(large_content.encode()).hexdigest()
        assert result == expected_hash

    def test_calculate_hash_handles_oserror(self, temp_dir):
        """Test hash calculation handles OSError."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner()

        # Mock file open to raise OSError
        with patch('builtins.open', side_effect=OSError("Mock error")):
            result = scanner.calculate_hash(task_file)

        # Should return empty string on error
        assert result == ""


class TestFindTaskFiles:
    """Tests for _find_task_files method."""

    def test_find_task_files_in_directory(self, temp_dir):
        """Test finding task files in directory."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        # Create task files and other files
        (source_path / "task-20260206-120000-test.md").write_text("# Task 1")
        (source_path / "task-20260206-120001-another.md").write_text("# Task 2")
        (source_path / "other-file.txt").write_text("Not a task")
        (source_path / "README.md").write_text("Readme")

        scanner = TaskScanner()
        result = scanner._find_task_files(source_path)

        assert len(result) == 2
        # Should only return task-*.md files
        assert all(f.name.startswith("task-") and f.suffix == ".md" for f in result)

    def test_find_task_files_ignores_directories(self, temp_dir):
        """Test that _find_task_files ignores directories matching pattern."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        # Create a directory that matches the pattern
        (source_path / "task-backup").mkdir()
        # Create actual task file
        (source_path / "task-20260206-120000-test.md").write_text("# Task")

        scanner = TaskScanner()
        result = scanner._find_task_files(source_path)

        # Should only return the file, not the directory
        assert len(result) == 1
        assert result[0].is_file()


class TestCreateDiscoveredTask:
    """Tests for _create_discovered_task method."""

    def test_create_discovered_task_valid(self, temp_dir):
        """Test creating DiscoveredTask from valid file."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test-task.md"
        task_file.write_text("# Test task")

        scanner = TaskScanner()
        result = scanner._create_discovered_task(task_file, "test-source")

        assert result is not None
        assert result.task_id == "task-20260206-120000-test-task"
        assert result.task_doc_file == task_file
        assert result.task_doc_dir_id == "test-source"

    def test_create_discovered_task_invalid_id(self, temp_dir):
        """Test creating DiscoveredTask with invalid task ID returns None."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        invalid_file = source_path / "invalid-name.md"
        invalid_file.write_text("# Invalid task")

        scanner = TaskScanner()
        result = scanner._create_discovered_task(invalid_file, "test-source")

        assert result is None

    def test_create_discovered_task_with_zero_byte_file(self, temp_dir):
        """Test creating DiscoveredTask from zero-byte file."""
        source_path = temp_dir / "tasks" / "task-documents"
        source_path.mkdir(parents=True)

        task_file = source_path / "task-20260206-120000-test.md"
        task_file.write_text("")  # Empty file

        scanner = TaskScanner(enable_file_hash=True)
        result = scanner._create_discovered_task(task_file, "test-source")

        assert result is not None
        assert result.file_size == 0
        # Zero-byte files should not have hash calculated
        assert result.file_hash is None
