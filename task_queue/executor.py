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
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file at module import time
_ENV_PATH = Path("/home/admin/workspaces/task-queue/.env")
load_dotenv(_ENV_PATH, override=True)

# Verify environment variables are loaded
# Note: .env uses ANTHROPIC_AUTH_TOKEN, but bundled CLI expects ANTHROPIC_API_KEY
_ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
_ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")


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

    def __init__(self, project_workspace: Optional[Path] = None):
        """
        Initialize sync executor.

        Args:
            project_workspace: Path to project workspace directory (can be overridden in execute())
        """
        self.project_workspace = Path(project_workspace).resolve() if project_workspace else None

    def execute(self, task_file: Path, project_workspace: Path = None) -> ExecutionResult:
        """
        Execute a task synchronously.

        Args:
            task_file: Path to task document file
            project_workspace: Project workspace directory

        Returns:
            ExecutionResult with execution outcome
        """
        if project_workspace:
            self.project_workspace = Path(project_workspace).resolve()

        if not self.project_workspace:
            raise ValueError("project_workspace must be set")

        task_file = Path(task_file)
        if not task_file.is_absolute():
            task_file = self.project_workspace / task_file

        if not task_file.exists():
            raise FileNotFoundError(f"Task document not found: {task_file}")

        task_id = task_file.stem
        relative_task_path = str(task_file.relative_to(self.project_workspace))

        logger.info(f"[{task_id}] Task started: {relative_task_path}")

        result = ExecutionResult(
            success=False,
            task_id=task_id
        )

        start_time = datetime.now()
        task_complete = False
        full_output = []

        try:
            # FIXED: Removed extras that break /task-worker skill invocation
            # - No cli_path forcing (let SDK find bundled CLI naturally)
            # - No stderr callback (interferes with execution)
            # - No extra_args/debug mode (causes issues)
            # Based on incremental testing: Step 7 works, Step 6 fails
            options = ClaudeAgentOptions(
                cwd=str(self.project_workspace),
                permission_mode="bypassPermissions",
                setting_sources=["project"],
                tools={"type": "preset", "preset": "claude_code"},
                env={
                    "ANTHROPIC_API_KEY": _ANTHROPIC_AUTH_TOKEN,
                    "ANTHROPIC_BASE_URL": _ANTHROPIC_BASE_URL
                },
            )

            # Invoke /task-worker skill with task document path (relative to project workspace)
            prompt_text = f"""/task-worker

Execute task at: {relative_task_path}
"""
            q = query(
                prompt=prompt_text,
                options=options
            )

            # FIXED: Use standard asyncio.run() instead of custom event loop
            # This matches the working test4_worker.py approach (Step 7)
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
                            return

                        elif message.subtype == 'error':
                            result.success = False
                            result.error = message.result or "Task failed"
                            logger.error(f"[{task_id}] Task failed: {result.error}")
                            task_complete = True
                            return
                    else:
                        if hasattr(message, 'content'):
                            for block in message.content:
                                if hasattr(block, 'text'):
                                    full_output.append(block.text)

            # FIXED: Use asyncio.run() like the working test4_worker.py
            asyncio.run(consume_messages())

        except asyncio.CancelledError:
            logger.info(f"[{task_id}] Task cancelled")
            if not task_complete:
                result.success = False
                result.error = "Task cancelled"

        except Exception as e:
            if not task_complete:
                result.success = False
                result.error = f"{type(e).__name__}: {str(e)}"
                logger.error(f"[{task_id}] Task exception: {type(e).__name__}: {str(e)}")

        return result


def create_executor(project_workspace: Path) -> SyncTaskExecutor:
    """
    Create a task executor for a project.

    Args:
        project_workspace: Path to project workspace

    Returns:
        Configured SyncTaskExecutor
    """
    return SyncTaskExecutor(project_workspace)
