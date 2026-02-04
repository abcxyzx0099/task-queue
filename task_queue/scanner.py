"""
Task specification scanner.

Automatically discovers task specification files in configured directories.
"""

from pathlib import Path
from typing import List, Optional
from datetime import datetime

from task_queue.models import DiscoveredTask, SpecDirectory


class TaskScanner:
    """
    Scans directories for task specification files.

    Auto-discovers task-*.md files and tracks them by file hash
    for change detection.
    """

    def __init__(self, enable_file_hash: bool = True):
        """
        Initialize task scanner.

        Args:
            enable_file_hash: Whether to calculate file hashes for change detection
        """
        self.enable_file_hash = enable_file_hash

    def scan_spec_directory(self, spec_dir: SpecDirectory) -> List[DiscoveredTask]:
        """
        Scan a single spec directory for task specifications.

        Args:
            spec_dir: Spec directory configuration

        Returns:
            List of discovered tasks
        """
        discovered = []
        spec_path = Path(spec_dir.path)

        if not spec_path.exists():
            return discovered

        # Find all task-*.md files
        for filepath in self._find_task_files(spec_path):
            task = self._create_discovered_task(filepath, spec_dir.id)
            if task:
                discovered.append(task)

        return discovered

    def scan_spec_directories(self, spec_dirs: List[SpecDirectory]) -> List[DiscoveredTask]:
        """
        Scan multiple spec directories for task specifications.

        Args:
            spec_dirs: List of spec directory configurations

        Returns:
            List of discovered tasks from all directories
        """
        discovered = []

        for spec_dir in spec_dirs:
            discovered.extend(self.scan_spec_directory(spec_dir))

        return discovered

    def _find_task_files(self, spec_dir: Path) -> List[Path]:
        """
        Find all task specification files in directory.

        Args:
            spec_dir: Directory to scan

        Returns:
            List of task file paths
        """
        task_files = []

        for filepath in spec_dir.glob("task-*.md"):
            if filepath.is_file():
                task_files.append(filepath)

        return task_files

    def _create_discovered_task(
        self,
        filepath: Path,
        spec_dir_id: str
    ) -> Optional[DiscoveredTask]:
        """
        Create a DiscoveredTask from a file path.

        Args:
            filepath: Path to task specification file
            spec_dir_id: ID of the spec directory

        Returns:
            DiscoveredTask or None if invalid
        """
        # Extract task_id from filename
        task_id = filepath.stem  # Removes .md suffix

        # Validate task_id format (task-YYYYMMDD-HHMMSS-description)
        if not self._is_valid_task_id(task_id):
            return None

        # Get file info
        file_size = 0
        file_hash = None

        try:
            file_size = filepath.stat().st_size

            if self.enable_file_hash and file_size > 0:
                file_hash = self._calculate_hash(filepath)

        except OSError:
            return None

        return DiscoveredTask(
            task_id=task_id,
            spec_file=filepath,
            spec_dir_id=spec_dir_id,
            file_hash=file_hash,
            file_size=file_size,
            discovered_at=datetime.now().isoformat()
        )

    def _is_valid_task_id(self, task_id: str) -> bool:
        """
        Validate task ID format.

        Expected format: task-YYYYMMDD-HHMMSS-description

        Args:
            task_id: Task ID to validate

        Returns:
            True if valid format
        """
        if not task_id.startswith("task-"):
            return False

        # Remove "task-" prefix
        rest = task_id[5:]

        # Check for timestamp pattern (YYYYMMDD-HHMMSS)
        parts = rest.split("-", 2)

        if len(parts) < 2:
            return False

        date_part = parts[0]
        time_part = parts[1]

        # Validate date (8 digits)
        if len(date_part) != 8 or not date_part.isdigit():
            return False

        # Validate time (6 digits)
        if len(time_part) != 6 or not time_part.isdigit():
            return False

        return True

    def _calculate_hash(self, filepath: Path) -> str:
        """
        Calculate MD5 hash of file.

        Args:
            filepath: File to hash

        Returns:
            Hexadecimal hash string
        """
        import hashlib

        hasher = hashlib.md5()

        try:
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hasher.update(chunk)

            return hasher.hexdigest()

        except OSError:
            return ""

    def is_file_modified(
        self,
        filepath: Path,
        known_hash: Optional[str]
    ) -> bool:
        """
        Check if file has been modified since last scan.

        Args:
            filepath: File to check
            known_hash: Previously known hash (None means unknown)

        Returns:
            True if file is modified or hash is unknown
        """
        if not self.enable_file_hash:
            return False

        if known_hash is None:
            return True

        current_hash = self._calculate_hash(filepath)

        return current_hash != known_hash
