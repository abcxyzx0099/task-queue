from pydantic import BaseModel
from enum import Enum
from datetime import datetime
from typing import Optional, List


class JobStatus(str, Enum):
    QUEUED = "queued"       # Waiting in queue
    RUNNING = "running"     # Currently executing
    COMPLETED = "completed" # Successfully completed
    FAILED = "failed"       # Failed with error
    RETRYING = "retrying"   # Being retried


class JobResult(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    queue_position: Optional[int] = None  # Position in queue (if queued)
    worker_output: Optional[dict] = None
    audit_score: Optional[int] = None
    audit_notes: Optional[str] = None
    artifacts: List[str] = []
    error: Optional[str] = None
    retry_count: int = 0
    # Job execution logs
    stdout: Optional[str] = None       # Captured stdout from job execution
    stderr: Optional[str] = None       # Captured stderr from job execution
    duration_seconds: Optional[float] = None  # Execution duration


class QueueState(BaseModel):
    """Current state of the job queue."""
    queue_size: int
    current_task: Optional[str]
    is_processing: bool
    queued_tasks: List[str]


class JobInfo(BaseModel):
    """Basic job info for status queries."""
    job_id: str
    status: JobStatus
    created_at: datetime
    queue_position: Optional[int] = None
