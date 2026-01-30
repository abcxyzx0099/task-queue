import asyncio
import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# System root for monitor code
MONITOR_SYSTEM_ROOT = Path("/home/admin/workspaces/job-monitor")
sys.path.insert(0, str(MONITOR_SYSTEM_ROOT))

from job_executor import JobExecutor
from models import JobStatus

# Configuration
REGISTRY_FILE = Path.home() / ".config" / "job-monitor" / "registered.json"


class MultiProjectMonitor:
    """Monitor multiple projects, each with their own jobs/items directory."""

    def __init__(self):
        self.projects = {}  # {project_name: {path, executor, queue, observer, event_handler}}
        self.running = False
        self.observers = []
        self.event_loop = None
        self.processor_tasks = []  # Track processor tasks for proper cleanup

    def load_registry(self):
        """Load project registry."""
        if not REGISTRY_FILE.exists():
            logging.warning(f"Registry file not found: {REGISTRY_FILE}")
            return {}

        with open(REGISTRY_FILE, 'r') as f:
            registry = json.load(f)

        return registry.get("projects", {})

    def setup_project(self, name: str, config: dict):
        """Setup monitoring for a single project."""
        project_path = Path(config["path"])

        if not project_path.exists():
            logging.error(f"Project path does not exist: {project_path}")
            return False

        # Create directories
        tasks_dir = project_path / "jobs" / "items"
        results_dir = project_path / "jobs" / "results"
        logs_dir = project_path / "jobs" / "logs"
        state_dir = project_path / "jobs" / "state"

        tasks_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        # Create project-specific queue
        queue = ProjectJobQueue(name, project_path, state_dir)

        # Create project-specific executor
        executor = JobExecutor(
            tasks_dir=str(tasks_dir),
            results_dir=str(results_dir),
            project_root=str(project_path)
        )

        self.projects[name] = {
            "path": project_path,
            "executor": executor,
            "queue": queue,
            "observer": None,
            "event_handler": None
        }

        logging.info(f"Project '{name}' configured: {project_path}")
        return True

    def start(self):
        """Start monitoring all projects."""
        # Configure root logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )
        logger = logging.getLogger(__name__)

        logger.info("Starting Multi-Project Job Monitor")

        # Load registry and setup all projects
        projects_config = self.load_registry()

        if not projects_config:
            logger.warning("No projects registered. Add projects with: job-monitor-control register <path>")
            return

        for name, config in projects_config.items():
            if not config.get("enabled", True):
                logger.info(f"Project '{name}' is disabled, skipping")
                continue
            self.setup_project(name, config)

        if not self.projects:
            logger.error("No valid projects configured")
            return

        logger.info(f"Monitoring {len(self.projects)} project(s)")

        # Run the async main function
        asyncio.run(self._run())

    async def _run(self):
        """Main async loop - setup observers and process queues."""
        self.running = True
        self.event_loop = asyncio.get_event_loop()

        # Create observers and event handlers with access to event loop
        for name, project in self.projects.items():
            tasks_dir = project["path"] / "jobs" / "items"
            event_handler = JobFileHandler(
                project["queue"],
                name,
                project["path"],
                self.event_loop
            )
            observer = Observer()
            observer.schedule(event_handler, str(tasks_dir), recursive=False)

            project["observer"] = observer
            project["event_handler"] = event_handler

        # Start all observers
        for name, project in self.projects.items():
            project["observer"].start()
            logging.info(f"Observer started for '{name}': {project['path'] / 'jobs' / 'items'}")

        # Start queue processors for all projects
        await self._run_all_queues()

    async def _run_all_queues(self):
        """Run queue processors for all projects."""
        self.processor_tasks = []

        for name, project in self.projects.items():
            processor = asyncio.create_task(
                self._process_project_queue(name, project)
            )
            self.processor_tasks.append(processor)

        # Wait for all processors, handling cancellation gracefully
        try:
            await asyncio.gather(*self.processor_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            # During shutdown, cancel all processor tasks
            logging.info("Shutting down queue processors...")
            for task in self.processor_tasks:
                if not task.done():
                    task.cancel()
            # Wait for all tasks to complete cancellation
            await asyncio.gather(*self.processor_tasks, return_exceptions=True)
            logging.info("Queue processors stopped")

    async def _process_project_queue(self, name: str, project: dict):
        """Process jobs for a specific project."""
        logger = logging.getLogger(__name__)
        queue = project["queue"]
        executor = project["executor"]

        logger.info(f"Queue processor started for '{name}'")

        try:
            while self.running:
                try:
                    # Wait for next task
                    task_file = await asyncio.wait_for(
                        queue.get_next(),
                        timeout=1.0
                    )

                    logger.info(f"[{name}] Starting job: {task_file}")
                    queue.is_processing = True
                    queue.current_task = task_file
                    queue._save_state()

                    # Execute job
                    try:
                        result = await executor.execute_job(task_file)
                        if result.completed_at:
                            duration = (result.completed_at - result.started_at).total_seconds()
                        else:
                            duration = 0
                        logger.info(
                            f"[{name}] Job completed: {task_file} - "
                            f"status={result.status}, "
                            f"duration={duration:.1f}s"
                        )
                    except Exception as e:
                        logger.error(f"[{name}] Job failed: {task_file} - {e}")

                    # Mark as ready for next job
                    queue.current_task = None
                    queue.is_processing = False
                    queue._save_state()

                    # Small delay before next job
                    await asyncio.sleep(0.5)

                except asyncio.TimeoutError:
                    # No job in queue, continue waiting
                    continue
                except Exception as e:
                    logger.error(f"[{name}] Error processing job: {e}")
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
        """Stop all observers."""
        logging.info("Stopping monitor...")
        self.running = False

        # Cancel all processor tasks first
        for task in self.processor_tasks:
            if not task.done():
                task.cancel()

        # Stop observers
        for name, project in self.projects.items():
            if project.get("observer"):
                project["observer"].stop()

        # Wait for observers to finish
        for project in self.projects.values():
            if project.get("observer"):
                project["observer"].join()

        logging.info("Monitor stopped")


class ProjectJobQueue:
    """Job queue for a specific project."""

    def __init__(self, project_name: str, project_path: Path, state_dir: Path):
        self.project_name = project_name
        self.project_path = project_path
        self.queue = asyncio.Queue()
        self.current_task = None
        self.is_processing = False
        self.STATE_FILE = state_dir / "queue_state.json"
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    async def put(self, job_file: str):
        """Add a job to the queue."""
        await self.queue.put(job_file)
        logging.info(f"[{self.project_name}] Job queued: {job_file} (queue size: {self.queue.qsize()})")
        self._save_state()

    async def get_next(self) -> str:
        """Get the next job from the queue."""
        job = await self.queue.get()
        logging.info(f"[{self.project_name}] Job retrieved: {job}")
        self._save_state()
        return job

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


class JobFileHandler(FileSystemEventHandler):
    """Handles job file creation events for a specific project."""

    def __init__(self, job_queue: ProjectJobQueue, project_name: str, project_path: Path, event_loop: asyncio.AbstractEventLoop):
        self.job_queue = job_queue
        self.project_name = project_name
        self.project_path = project_path
        self.event_loop = event_loop

    def on_created(self, event):
        """Called when a file is created."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        logging.info(f"[{self.project_name}] File event detected: {file_path.name}")

        if file_path.match(r"job-????????-??????-*.md"):
            logging.info(f"[{self.project_name}] Job file matches pattern: {file_path.name}")
            try:
                # Add to project's queue (non-blocking)
                future = asyncio.run_coroutine_threadsafe(
                    self.job_queue.put(file_path.name),
                    self.event_loop
                )
                future.result(timeout=5)  # Wait for confirmation
                logging.info(f"[{self.project_name}] Job queued successfully: {file_path.name}")
            except Exception as e:
                logging.error(f"[{self.project_name}] Failed to queue job {file_path.name}: {e}", exc_info=True)
        else:
            logging.debug(f"[{self.project_name}] File does not match job pattern: {file_path.name}")


if __name__ == "__main__":
    monitor = MultiProjectMonitor()
    try:
        monitor.start()
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
        monitor.stop()
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        monitor.stop()
