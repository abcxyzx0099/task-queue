"""
Simplified data models for directory-based task queue.

No state file - directory structure is the source of truth.
"""

from pathlib import Path
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class TaskSourceDirectory(BaseModel):
    """
    Configuration for a Task Source Directory.

    A directory that contains task document files to be monitored.
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(description="Unique identifier for this source")
    path: str = Field(description="Path to directory containing task documents")
    description: str = Field(default="", description="Human-readable description")
    added_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="When this source was added"
    )


class QueueSettings(BaseModel):
    """Queue settings."""

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
    A task document discovered by scanning a Task Source Directory.

    Used internally by the scanner to report found tasks.
    """
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(description="Task identifier (filename without extension)")
    task_doc_file: Path = Field(description="Path to task document file")
    task_doc_dir_id: str = Field(description="ID of the Task Source Directory")
    file_hash: Optional[str] = Field(default=None, description="MD5 hash of file contents")
    file_size: int = Field(default=0, description="File size in bytes")
    discovered_at: str = Field(description="ISO timestamp of discovery")


class QueueConfig(BaseModel):
    """
    Queue configuration.

    Simplified - only configuration, no state.
    """

    model_config = ConfigDict(populate_by_name=True)

    version: str = "2.0"
    settings: QueueSettings = Field(default_factory=QueueSettings)

    # Single Project Workspace (where SDK executes)
    project_workspace: Optional[str] = Field(
        default=None,
        description="Path to project root (used as cwd for SDK execution)"
    )

    # Multiple Task Source Directories to scan
    task_source_directories: List[TaskSourceDirectory] = Field(
        default_factory=list,
        description="List of Task Source Directories to monitor"
    )

    # Metadata
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def get_task_source_directory(self, source_id: str) -> Optional[TaskSourceDirectory]:
        """Get Task Source Directory by ID."""
        for source_dir in self.task_source_directories:
            if source_dir.id == source_id:
                return source_dir
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

    def add_task_source_directory(
        self,
        path: str,
        id: str,
        description: str = ""
    ) -> TaskSourceDirectory:
        """Add a Task Source Directory to configuration."""
        # Check for duplicate ID
        if self.get_task_source_directory(id):
            raise ValueError(f"Task Source Directory ID '{id}' already exists")

        path_obj = Path(path).resolve()
        if not path_obj.exists():
            raise ValueError(f"Task Source Directory does not exist: {path_obj}")
        if not path_obj.is_dir():
            raise ValueError(f"Task Source Directory is not a directory: {path_obj}")

        source_dir = TaskSourceDirectory(
            id=id,
            path=str(path_obj),
            description=description
        )
        self.task_source_directories.append(source_dir)
        self.updated_at = datetime.now().isoformat()
        return source_dir

    def remove_task_source_directory(self, source_id: str) -> bool:
        """Remove a Task Source Directory by ID."""
        for i, source_dir in enumerate(self.task_source_directories):
            if source_dir.id == source_id:
                self.task_source_directories.pop(i)
                self.updated_at = datetime.now().isoformat()
                return True
        return False
