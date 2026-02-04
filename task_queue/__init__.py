"""
Task Queue - Single project path, multiple spec directories queue system.

Loads tasks from configured spec directories and executes them
via Claude Agent SDK with the /task-worker skill.
"""

__version__ = "1.0.0"
__author__ = "DataChat Project"

from task_queue.models import (
    TaskStatus,
    Task,
    TaskResult,
    QueueState,
    Statistics as _Statistics,
    SpecDirectory,
    QueueConfig,
    QueueSettings,
    DiscoveredTask,
    SystemStatus,
    SpecDirectoryStatus,
)

# Backward compatibility alias
ProjectStatistics = _Statistics

from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.atomic import AtomicFileWriter, FileLock
from task_queue.scanner import TaskScanner
from task_queue.executor import SyncTaskExecutor, create_executor
from task_queue.processor import TaskProcessor
from task_queue.monitor import TaskQueue, create_queue

__all__ = [
    # Models
    "TaskStatus",
    "Task",
    "TaskResult",
    "QueueState",
    "Statistics",
    "SpecDirectory",
    "QueueConfig",
    "QueueSettings",
    "DiscoveredTask",
    "SystemStatus",
    "SpecDirectoryStatus",
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
]
