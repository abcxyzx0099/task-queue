"""
Watchdog-based file system monitoring for Task Source Directories.

Provides event-driven task loading when Task Document files are created or modified.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Set, Callable, TYPE_CHECKING
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent, FileCreatedEvent, FileModifiedEvent

from task_queue.models import DiscoveredTask
from task_queue.file_utils import is_valid_task_id


logger = logging.getLogger(__name__)


class DebounceTracker:
    """
    Tracks file events with debouncing to prevent duplicate processing.

    Multiple events within the debounce window are coalesced into a single event.
    """

    def __init__(self, debounce_ms: int = 500):
        """
        Initialize debounce tracker.

        Args:
            debounce_ms: Debounce delay in milliseconds
        """
        self.debounce_seconds = debounce_ms / 1000.0
        self._pending_events: Dict[str, float] = {}

    def should_process(self, file_path: str) -> bool:
        """
        Check if file event should be processed (debounced).

        Args:
            file_path: Path to file that triggered event

        Returns:
            True if event should be processed, False if debounced
        """
        now = time.time()

        # Check if we have a recent pending event for this file
        last_event_time = self._pending_events.get(file_path, 0)

        if now - last_event_time < self.debounce_seconds:
            # Too soon, debounce this event
            return False

        # Record this event
        self._pending_events[file_path] = now
        return True

    def cleanup_old_events(self, max_age_seconds: float = 60.0) -> None:
        """
        Remove old event timestamps to prevent memory growth.

        Args:
            max_age_seconds: Maximum age to keep events
        """
        now = time.time()
        cutoff = now - max_age_seconds

        self._pending_events = {
            path: ts
            for path, ts in self._pending_events.items()
            if ts > cutoff
        }


class TaskDocumentWatcher(FileSystemEventHandler):
    """
    Watches Task Source Directories for Task Document file changes.

    Automatically loads new Task Documents when files are created or modified.
    """

    def __init__(
        self,
        source_dir: TaskSourceDirectory,
        load_callback: Callable[[str, str], None],
        debounce_ms: int = 500,
        pattern: str = "task-*.md"
    ):
        """
        Initialize Task Document watcher.

        Args:
            source_dir: Task Source Directory configuration
            load_callback: Function to call when task is discovered.
                          Takes (task_doc_file, source_id) as arguments
            debounce_ms: Debounce delay in milliseconds
            pattern: File pattern to match (default: task-*.md)
        """
        super().__init__()

        self.source_dir = source_dir
        self.load_callback = load_callback
        self.pattern = pattern

        # Debouncing
        self.debounce = DebounceTracker(debounce_ms)

        # Track files we've already processed
        self._processed_files: Set[str] = set()

        # Observer
        self._observer: Optional[Observer] = None

        logger.debug(
            f"TaskDocumentWatcher initialized for {source_dir.id} at {source_dir.path}"
        )

    def on_created(self, event: FileCreatedEvent) -> None:
        """
        Handle file creation event.

        Args:
            event: File created event
        """
        if event.is_directory:
            return

        self._handle_file_event(event.src_path, "created")

    def on_modified(self, event: FileModifiedEvent) -> None:
        """
        Handle file modification event.

        Args:
            event: File modified event
        """
        if event.is_directory:
            return

        self._handle_file_event(event.src_path, "modified")

    def _handle_file_event(self, file_path: str, event_type: str) -> None:
        """
        Process a file event (created or modified).

        Args:
            file_path: Path to file that triggered event
            event_type: Type of event ("created" or "modified")
        """
        # Check if file matches pattern
        filepath = Path(file_path)
        if not filepath.match(self.pattern):
            return

        # Apply debouncing
        if not self.debounce.should_process(file_path):
            logger.debug(f"Debounced {event_type} event for: {filepath.name}")
            return

        # Validate task ID format
        task_id = filepath.stem
        if not is_valid_task_id(task_id):
            logger.debug(f"Ignoring file with invalid task ID format: {filepath.name}")
            return

        logger.debug(f"Task document {event_type}: {filepath.name}")

        # Trigger load callback
        try:
            self.load_callback(file_path, self.source_dir.id)
        except Exception as e:
            logger.error(
                f"Error in load callback for {filepath.name}: {e}",
                exc_info=True
            )

        # Periodic cleanup
        self.debounce.cleanup_old_events()

    def start(self) -> None:
        """
        Start watching the Task Source Directory.

        Creates and starts a watchdog observer for the configured path.
        """
        if self._observer is not None:
            logger.warning(
                f"Observer already running for source '{self.source_dir.id}'"
            )
            return

        # Ensure directory exists
        watch_path = Path(self.source_dir.path)
        if not watch_path.exists():
            logger.error(
                f"Task Source Directory does not exist: {watch_path}"
            )
            return

        # Create observer
        self._observer = Observer()
        self._observer.schedule(
            event_handler=self,
            path=str(watch_path),
            recursive=False
        )

        # Start watching
        self._observer.start()
        logger.info(f"Watching '{self.source_dir.id}': {watch_path}")

    def stop(self) -> None:
        """
        Stop watching the Task Source Directory.

        Stops and cleans up the watchdog observer.
        """
        if self._observer is None:
            return

        logger.debug(f"Stopped watching '{self.source_dir.id}'")

        try:
            self._observer.stop()
            self._observer.join(timeout=5.0)
        except Exception as e:
            logger.error(
                f"Error stopping observer for '{self.source_dir.id}': {e}",
                exc_info=True
            )
        finally:
            self._observer = None

    def is_running(self) -> bool:
        """
        Check if the watcher is currently running.

        Returns:
            True if observer is running
        """
        return self._observer is not None and self._observer.is_alive()


class WatchdogManager:
    """
    Manages multiple TaskDocumentWatcher instances.

    One watcher per Task Source Directory for parallel monitoring.
    """

    def __init__(self, load_callback: Callable[[str, str], None]):
        """
        Initialize watchdog manager.

        Args:
            load_callback: Function to call when task is discovered.
                          Takes (task_doc_file, source_id) as arguments
        """
        self.load_callback = load_callback
        self._watchers: Dict[str, TaskDocumentWatcher] = {}

    def add_source(
        self,
        source_dir: TaskSourceDirectory,
        debounce_ms: int = 500,
        pattern: str = "task-*.md"
    ) -> None:
        """
        Add a Task Source Directory to watch.

        Args:
            source_dir: Task Source Directory configuration
            debounce_ms: Debounce delay in milliseconds
            pattern: File pattern to watch
        """
        if source_dir.id in self._watchers:
            logger.warning(
                f"Task Source Directory '{source_dir.id}' is already being watched"
            )
            return

        watcher = TaskDocumentWatcher(
            source_dir=source_dir,
            load_callback=self.load_callback,
            debounce_ms=debounce_ms,
            pattern=pattern
        )

        self._watchers[source_dir.id] = watcher
        watcher.start()

    def remove_source(self, source_id: str) -> None:
        """
        Remove a Task Source Directory from watching.

        Args:
            source_id: Source ID to stop watching
        """
        watcher = self._watchers.pop(source_id, None)

        if watcher:
            watcher.stop()

    def start_all(self) -> None:
        """Start all registered watchers."""
        for watcher in self._watchers.values():
            if not watcher.is_running():
                watcher.start()

    def stop_all(self) -> None:
        """Stop all registered watchers."""
        for source_id in list(self._watchers.keys()):
            self.remove_source(source_id)

    def is_watching(self, source_id: str) -> bool:
        """
        Check if a source is currently being watched.

        Args:
            source_id: Source ID to check

        Returns:
            True if source is being watched
        """
        watcher = self._watchers.get(source_id)
        return watcher is not None and watcher.is_running()

    def get_watched_sources(self) -> Set[str]:
        """
        Get list of sources currently being watched.

        Returns:
            Set of source IDs
        """
        return {
            source_id
            for source_id, watcher in self._watchers.items()
            if watcher.is_running()
        }


# Import at end to avoid circular dependency
if TYPE_CHECKING:
    from task_queue.models import TaskSourceDirectory
