"""
Configuration management for task-monitor.

Handles loading, saving, and updating monitor configuration.
"""

from pathlib import Path
from typing import Optional, List

from task_queue.models import MonitorConfig, Queue
from task_queue.file_utils import AtomicFileWriter, FileLock


# Default configuration paths
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "task-monitor"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


class ConfigManager:
    """
    Manages task monitor configuration.

    Handles loading configuration from disk, making updates,
    and persisting changes atomically.
    """

    def __init__(self, config_file: Optional[Path] = None):
        """
        Initialize configuration manager.

        Args:
            config_file: Path to configuration file. Defaults to ~/.config/task-monitor/config.json
        """
        self.config_file = Path(config_file) if config_file else DEFAULT_CONFIG_FILE
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        # Lock file for config access
        self.lock = FileLock(self.config_file.with_suffix('.lock'))

        # Load or create default config
        self.config = self._load_config()

    def _load_config(self) -> MonitorConfig:
        """Load configuration from file or create default."""
        data = AtomicFileWriter.read_json(self.config_file)

        if data is None:
            return self._create_default_config()

        try:
            # Handle migration from old config format
            if "task_source_directories" in data:
                data["queues"] = data.pop("task_source_directories")
            if "QueueSettings" in str(data.get("settings", {})):
                # QueueSettings -> MonitorSettings is just a rename
                pass
            return MonitorConfig(**data)
        except Exception as e:
            print(f"Warning: Invalid config file, using defaults: {e}")
            return self._create_default_config()

    def _create_default_config(self) -> MonitorConfig:
        """Create default configuration."""
        return MonitorConfig()

    def save_config(self) -> None:
        """Save configuration atomically with locking."""
        if not self.lock.acquire(timeout=5):
            raise RuntimeError("Could not acquire config lock")

        try:
            AtomicFileWriter.write_json(self.config_file, self.config.model_dump(), indent=2)
        finally:
            self.lock.release()

    def reload(self) -> None:
        """Reload configuration from disk."""
        self.config = self._load_config()

    # Project workspace management

    def set_project_workspace(self, path: str) -> None:
        """
        Set the project workspace (replaces any existing path).

        Args:
            path: Path to project root directory

        Raises:
            ValueError: If path doesn't exist or is not a directory
        """
        self.config.set_project_workspace(path)
        self.save_config()

    def get_project_workspace(self) -> Optional[str]:
        """Get the current project workspace path."""
        return self.config.project_workspace

    # Queue management

    def add_queue(
        self,
        path: str,
        id: str,
        description: str = ""
    ) -> Queue:
        """
        Add a Queue to monitor.

        Args:
            path: Path to the Queue directory (contains pending/, completed/, failed/, results/)
            id: Unique identifier for this Queue
            description: Optional description

        Returns:
            The created Queue

        Raises:
            ValueError: If path doesn't exist or ID already exists
        """
        queue = self.config.add_queue(
            path=path,
            id=id,
            description=description
        )
        self.save_config()
        return queue

    def remove_queue(self, queue_id: str) -> bool:
        """
        Remove a Queue from monitoring.

        Args:
            queue_id: Queue ID to remove

        Returns:
            True if removed, False if not found
        """
        result = self.config.remove_queue(queue_id)

        if result:
            self.save_config()

        return result

    def list_queues(self) -> List[Queue]:
        """
        List configured Queues.

        Returns:
            List of Queues
        """
        return self.config.queues

    def get_queue(self, queue_id: str) -> Optional[Queue]:
        """Get Queue by ID."""
        return self.config.get_queue(queue_id)

    # Settings management

    def update_settings(self, **kwargs) -> None:
        """
        Update global monitor settings.

        Args:
            **kwargs: Settings to update (watch_enabled, watch_debounce_ms, etc.)
        """
        for key, value in kwargs.items():
            if hasattr(self.config.settings, key):
                setattr(self.config.settings, key, value)
            else:
                raise ValueError(f"Unknown setting: {key}")

        self.save_config()

    # Lock management for external access

    def acquire_lock(self, timeout: float = 10.0) -> bool:
        """Acquire configuration lock."""
        return self.lock.acquire(timeout=timeout)

    def release_lock(self) -> None:
        """Release configuration lock."""
        self.lock.release()


def get_default_config_manager() -> ConfigManager:
    """Get the default configuration manager."""
    return ConfigManager(DEFAULT_CONFIG_FILE)
