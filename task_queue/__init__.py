"""
Task Queue - Directory-based state system with watchdog support.

Scans Task Source Directories and executes tasks via Claude Agent SDK.

Architecture: No state file - directory structure is the source of truth.
- tasks/task-documents/  - pending tasks
- tasks/task-archive/    - completed tasks
- tasks/task-failed/    - failed tasks
- .task-XXX.running     - marker file for running tasks
"""

__version__ = "2.0.0"
__author__ = "DataChat Project"

from task_queue.models import (
    TaskSourceDirectory,
    QueueConfig,
    QueueSettings,
    DiscoveredTask,
)

from task_queue.config import ConfigManager, DEFAULT_CONFIG_FILE
from task_queue.scanner import TaskScanner
from task_queue.executor import SyncTaskExecutor, create_executor
from task_queue.task_runner import TaskRunner
from task_queue.watchdog import WatchdogManager, TaskDocumentWatcher

__all__ = [
    # Models
    "TaskSourceDirectory",
    "QueueConfig",
    "QueueSettings",
    "DiscoveredTask",
    # Config
    "ConfigManager",
    "DEFAULT_CONFIG_FILE",
    # Components
    "TaskScanner",
    "SyncTaskExecutor",
    "create_executor",
    "TaskRunner",
    "WatchdogManager",
    "TaskDocumentWatcher",
]
