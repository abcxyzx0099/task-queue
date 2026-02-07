"""
Task document scanner.

Automatically discovers task document files in configured directories.
"""

from pathlib import Path
from typing import List, Optional
from datetime import datetime

from task_queue.models import DiscoveredTask, Queue
from task_queue.file_utils import is_valid_task_id


class TaskScanner:
    """
    Scans Queues for Task Document files.

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

    def scan_queue(self, queue: Queue) -> List[DiscoveredTask]:
        """
        Scan a single Queue for Task Documents.

        Args:
            queue: Queue configuration

        Returns:
            List of discovered tasks (sorted by filename = chronological order)
        """
        discovered = []
        queue_path = Path(queue.path) / "pending"

        if not queue_path.exists():
            return discovered

        # Find all task-*.md files
        for filepath in self._find_task_files(queue_path):
            task = self._create_discovered_task(filepath, queue.id)
            if task:
                discovered.append(task)

        # Sort by filename (which contains timestamp: task-YYYYMMDD-HHMMSS-*)
        # This ensures chronological order regardless of filesystem glob order
        discovered.sort(key=lambda t: t.task_doc_file.name)

        return discovered

    def scan_queues(self, queues: List[Queue]) -> List[DiscoveredTask]:
        """
        Scan multiple Queues for Task Documents.

        Args:
            queues: List of Queue configurations

        Returns:
            List of discovered tasks from all queues (sorted chronologically)
        """
        discovered = []

        for queue in queues:
            discovered.extend(self.scan_queue(queue))

        # Sort all tasks by filename (chronological order)
        discovered.sort(key=lambda t: t.task_doc_file.name)

        return discovered

    def _find_task_files(self, source_dir: Path) -> List[Path]:
        """
        Find all Task Document files in Task Source Directory.

        Args:
            source_dir: Task Source Directory to scan

        Returns:
            List of task file paths
        """
        task_files = []

        for filepath in source_dir.glob("task-*.md"):
            if filepath.is_file():
                task_files.append(filepath)

        return task_files

    def _create_discovered_task(
        self,
        filepath: Path,
        queue_id: str
    ) -> Optional[DiscoveredTask]:
        """
        Create a DiscoveredTask from a file path.

        Args:
            filepath: Path to Task Document file
            queue_id: ID of the Queue

        Returns:
            DiscoveredTask or None if invalid
        """
        # Extract task_id from filename
        task_id = filepath.stem  # Removes .md suffix

        # Validate task_id format (task-YYYYMMDD-HHMMSS-description)
        if not is_valid_task_id(task_id):
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
            task_doc_file=filepath,
            queue_id=queue_id,
            file_hash=file_hash,
            file_size=file_size,
            discovered_at=datetime.now().isoformat()
        )

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

    def get_file_modification_time(self, filepath: Path) -> Optional[str]:
        """
        Get file modification time as ISO format string.

        Args:
            filepath: File to check

        Returns:
            ISO format modification time or None if error
        """
        try:
            mtime = filepath.stat().st_mtime
            return datetime.fromtimestamp(mtime).isoformat()
        except OSError:
            return None

    def calculate_hash(self, filepath: Path) -> str:
        """
        Public method to calculate MD5 hash of file.

        Args:
            filepath: File to hash

        Returns:
            Hexadecimal hash string
        """
        return self._calculate_hash(filepath)
