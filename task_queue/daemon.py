"""
Background daemon for task processing.

Runs as a systemd user service, processing queued tasks.
"""

import os
import sys
import signal
import time
import logging
from pathlib import Path
from datetime import datetime

from task_queue.monitor import create_queue
from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE


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


class TaskMonitorDaemon:
    """
    Background daemon for task processing.

    Processes queued tasks (no auto-scanning).
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
                # Recreate processor with new config
                self.monitor._processor = None
            logger.info("Configuration reloaded")
        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")

    def start(self) -> None:
        """Start the daemon."""
        logger.info("="*60)
        logger.info("Task Monitor Daemon Starting")
        logger.info("="*60)

        # Create monitor
        try:
            self.monitor = create_queue(config_file=self.config_file)
        except Exception as e:
            logger.error(f"Failed to create monitor: {e}")
            sys.exit(1)

        # Log configuration
        config = self.monitor.config_manager.config
        spec_dirs = config.spec_directories

        logger.info(f"Configuration loaded from: {self.config_file}")
        logger.info(f"Project path: {config.project_path}")
        logger.info(f"Spec directories: {len(spec_dirs)}")

        for spec_dir in spec_dirs:
            logger.info(f"  - {spec_dir.id}: {spec_dir.path}")

        logger.info(f"Processing interval: {config.settings.processing_interval}s")

        # Start processing loop
        self.running = True
        self._run_loop()

    def _run_loop(self) -> None:
        """Main processing loop."""
        config = self.monitor.config_manager.config
        processing_interval = config.settings.processing_interval

        logger.info("Processing loop started (no auto-scanning)")
        logger.info("Use 'task-queue load' to scan for tasks")

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

                # Wait for next cycle
                logger.info(f"Cycle {cycle} completed, waiting {processing_interval}s...")
                logger.info("-"*60)

                # Sleep with interrupt check
                for _ in range(processing_interval * 10):
                    if self.shutdown_requested:
                        break
                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"Error in processing cycle: {e}", exc_info=True)

                # Wait before retry
                logger.info("Waiting 60s before retry...")
                time.sleep(60)

        self._shutdown()

    def _shutdown(self) -> None:
        """Perform graceful shutdown."""
        logger.info("="*60)
        logger.info("Task Monitor Daemon Shutting Down")
        logger.info("="*60)

        self.running = False

        if self.monitor:
            self.monitor.stop()

        logger.info("Daemon stopped")


def main():
    """Daemon entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Task Monitor Daemon"
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
    daemon = TaskMonitorDaemon(
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
