"""
Task executor using Claude Agent SDK.

Simplified for directory-based state architecture.
No Task model - just execute task document files.

Lock file tracking: Each running task has a .task-{id}.lock file
containing thread_id, worker, pid, and started_at timestamp.
"""

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, Dict
from dataclasses import dataclass, field, asdict

from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file at module import time
# Try to find .env in the task-queue package directory or its parent
try:
    # Get the directory containing this module
    _MODULE_DIR = Path(__file__).parent.parent
    _ENV_PATH = _MODULE_DIR / ".env"
    if not _ENV_PATH.exists():
        # Fallback to current working directory
        _ENV_PATH = Path.cwd() / ".env"
    load_dotenv(_ENV_PATH, override=True)
except Exception:
    # If all else fails, try loading from cwd
    load_dotenv(override=True)

# Verify environment variables are loaded
_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")


@dataclass
class LockInfo:
    """Lock file information for running task tracking."""
    task_id: str
    worker: str  # e.g., "ad-hoc", "planned"
    thread_id: str
    pid: int
    started_at: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_file(cls, lock_file: Path) -> Optional['LockInfo']:
        """Read lock info from file."""
        try:
            with open(lock_file, 'r') as f:
                data = json.load(f)
            return cls(**data)
        except Exception:
            return None

    def save(self, lock_file: Path) -> None:
        """Save lock info to file."""
        with open(lock_file, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)


def get_lock_file_path(task_file: Path) -> Path:
    """Get the lock file path for a task file."""
    # Lock file is in the same directory as the task file
    # Name: .task-{id}.lock
    return task_file.parent / f".{task_file.stem}.lock"


def is_task_locked(task_file: Path) -> bool:
    """Check if a task is currently locked (running)."""
    lock_file = get_lock_file_path(task_file)
    if not lock_file.exists():
        return False

    # Check if lock is stale (process no longer running)
    lock_info = LockInfo.from_file(lock_file)
    if lock_info and not process_exists(lock_info.pid):
        # Stale lock - remove it
        try:
            lock_file.unlink()
        except Exception:
            pass
        return False

    return lock_file.exists()


def get_locked_task(task_source_dir: Path) -> Optional[str]:
    """Get the currently locked task ID in a directory."""
    lock_files = list(task_source_dir.glob(".task-*.lock"))
    if not lock_files:
        return None

    # Return the first locked task (should be only one per directory)
    for lock_file in lock_files:
        lock_info = LockInfo.from_file(lock_file)
        if lock_info and process_exists(lock_info.pid):
            return lock_info.task_id

    # If all locks are stale, return None
    return None


def process_exists(pid: int) -> bool:
    """Check if a process with given PID exists."""
    try:
        return os.path.exists(f"/proc/{pid}")
    except Exception:
        return False


