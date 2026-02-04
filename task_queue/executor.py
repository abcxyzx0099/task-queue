"""
Task executor using Claude Agent SDK.

Copied from task-management module for consistent SDK usage.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from claude_agent_sdk import query, ClaudeAgentOptions

from task_queue.models import Task, TaskResult, TaskStatus
from task_queue.atomic import AtomicFileWriter


# Paths relative to project root
task_specifications_path = "tasks/task-documents"
task_worker_reports_path = "tasks/task-reports"
task_archive_path = "tasks/task-archive"


logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class TaskExecutor:
    """
    Executes tasks using Claude Agent SDK - invokes /task-worker skill.

    Copied from task-management module for consistent behavior.
    """

    def __init__(self, project_root: Path):
        """
        Initialize executor for a project.

        Args:
            project_root: Path to project root directory
        """
        self.project_root = Path(project_root).resolve()

        # Source directories
        self.specs_dir = self.project_root / task_specifications_path

        # Output directories
        self.reports_dir = self.project_root / task_worker_reports_path
        self.results_dir = self.project_root / "tasks" / "task-queue" / "results"
        self.archive_dir = self.project_root / task_archive_path

        # Create directories
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    async def execute_task(self, task: Task) -> TaskResult:
        """
        Execute a task by invoking /task-worker skill.

        Args:
            task: Task to execute

        Returns:
            TaskResult with execution outcome
        """
        task_id = task.task_id

        # Get task spec path
        if Path(task.spec_file).is_absolute:
            task_path = Path(task.spec_file)
        else:
            task_path = self.project_root / task.spec_file

        if not task_path.exists():
            raise FileNotFoundError(f"Task specification not found: {task_path}")

        # Calculate relative path from project root
        relative_task_path = task_path.relative_to(self.project_root)

        logger.info(f"[{task_id}] Task started")
        logger.info(f"[{task_id}] Spec: {relative_task_path}")

        # Configure SDK with system_prompt to enforce coordinator behavior
        options = ClaudeAgentOptions(
            cwd=str(self.project_root),
            permission_mode="bypassPermissions",
            setting_sources=["project"],
            tools={"type": "preset", "preset": "claude_code"},
            # CRITICAL: Force coordinator-only behavior - no direct implementation
            system_prompt="""You are a TASK COORDINATOR. Your ONLY job is to coordinate work through sub-agents using the Task tool.

CRITICAL RULES:
1. You are FORBIDDEN from doing any implementation work yourself
2. You MUST ALWAYS use the Task tool to spawn sub-agents for ALL implementation work
3. NEVER use Write, Edit, NotebookEdit, or any implementation tool directly
4. DO NOT think "this is simple, I'll do it myself" - ALWAYS use Task tool

Your workflow for the task-worker skill:
1. Read the task specification document
2. Spawn Implementation Agent: Use Task tool with subagent_type="general-purpose"
   - description: "Execute the task"
   - prompt: [full task document content]
3. Spawn Auditor Agent: Use Task tool with subagent_type="general-purpose"
   - description: "Audit implementation quality"
   - prompt: [task document + implementation result]
4. Check audit verdict
5. If audit fails (FAIL, NEEDS_REVISION), iterate: spawn agents again with feedback
6. Return final result

You MUST use the Task tool for ALL implementation. DO NOT take shortcuts.
""",
        )

        start_time = datetime.now()
        result = TaskResult(
            task_id=task_id,
            spec_file=str(task_path),
            spec_dir_id=task.spec_dir_id,
            status=TaskStatus.RUNNING,
            started_at=start_time.isoformat(),
            completed_at=None,
            duration_seconds=0.0,
            attempts=task.attempts + 1,
        )

        task_complete = False
        full_output = []

        try:
            # Invoke /task-worker skill with task specification path
            q = query(
                prompt=f"""/task-worker

