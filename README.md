# Task Queue

A task monitoring and execution system that processes task specifications using the Claude Agent SDK. Features event-driven file monitoring with parallel worker architecture.

## Architecture Overview

```
[Task Queue System - v2.0 Directory-Based State with Parallel Workers]

Task Source Directory A          Task Source Directory B          Task Source Directory C
tasks/a/                          tasks/b/                          tasks/c/
[task-a1.md]                      [task-b1.md]                      [task-c1.md]
[task-a2.md]                      [task-b2.md]                      [task-c2.md]
     |                                  |                                  |
     ▼                                  ▼                                  ▼
┌─────────────────┐            ┌─────────────────┐            ┌─────────────────┐
│  Worker Thread  │            │  Worker Thread  │            │  Worker Thread  │
│  for Source A   │            │  for Source B   │            │  for Source C   │
│                 │            │                 │            │                 │
│  Sequential     │            │  Sequential     │            │  Sequential     │
│  FIFO Queue     │            │  FIFO Queue     │            │  FIFO Queue     │
│                 │            │                 │            │                 │
│ task-a1 → a2    │            │ task-b1 → b2    │            │ task-c1 → c2    │
└─────────────────┘            └─────────────────┘            └─────────────────┘
     |                                  |                                  |
     └────────────────┬─────────────────┴────────────────┬─────────────────┘
                      │                                  │
                      ▼                                  ▼
              ┌──────────────────────────────────────────────┐
              │         Project Workspace (single)          │
              │    /home/admin/workspaces/datachat          │
              └──────────────────────────────────────────────┘

Execution Model:
- Within each source: Sequential (one task at a time)
- Across sources: Parallel (multiple workers run simultaneously)
```

## Key Concepts

| Concept | Term | Definition |
|---------|------|------------|
| **1** | **Task Source Directory** | A folder containing task document files. Watched for file changes. |
| **2** | **Task Document** | Individual task specification file (e.g., `task-YYYYMMDD-HHMMSS-description.md`). |
| **3** | **Project Workspace** | The working directory where Claude Agent SDK executes. |
| **4** | **Directory-Based State** | File system is the source of truth. Running tasks marked by `.task-XXX.running` files. |

## Features

### Core Features

| Feature | Description |
|---------|-------------|
| **Event-Driven** | Watchdog detects file changes instantly (no polling delay) |
| **Parallel Workers** | One worker thread per Task Source Directory |
| **Sequential Within Source** | Tasks from same source execute one at a time (FIFO) |
| **Parallel Across Sources** | Different sources execute simultaneously |
| **Directory-Based State** | No state file - filesystem structure is the source of truth |
| **Auto-Load on Create** | Watchdog auto-detects new Task Documents |
| **Manual Run** | Explicit control via `run` command |
| **Unload by Source** | Remove all tasks from a specific source |
| **Claude Agent SDK Integration** | Executes tasks via `/task-worker` skill |
| **Daemon Service** | Runs as systemd user service for continuous processing |

### Execution Model

**Same source:** Sequential FIFO (task-a1 → task-a2 → task-a3)

**Different sources:** Parallel (A-1 and B-1 run simultaneously)

### Task Directories

| Directory | Purpose |
|-----------|---------|
| `{source}/` | Pending task documents (task-*.md) |
| `{source}/.task-XXX.running` | Marker file for task currently executing |
| `{source}/../task-archive/` | Completed task documents |
| `{source}/../task-failed/` | Failed task documents |

### Safety Features

- **Atomic Writes**: Config files use temporary file + atomic replacement
- **File Locking**: fcntl-based locks prevent concurrent modification
- **Running Markers**: `.task-XXX.running` files indicate task in progress
- **Stale Detection**: Orphaned markers are cleaned up automatically
- **Archive Preservation**: Completed/failed task specs preserved in directories
- **Graceful Shutdown**: All workers stop cleanly on SIGTERM/SIGINT

## Installation

### From Source

```bash
cd /home/admin/workspaces/task-queue
pip install -e .
```

### Systemd Service

```bash
# Copy service file
cp task-queue.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable at login
systemctl --user enable task-queue
```

## Quick Start

### 1. Initialize and Configure

```bash
# Initialize configuration
task-queue init

# Load a Task Source Directory
task-queue load --task-source-dir tasks/task-documents --project-workspace /home/admin/workspaces/datachat --source-id main
# Output: ✅ Registered Task Source Directory 'main'
```

### 2. Create a Task Document

Create a file in your Task Source Directory following the naming pattern:
```
task-YYYYMMDD-HHMMSS-description.md
```

