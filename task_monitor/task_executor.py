import asyncio
import sys
import logging
import shutil
from pathlib import Path
from datetime import datetime
from claude_agent_sdk import query, ClaudeAgentOptions

# Add paths for module imports
PROJECT_ROOT = Path("/home/admin/workspaces/datachat")
MONITOR_SYSTEM_ROOT = Path("/home/admin/workspaces/task-monitor")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(MONITOR_SYSTEM_ROOT))
from task_monitor.models import TaskResult, TaskStatus

# Task monitor path relative to project root (e.g., "tasks/task-monitor")
task_monitor_path = "tasks/task-monitor"

# Configure logging to systemd journal (standard for Linux services)
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'  # Simple format for journald
)
logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes tasks using Claude Agent SDK - directly invokes skills."""

    def __init__(self, tasks_dir: str, results_dir: str, project_root: str = "."):
        self.tasks_dir = Path(tasks_dir)
        self.results_dir = Path(results_dir)
        self.project_root = Path(project_root).resolve()
        self.results_dir.mkdir(parents=True, exist_ok=True)
        # Archive is in task-monitor subdirectory
        self.archive_dir = self.project_root / task_monitor_path / 'archive'
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    async def execute_task(self, task_file: str) -> TaskResult:
        """Execute a task by directly invoking task-coordination skill."""
        task_id = Path(task_file).stem
        task_path = self.tasks_dir / task_file

        # Calculate relative path from project root for skill invocation
        relative_task_path = task_path.relative_to(self.project_root)

        # Log task start to systemd journal
        logger.info(f"[{task_id}] Task started")

        # Configure SDK
        options = ClaudeAgentOptions(
            cwd=str(self.project_root),  # Set working directory
            permission_mode="bypassPermissions",  # Full autonomous execution
            setting_sources=["project"],  # Load project settings (including skills)
            tools={"type": "preset", "preset": "claude_code"},  # Full access to Claude Code tools
        )

        start_time = datetime.now()
        result = TaskResult(
            task_id=task_id,
            status=TaskStatus.RUNNING,
            created_at=start_time,
            started_at=start_time,
        )

        # Track if we've received final result (to avoid break)
        task_complete = False
        full_output = []

        try:
            # Create query object - pass file path instead of content
            q = query(
                prompt=f"""/task-implementation

Execute task at: {relative_task_path}
""",
                options=options
            )

            # Iterate through messages - DO NOT use break, consume all messages naturally
            async for message in q:
                # Skip processing if task is already complete
                if task_complete:
                    continue

                if hasattr(message, 'subtype'):
                    if message.subtype == 'success':
                        result.status = TaskStatus.COMPLETED
                        result.completed_at = datetime.now()
                        result.duration_seconds = (result.completed_at - start_time).total_seconds()
                        result.stdout = "\n".join(full_output) if full_output else ""
                        result.worker_output = {
                            "summary": message.result or "Task completed",
                            "raw_output": result.stdout
                        }
                        if hasattr(message, 'usage'):
                            result.worker_output['usage'] = message.usage
                        if hasattr(message, 'total_cost_usd'):
                            result.worker_output['cost_usd'] = message.total_cost_usd
                        logger.info(f"[{task_id}] Task completed in {result.duration_seconds:.1f}s")
                        # Mark complete but don't break - consume remaining messages naturally
                        task_complete = True

                    elif message.subtype == 'error':
                        result.status = TaskStatus.FAILED
                        result.completed_at = datetime.now()
                        result.duration_seconds = (result.completed_at - start_time).total_seconds()
                        result.stdout = "\n".join(full_output) if full_output else ""
                        result.stderr = message.result or "Task failed"
                        result.error = result.stderr
                        logger.error(f"[{task_id}] Task failed: {result.error}")
                        # Mark complete but don't break - consume remaining messages naturally
                        task_complete = True
                else:
                    # Collect output from other message types
                    if hasattr(message, 'content'):
                        for block in message.content:
                            if hasattr(block, 'text'):
                                full_output.append(block.text)

            # Save result after consuming all messages naturally
            self._save_result(result)
            # Archive task document
            self._archive_task(task_file)

        except asyncio.CancelledError:
            # Handle task cancellation gracefully
            logger.info(f"[{task_id}] Task cancelled")
            if not task_complete:
                result.status = TaskStatus.FAILED
                result.completed_at = datetime.now()
                result.duration_seconds = (result.completed_at - start_time).total_seconds()
                result.error = "Task cancelled"
                self._save_result(result)
                self._archive_task(task_file)
            # Re-raise to allow proper cleanup
            raise

        except Exception as e:
            if not task_complete:
                result.status = TaskStatus.FAILED
                result.completed_at = datetime.now()
                result.duration_seconds = (result.completed_at - start_time).total_seconds()
                result.error = f"{type(e).__name__}: {str(e)}"
                logger.error(f"[{task_id}] Task exception: {result.error}")
                self._save_result(result)
                self._archive_task(task_file)

        return result

    def _read_task_document(self, task_path: Path) -> str:
        """Read task document content."""
        try:
            with open(task_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"Task document not found: {task_path}")

    def _save_result(self, result: TaskResult):
        """Save result to JSON file."""
        output_file = self.results_dir / f"{result.task_id}.json"
        with open(output_file, "w") as f:
            f.write(result.model_dump_json(indent=2))

    def _archive_task(self, task_file: str):
        """Move completed task document to archive."""
        # Only archive .md files
        if not task_file.endswith('.md'):
            return

        # Move task document to archive (flat structure)
        src_path = self.tasks_dir / task_file
        if src_path.exists():
            dest_path = self.archive_dir / task_file
            shutil.move(str(src_path), str(dest_path))
            logging.info(f"Archived task document: {task_file}")
