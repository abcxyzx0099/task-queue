"""Tests for job_monitor.models module."""

import pytest
from datetime import datetime
from pydantic import ValidationError

from job_monitor.models import JobStatus, JobResult, QueueState, JobInfo


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_job_status_values(self):
        """Test JobStatus enum has correct values."""
        assert JobStatus.QUEUED == "queued"
        assert JobStatus.RUNNING == "running"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.RETRYING == "retrying"

    def test_job_status_comparison(self):
        """Test JobStatus comparison works."""
        status = JobStatus.COMPLETED
        assert status == "completed"
        assert status != "failed"


class TestJobResult:
    """Tests for JobResult model."""

    def test_job_result_creation_minimal(self):
        """Test JobResult creation with minimal required fields."""
        result = JobResult(
            job_id="test-001",
            status=JobStatus.COMPLETED,
            created_at=datetime.now(),
        )
        assert result.job_id == "test-001"
        assert result.status == JobStatus.COMPLETED
        assert result.started_at is None
        assert result.completed_at is None
        assert result.queue_position is None
        assert result.worker_output is None
        assert result.audit_score is None
        assert result.audit_notes is None
        assert result.artifacts == []
        assert result.error is None
        assert result.retry_count == 0
        assert result.stdout is None
        assert result.stderr is None
        assert result.duration_seconds is None

    def test_job_result_creation_full(self):
        """Test JobResult creation with all fields."""
        created_at = datetime(2025, 1, 31, 10, 0, 0)
        started_at = datetime(2025, 1, 31, 10, 0, 5)
        completed_at = datetime(2025, 1, 31, 10, 0, 15)

        result = JobResult(
            job_id="test-002",
            status=JobStatus.COMPLETED,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            queue_position=1,
            worker_output={"summary": "Success"},
            audit_score=100,
            audit_notes="Perfect",
            artifacts=["file1.txt", "file2.txt"],
            error=None,
            retry_count=0,
            stdout="Output here",
            stderr="Errors here",
            duration_seconds=10.5,
        )
        assert result.job_id == "test-002"
        assert result.status == JobStatus.COMPLETED
        assert result.created_at == created_at
        assert result.started_at == started_at
        assert result.completed_at == completed_at
        assert result.queue_position == 1
        assert result.worker_output == {"summary": "Success"}
        assert result.audit_score == 100
        assert result.audit_notes == "Perfect"
        assert result.artifacts == ["file1.txt", "file2.txt"]
        assert result.error is None
        assert result.retry_count == 0
        assert result.stdout == "Output here"
        assert result.stderr == "Errors here"
        assert result.duration_seconds == 10.5

    def test_job_result_serialization(self):
        """Test JobResult can be serialized to JSON."""
        result = JobResult(
            job_id="test-003",
            status=JobStatus.FAILED,
            created_at=datetime(2025, 1, 31, 10, 0, 0),
            error="Something went wrong",
            retry_count=2,
        )
        json_str = result.model_dump_json()
        assert "test-003" in json_str
        assert "failed" in json_str
        assert "Something went wrong" in json_str

    def test_job_result_deserialization(self):
        """Test JobResult can be deserialized from JSON."""
        json_data = {
            "job_id": "test-004",
            "status": "completed",
            "created_at": "2025-01-31T10:00:00",
            "retry_count": 0,
            "artifacts": [],
        }
        result = JobResult(**json_data)
        assert result.job_id == "test-004"
        assert result.status == JobStatus.COMPLETED


class TestQueueState:
    """Tests for QueueState model."""

    def test_queue_state_creation(self):
        """Test QueueState creation."""
        state = QueueState(
            queue_size=5,
            current_task="job-001.md",
            is_processing=True,
            queued_tasks=["job-002.md", "job-003.md", "job-004.md", "job-005.md"],
        )
        assert state.queue_size == 5
        assert state.current_task == "job-001.md"
        assert state.is_processing is True
        assert len(state.queued_tasks) == 4

    def test_queue_state_optional_fields(self):
        """Test QueueState with optional fields."""
        state = QueueState(
            queue_size=0,
            current_task=None,
            is_processing=False,
            queued_tasks=[],
        )
        assert state.queue_size == 0
        assert state.current_task is None
        assert state.is_processing is False
        assert state.queued_tasks == []


class TestJobInfo:
    """Tests for JobInfo model."""

    def test_job_info_creation(self):
        """Test JobInfo creation."""
        info = JobInfo(
            job_id="info-001",
            status=JobStatus.QUEUED,
            created_at=datetime.now(),
            queue_position=3,
        )
        assert info.job_id == "info-001"
        assert info.status == JobStatus.QUEUED
        assert info.queue_position == 3

    def test_job_info_without_queue_position(self):
        """Test JobInfo without queue position."""
        info = JobInfo(
            job_id="info-002",
            status=JobStatus.RUNNING,
            created_at=datetime.now(),
        )
        assert info.job_id == "info-002"
        assert info.status == JobStatus.RUNNING
        assert info.queue_position is None
