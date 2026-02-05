"""
Source Coordinator for round-robin execution across Task Source Directories.

Ensures fair scheduling and sequential execution within each source.
"""

import logging
from typing import Optional, List, Dict, Set
from datetime import datetime
from collections import deque

from task_queue.models import (
    QueueState,
    SourceState,
    TaskStatus,
    CoordinatorState
)


logger = logging.getLogger(__name__)


class SourceCoordinator:
    """
    Coordinates round-robin execution across Task Source Directories.

    Rules:
    - Tasks within same source execute sequentially (one at a time)
    - Tasks from different sources can execute in parallel
    - Fair scheduling: round-robin through sources with pending tasks
    """

    def __init__(self, state: QueueState):
        """
        Initialize source coordinator.

        Args:
            state: Queue state with per-source queues
        """
        self.state = state
        self.coordinator_state = state.coordinator

        # Initialize round-robin queue if not exists
        if not self.coordinator_state.source_order:
            self._rebuild_source_order()

    def _rebuild_source_order(self) -> None:
        """
        Rebuild the round-robin source order from available sources.

        Creates a stable ordering of all configured source IDs.
        """
        source_ids = list(self.state.sources.keys())

        # Keep existing order where possible
        new_order = [
            source_id
            for source_id in self.coordinator_state.source_order
            if source_id in source_ids
        ]

        # Add new sources at the end
        for source_id in source_ids:
            if source_id not in new_order:
                new_order.append(source_id)

        self.coordinator_state.source_order = new_order
        self.coordinator_state.updated_at = datetime.now().isoformat()

        logger.debug(f"Source order rebuilt: {new_order}")

    def add_source(self, source_id: str) -> None:
        """
        Add a new source to the coordinator.

        Args:
            source_id: Source ID to add
        """
        if source_id not in self.coordinator_state.source_order:
            self.coordinator_state.source_order.append(source_id)
            self.coordinator_state.updated_at = datetime.now().isoformat()

            logger.info(
                f"Source '{source_id}' added to coordinator. "
                f"Order: {self.coordinator_state.source_order}"
            )

    def remove_source(self, source_id: str) -> None:
        """
        Remove a source from the coordinator.

        Args:
            source_id: Source ID to remove
        """
        if source_id in self.coordinator_state.source_order:
            self.coordinator_state.source_order.remove(source_id)
            self.coordinator_state.updated_at = datetime.now().isoformat()

            # Reset current source if it was the removed one
            if self.coordinator_state.current_source == source_id:
                self.coordinator_state.current_source = None
                self.coordinator_state.last_switch = None

            logger.info(
                f"Source '{source_id}' removed from coordinator. "
                f"Order: {self.coordinator_state.source_order}"
            )

    def get_next_source(self) -> Optional[str]:
        """
        Get the next source with pending tasks using round-robin.

        Args:
            Next source ID with pending tasks, or None if no pending tasks

        Returns:
            Source ID or None
        """
        # Get sources with pending tasks
        pending_sources = self._get_sources_with_pending_tasks()

        if not pending_sources:
            # No pending tasks anywhere
            return None

        # Get current position
        current = self.coordinator_state.current_source

        # Find next source in round-robin order
        order = self.coordinator_state.source_order

        if current is None:
            # Start from first available source
            next_source = pending_sources[0]
        else:
            # Find next source after current
            current_index = order.index(current) if current in order else -1

            # Search for next source with pending tasks
            next_source = None

            # Check sources after current
            for i in range(current_index + 1, len(order)):
                source_id = order[i]
                if source_id in pending_sources:
                    next_source = source_id
                    break

            # Wrap around to beginning if needed
            if next_source is None:
                for source_id in order:
                    if source_id in pending_sources:
                        next_source = source_id
                        break

        return next_source

    def switch_to_source(self, source_id: str) -> None:
        """
        Switch coordinator to execute from a specific source.

        Args:
            source_id: Source ID to switch to
        """
        old_source = self.coordinator_state.current_source

        self.coordinator_state.current_source = source_id
        self.coordinator_state.last_switch = datetime.now().isoformat()
        self.coordinator_state.updated_at = datetime.now().isoformat()

        if old_source != source_id:
            logger.info(
                f"Coordinator switched from '{old_source}' to '{source_id}'"
            )

    def get_current_source(self) -> Optional[str]:
        """
        Get the currently executing source.

        Returns:
            Current source ID or None
        """
        return self.coordinator_state.current_source

    def can_execute_from_source(self, source_id: str) -> bool:
        """
        Check if tasks from a source can currently execute.

        A source can execute if:
        - It has pending tasks
        - No source is currently active, OR it's the currently active source

        Args:
            source_id: Source ID to check

        Returns:
            True if tasks from this source can execute
        """
        source_state = self.state.sources.get(source_id)

        if not source_state:
            return False

        # Check if source has pending tasks
        if source_state.get_pending_count() == 0:
            return False

        # Check if another source is currently active
        current = self.coordinator_state.current_source

        if current is None:
            # No source active, this one can start
            return True

        if current == source_id:
            # This is the active source
            return True

        # Another source is active, this one must wait
        return False

    def get_next_pending_task(self) -> Optional[tuple]:
        """
        Get the next pending task using round-robin source selection.

        Returns:
            Tuple of (task, source_id) or None if no pending tasks
        """
        # Get next source
        source_id = self.get_next_source()

        if source_id is None:
            return None

        # Get source state
        source_state = self.state.sources.get(source_id)

        if not source_state:
            return None

        # Get next pending task from this source
        task = source_state.get_next_pending()

        if task:
            # Switch to this source
            self.switch_to_source(source_id)
            return (task, source_id)

        return None

    def mark_source_complete(self, source_id: str) -> None:
        """
        Mark a source as complete (no more pending tasks).

        Switches coordinator to next source if available.

        Args:
            source_id: Source ID that completed
        """
        source_state = self.state.sources.get(source_id)

        if source_state and source_state.get_pending_count() == 0:
            # This source has no more pending tasks
            # Try to switch to next source
            next_source = self.get_next_source()

            if next_source:
                self.switch_to_source(next_source)
            else:
                # No more pending tasks anywhere
                self.coordinator_state.current_source = None
                self.coordinator_state.last_switch = None

            logger.info(
                f"Source '{source_id}' complete. "
                f"Next: {self.coordinator_state.current_source}"
            )

    def _get_sources_with_pending_tasks(self) -> List[str]:
        """
        Get list of sources that have pending tasks.

        Returns:
            List of source IDs with pending tasks
        """
        pending = []

        for source_id, source_state in self.state.sources.items():
            if source_state.get_pending_count() > 0:
                pending.append(source_id)

        return pending

    def get_source_status(self) -> Dict[str, dict]:
        """
        Get status of all sources from coordinator perspective.

        Returns:
            Dict mapping source_id to status dict
        """
        status = {}

        for source_id in self.coordinator_state.source_order:
            source_state = self.state.sources.get(source_id)

            if not source_state:
                continue

            is_current = self.coordinator_state.current_source == source_id

            status[source_id] = {
                "is_current": is_current,
                "pending": source_state.get_pending_count(),
                "running": source_state.get_running_count(),
                "completed": source_state.get_completed_count(),
                "failed": source_state.get_failed_count(),
            }

        return status

    def get_statistics(self) -> Dict:
        """
        Get coordinator statistics.

        Returns:
            Dict with coordinator stats
        """
        pending_sources = self._get_sources_with_pending_tasks()

        return {
            "current_source": self.coordinator_state.current_source,
            "last_switch": self.coordinator_state.last_switch,
            "total_sources": len(self.coordinator_state.source_order),
            "sources_with_pending": len(pending_sources),
            "source_order": self.coordinator_state.source_order,
        }
