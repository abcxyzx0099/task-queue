import asyncio
import fcntl
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# System root for monitor code
MONITOR_SYSTEM_ROOT = Path("/home/admin/workspaces/task-monitor")
sys.path.insert(0, str(MONITOR_SYSTEM_ROOT))

from task_queue.task_executor import TaskExecutor
from task_queue.models import TaskStatus

# Configuration
# Task monitor path relative to project root (e.g., "tasks/task-monitor")
task_monitor_path = "tasks/task-monitor"

# Environment variable name for current project (must match cli.py)
ENV_VAR_NAME = "TASK_MONITOR_PROJECT"

# .env file location (matches CLI location)
ENV_FILE = Path(__file__).parent.parent / ".env"

LOCK_FILE = Path.home() / ".config" / "task-monitor" / "task-monitor.lock"


class InstanceLock:
    """File-based lock to prevent multiple instances."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = None
        self.acquired = False

    def acquire(self) -> bool:
        """Acquire the lock. Returns True if successful, False if already locked."""
        try:
            self.lock_file = open(self.lock_path, 'w')
            # Try to acquire exclusive non-blocking lock
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID to lock file
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()
            self.acquired = True
            return True
        except (IOError, OSError):
            # Lock is held by another process
            if self.lock_file:
                self.lock_file.close()
            self.lock_file = None
            return False

    def release(self):
        """Release the lock."""
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
            except Exception:
                pass
            self.lock_file = None

        if self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except Exception:
                pass

        self.acquired = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class TaskMonitor:
    """Monitor a single project's task_monitor_path/pending directory."""

    def __init__(self):
        self.project = None  # {name, path, executor, queue, observer, event_handler, started}
        self.running = False
        self.event_loop = None
        self.processor_task = None  # Track processor task for proper cleanup
        self.instance_lock = InstanceLock(LOCK_FILE)

    def _get_current_project_path(self) -> Path:
        """Get the current project path from .env file or environment variable."""
        # Try loading from .env file (works for both CLI and systemd)
        if ENV_FILE.exists():
            load_dotenv(ENV_FILE)

        # Read from environment (loaded from .env or already set)
        path = os.environ.get(ENV_VAR_NAME)
        if path:
            return Path(path)

        return None

    def _setup_project(self, project_path: Path) -> bool:
        """Setup monitoring for the current project."""
        if not project_path.exists():
            logging.error(f"Project path does not exist: {project_path}")
            return False

        # Use project directory name as the project name
        name = project_path.name

        # Create directories
        tasks_dir = project_path / task_monitor_path / "pending"
        results_dir = project_path / task_monitor_path / "results"
        logs_dir = project_path / task_monitor_path / "logs"
        state_dir = project_path / task_monitor_path / "state"

        tasks_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        # Create project-specific queue
        queue = ProjectTaskQueue(name, project_path, state_dir)

        # Create project-specific executor
        executor = TaskExecutor(
            tasks_dir=str(tasks_dir),
            results_dir=str(results_dir),
            project_root=str(project_path)
        )

        self.project = {
            "name": name,
            "path": project_path,
            "executor": executor,
            "queue": queue,
            "observer": None,
            "event_handler": None,
            "started": False
        }

        logging.info(f"Project '{name}' configured: {project_path}")
        return True

    def start(self):
        """Start monitoring the current project."""
        # Configure root logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )
        logger = logging.getLogger(__name__)

        logger.info("Starting Task Monitor")

        # Try to acquire instance lock
        if not self.instance_lock.acquire():
            logger.error(f"Another instance is already running (lock file: {LOCK_FILE}). Exiting.")
            sys.exit(1)

        logger.info(f"Instance lock acquired: {LOCK_FILE} (PID {os.getpid()})")

        # Get current project from environment variable
        project_path = self._get_current_project_path()

        if not project_path:
            logger.warning(f"No current project set.")
            logger.warning(f"Set a project with: task-monitor use <path>")
            logger.warning(f"Or set the ${ENV_VAR_NAME} environment variable")
            return

        # Setup the project
        if not self._setup_project(project_path):
            logger.error(f"Failed to setup project: {project_path}")
            return

        logger.info(f"Monitoring project: {self.project['name']} at {project_path}")

        # Run the async main function
        asyncio.run(self._run())

    async def _run(self):
        """Main async loop - setup observer and process queue."""
        self.running = True
        self.event_loop = asyncio.get_event_loop()

        # Create observer and event handler with access to event loop
        tasks_dir = self.project["path"] / task_monitor_path / "pending"
        event_handler = TaskFileHandler(
            self.project["queue"],
            self.project["name"],
            self.project["path"],
            self.event_loop
        )
        observer = Observer()
        observer.schedule(event_handler, str(tasks_dir), recursive=False)

        self.project["observer"] = observer
        self.project["event_handler"] = event_handler

        # Start observer
        observer.start()
        self.project["started"] = True
        logging.info(f"Observer started: {self.project['path'] / task_monitor_path / 'pending'}")

        # Start queue processor
        await self._process_queue()

    async def _process_queue(self):
        """Process tasks for the current project."""
        name = self.project["name"]
        queue = self.project["queue"]
        executor = self.project["executor"]
        logger = logging.getLogger(__name__)

        logger.info(f"Queue processor started for '{name}'")

        try:
            while True:
                # Wait for next task (blocks indefinitely, zero CPU when idle)
                task_file = await queue.get_next()

                # Poison pill: None signals graceful shutdown
                if task_file is None:
                    logger.info(f"[{name}] Received shutdown signal")
                    break

                logger.info(f"[{name}] Starting task: {task_file}")
                queue.is_processing = True
                queue.current_task = task_file
                queue._save_state()

                # Execute task
                try:
                    result = await executor.execute_task(task_file)
                    if result.completed_at:
                        duration = (result.completed_at - result.started_at).total_seconds()
                    else:
                        duration = 0
                    logger.info(
                        f"[{name}] Task completed: {task_file} - "
                        f"status={result.status}, "
                        f"duration={duration:.1f}s"
                    )
                except Exception as e:
                    logger.error(f"[{name}] Task failed: {task_file} - {e}")

                # Mark as ready for next task
                queue.current_task = None
                queue.is_processing = False
                queue._save_state()

        except asyncio.CancelledError:
            # Handle cancellation gracefully (normal shutdown)
            logging.info(f"[{name}] Queue processor cancelled, shutting down...")
            # Clean up state before exiting
            queue.current_task = None
            queue.is_processing = False
            queue._save_state()
            # Re-raise to allow proper cleanup
            raise

    def stop(self):
        """Stop the observer and queue processor."""
        logging.info("Stopping monitor...")
        self.running = False

        if not self.project:
            return

        # Send poison pill to queue to signal graceful shutdown
        asyncio.create_task(self.project["queue"].put(None))
        logging.info(f"[{self.project['name']}] Sent shutdown signal to queue")

        # Cancel processor task
        if self.processor_task and not self.processor_task.done():
            self.processor_task.cancel()

        # Stop observer
        if self.project.get("observer"):
            self.project["observer"].stop()

        # Wait for observer to finish (only if it was started)
        if self.project.get("observer") and self.project.get("started", False):
            self.project["observer"].join()

        # Release instance lock
        self.instance_lock.release()
        logging.info(f"Instance lock released: {LOCK_FILE}")

        logging.info("Monitor stopped")


