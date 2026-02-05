"""
Data models for task monitoring system.

Defines Pydantic models for tasks, queues, and execution results.
"""

from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, field_validator, ConfigDict


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskSource(str, Enum):
    """How the task was discovered."""
    LOAD = "load"           # Added via load command
    MANUAL = "manual"       # Manually added
    API = "api"             # Added via API
    WATCHDOG = "watchdog"   # Auto-loaded by watchdog
    RELOAD = "reload"       # Manual reload command


class Task(BaseModel):
    """
    A task in the queue.

    Represents a single task document waiting to be executed.
    """

    task_id: str = Field(..., description="Unique task identifier (task-YYYYMMDD-HHMMSS-description)")
    task_doc_file: str = Field(..., description="Path to task document file")
    task_doc_dir_id: str = Field(..., description="ID of Task Source Directory where task was found")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current task status")
    source: TaskSource = Field(default=TaskSource.LOAD, description="How task was discovered")

    # Timestamps
    added_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="When task was added")
    started_at: Optional[str] = Field(default=None, description="When task started execution")
    completed_at: Optional[str] = Field(default=None, description="When task completed")

    # Execution tracking
    attempts: int = Field(default=0, description="Number of execution attempts")
    error: Optional[str] = Field(default=None, description="Error message if failed")

    # Optional file tracking
    file_hash: Optional[str] = Field(default=None, description="MD5 hash for change detection")
    file_size: int = Field(default=0, description="File size in bytes")
    last_modified: Optional[str] = Field(default=None, description="Task Document file modification time")


class TaskResult(BaseModel):
    """
    Result of task execution.

    Captures the outcome of executing a task via Claude Agent SDK.
    """

    task_id: str
    task_doc_file: str
    task_doc_dir_id: str = ""
    status: TaskStatus

    # Execution details
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: float
    cost_usd: float = 0.0

    # Output
    stdout: Optional[str] = None
    stderr: Optional[str] = None

    # Worker report location
    worker_report_path: Optional[str] = None

    # Metadata
    attempts: int = 1
    error: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


class SourceStatistics(BaseModel):
    """Statistics for a single Task Source Directory."""

    total_queued: int = 0
    total_completed: int = 0
    total_failed: int = 0
    last_processed_at: Optional[str] = None
    last_loaded_at: Optional[str] = None


class SourceProcessingState(BaseModel):
    """Current processing state for a single Task Source Directory."""

    is_processing: bool = False
    current_task: Optional[str] = None
    process_id: Optional[int] = None
    started_at: Optional[str] = None
    hostname: Optional[str] = None


class SourceState(BaseModel):
    """
    State for a single Task Source Directory.

    Contains queue, processing state, and statistics for one source.
    """

    id: str = Field(..., description="Source ID (from config)")
    path: str = Field(..., description="Path to Task Source Directory")
    queue: List[Task] = Field(default_factory=list, description="Tasks for this source")
    processing: SourceProcessingState = Field(default_factory=SourceProcessingState)
    statistics: SourceStatistics = Field(default_factory=SourceStatistics)

    # Metadata
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def get_pending_count(self) -> int:
        """Get count of pending tasks for this source."""
        return len([t for t in self.queue if t.status == TaskStatus.PENDING])

    def get_running_count(self) -> int:
        """Get count of running tasks for this source."""
        return len([t for t in self.queue if t.status == TaskStatus.RUNNING])

    def get_completed_count(self) -> int:
        """Get count of completed tasks for this source."""
        return len([t for t in self.queue if t.status == TaskStatus.COMPLETED])

    def get_failed_count(self) -> int:
        """Get count of failed tasks for this source."""
        return len([t for t in self.queue if t.status == TaskStatus.FAILED])

    def get_next_pending(self) -> Optional[Task]:
        """Get next pending task from this source (FIFO order)."""
        for task in self.queue:
            if task.status == TaskStatus.PENDING:
                return task
        return None


class CoordinatorState(BaseModel):
    """
    State for the Source Coordinator.

    Manages round-robin execution across Task Source Directories.
    """

    current_source: Optional[str] = Field(default=None, description="Which source is currently executing")
    last_switch: Optional[str] = Field(default=None, description="When we switched to current source")
    source_order: List[str] = Field(default_factory=list, description="Round-robin order of sources")

    # Metadata
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class GlobalStatistics(BaseModel):
    """Global statistics across all sources."""

    total_sources: int = 0
    total_queued: int = 0
    total_completed: int = 0
    total_failed: int = 0
    last_processed_at: Optional[str] = None


