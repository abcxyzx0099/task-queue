"""
Task Queue - Per-source task queue system with watchdog support.

Loads tasks from multiple Task Source Directories and executes them
via Claude Agent SDK with the /task-worker skill.
"""

__version__ = "2.0.0"
__author__ = "DataChat Project"

from task_queue.models import (
    TaskStatus,
    Task,
    TaskResult,
    QueueState,
    SourceState,
    SourceStatistics,
    SourceProcessingState,
    CoordinatorState,
    GlobalStatistics,
    TaskSourceDirectory,
    QueueConfig,
    QueueSettings,
    DiscoveredTask,
    SystemStatus,
    TaskSourceDirectoryStatus,
)

# Backward compatibility aliases
Statistics = SourceStatistics
TaskDocDirectory = TaskSourceDirectory
TaskDocDirectoryStatus = TaskSourceDirectoryStatus
ProjectStatistics = GlobalStatistics

from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.atomic import AtomicFileWriter, FileLock
from task_queue.scanner import TaskScanner
from task_queue.executor import SyncTaskExecutor, create_executor
from task_queue.processor import TaskProcessor
from task_queue.monitor import TaskQueue, create_queue
from task_queue.watchdog import WatchdogManager, TaskDocumentWatcher
from task_queue.coordinator import SourceCoordinator

__all__ = [
    # Models
    "TaskStatus",
    "Task",
    "TaskResult",
    "QueueState",
    "SourceState",
    "SourceStatistics",
    "SourceProcessingState",
    "CoordinatorState",
    "GlobalStatistics",
    "TaskSourceDirectory",
    "QueueConfig",
    "QueueSettings",
    "DiscoveredTask",
    "SystemStatus",
    "TaskSourceDirectoryStatus",
    # Backward compatibility
    "Statistics",
    "TaskDocDirectory",
    "TaskDocDirectoryStatus",
    "ProjectStatistics",
    # Config
    "ConfigManager",
    "DEFAULT_CONFIG_FILE",
    # Utilities
    "AtomicFileWriter",
    "FileLock",
    # Components
    "TaskScanner",
    "SyncTaskExecutor",
    "create_executor",
    "TaskProcessor",
    "TaskQueue",
    "create_queue",
    # New components
    "WatchdogManager",
    "TaskDocumentWatcher",
    "SourceCoordinator",
]
