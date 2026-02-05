"""
Task executor using Claude Agent SDK.

Simplified for directory-based state architecture.
No Task model - just execute task document files.
"""

import asyncio
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions


logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file at module import time
_ENV_PATH = Path("/home/admin/workspaces/task-queue/.env")
load_dotenv(_ENV_PATH, override=True)

# Verify environment variables are loaded
_ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
_ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
logger.info(f"Executor initialized: Auth token loaded={bool(_ANTHROPIC_AUTH_TOKEN)}, Base URL loaded={bool(_ANTHROPIC_BASE_URL)}")


@dataclass
class ExecutionResult:
    """Result of task execution."""
    success: bool
    output: str = ""
    error: str = ""
    task_id: str = ""


class SyncTaskExecutor:
    """
    Synchronous task executor using Claude Agent SDK.

    Simplified for directory-based state - executes task files directly.
    """

    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize sync executor.

        Args:
            project_root: Path to project root directory (can be overridden in execute())
        """
        self.project_root = Path(project_root).resolve() if project_root else None

    def execute(self, task_file: Path, project_root: Path = None) -> ExecutionResult:
        """
        Execute a task synchronously.

        Args:
            task_file: Path to task document file
            project_root: Project root directory

        Returns:
            ExecutionResult with execution outcome
        """
        if project_root:
            self.project_root = Path(project_root).resolve()

        if not self.project_root:
            raise ValueError("project_root must be set")

        task_file = Path(task_file)
        if not task_file.is_absolute():
            task_file = self.project_root / task_file

        if not task_file.exists():
            raise FileNotFoundError(f"Task document not found: {task_file}")

        task_id = task_file.stem
        relative_task_path = task_file.relative_to(self.project_root)

        logger.info(f"[{task_id}] Task started")
        logger.info(f"[{task_id}] Task doc: {relative_task_path}")

        result = ExecutionResult(
            success=False,
            task_id=task_id
        )

        start_time = datetime.now()
        task_complete = False
        full_output = []

        # Collect stderr output for debugging
        stderr_output = []

        def stderr_callback(line: str):
            stderr_output.append(line)
            logger.info(f"[{task_id}] STDERR: {line}")

        logger.info(f"[{task_id}] Using auth token from .env: {bool(_ANTHROPIC_AUTH_TOKEN)}, Base URL: {bool(_ANTHROPIC_BASE_URL)}")

        # Set environment variables for the subprocess (will be inherited by bundled CLI)
        os.environ["ANTHROPIC_AUTH_TOKEN"] = _ANTHROPIC_AUTH_TOKEN
        os.environ["ANTHROPIC_BASE_URL"] = _ANTHROPIC_BASE_URL

        try:
            # Configure SDK with system_prompt to enforce coordinator behavior
            options = ClaudeAgentOptions(
                cwd=str(self.project_root),
                permission_mode="bypassPermissions",
                setting_sources=["project"],
                tools={"type": "preset", "preset": "claude_code"},
                stderr=stderr_callback,
                extra_args={"debug-to-stderr": True},
                # CRITICAL: Force coordinator-only behavior - no direct implementation
                system_prompt="""You are a TASK COORDINATOR. Your ONLY job is to coordinate work through sub-agents using the Task tool.

CRITICAL RULES:
1. You are FORBIDDEN from doing any implementation work yourself
2. You MUST ALWAYS use the Task tool to spawn sub-agents for ALL implementation work
3. NEVER use Write, Edit, NotebookEdit, or any implementation tool directly
4. DO NOT think "this is simple, I'll do it myself" - ALWAYS use Task tool

Your workflow for the task-worker skill:
1. Read the task document
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

            # Invoke /task-worker skill with task document path
            q = query(
                prompt=f"""/task-worker

Execute task at: {relative_task_path}
""",
                options=options
            )

            # Run async query in new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def consume_messages():
                    nonlocal task_complete, full_output
                    async for message in q:
                        if task_complete:
                            continue

                        if hasattr(message, 'subtype'):
                            if message.subtype == 'success':
                                result.success = True
                                result.output = "\n".join(full_output) if full_output else ""
                                duration = (datetime.now() - start_time).total_seconds()
                                logger.info(f"[{task_id}] Task completed in {duration:.1f}s")
                                task_complete = True

                            elif message.subtype == 'error':
                                result.success = False
                                result.error = message.result or "Task failed"
                                logger.error(f"[{task_id}] Task failed: {result.error}")
                                task_complete = True
                        else:
                            if hasattr(message, 'content'):
                                for block in message.content:
                                    if hasattr(block, 'text'):
                                        full_output.append(block.text)

                loop.run_until_complete(consume_messages())
            finally:
                loop.close()

        except asyncio.CancelledError:
            logger.info(f"[{task_id}] Task cancelled")
            if not task_complete:
                result.success = False
                result.error = "Task cancelled"

        except Exception as e:
            if not task_complete:
                result.success = False
                stderr_str = "\n".join(stderr_output) if stderr_output else ""
                result.error = f"{type(e).__name__}: {str(e)}\nSTDERR:\n{stderr_str}"
                logger.error(f"[{task_id}] Task exception: {type(e).__name__}: {str(e)}")

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