Execute task at: {relative_task_path}
""",
                options=options
            )

            # Consume all messages
            async for message in q:
                if task_complete:
                    continue

                if hasattr(message, 'subtype'):
                    if message.subtype == 'success':
                        result.status = TaskStatus.COMPLETED
                        result.completed_at = datetime.now().isoformat()
                        result.duration_seconds = (datetime.now() - start_time).total_seconds()
                        result.stdout = "\n".join(full_output) if full_output else ""
                        result.worker_report_path = f"tasks/task-reports/{task_id}/"

                        # Extract usage info
                        worker_output = {}
                        worker_output["summary"] = message.result or "Task completed"
                        worker_output["raw_output"] = result.stdout

                        if hasattr(message, 'usage'):
                            worker_output['usage'] = message.usage
                        if hasattr(message, 'total_cost_usd'):
                            worker_output['cost_usd'] = message.total_cost_usd
                            result.cost_usd = message.total_cost_usd

                        logger.info(f"[{task_id}] Task completed in {result.duration_seconds:.1f}s")
                        task_complete = True

                    elif message.subtype == 'error':
                        result.status = TaskStatus.FAILED
                        result.completed_at = datetime.now().isoformat()
                        result.duration_seconds = (datetime.now() - start_time).total_seconds()
                        result.stdout = "\n".join(full_output) if full_output else ""
                        result.stderr = message.result or "Task failed"
                        result.error = result.stderr
                        logger.error(f"[{task_id}] Task failed: {result.error}")
                        task_complete = True
                else:
                    if hasattr(message, 'content'):
                        for block in message.content:
                            if hasattr(block, 'text'):
                                full_output.append(block.text)

            # Save result
            self._save_result(result)

            # Archive task specification
            self._archive_task_spec(task_path)

        except asyncio.CancelledError:
            logger.info(f"[{task_id}] Task cancelled")
            if not task_complete:
                result.status = TaskStatus.FAILED
                result.completed_at = datetime.now().isoformat()
                result.duration_seconds = (datetime.now() - start_time).total_seconds()
                result.error = "Task cancelled"
                self._save_result(result)
                self._archive_task_spec(task_path)
            raise

        except Exception as e:
            if not task_complete:
                result.status = TaskStatus.FAILED
                result.completed_at = datetime.now().isoformat()
                result.duration_seconds = (datetime.now() - start_time).total_seconds()
                result.error = f"{type(e).__name__}: {str(e)}"
                logger.error(f"[{task_id}] Task exception: {result.error}")
                self._save_result(result)
                self._archive_task_spec(task_path)

        return result

    def _save_result(self, result: TaskResult):
        """Save result to JSON file."""
        output_file = self.results_dir / f"{result.task_id}.json"
        AtomicFileWriter.write_json(
            output_file,
            result.model_dump(),
            indent=2
        )
        logger.info(f"[{result.task_id}] Result saved: {output_file}")

    def _archive_task_spec(self, task_path: Path):
        """Move completed task specification to archive."""
        if task_path.exists():
            # Get just the filename
            task_file = task_path.name
            dest_path = self.archive_dir / task_file
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(task_path), str(dest_path))
            logger.info(f"[{task_file}] Archived to: {dest_path}")


# Synchronous wrapper for compatibility
class SyncTaskExecutor:
    """
    Synchronous wrapper for TaskExecutor.

    Provides a sync execute() method that runs the async execute_task().
    """

    def __init__(self, project_root: Path):
        """Initialize sync executor."""
        self._executor = TaskExecutor(project_root)
        self.project_root = project_root

    def execute(self, task: Task, project_root: Path = None, state_dir: Path = None) -> TaskResult:
        """
        Execute a task synchronously.

        Args:
            task: Task to execute
            project_root: Project root (uses init path if None)
            state_dir: Ignored (for compatibility)

        Returns:
            TaskResult with execution outcome
        """
        if project_root:
            self._executor = TaskExecutor(project_root)

        # Run async function in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self._executor.execute_task(task))
        finally:
            loop.close()

        return result


def create_executor(project_root: Path) -> SyncTaskExecutor:
    """
    Create a task executor for a project.

    Args:
        project_root: Path to project root

    Returns:
        Configured SyncTaskExecutor
    """
    return SyncTaskExecutor(project_root)
