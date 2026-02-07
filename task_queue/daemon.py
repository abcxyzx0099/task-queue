"""
Background daemon for task processing with watchdog support.

Runs as a systemd user service, processing queued tasks with event-driven file monitoring.

Simplified architecture: No state file - directory structure is the source of truth.

Parallel execution: One worker thread per Task Source Directory.
- Sequential execution within each source
- Parallel execution across different sources
"""

import os
import sys
import signal
import logging
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from task_queue.task_runner import TaskRunner
from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.watchdog import WatchdogManager
from task_queue.models import Queue


# Worker timeouts
WORKER_KEEPALIVE_TIMEOUT = 60  # seconds
WORKER_RETRY_DELAY = 10  # seconds
WORKER_CYCLE_PAUSE = 0.1  # seconds


# Configure logging
log_format = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Suppress verbose watchdog library logging
logging.getLogger("watchdog.observers.inotify_buffer").setLevel(logging.WARNING)
logging.getLogger("watchdog.observers").setLevel(logging.WARNING)

logger = logging.getLogger("task-queue")


class TaskQueueDaemon:
    """
    Background daemon for task processing with watchdog.

    Simplified architecture - no state file, directory-based state.

    Parallel execution: One worker thread per Task Source Directory.
    - Sequential execution within each source
    - Parallel execution across different sources
    """

    def __init__(
        self,
        config_file: Path = None
    ):
        """
        Initialize daemon.

        Args:
            config_file: Path to configuration file
        """
        self.config_file = config_file or DEFAULT_CONFIG_FILE

        self.task_runner: TaskRunner = None
        self.running = False
        self.shutdown_requested = False

        # Watchdog manager
        self.watchdog_manager: WatchdogManager = None

        # Worker threads (one per Task Source Directory)
        self._worker_threads: Dict[str, threading.Thread] = {}
        self._worker_lock = threading.Lock()

        # Per-source event for signaling when tasks are added to that source
        self._source_events: Dict[str, threading.Event] = {}
        self._events_lock = threading.Lock()

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGHUP, self._reload_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True
        # Wake up all waiting worker threads
        with self._events_lock:
            for event in self._source_events.values():
                event.set()

    def _reload_handler(self, signum, frame):
        """Handle reload signal (SIGHUP)."""
        logger.info("Received SIGHUP, reloading configuration...")
        try:
            # For now, just log - full reload would require restarting workers
            # This is a complex operation that needs careful coordination
            logger.info("Configuration reload not yet implemented for parallel mode")
            logger.info("Use 'systemctl --user restart task-queue.service' instead")
        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")

    def _setup_watchdog(self) -> None:
        """Setup watchdog for all configured Task Source Directories."""
        if self.watchdog_manager is None:
            self.watchdog_manager = WatchdogManager(self._on_watchdog_event)

        config_manager = ConfigManager(self.config_file)
        config = config_manager.config

        # Get settings
        settings = config.settings
        watch_enabled = settings.watch_enabled
        watch_debounce_ms = settings.watch_debounce_ms
        watch_patterns = settings.watch_patterns
        watch_recursive = settings.watch_recursive

        if not watch_enabled:
            logger.info("Watchdog monitoring is disabled")
            return

        # Get pattern from list (use first)
        pattern = watch_patterns[0] if watch_patterns else "task-*.md"

        # Get all source directories
        queues = config.queues

        if not queues:
            logger.warning("No Task Source Directories configured for watchdog")
            return

        # Create per-source events
        with self._events_lock:
            for queue in queues:
                if queue.id not in self._source_events:
                    self._source_events[queue.id] = threading.Event()

        # Add watcher for each source directory
        for queue in queues:
            try:
                self.watchdog_manager.add_source(
                    queue=queue,
                    debounce_ms=watch_debounce_ms,
                    pattern=pattern
                )
            except Exception as e:
                logger.error(
                    f"Failed to setup watcher for '{queue.id}': {e}",
                    exc_info=True
                )

    def _on_watchdog_event(self, task_doc_file: str, source_id: str) -> None:
        """
        Handle watchdog file event (task created or modified).

        Signals the specific worker thread for this source.

        Args:
            task_doc_file: Path to Task Document file
            source_id: Task Source Directory ID
        """
        logger.debug(f"Watchdog event: {Path(task_doc_file).name} in '{source_id}'")

        # Signal the specific worker for this source
        with self._events_lock:
            if source_id in self._source_events:
                self._source_events[source_id].set()

    def start(self) -> None:
        """Start the daemon."""
        logger.info("="*60)
        logger.info("Task Queue Daemon Starting")
        logger.info("="*60)

        # Load configuration
        try:
            config_manager = ConfigManager(self.config_file)
            config = config_manager.config
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)

        # Log configuration
        logger.info(f"Project Workspace: {config.project_workspace}")

        if not config.project_workspace:
            logger.error("No Project Workspace set. Use 'task-queue load' to set up the workspace")
            sys.exit(1)

        # Create task runner
        self.task_runner = TaskRunner(
            project_workspace=config.project_workspace
        )

        queues = config.queues
        logger.info(f"Task Source Directories: {len(queues)}")

        # Setup watchdog
        self._setup_watchdog()

        # Log watchdog status
        if self.watchdog_manager:
            watched = self.watchdog_manager.get_watched_sources()
            logger.info(f"Monitoring {len(watched)} source(s)")

        # Start processing loop
        self.running = True
        self._run_loop(queues)

    def _run_loop(self, queues: List[Queue]) -> None:
        """
        Main processing loop - spawns worker threads per source directory.

        Each worker thread processes tasks from its source sequentially.
        Different sources run in parallel.

        Args:
            queues: List of Task Source Directories to monitor
        """
        # Create and start one worker thread per source directory
        for queue in queues:
            # Create event for this source
            with self._events_lock:
                if queue.id not in self._source_events:
                    self._source_events[queue.id] = threading.Event()

            # Create and start worker thread
            worker = threading.Thread(
                target=self._worker_loop,
                args=(source_dir,),
                name=f"Worker-{queue.id}",
                daemon=False  # Non-daemon threads keep the process running
            )

            with self._worker_lock:
                self._worker_threads[queue.id] = worker

            worker.start()

        # Wait for all workers to complete
        for source_id, worker in list(self._worker_threads.items()):
            worker.join()

        logger.info("All worker threads stopped")

    def _worker_loop(self, queue: Queue) -> None:
        """
        Worker loop for a single Task Source Directory.

        Each worker processes tasks from its own source sequentially.
        Multiple workers run in parallel for different sources.

        Args:
            queue: The Queue to process
        """
        logger.info(f"[{queue.id}] Worker started")

        # Get this source's event
        with self._events_lock:
            source_event = self._source_events.get(queue.id)
            if not source_event:
                logger.error(f"[{queue.id}] No event found for source")
                return

        while self.running and not self.shutdown_requested:
            try:
                # Clear the event before processing
                source_event.clear()

                # Pick next task from THIS source only
                task_file = self.task_runner.pick_next_task_from_queue(queue)

                # Check if shutdown requested
                if self.shutdown_requested:
                    break

                if task_file:
                    # Execute the task
                    logger.info(f"[{queue.id}] Executing: {task_file.name}")
                    result = self.task_runner.execute_task(task_file, queue)
                    logger.info(f"[{queue.id}] Task completed: {result['status']}")
                    if result.get("error"):
                        logger.warning(f"[{queue.id}] Error: {result['error']}")
                else:
                    # No pending tasks - wait for watchdog event
                    source_event.wait(timeout=WORKER_KEEPALIVE_TIMEOUT)

                # Brief pause before next cycle
                time.sleep(WORKER_CYCLE_PAUSE)

            except Exception as e:
                logger.error(f"[{queue.id}] Error in worker loop: {e}", exc_info=True)

                # Wait before retry
                logger.info(f"[{queue.id}] Waiting {WORKER_RETRY_DELAY}s before retry...")
                source_event.wait(timeout=WORKER_RETRY_DELAY)

        logger.info(f"[{queue.id}] Worker stopped")

    def _shutdown(self) -> None:
        """Perform graceful shutdown."""
        logger.info("="*60)
        logger.info("Task Queue Daemon Shutting Down")
        logger.info("="*60)

        self.running = False
        self.shutdown_requested = True

        # Wake up all worker threads
        with self._events_lock:
            for event in self._source_events.values():
                event.set()

        # Wait for all workers to stop
        logger.info("Waiting for worker threads to stop...")
        for source_id, worker in list(self._worker_threads.items()):
            if worker.is_alive():
                worker.join(timeout=5.0)
                if worker.is_alive():
                    logger.warning(f"Worker '{source_id}' did not stop gracefully")

        # Stop watchdog
        if self.watchdog_manager:
            logger.info("Stopping watchdog...")
            self.watchdog_manager.stop_all()

        logger.info("Daemon stopped")


def main():
    """Daemon entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Task Queue Daemon (Directory-Based State)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to configuration file"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single cycle and exit"
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in foreground (not as daemon)"
    )

    args = parser.parse_args()

    # Create daemon
    daemon = TaskQueueDaemon(
        config_file=args.config
    )

    if args.once:
        # Single cycle mode
        logger.info("Running single cycle...")
        daemon.start()
        logger.info("Single cycle completed")
    else:
        # Normal daemon mode
        daemon.start()


if __name__ == "__main__":
    main()
