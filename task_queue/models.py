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


class Task(BaseModel):
    """
    A task in the queue.

    Represents a single task document waiting to be executed.
    """

    task_id: str = Field(..., description="Unique task identifier (task-YYYYMMDD-HHMMSS-description)")
    task_doc_file: str = Field(..., description="Path to task document file")
    task_doc_dir_id: str = Field(..., description="ID of task doc directory where task was found")
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


class Statistics(BaseModel):
    """Statistics for task queue."""

    total_queued: int = 0
    total_completed: int = 0
    total_failed: int = 0
    last_processed_at: Optional[str] = None
    last_load_at: Optional[str] = None


class ProcessingState(BaseModel):
    """Current processing state."""

    is_processing: bool = False
    current_task: Optional[str] = None
    process_id: Optional[int] = None
    started_at: Optional[str] = None
    hostname: Optional[str] = None


class QueueState(BaseModel):
    """
    State of the task queue.

    Persisted to disk for recovery across restarts.
    """

    version: str = "1.0"

    # Queue
    queue: List[Task] = Field(default_factory=list)

    # Processing state
    processing: ProcessingState = Field(default_factory=ProcessingState)

    # Statistics
    statistics: Statistics = Field(default_factory=Statistics)

    # Metadata
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def get_pending_count(self) -> int:
        """Get count of pending tasks."""
        return len([t for t in self.queue if t.status == TaskStatus.PENDING])

    def get_running_count(self) -> int:
        """Get count of running tasks."""
        return len([t for t in self.queue if t.status == TaskStatus.RUNNING])

    def get_completed_count(self) -> int:
        """Get count of completed tasks."""
        return len([t for t in self.queue if t.status == TaskStatus.COMPLETED])

    def get_failed_count(self) -> int:
        """Get count of failed tasks."""
        return len([t for t in self.queue if t.status == TaskStatus.FAILED])

    def get_next_pending(self) -> Optional[Task]:
        """Get next pending task (FIFO order)."""
        for task in self.queue:
            if task.status == TaskStatus.PENDING:
                return task
        return None


class TaskDocDirectory(BaseModel):
    """
    Configuration for a monitored task document directory.

    Defines where to scan for task document files.
    """

    id: str = Field(..., description="Unique identifier for this task doc directory")
    path: str = Field(..., description="Path to task document directory")
    description: str = Field(default="", description="Description of this task doc directory")

    # Metadata
    added_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @field_validator('path')
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate and resolve path."""
        path = Path(v).resolve()
        if not path.exists():
            raise ValueError(f"Task doc directory does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        return str(path)


class QueueSettings(BaseModel):
    """Global monitor settings."""

    processing_interval: int = Field(default=10, description="Seconds between processing cycles")
    batch_size: int = Field(default=10, description="Max tasks to process per cycle")
    task_doc_pattern: str = Field(default="task-*.md", description="Pattern for task doc files")

    # Retry settings
    max_attempts: int = Field(default=3, description="Max execution attempts per task")

    # File tracking
    enable_file_hash: bool = Field(default=True, description="Track file hashes for change detection")


class QueueConfig(BaseModel):
    """
    Complete monitor configuration.

    Single project path + Multiple task doc directories.
    """

    version: str = "1.0"
    settings: QueueSettings = Field(default_factory=QueueSettings)

    # Single project path
    project_path: Optional[str] = Field(default=None, description="Path to project root (used as cwd)")

    # Multiple task doc directories to scan
    task_doc_directories: List[TaskDocDirectory] = Field(default_factory=list)

    # Metadata
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def get_task_doc_directory(self, doc_id: str) -> Optional[TaskDocDirectory]:
        """Get task doc directory by ID."""
        for doc_dir in self.task_doc_directories:
            if doc_dir.id == doc_id:
                return doc_dir
        return None

    def set_project_path(self, path: str) -> None:
        """Set the project path."""
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            raise ValueError(f"Project path does not exist: {path_obj}")
        if not path_obj.is_dir():
            raise ValueError(f"Project path is not a directory: {path_obj}")
        self.project_path = str(path_obj)
        self.updated_at = datetime.now().isoformat()

    def add_task_doc_directory(
        self,
        path: str,
        id: str,
        description: str = ""
    ) -> TaskDocDirectory:
        """Add a task doc directory to configuration."""
        # Check for duplicate ID
        if self.get_task_doc_directory(id):
            raise ValueError(f"Task doc directory ID already exists: {id}")

        doc_dir = TaskDocDirectory(
            id=id,
            path=path,
            description=description
        )

        self.task_doc_directories.append(doc_dir)
        self.updated_at = datetime.now().isoformat()

        return doc_dir

    def remove_task_doc_directory(self, doc_id: str) -> bool:
        """Remove a task doc directory by ID."""
        for i, doc_dir in enumerate(self.task_doc_directories):
            if doc_dir.id == doc_id:
                self.task_doc_directories.pop(i)
                self.updated_at = datetime.now().isoformat()
                return True
        return False


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
    project_path: Optional[str] = None

    # Task doc directories
    total_task_doc_dirs: int = 0
    active_task_doc_dirs: int = 0

    # Queue stats
    total_pending: int = 0
    total_running: int = 0
    total_completed: int = 0
    total_failed: int = 0


class TaskDocDirectoryStatus(BaseModel):
    """Status of a single task doc directory."""

    id: str
    path: str
    description: str

    # Queue stats for this task doc directory
    queue_stats: Dict[str, int] = Field(default_factory=dict)


# Re-export ProjectStatistics for backward compatibility
ProjectStatistics = Statistics
