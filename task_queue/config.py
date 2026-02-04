"""
Configuration management for task queue.

Handles loading, saving, and updating queue configuration.
"""

from pathlib import Path
from typing import Optional, List

from task_queue.models import QueueConfig, SpecDirectory
from task_queue.atomic import AtomicFileWriter, FileLock


# Default configuration paths
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "task-queue"
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

    def _load_config(self) -> QueueConfig:
        """Load configuration from file or create default."""
        data = AtomicFileWriter.read_json(self.config_file)

        if data is None:
            return self._create_default_config()

        try:
            return QueueConfig(**data)
        except Exception as e:
            print(f"Warning: Invalid config file, using defaults: {e}")
            return self._create_default_config()

    def _create_default_config(self) -> QueueConfig:
        """Create default configuration."""
        return QueueConfig()

    def save_config(self) -> None:
        """Save configuration atomically with locking."""
        if not self.lock.acquire(timeout=5):
            raise RuntimeError("Could not acquire config lock")

        try:
            self.config.updated_at = self.config.updated_at
            AtomicFileWriter.write_json(self.config_file, self.config.model_dump(), indent=2)
        finally:
            self.lock.release()

    def reload(self) -> None:
        """Reload configuration from disk."""
        self.config = self._load_config()

    # Project path management

    def set_project_path(self, path: str) -> None:
        """
        Set the project path (replaces any existing path).

        Args:
            path: Path to project root directory

        Raises:
            ValueError: If path doesn't exist or is not a directory
        """
        self.config.set_project_path(path)
        self.save_config()

    def get_project_path(self) -> Optional[str]:
        """Get the current project path."""
        return self.config.project_path

    def clear_project_path(self) -> None:
        """Clear the project path."""
        self.config.project_path = None
        self.save_config()

    # Spec directory management

    def add_spec_directory(
        self,
        path: str,
        id: str,
        description: str = ""
    ) -> SpecDirectory:
        """
        Add a spec directory to monitor.

        Args:
            path: Path to task specification directory
            id: Unique identifier for this spec directory
            description: Optional description

        Returns:
            The created SpecDirectory

        Raises:
            ValueError: If path doesn't exist or ID already exists
        """
        spec_dir = self.config.add_spec_directory(
            path=path,
            id=id,
            description=description
        )
        self.save_config()
        return spec_dir

    def remove_spec_directory(self, spec_id: str) -> bool:
        """
        Remove a spec directory from monitoring.

        Args:
            spec_id: Spec directory ID to remove

        Returns:
            True if removed, False if not found
        """
        result = self.config.remove_spec_directory(spec_id)

        if result:
            self.save_config()

        return result

    def list_spec_directories(self, enabled_only: bool = False) -> List[SpecDirectory]:
        """
        List configured spec directories.

        Args:
            enabled_only: Ignored (kept for backward compatibility)

        Returns:
            List of spec directories
        """
        return self.config.spec_directories

    def get_spec_directory(self, spec_id: str) -> Optional[SpecDirectory]:
        """Get spec directory by ID."""
        return self.config.get_spec_directory(spec_id)

    # Settings management

    def update_settings(self, **kwargs) -> None:
        """
        Update global monitor settings.

        Args:
            **kwargs: Settings to update
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