class ProjectTaskQueue:
    """Task queue for a specific project."""

    def __init__(self, project_name: str, project_path: Path, state_dir: Path):
        self.project_name = project_name
        self.project_path = project_path
        self.queue = asyncio.Queue()
        self.current_task = None
        self.is_processing = False
        self.STATE_FILE = state_dir / "queue_state.json"
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    async def put(self, task_file: str):
        """Add a task to the queue."""
        await self.queue.put(task_file)
        logging.info(f"[{self.project_name}] Task queued: {task_file} (queue size: {self.queue.qsize()})")
        self._save_state()

    async def get_next(self) -> str:
        """Get the next task from the queue."""
        task = await self.queue.get()
        logging.info(f"[{self.project_name}] Task retrieved: {task}")
        self._save_state()
        return task

    @property
    def size(self) -> int:
        """Return current queue size."""
        return self.queue.qsize()

    def _load_state(self) -> dict:
        """Load queue state from file."""
        if self.STATE_FILE.exists():
            with open(self.STATE_FILE, 'r') as f:
                return json.load(f)
        return {
            "queue_size": 0,
            "current_task": None,
            "is_processing": False
        }

    def _save_state(self):
        """Save queue state to file."""
        state = {
            "project": self.project_name,
            "queue_size": self.queue.qsize(),
            "current_task": self.current_task,
            "is_processing": self.is_processing
        }
        with open(self.STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)


class TaskFileHandler(FileSystemEventHandler):
    """Handles task file creation events for a specific project."""

    def __init__(self, task_queue: ProjectTaskQueue, project_name: str, project_path: Path, event_loop: asyncio.AbstractEventLoop):
        self.task_queue = task_queue
        self.project_name = project_name
        self.project_path = project_path
        self.event_loop = event_loop

    def on_created(self, event):
        """Called when a file is created."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        logging.info(f"[{self.project_name}] File event detected: {file_path.name}")

        if file_path.match(r"task-????????-??????-*.md"):
            logging.info(f"[{self.project_name}] Task file matches pattern: {file_path.name}")
            try:
                # Add to project's queue (non-blocking)
                future = asyncio.run_coroutine_threadsafe(
                    self.task_queue.put(file_path.name),
                    self.event_loop
                )
                future.result(timeout=5)  # Wait for confirmation
                logging.info(f"[{self.project_name}] Task queued successfully: {file_path.name}")
            except Exception as e:
                logging.error(f"[{self.project_name}] Failed to queue task {file_path.name}: {e}", exc_info=True)
        else:
            logging.debug(f"[{self.project_name}] File does not match task pattern: {file_path.name}")

    def on_moved(self, event):
        """Called when a file is moved/renamed."""
        if event.is_directory:
            return

        dest_path = Path(event.dest_path)
        logging.info(f"[{self.project_name}] File moved/renamed: {dest_path.name}")

        if dest_path.match(r"task-????????-??????-*.md"):
            logging.info(f"[{self.project_name}] Moved task file matches pattern: {dest_path.name}")
            try:
                # Add to project's queue (non-blocking)
                future = asyncio.run_coroutine_threadsafe(
                    self.task_queue.put(dest_path.name),
                    self.event_loop
                )
                future.result(timeout=5)  # Wait for confirmation
                logging.info(f"[{self.project_name}] Moved task queued successfully: {dest_path.name}")
            except Exception as e:
                logging.error(f"[{self.project_name}] Failed to queue moved task {dest_path.name}: {e}", exc_info=True)
        else:
            logging.debug(f"[{self.project_name}] Moved file does not match task pattern: {dest_path.name}")


if __name__ == "__main__":
    monitor = TaskMonitor()
    try:
        monitor.start()
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
        monitor.stop()
    except SystemExit as e:
        # Exit from check_pid_file - don't remove PID file
        sys.exit(e.code)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        monitor.stop()
        sys.exit(1)