Example: `task-20260205-100000-fix-auth-timeout.md`

The watchdog will auto-detect the new task immediately.

### 3. Check status

```bash
task-queue status
```

### 4. Run tasks

```bash
# Manual execution (one cycle)
task-queue run

# Run N cycles
task-queue run --cycles 5

# Run indefinitely (daemon mode)
systemctl --user start task-queue
```

## CLI Commands

### Configuration

```bash
# Initialize configuration
task-queue init

# Load a Task Source Directory (sets workspace if not set)
task-queue load --task-source-dir <path> --project-workspace <path> --source-id <id>

# Remove a Task Source Directory
task-queue unload --source-id <id>

# List Task Source Directories
task-queue list-sources
```

### Task Operations

```bash
# Run tasks (manual execution)
task-queue run [--cycles N]  # N=0 for infinite
```

### Monitoring

```bash
# Show system status
task-queue status
```

## Configuration

Configuration file: `~/.config/task-queue/config.json`

```json
{
  "version": "2.0",
  "project_workspace": "/home/admin/workspaces/datachat",
  "task_source_directories": [
    {
      "id": "main",
      "path": "/home/admin/workspaces/datachat/tasks/task-documents",
      "description": "Main Task Source Directory",
      "added_at": "2026-02-05T10:00:00.000000"
    },
    {
      "id": "experimental",
      "path": "/home/admin/workspaces/datachat/tasks/experimental",
      "description": "Experimental features",
      "added_at": "2026-02-05T10:05:00.000000"
    }
  ],
  "settings": {
    "watch_enabled": true,
    "watch_debounce_ms": 500,
    "watch_patterns": ["task-*.md"],
    "watch_recursive": false,
    "max_attempts": 3,
    "enable_file_hash": true
  },
  "created_at": "2026-02-05T10:00:00.000000",
  "updated_at": "2026-02-05T10:00:00.000000"
}
```

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `watch_enabled` | true | Enable watchdog for file system events |
| `watch_debounce_ms` | 500 | Debounce delay in milliseconds for file events |
| `watch_patterns` | ["task-*.md"] | File patterns to watch |
| `watch_recursive` | false | Watch subdirectories |
| `max_attempts` | 3 | Max execution attempts per task |
| `enable_file_hash` | true | Track file hashes for change detection |

## Directory Structure

```
~/.config/task-queue/          # Configuration directory
└── config.json                  # Main configuration

{project-workspace}/            # Your project workspace
└── tasks/
    ├── task-documents/         # Task Source Directory (pending tasks)
    │   ├── task-001.md
    │   ├── task-002.md
    │   └── .task-001.running   # Marker: task currently executing
    ├── task-archive/           # Completed task documents
    │   ├── task-001.md
    │   └── task-002.md
    ├── task-failed/            # Failed task documents
    │   └── task-003.md
    └── task-queue/             # Result JSON files (flat)
        ├── task-001.json
        └── task-002.json
```

## Task Document Format

### Naming Convention

```
task-YYYYMMDD-HHMMSS-description.md
```

Components:
- `task-` - Required prefix
- `YYYYMMDD` - Date (8 digits)
- `HHMMSS` - Time (6 digits)
- `description` - Hyphen-separated description (optional but recommended)

### Example

```markdown
# Task: Fix authentication timeout

## Task
The authentication system times out after 30 seconds. Investigate and fix the timeout issue.

## Expected Outcome
- Authentication completes within 10 seconds
- Error handling for timeout scenarios
- Unit tests for timeout scenarios
```

## Daemon Service

### Service Management

```bash
# Enable at login
systemctl --user enable task-queue

# Start/stop/restart
systemctl --user start task-queue
systemctl --user stop task-queue
systemctl --user restart task-queue

# Check status
systemctl --user status task-queue
```

### Viewing Logs

```bash
# Follow logs in real-time
journalctl --user -u task-queue -f

# View last 100 lines
journalctl --user -u task-queue -n 100

# View logs since today
journalctl --user -u task-queue --since today
```

### Log Examples

```
Feb 05 10:00:00 task-queue: ============================================================
Feb 05 10:00:00 task-queue: Task Queue Daemon Starting
Feb 05 10:00:00 task-queue: Configuration loaded from: ~/.config/task-queue/config.json
Feb 05 10:00:00 task-queue: Project Workspace: /home/admin/workspaces/datachat
Feb 05 10:00:00 task-queue: Task Source Directories: 2
Feb 05 10:00:00 task-queue:   - main: /home/admin/workspaces/datachat/tasks/task-documents
Feb 05 10:00:00 task-queue:   - experimental: /home/admin/workspaces/datachat/tasks/experimental
Feb 05 10:00:00 task-queue: Spawning 2 worker threads (parallel execution)
Feb 05 10:00:00 task-queue: Processing loop started (event-driven with watchdog)
Feb 05 10:00:01 task-queue: Watchdog event: task-001.md in source 'main'
Feb 05 10:00:01 task-queue: [Worker-main] Executing task: task-001.md
Feb 05 10:00:10 task-queue: [Worker-main] [OK] Completed: task-001.md
```

