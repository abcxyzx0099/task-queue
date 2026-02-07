"""
Data models for task-monitor.

No state file - directory structure is the source of truth.
"""

from pathlib import Path
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class Queue(BaseModel):
    """
    Configuration for a Task Queue.

    A queue directory that contains pending/, completed/, failed/, results/ subdirectories.
    The monitor watches the pending/ subdirectory for new tasks.
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(description="Unique identifier for this queue (e.g., 'ad-hoc', 'planned')")
    path: str = Field(description="Path to the queue directory (contains pending/, completed/, failed/, results/)")
    description: str = Field(default="", description="Human-readable description")
    added_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="When this queue was added"
    )


class MonitorSettings(BaseModel):
    """Monitor settings."""

    watch_enabled: bool = Field(default=True, description="Enable watchdog file monitoring")
    watch_debounce_ms: int = Field(default=500, description="Debounce delay for file events (ms)")
    watch_patterns: List[str] = Field(
        default=["task-*.md"],
        description="File patterns to watch"
    )
    watch_recursive: bool = Field(default=False, description="Watch subdirectories")
    max_attempts: int = Field(default=3, description="Max execution attempts per task")
    enable_file_hash: bool = Field(default=True, description="Track file hashes for change detection")


class DiscoveredTask(BaseModel):
    """
    A task document discovered by scanning a Queue.

    Used internally by the scanner to report found tasks.
    """
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(description="Task identifier (filename without extension)")
    task_doc_file: Path = Field(description="Path to task document file")
    queue_id: str = Field(description="ID of the Queue where this task was found")
    file_hash: Optional[str] = Field(default=None, description="MD5 hash of file contents")
    file_size: int = Field(default=0, description="File size in bytes")
    discovered_at: str = Field(description="ISO timestamp of discovery")


class MonitorConfig(BaseModel):
    """
    Task Monitor configuration.

    Simplified - only configuration, no state.
    """

    model_config = ConfigDict(populate_by_name=True)

    version: str = "2.0"
    settings: MonitorSettings = Field(default_factory=MonitorSettings)

    # Single Project Workspace (where SDK executes)
    project_workspace: Optional[str] = Field(
        default=None,
        description="Path to project root (used as cwd for SDK execution)"
    )

    # Multiple Queues to monitor
    queues: List[Queue] = Field(
        default_factory=list,
        description="List of Queues to monitor"
    )

    # Metadata
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def get_queue(self, queue_id: str) -> Optional[Queue]:
        """Get Queue by ID."""
        for queue in self.queues:
            if queue.id == queue_id:
                return queue
        return None

    def set_project_workspace(self, path: str) -> None:
        """Set the Project Workspace path."""
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            raise ValueError(f"Project Workspace does not exist: {path_obj}")
        if not path_obj.is_dir():
            raise ValueError(f"Project Workspace is not a directory: {path_obj}")
        self.project_workspace = str(path_obj)
        self.updated_at = datetime.now().isoformat()

    def add_queue(
        self,
        path: str,
        id: str,
        description: str = ""
    ) -> Queue:
        """Add a Queue to configuration."""
        # Check for duplicate ID
        if self.get_queue(id):
            raise ValueError(f"Queue ID '{id}' already exists")

        path_obj = Path(path).resolve()
        if not path_obj.exists():
            raise ValueError(f"Queue directory does not exist: {path_obj}")
        if not path_obj.is_dir():
            raise ValueError(f"Queue path is not a directory: {path_obj}")

        queue = Queue(
            id=id,
            path=str(path_obj),
            description=description
        )
        self.queues.append(queue)
        self.updated_at = datetime.now().isoformat()
        return queue

    def remove_queue(self, queue_id: str) -> bool:
        """Remove a Queue by ID."""
        for i, queue in enumerate(self.queues):
            if queue.id == queue_id:
                self.queues.pop(i)
                self.updated_at = datetime.now().isoformat()
                return True
        return False