@dataclass
class ExecutionResult:
    """Result of task execution with SDK metadata."""
    success: bool
    output: str = ""
    error: str = ""
    task_id: str = ""
    # SDK metadata
    duration_ms: Optional[int] = None
    duration_api_ms: Optional[int] = None
    total_cost_usd: Optional[float] = None
    usage: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    num_turns: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        data = asdict(self)
        # Remove None values
        return {k: v for k, v in data.items() if v is not None}

    def save_to_file(self, project_workspace: Path, worker: str = "ad-hoc") -> Path:
        """
        Save result as JSON file to tasks/{worker}/results/{task_id}.json

        Args:
            project_workspace: Path to project workspace
            worker: Worker name (e.g., "ad-hoc", "planned")

        Returns:
            Path to saved result file
        """
        result_dir = project_workspace / "tasks" / worker / "results"
        result_dir.mkdir(parents=True, exist_ok=True)

        result_file = result_dir / f"{self.task_id}.json"
        with open(result_file, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

        return result_file


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

    def execute(
        self,
        task_file: Path,
        project_workspace: Path = None,
        worker: str = "unknown"
    ) -> ExecutionResult:
        """
        Execute a task synchronously.

        Args:
            task_file: Path to task document file
            project_workspace: Project workspace directory
            worker: Worker name (e.g., "ad-hoc", "planned")

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

        # Create lock file to track running task
        current_thread = threading.current_thread()
        thread_id = str(current_thread.ident or 0)
        process_pid = os.getpid()

        lock_info = LockInfo(
            task_id=task_id,
            worker=worker,
            thread_id=thread_id,
            pid=process_pid,
            started_at=datetime.now().isoformat()
        )

        lock_file = get_lock_file_path(task_file)
        lock_info.save(lock_file)
        logger.info(f"[{task_id}] Lock created: {lock_file}")

        logger.info(f"[{task_id}] Task started: {relative_task_path}")

        start_time = datetime.now()
        started_at_str = start_time.isoformat()

        result = ExecutionResult(
            success=False,
            task_id=task_id,
            started_at=started_at_str
        )

        task_complete = False
        full_output = []

        try:
            # FIXED: Removed extras that break /task-execution skill invocation
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
                    "ANTHROPIC_API_KEY": _ANTHROPIC_API_KEY,
                    "ANTHROPIC_BASE_URL": _ANTHROPIC_BASE_URL
                },
            )

            # Invoke task-execution by asking agent to READ skill documentation and follow it
            # This approach was tested and proven to spawn Implementation/Auditor agents
            # See: temp/test_read_skill_doc.py for test results
            prompt_text = f"""Read the task-execution skill documentation at: .claude/skills/task-execution/SKILL.md

Follow the skill's workflow EXACTLY to execute the task at: {relative_task_path}

IMPORTANT:
- Read the skill document carefully first
- Follow ALL steps in the workflow (Safety Checkpoint, Task Report, Implementation Agent, Auditor Agent, Commit)
- Do NOT skip any steps
- Do NOT execute the task directly - spawn sub-agents as specified in the skill documentation"""
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

                            # Capture SDK metadata from ResultMessage
                            result.duration_ms = getattr(message, 'duration_ms', None)
                            result.duration_api_ms = getattr(message, 'duration_api_ms', None)
                            result.total_cost_usd = getattr(message, 'total_cost_usd', None)
                            result.usage = getattr(message, 'usage', None)
                            result.session_id = getattr(message, 'session_id', None)
                            result.num_turns = getattr(message, 'num_turns', None)

                            duration = (datetime.now() - start_time).total_seconds()
                            result.completed_at = datetime.now().isoformat()
                            logger.info(f"[{task_id}] Task completed in {duration:.1f}s")

                            # Delete lock file
                            try:
                                if lock_file.exists():
                                    lock_file.unlink()
                                    logger.info(f"[{task_id}] Lock deleted")
                            except Exception as e:
                                logger.warning(f"[{task_id}] Failed to delete lock: {e}")

                            # Save result JSON file
                            try:
                                result_path = result.save_to_file(self.project_workspace, worker)
                                logger.info(f"[{task_id}] Result saved to: {result_path}")
                            except Exception as e:
                                logger.warning(f"[{task_id}] Failed to save result file: {e}")

                            task_complete = True
                            return

                        elif message.subtype == 'error':
                            result.success = False
                            result.error = message.result or "Task failed"
                            result.completed_at = datetime.now().isoformat()

                            # Also capture error metadata
                            result.duration_ms = getattr(message, 'duration_ms', None)
                            result.duration_api_ms = getattr(message, 'duration_api_ms', None)
                            result.session_id = getattr(message, 'session_id', None)

                            logger.error(f"[{task_id}] Task failed: {result.error}")

                            # Delete lock file
                            try:
                                if lock_file.exists():
                                    lock_file.unlink()
                                    logger.info(f"[{task_id}] Lock deleted")
                            except Exception as e:
                                logger.warning(f"[{task_id}] Failed to delete lock: {e}")

                            # Save result JSON file even for errors
                            try:
                                result_path = result.save_to_file(self.project_workspace, worker)
                                logger.info(f"[{task_id}] Error result saved to: {result_path}")
                            except Exception as save_err:
                                logger.warning(f"[{task_id}] Failed to save error result: {save_err}")

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
                result.completed_at = datetime.now().isoformat()

                # Delete lock file
                try:
                    if lock_file.exists():
                        lock_file.unlink()
                        logger.info(f"[{task_id}] Lock deleted")
                except Exception:
                    pass

                try:
                    result.save_to_file(self.project_workspace, worker)
                except Exception:
                    pass

        except Exception as e:
            if not task_complete:
                result.success = False
                result.error = f"{type(e).__name__}: {str(e)}"
                result.completed_at = datetime.now().isoformat()
                logger.error(f"[{task_id}] Task exception: {type(e).__name__}: {str(e)}")

                # Delete lock file
                try:
                    if lock_file.exists():
                        lock_file.unlink()
                        logger.info(f"[{task_id}] Lock deleted")
                except Exception:
                    pass

                try:
                    result.save_to_file(self.project_workspace, worker)
                except Exception:
                    pass

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
