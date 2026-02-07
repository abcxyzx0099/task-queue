"""
Comprehensive tests for task_queue.file_utils module to improve coverage.

Tests for error handling, edge cases, and less-covered code paths.
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import os

from task_queue.file_utils import AtomicFileWriter, FileLock, is_valid_task_id


class TestAtomicFileWriterErrorHandling:
    """Tests for error handling in AtomicFileWriter."""

    def test_write_json_creates_parent_dirs(self, temp_dir):
        """Test write_json creates parent directories."""
        nested_path = temp_dir / "deeply" / "nested" / "config.json"

        AtomicFileWriter.write_json(nested_path, {"test": "data"})

        assert nested_path.exists()
        assert nested_path.parent.exists()

    def test_write_json_error_cleans_temp_file(self, temp_dir):
        """Test write_json cleans up temp file on error."""
        target_file = temp_dir / "config.json"

        # Mock json.dump to raise exception
        with patch('json.dump', side_effect=RuntimeError("Write failed")):
            with pytest.raises(RuntimeError):
                AtomicFileWriter.write_json(target_file, {"test": "data"})

        # Temp file should be cleaned up
        temp_files = list(temp_dir.glob(".config.json.*.tmp"))
        assert len(temp_files) == 0

    def test_write_json_error_cleanup_handles_failures(self, temp_dir):
        """Test write_json handles cleanup failures gracefully."""
        target_file = temp_dir / "config.json"

        # Make json.dump fail, then make unlink fail too
        call_count = [0]

        original_dump = json.dump

        def failing_dump(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:
                return original_dump(*args, **kwargs)
            raise RuntimeError("Write failed")

        with patch('json.dump', side_effect=failing_dump):
            with patch.object(Path, 'unlink', side_effect=OSError("Cleanup failed")):
                # Should still raise the original error
                with pytest.raises(RuntimeError, match="Write failed"):
                    AtomicFileWriter.write_json(target_file, {"test": "data"})

    def test_read_json_with_default(self, temp_dir):
        """Test read_json returns default for non-existent file."""
        non_existent = temp_dir / "nonexistent.json"

        result = AtomicFileWriter.read_json(non_existent, default={"key": "value"})

        assert result == {"key": "value"}

    def test_read_json_invalid_json(self, temp_dir):
        """Test read_json returns default for invalid JSON."""
        invalid_file = temp_dir / "invalid.json"
        invalid_file.write_text("not valid json {}")

        result = AtomicFileWriter.read_json(invalid_file, default=None)

        assert result is None

    def test_read_json_io_error(self, temp_dir):
        """Test read_json handles IOError gracefully."""
        invalid_file = temp_dir / "unreadable.json"

        # Create file but make it unreadable
        invalid_file.write_text("{}")
        invalid_file.chmod(0o000)

        try:
            result = AtomicFileWriter.read_json(invalid_file, default=None)
            # On some systems, we might still read it or get default
            assert result is None or result == {}
        finally:
            # Restore permissions for cleanup
            invalid_file.chmod(0o644)


class TestFileLockErrorHandling:
    """Tests for error handling in FileLock."""

    def test_acquire_timeout(self, temp_dir):
        """Test acquire returns False on timeout."""
        lock_file = temp_dir / "test.lock"

        lock1 = FileLock(lock_file)
        lock2 = FileLock(lock_file)

        # First lock should acquire
        assert lock1.acquire(timeout=0.1) is True

        # Second lock should timeout
        assert lock2.acquire(timeout=0.1) is False

        # Clean up
        lock1.release()

    def test_acquire_exception_reraises(self, temp_dir):
        """Test acquire closes FD and re-raises non-locking exceptions."""
        lock_file = temp_dir / "test.lock"

        lock = FileLock(lock_file)

        # Patch to simulate exception after fd is opened
        original_flock = __import__('fcntl').flock
        call_count = [0]

        def failing_flock(fd, operation):
            call_count[0] += 1
            # Raise a non-IOError exception
            raise RuntimeError("Unexpected error")

        with patch('fcntl.flock', side_effect=failing_flock):
            with pytest.raises(RuntimeError, match="Unexpected error"):
                lock.acquire(timeout=0.1)

        # FD should be cleaned up
        assert lock.fd is None

    def test_acquire_exception_closes_fd(self, temp_dir):
        """Test acquire closes file descriptor on exception."""
        lock_file = temp_dir / "test.lock"

        lock = FileLock(lock_file)

        # Mock to cause exception after opening
        original_open = open
        opened_fds = []

        def tracking_open(*args, **kwargs):
            result = original_open(*args, **kwargs)
            opened_fds.append(result)
            return result

        with patch('builtins.open', side_effect=tracking_open):
            with patch('fcntl.flock', side_effect=OSError("Lock error")):
                try:
                    lock.acquire(timeout=0.1)
                except OSError:
                    pass

                # All opened FDs should be closed
                for fd in opened_fds:
                    assert fd.closed

    def test_release_exception_handling(self, temp_dir):
        """Test release handles exceptions gracefully."""
        lock_file = temp_dir / "test.lock"

        lock = FileLock(lock_file)
        lock.acquire(timeout=1.0)

        # Mock flock to raise exception
        with patch('fcntl.flock', side_effect=OSError("Release error")):
            # Should not raise, fd should still be set to None
            lock.release()

        assert lock.fd is None

    def test_release_without_acquire(self, temp_dir):
        """Test release when never acquired is safe."""
        lock_file = temp_dir / "test.lock"
        lock = FileLock(lock_file)

        # Should not raise
        lock.release()

    def test_lock_file_cleanup_error(self, temp_dir):
        """Test lock file cleanup errors are handled."""
        lock_file = temp_dir / "test.lock"

        lock = FileLock(lock_file)
        lock.acquire(timeout=1.0)

        # Mock unlink to raise exception
        with patch.object(Path, 'unlink', side_effect=OSError("Cleanup error")):
            # Should not raise
            lock.release()

        assert lock.fd is None

    def test_context_manager_acquire_fails(self, temp_dir):
        """Test context manager raises when acquire fails."""
        lock_file = temp_dir / "test.lock"

        # Create first lock to block second
        lock1 = FileLock(lock_file)
        lock1.acquire(timeout=1.0)

        lock2 = FileLock(lock_file)

        with patch.object(lock2, 'acquire', return_value=False):
            with pytest.raises(RuntimeError, match="Could not acquire lock"):
                with lock2:
                    pass

        lock1.release()

    def test_is_locked_true(self, temp_dir):
        """Test is_locked returns True when locked."""
        lock_file = temp_dir / "test.lock"

        lock1 = FileLock(lock_file)
        lock1.acquire(timeout=1.0)

        lock2 = FileLock(lock_file)

        assert lock2.is_locked() is True

        lock1.release()

    def test_is_locked_false(self, temp_dir):
        """Test is_locked returns False when not locked."""
        lock_file = temp_dir / "test.lock"

        lock = FileLock(lock_file)

        assert lock.is_locked() is False


class TestIsValidTaskId:
    """Tests for is_valid_task_id function."""

    def test_valid_task_id(self):
        """Test valid task ID format."""
        assert is_valid_task_id("task-20260207-123456-test-description") is True

    def test_no_task_prefix(self):
        """Test task ID without 'task-' prefix."""
        assert is_valid_task_id("20260207-123456-test") is False

    def test_missing_date_part(self):
        """Test task ID with missing date part."""
        assert is_valid_task_id("task-123456-test") is False

    def test_missing_time_part(self):
        """Test task ID with missing time part."""
        assert is_valid_task_id("task-20260207-test") is False

    def test_invalid_date_format(self):
        """Test task ID with invalid date format."""
        assert is_valid_task_id("task-2026020-123456-test") is False  # 7 digits
        assert is_valid_task_id("task-202602077-123456-test") is False  # 9 digits
        assert is_valid_task_id("task-2026a207-123456-test") is False  # Contains letter

    def test_invalid_time_format(self):
        """Test task ID with invalid time format."""
        assert is_valid_task_id("task-20260207-12345-test") is False  # 5 digits
        assert is_valid_task_id("task-20260207-1234567-test") is False  # 7 digits
        assert is_valid_task_id("task-20260207-12345a-test") is False  # Contains letter

    def test_minimal_valid_task_id(self):
        """Test minimal valid task ID (task-YYYYMMDD-HHMMSS)."""
        assert is_valid_task_id("task-20260207-123456") is True

    def test_empty_string(self):
        """Test empty string."""
        assert is_valid_task_id("") is False

    def test_only_prefix(self):
        """Test only 'task-' prefix."""
        assert is_valid_task_id("task-") is False