## Workflow Example

### Complete Workflow

```bash
# 1. Initialize configuration
task-queue init

# 2. Load Task Source Directories
task-queue load --task-source-dir tasks/task-documents --project-workspace /home/admin/workspaces/datachat --source-id main
task-queue load --task-source-dir tasks/experimental --project-workspace /home/admin/workspaces/datachat --source-id experimental

# 3. Check registered sources
task-queue list-sources

# 4. Create task documents (watchdog auto-detects them)
# Create files like: task-20260205-120000-feature-x.md

# 5. Run tasks (manual)
task-queue run

# OR start daemon for automatic processing
systemctl --user start task-queue

# 6. Monitor progress
journalctl --user -u task-queue -f
```

### Watchdog vs Manual Running

| Approach | When to Use |
|----------|-------------|
| **Watchdog (daemon)** | Production, continuous operation |
| **Manual Run** | One-off processing, testing, specific cycles |

## Task Execution

### Two-Agent Workflow

Each task is executed using a two-agent workflow via the `/task-worker` skill:

1. **Implementation Agent** - Executes the task specification
2. **Auditor Agent** - Reviews and verifies the implementation
3. **Automatic Iteration** - Re-runs if audit fails (max 3 iterations)
4. **Safety Checkpoint** - Git commit before starting
5. **Final Commit** - Commits approved work when complete

### Execution Flow

```
                    ┌─────────────────┐
                    │  Task Document  │
                    │  task-XXX.md    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Create .running │
                    │  marker file    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Execute via    │
                    │  Claude SDK     │
                    │  (2 agents)     │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Success?       │
                    └────┬──────┬─────┘
                         │ Yes  │ No
                         │      │
                         ▼      ▼
                  Move to    Move to
               task-archive/  task-failed/
                         │
                         ▼
                  Remove .running
                  marker file
```

## Troubleshooting

### Common Issues

#### Issue: "No Project Workspace set"

```bash
# Solution: Use the load command with --project-workspace
task-queue load --task-source-dir <path> --project-workspace /path/to/project --source-id <id>
```

#### Issue: "No Task Source Directories configured"

```bash
# Solution: Load a Task Source Directory
task-queue load --task-source-dir <path> --project-workspace /path/to/project --source-id <id>
```

#### Issue: Daemon shows "No pending tasks"

```bash
# Solution: Create task documents in the Task Source Directory
# Watchdog will auto-detect new files
```

#### Issue: Task stuck with .running marker

```bash
# Solution: The daemon auto-detects stale markers and cleans them up
# To manually clear: remove the .task-XXX.running file
rm tasks/task-documents/.task-XXX.running
```

#### Issue: Task failed

```bash
# Check failed task document
cat tasks/task-failed/task-XXX.md

# Check result file
cat tasks/task-queue/task-XXX.json

# View daemon logs
journalctl --user -u task-queue -n 50
```

## Development

### Project Structure

```
task-queue/
├── task_queue/
│   ├── __init__.py           # Package exports
│   ├── atomic.py             # AtomicFileWriter, FileLock
│   ├── cli.py                # CLI commands
│   ├── config.py             # ConfigManager
│   ├── daemon.py             # Daemon service with parallel workers
│   ├── executor.py           # Claude Agent SDK executor
│   ├── models.py             # Pydantic models (v2.0)
│   ├── scanner.py            # Task document scanner
│   └── task_runner.py        # Task execution logic
├── tests/                    # Unit tests
│   ├── conftest.py           # Test fixtures
│   ├── test_atomic.py
│   ├── test_config.py
│   ├── test_daemon_parallel.py  # Parallel execution tests
│   ├── test_executor.py
│   ├── test_models.py
│   ├── test_scanner.py
│   └── test_task_runner.py      # Task runner tests
├── README.md                 # This file
├── pyproject.toml           # Python package config
└── task-queue.service       # Systemd service file
```

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest --cov=task_queue tests/

# Run specific test file
python -m pytest tests/test_daemon_parallel.py -v
```

## License

MIT License - See LICENSE file for details.

## Contributing

This is an internal project for the DataChat system. For questions or issues, please contact the development team.
