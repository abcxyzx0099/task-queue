"""
Background daemon for task processing with watchdog support.

Runs as a systemd user service, processing queued tasks with event-driven file monitoring.
"""

import os
import sys
import signal
import logging
from pathlib import Path
from datetime import datetime

from task_queue.monitor import create_queue
from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.watchdog import WatchdogManager
from task_queue.models import TaskSource


# Configure logging
log_format = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("task-queue")


class TaskQueueDaemon:
    """
    Background daemon for task processing with watchdog.

    Uses file system events for instant task detection (no polling).
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

        self.monitor = None
        self.running = False
        self.shutdown_requested = False

        # Watchdog manager
        self.watchdog_manager: WatchdogManager = None

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGHUP, self._reload_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True

    def _reload_handler(self, signum, frame):
        """Handle reload signal (SIGHUP)."""
        logger.info("Received SIGHUP, reloading configuration...")
        try:
            if self.monitor:
                self.monitor.config_manager.reload()

                # Restart watchdog with new config
                self._setup_watchdog()

                # Recreate processor with new config
                self.monitor._processor = None

            logger.info("Configuration reloaded")
        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")

    def _setup_watchdog(self) -> None:
        """Setup watchdog for all configured Task Source Directories."""
        if self.watchdog_manager is None:
            self.watchdog_manager = WatchdogManager(self._on_watchdog_event)

        config = self.monitor.config_manager.config

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
        source_dirs = config.task_source_directories

        if not source_dirs:
            logger.warning("No Task Source Directories configured for watchdog")
            return

        # Add watcher for each source directory
        for source_dir in source_dirs:
            try:
                self.watchdog_manager.add_source(
                    source_dir=source_dir,
                    debounce_ms=watch_debounce_ms,
                    pattern=pattern
                )
                logger.info(
                    f"Watching Task Source Directory '{source_dir.id}': {source_dir.path}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to setup watcher for '{source_dir.id}': {e}",
                    exc_info=True
                )

    def _on_watchdog_event(self, task_doc_file: str, source_id: str) -> None:
        """
        Handle watchdog file event (task created or modified).

        Args:
            task_doc_file: Path to Task Document file
            source_id: Task Source Directory ID
        """
        logger.info(f"Watchdog event: {task_doc_file} in source '{source_id}'")

        try:
            processor = self.monitor.get_processor()

            if processor:
                # Load the task
                result = processor.load_single_task(
                    task_doc_file=task_doc_file,
                    source_id=source_id,
                    source=TaskSource.WATCHDOG
                )

                if result:
                    logger.info(f"✅ Auto-loaded task: {Path(task_doc_file).name}")
                else:
                    logger.debug(f"Task already exists: {Path(task_doc_file).name}")

        except Exception as e:
            logger.error(
                f"Error handling watchdog event for {task_doc_file}: {e}",
                exc_info=True
            )

    def start(self) -> None:
        """Start the daemon."""
        logger.info("="*60)
        logger.info("Task Queue Daemon Starting")
        logger.info("="*60)

        # Create monitor
        try:
            self.monitor = create_queue(config_file=self.config_file)
        except Exception as e:
            logger.error(f"Failed to create monitor: {e}")
            sys.exit(1)

        # Log configuration
        config = self.monitor.config_manager.config

        logger.info(f"Configuration loaded from: {self.config_file}")
        logger.info(f"Project Workspace: {config.project_workspace}")
        logger.info(f"Task Source Directories: {len(config.task_source_directories)}")

        for source_dir in config.task_source_directories:
            logger.info(f"  - {source_dir.id}: {source_dir.path}")

        # Setup watchdog
        self._setup_watchdog()

        # Log watchdog status
        if self.watchdog_manager:
            watched = self.watchdog_manager.get_watched_sources()
            logger.info(f"Watchdog monitoring: {len(watched)} sources")

        # Start processing loop
        self.running = True
        self._run_loop()

    def _run_loop(self) -> None:
        """Main processing loop (event-driven, no polling)."""
        config = self.monitor.config_manager.config

        logger.info("Processing loop started (event-driven with watchdog)")
        logger.info("Use 'task-queue load' or 'task-queue reload' for manual loading")

        cycle = 0

        while self.running and not self.shutdown_requested:
            try:
                cycle += 1
                logger.info("-"*60)
                logger.info(f"Cycle {cycle} started at {datetime.now().isoformat()}")

                # Process tasks (no auto-loading)
                self.monitor.process_tasks()

                # Check if shutdown requested
                if self.shutdown_requested:
                    break

                # Check if there are more tasks to process
                processor = self.monitor.get_processor()
                if processor and processor.state.get_total_pending_count() == 0:
                    logger.info("No more pending tasks, waiting for watchdog events...")
                    # Wait for watchdog events (no sleep, just wait for signal)
                    # In a real implementation, we might use a condition variable
                    # to wait for watchdog events

                logger.info(f"Cycle {cycle} completed")
                logger.info("-"*60)

                # Wait briefly before next cycle
                # This is just a short pause to avoid CPU spinning
                # Actual task detection happens via watchdog events
                import time
                for _ in range(100):  # 10 seconds with interrupt check
                    if self.shutdown_requested:
                        break
                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"Error in processing cycle: {e}", exc_info=True)

                # Wait before retry
                logger.info("Waiting 60s before retry...")
                import time
                time.sleep(60)

        self._shutdown()

    def _shutdown(self) -> None:
        """Perform graceful shutdown."""
        logger.info("="*60)
        logger.info("Task Queue Daemon Shutting Down")
        logger.info("="*60)

        self.running = False

        # Stop watchdog
        if self.watchdog_manager:
            logger.info("Stopping watchdog...")
            self.watchdog_manager.stop_all()

        # Stop monitor
        if self.monitor:
            self.monitor.stop()

        logger.info("Daemon stopped")


def main():
    """Daemon entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Task Queue Daemon"
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
        daemon.monitor = create_queue(
            config_file=args.config
        )
        daemon.monitor.process_tasks()
        logger.info("Single cycle completed")
    else:
        # Normal daemon mode
        daemon.start()


if __name__ == "__main__":
    main()