class QueueState(BaseModel):
    """
    State of the task queue - Per-Source Architecture.

    Persisted to disk for recovery across restarts.
    """

    version: str = "2.0"

    # Per-source states (key = source_id)
    sources: Dict[str, SourceState] = Field(default_factory=dict)

    # Coordinator state
    coordinator: CoordinatorState = Field(default_factory=CoordinatorState)

    # Global statistics
    global_statistics: GlobalStatistics = Field(default_factory=GlobalStatistics)

    # Metadata
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def get_source_ids(self) -> List[str]:
        """Get list of source IDs."""
        return list(self.sources.keys())

    def get_source_state(self, source_id: str) -> Optional[SourceState]:
        """Get state for a specific source."""
        return self.sources.get(source_id)

    def get_total_pending_count(self) -> int:
        """Get total pending count across all sources."""
        return sum(state.get_pending_count() for state in self.sources.values())

    def get_total_running_count(self) -> int:
        """Get total running count across all sources."""
        return sum(state.get_running_count() for state in self.sources.values())

    def get_total_completed_count(self) -> int:
        """Get total completed count across all sources."""
        return sum(state.get_completed_count() for state in self.sources.values())

    def get_total_failed_count(self) -> int:
        """Get total failed count across all sources."""
        return sum(state.get_failed_count() for state in self.sources.values())


class TaskSourceDirectory(BaseModel):
    """
    Configuration for a monitored Task Source Directory.

    Defines where to scan for task document files.
    """

    id: str = Field(..., description="Unique identifier for this Task Source Directory")
    path: str = Field(..., description="Path to Task Source Directory")
    description: str = Field(default="", description="Description of this Task Source Directory")

    # Metadata
    added_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @field_validator('path')
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate and resolve path."""
        path = Path(v).resolve()
        if not path.exists():
            raise ValueError(f"Task Source Directory does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        return str(path)


class QueueSettings(BaseModel):
    """Global monitor settings."""

    # Watchdog settings
    watch_enabled: bool = Field(default=True, description="Enable watchdog for file system events")
    watch_debounce_ms: int = Field(default=500, description="Debounce delay in milliseconds for file events")
    watch_patterns: List[str] = Field(default_factory=lambda: ["task-*.md"], description="File patterns to watch")
    watch_recursive: bool = Field(default=False, description="Watch subdirectories")

    # Task pattern (for manual scanning)
    task_pattern: str = Field(default="task-*.md", description="Pattern for task doc files")

    # Retry settings
    max_attempts: int = Field(default=3, description="Max execution attempts per task")

    # File tracking
    enable_file_hash: bool = Field(default=True, description="Track file hashes for change detection")


class QueueConfig(BaseModel):
    """
    Complete monitor configuration.

    Single Project Workspace + Multiple Task Source Directories.
    """

    version: str = "1.0"
    settings: QueueSettings = Field(default_factory=QueueSettings)

    # Single Project Workspace (where SDK executes)
    project_workspace: Optional[str] = Field(
        default=None,
        description="Path to project root (used as cwd for SDK execution)"
    )

    # Multiple Task Source Directories to scan
    task_source_directories: List[TaskSourceDirectory] = Field(default_factory=list)

    # Metadata
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

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
            raise ValueError(f"Task Source Directory ID already exists: {id}")

        source_dir = TaskSourceDirectory(
            id=id,
            path=path,
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

    def list_task_source_directories(self) -> List[TaskSourceDirectory]:
        """List configured Task Source Directories."""
        return self.task_source_directories


class DiscoveredTask(BaseModel):
    """
    A task discovered by the scanner.

    Represents a task document file found during scanning.
    """

    task_id: str
    task_doc_file: Path
    task_doc_dir_id: str
    file_hash: Optional[str] = None
    file_size: int = 0
    discovered_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class SystemStatus(BaseModel):
    """Overall system status."""

    running: bool = False
    uptime_seconds: float = 0.0
    load_count: int = 0
    last_load_at: Optional[str] = None

    # Project info
    project_workspace: Optional[str] = None

    # Task Source Directories
    total_task_source_dirs: int = 0
    active_task_source_dirs: int = 0

    # Queue stats
    total_pending: int = 0
    total_running: int = 0
    total_completed: int = 0
    total_failed: int = 0


class TaskSourceDirectoryStatus(BaseModel):
    """Status of a single Task Source Directory."""

    id: str
    path: str
    description: str

    # Queue stats for this source
    queue_stats: Dict[str, int] = Field(default_factory=dict)


# Backward compatibility aliases
TaskDocDirectory = TaskSourceDirectory
ProjectStatistics = GlobalStatistics
Statistics = SourceStatistics  # Note: This was the old single statistics
