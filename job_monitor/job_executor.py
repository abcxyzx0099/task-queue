import asyncio
import sys
import logging
from pathlib import Path
from datetime import datetime
from claude_agent_sdk import query, ClaudeAgentOptions

# Add paths for module imports
PROJECT_ROOT = Path("/home/admin/workspaces/datachat")
MONITOR_SYSTEM_ROOT = Path("/home/admin/workspaces/job-monitor")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(MONITOR_SYSTEM_ROOT))
from job_monitor.models import JobResult, JobStatus

# Configure logging to systemd journal (standard for Linux services)
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'  # Simple format for journald
)
logger = logging.getLogger(__name__)


class JobExecutor:
    """Executes jobs using Claude Agent SDK - directly invokes skills."""

    def __init__(self, tasks_dir: str, results_dir: str, project_root: str = "."):
        self.tasks_dir = Path(tasks_dir)
        self.results_dir = Path(results_dir)
        self.project_root = Path(project_root).resolve()
        self.results_dir.mkdir(parents=True, exist_ok=True)

    async def execute_job(self, job_file: str) -> JobResult:
        """Execute a job by directly invoking task-coordination skill."""
        job_id = Path(job_file).stem
        job_path = self.tasks_dir / job_file

        # Read job document content
        job_content = self._read_job_document(job_path)

        # Log job start to systemd journal
        logger.info(f"[{job_id}] Job started")

        # Configure SDK
        options = ClaudeAgentOptions(
            cwd=str(self.project_root),  # Set working directory
            permission_mode="acceptEdits",  # Auto-accept file edits
            setting_sources=["project"],  # Load project settings (including skills)
        )

        start_time = datetime.now()
        result = JobResult(
            job_id=job_id,
            status=JobStatus.RUNNING,
            created_at=start_time,
            started_at=start_time,
        )

        # Track if we've received final result (to avoid break)
        job_complete = False
        full_output = []

        try:
            # Create query object
            q = query(
                prompt=f"""/task-coordination

Execute the following job:

{job_content}
""",
                options=options
            )

            # Iterate through messages - DO NOT use break, consume all messages naturally
            async for message in q:
                # Skip processing if job is already complete
                if job_complete:
                    continue

                if hasattr(message, 'subtype'):
                    if message.subtype == 'success':
                        result.status = JobStatus.COMPLETED
                        result.completed_at = datetime.now()
                        result.duration_seconds = (result.completed_at - start_time).total_seconds()
                        result.stdout = "\n".join(full_output) if full_output else ""
                        result.worker_output = {
                            "summary": message.result or "Job completed",
                            "raw_output": result.stdout
                        }
                        if hasattr(message, 'usage'):
                            result.worker_output['usage'] = message.usage
                        if hasattr(message, 'total_cost_usd'):
                            result.worker_output['cost_usd'] = message.total_cost_usd
                        logger.info(f"[{job_id}] Job completed in {result.duration_seconds:.1f}s")
                        # Mark complete but don't break - consume remaining messages naturally
                        job_complete = True

                    elif message.subtype == 'error':
                        result.status = JobStatus.FAILED
                        result.completed_at = datetime.now()
                        result.duration_seconds = (result.completed_at - start_time).total_seconds()
                        result.stdout = "\n".join(full_output) if full_output else ""
                        result.stderr = message.result or "Job failed"
                        result.error = result.stderr
                        logger.error(f"[{job_id}] Job failed: {result.error}")
                        # Mark complete but don't break - consume remaining messages naturally
                        job_complete = True
                else:
                    # Collect output from other message types
                    if hasattr(message, 'content'):
                        for block in message.content:
                            if hasattr(block, 'text'):
                                full_output.append(block.text)

            # Save result after consuming all messages naturally
            self._save_result(result)

        except asyncio.CancelledError:
            # Handle job cancellation gracefully
            logger.info(f"[{job_id}] Job cancelled")
            if not job_complete:
                result.status = JobStatus.FAILED
                result.completed_at = datetime.now()
                result.duration_seconds = (result.completed_at - start_time).total_seconds()
                result.error = "Job cancelled"
                self._save_result(result)
            # Re-raise to allow proper cleanup
            raise

        except Exception as e:
            if not job_complete:
                result.status = JobStatus.FAILED
                result.completed_at = datetime.now()
                result.duration_seconds = (result.completed_at - start_time).total_seconds()
                result.error = f"{type(e).__name__}: {str(e)}"
                logger.error(f"[{job_id}] Job exception: {result.error}")
                self._save_result(result)

        return result

    def _read_job_document(self, job_path: Path) -> str:
        """Read job document content."""
        try:
            with open(job_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"Job document not found: {job_path}")

    def _save_result(self, result: JobResult):
        """Save result to JSON file."""
        output_file = self.results_dir / f"{result.job_id}.json"
        with open(output_file, "w") as f:
            f.write(result.model_dump_json(indent=2))
