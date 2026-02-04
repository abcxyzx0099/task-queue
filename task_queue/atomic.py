"""
Atomic file operations and file locking utilities.

Provides safe file write operations and inter-process locking
for concurrent task monitoring.
"""

import os
import fcntl
import tempfile
import atexit
from pathlib import Path
from typing import Any, Optional
import json


class AtomicFileWriter:
    """
    Atomic file writer using temp file + atomic replace.

    Ensures that state files are never corrupted by partial writes.
    Writes to a temporary file first, then atomically replaces
    the target file using os.replace().
    """

    @staticmethod
    def write_json(filepath: Path, data: Any, indent: int = 2) -> None:
        """
        Atomically write JSON data to a file.

        Args:
            filepath: Target file path
            data: Data to serialize as JSON
            indent: JSON indentation level

        Raises:
            Exception: If write fails (temp file is cleaned up)
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        temp_path = None
        try:
            # Create temporary file in same directory for atomic replace
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=filepath.parent,
                prefix=f".{filepath.name}.",
                suffix='.tmp',
                delete=False
            ) as tmp_file:
                temp_path = Path(tmp_file.name)
                json.dump(data, tmp_file, indent=indent, default=str)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())  # Force write to disk

            # Atomic replace (POSIX guarantees this is atomic)
            os.replace(temp_path, filepath)

        except Exception as e:
            # Clean up temp file on error
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise e

    @staticmethod
    def read_json(filepath: Path, default: Any = None) -> Any:
        """
        Read JSON file with safe defaults.

        Args:
            filepath: File to read
            default: Default value if file doesn't exist or is invalid

        Returns:
            Parsed JSON data or default value
        """
        filepath = Path(filepath)

        if not filepath.exists():
            return default

        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return default


class FileLock:
    """
    File-based lock using fcntl for inter-process synchronization.

    Provides exclusive locking to prevent multiple processes from
    accessing the same resource concurrently.

    Usage:
        lock = FileLock("/path/to/lockfile")
        if lock.acquire(timeout=10):
            try:
                # Critical section
                ...
            finally:
                lock.release()
    """

    def __init__(self, lockfile: Path):
        """
        Initialize file lock.

        Args:
            lockfile: Path to lock file (will be created if needed)
        """
        self.lockfile = Path(lockfile)
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        self.fd: Optional[Any] = None

    def acquire(self, timeout: float = 10.0) -> bool:
        """
        Acquire exclusive lock with timeout.

        Args:
            timeout: Maximum seconds to wait for lock

        Returns:
            True if lock acquired, False if timeout
        """
        import time

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Open lock file
                self.fd = open(self.lockfile, 'w')

                # Try to acquire exclusive lock (non-blocking)
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Write process info for debugging
                self.fd.write(f"{os.getpid()}:{time.time()}\n")
                self.fd.flush()

                # Ensure lock is released on exit
                atexit.register(self.release)

                return True

            except (IOError, BlockingIOError):
                # Lock held by another process
                if self.fd:
                    self.fd.close()
                    self.fd = None
                time.sleep(0.1)

            except Exception as e:
                if self.fd:
                    self.fd.close()
                    self.fd = None
                raise e

        return False

    def release(self) -> None:
        """Release the lock."""
        if self.fd:
            try:
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
                self.fd.close()
            except Exception:
                pass
            finally:
                self.fd = None

        # Clean up lock file
        if self.lockfile.exists():
            try:
                self.lockfile.unlink()
            except Exception:
                pass

    def __enter__(self):
        """Context manager entry."""
        if not self.acquire():
            raise RuntimeError(f"Could not acquire lock: {self.lockfile}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False

    def is_locked(self) -> bool:
        """
        Check if lock is currently held by another process.

        Returns:
            True if locked by another process
        """
        try:
            test_fd = open(self.lockfile, 'w')
            fcntl.flock(test_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(test_fd.fileno(), fcntl.LOCK_UN)
            test_fd.close()
            return False
        except (IOError, BlockingIOError):
            return True
