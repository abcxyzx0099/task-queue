# Task Queue

A task monitoring and execution system that processes task specifications using the Claude Agent SDK. Features event-driven file monitoring with parallel worker architecture and lock file-based running task tracking.

## Architecture Overview

```
[Task Queue System - v2.1 Directory-Based State with Parallel Workers & Lock Files]

Task Source Directory A          Task Source Directory B
tasks/a/                          tasks/b/
[task-a1.md]                      [task-b1.md]
[.task-a1.lock] ← Running        [task-b2.md]
[task-a2.md]
     │                                  │
     ▼                                  ▼
┌─────────────────┐            ┌─────────────────┐
│  Worker Thread  │            │  Worker Thread  │
│  for Source A   │            │  for Source B   │
│                 │            │                 │
│  Sequential     │            │  Sequential     │
│  FIFO Queue     │            │  FIFO Queue     │
│                 │            │                 │
│ task-a1 → a2    │            │ task-b1 → b2    │
└─────────────────┘            └─────────────────┘
     │                                  │
     └────────────────┬─────────────────┘
                      │
                      ▼
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
| **4** | **Directory-Based State** | File system is the source of truth. Lock files track running tasks. |

## Features

### Core Features

| Feature | Description |
|---------|-------------|
| **Event-Driven** | Watchdog detects file changes instantly (no polling delay) |
| **Parallel Workers** | One worker thread per Task Source Directory |
| **Sequential Within Source** | Tasks from same source execute one at a time (FIFO) |
| **Parallel Across Sources** | Different sources execute simultaneously |
| **Directory-Based State** | No state file - filesystem structure is the source of truth |
| **Lock File Tracking** | `.task-XXX.lock` files track running tasks with metadata |
| **JSON Result Files** | Captures execution metadata, cost, token usage per task |
| **Auto-Load on Create** | Watchdog auto-detects new Task Documents |
| **Claude Agent SDK Integration** | Executes tasks via `/task-worker` skill |
| **Daemon Service** | Runs as systemd user service for continuous processing |

### Execution Model

**Same source:** Sequential FIFO (task-a1 → task-a2 → task-a3)

**Different sources:** Parallel (A-1 and B-1 run simultaneously)

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│              ONE DAEMON PROCESS (PID-locked)            │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Thread 1     │  │ Thread 2     │  │ Thread 3     │ │
│  │ ↓            │  │ ↓            │  │ ↓            │ │
│  │ Directory A  │  │ Directory B  │  │ Directory C  │ │
│  │ (Sequential) │  │ (Sequential) │  │ (Sequential) │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│           1 Thread per Directory (1:1 mapping)          │
└─────────────────────────────────────────────────────────┘
```

| Component | Count | Behavior |
|-----------|-------|----------|
| Process | 1 | Single daemon (PID lock prevents multiples) |
| Threads | N | One worker thread per Task Source Directory |
| Per Directory | Sequential | Tasks execute one at a time (FIFO) |
| Across Directories | Parallel | Multiple directories run simultaneously |

### Lock File Format

When a task is running, a lock file is created in the task source directory:

**Location:** `{source-directory}/.task-{task-id}.lock`

**Format:**
```json
{
  "task_id": "task-20260207-123456-fix-bug",
  "worker": "ad-hoc",
  "thread_id": "140234567890123",
  "pid": 12345,
  "started_at": "2026-02-07T12:35:00.123456"
}
```

**Purpose:**
- Track which task is currently running
- Identify which worker is executing
- Enable stale lock detection (via PID check)
- Track execution start time

### Task Directories

| Directory | Purpose |
|-----------|---------|
| `{source}/staging/` | Staging area for atomic writes |
| `{source}/pending/` | Pending task documents (watchdog monitors) |
| `{source}/.task-XXX.lock` | Lock file for running task |
| `{source}/../completed/` | Completed task documents |
| `{source}/../failed/` | Failed task documents |
| `{source}/../results/` | JSON result files |
| `{source}/../reports/` | Worker execution reports |

### Safety Features

- **Atomic Writes**: Config files use temporary file + atomic replacement
- **File Locking**: fcntl-based locks prevent concurrent modification
- **Lock File Tracking**: Running tasks tracked with metadata (worker, thread, PID)
- **Stale Lock Detection**: Lock files with dead PIDs are automatically cleaned up
- **Archive Preservation**: Completed/failed task specs preserved in directories
- **Result Tracking**: JSON files capture execution metadata for every task
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

### 1. Initialize the System

```bash
# From your project directory
cd /home/admin/workspaces/datachat

# Initialize (creates directories, registers ad-hoc and planned queues)
python -m task_queue.cli init
```

This creates:
```
tasks/
├── ad-hoc/
│   ├── staging/             # Staging area for atomic writes
│   ├── pending/             # Task Source Directory (watchdog monitors)
│   ├── completed/           # Completed task documents
│   ├── failed/              # Failed task documents
│   ├── results/             # JSON result files
│   ├── reports/             # Worker execution reports
│   └── planning/            # Planning documents (planned queue only)
└── planned/
    └── (same structure, plus planning/)
```

### 2. Create a Task Document

Create a file in your Task Source Directory following the naming pattern:
```
task-YYYYMMDD-HHMMSS-description.md
```

Example: `task-20260207-120000-fix-auth-timeout.md`

The watchdog will auto-detect the new task immediately.

### 3. Check status

```bash
# Overview mode
python -m task_queue.cli status

# Detailed mode (shows running tasks)
python -m task_queue.cli status --detailed
```

### 4. Start daemon

```bash
# Start the daemon for automatic processing
systemctl --user start task-queue.service

# View live logs
journalctl --user -u task-queue.service -f
```

## CLI Commands

### System Commands

```bash
# Initialize task system from current directory
python -m task_queue.cli init

# Show system status (overview)
python -m task_queue.cli status

# Show detailed status (with running tasks and lists)
python -m task_queue.cli status --detailed
```

### Sources Commands

```bash
# List Task Source Directories
python -m task_queue.cli sources list

# Add a custom Task Source Directory
python -m task_queue.cli sources add /path/to/tasks --id my-queue \
    --project-workspace /home/admin/workspaces/datachat \
    --description "My custom queue"

# Remove a Task Source Directory
python -m task_queue.cli sources rm --source-id my-queue
```

### Tasks Commands

```bash
# Show task document path (simple output with reminder)
python -m task_queue.cli tasks show task-20260207-120000

# Show task result logs path
python -m task_queue.cli tasks logs task-20260207-120000

# Cancel a running task
python -m task_queue.cli tasks cancel task-20260207-120000
```

### Workers Commands

```bash
# Show detailed worker status
python -m task_queue.cli workers status

# List workers summary
python -m task_queue.cli workers list
```

### Logs Command

```bash
# Show daemon logs (exit with Ctrl+C)
python -m task_queue.cli logs

# Follow logs live
python -m task_queue.cli logs --follow

# Show last 50 lines
python -m task_queue.cli logs --lines 50
```

### Testing Command

```bash
# Run interactively (for testing)
python -m task_queue.cli run --cycles 5
```

## Configuration

Configuration file: `~/.config/task-queue/config.json`

```json
{
  "version": "2.1",
  "project_workspace": "/home/admin/workspaces/datachat",
  "task_source_directories": [
    {
      "id": "ad-hoc",
      "path": "/home/admin/workspaces/datachat/tasks/ad-hoc/pending",
      "description": "Quick, spontaneous tasks from conversation",
      "added_at": "2026-02-07T00:00:00.000000"
    },
    {
      "id": "planned",
      "path": "/home/admin/workspaces/datachat/tasks/planned/pending",
      "description": "Organized, sequential tasks from planning docs",
      "added_at": "2026-02-07T00:00:01.000000"
    }
  ],
  "created_at": "2026-02-07T00:00:00.000000",
  "updated_at": "2026-02-07T00:00:00.000000"
}
```

## Directory Structure

```
~/.config/task-queue/          # Configuration directory
└── config.json                  # Main configuration

{project-workspace}/            # Your project workspace
└── tasks/
    ├── ad-hoc/                  # Ad-hoc queue
    │   ├── staging/             # Staging area for atomic writes
    │   ├── pending/             # Task Source Directory (watchdog monitors)
    │   │   ├── task-001.md
    │   │   └── .task-002.lock   # Lock file for running task
    │   ├── completed/           # Completed tasks
    │   ├── failed/              # Failed tasks
    │   ├── results/             # Result JSON files
    │   │   ├── task-001.json
    │   │   └── task-002.json
    │   └── reports/             # Worker reports
    └── planned/                 # Planned queue
        └── (same structure, plus planning/)
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
                    │ Create Lock File │
                    │ .task-XXX.lock  │
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
              Delete Lock   Move to
              + Archive    failed/
```

## JSON Result Files

After each task execution, a JSON result file is automatically created at:

```
{project-workspace}/tasks/ad-hoc/results/{task_id}.json
{project-workspace}/tasks/planned/results/{task_id}.json
```

### Result File Structure

```json
{
  "success": true,
  "output": "Task execution output from Claude...",
  "error": "",
  "task_id": "task-20260206-105319",
  "started_at": "2026-02-06T10:56:17.747530",
  "completed_at": "2026-02-06T10:56:45.316864",
  "duration_ms": 8829,
  "duration_api_ms": 7785,
  "total_cost_usd": 0.176559,
  "usage": {
    "input_tokens": 25836,
    "cache_read_input_tokens": 81408,
    "output_tokens": 267
  },
  "session_id": "4e23bdf6-95b2-4856-ad69-5187d539b87a",
  "num_turns": 4
}
```

### Viewing Results

```bash
# List all result files
ls tasks/ad-hoc/results/

# View specific result
cat tasks/ad-hoc/results/task-{id}.json

# View with pretty formatting (requires jq)
cat tasks/ad-hoc/results/task-{id}.json | jq .

# Check recent results
ls -lt tasks/ad-hoc/results/ | head -10
```

## Troubleshooting

### Common Issues

#### Issue: "No Project Workspace set"

```bash
# Solution: Use init command
python -m task_queue.cli init
```

#### Issue: "No Task Source Directories configured"

```bash
# Solution: Use init command
python -m task_queue.cli init

# Or add manually
python -m task_queue.cli sources add /path/to/tasks --id my-queue
```

#### Issue: Daemon shows "No pending tasks"

```bash
# Solution: Create task documents in the Task Source Directory
# Watchdog will auto-detect new files
```

#### Issue: Task stuck with lock file

```bash
# Check lock file
ls tasks/ad-hoc/pending/.task-*.lock

# Check if process is still running
cat ~/.config/task-queue/config.json

# If process is dead, daemon will clean up stale locks automatically
# Or manually remove the lock file
rm tasks/ad-hoc/pending/.task-XXX.lock
```

## Development

### Project Structure

```
task-queue/
├── task_queue/
│   ├── __init__.py           # Package exports
│   ├── cli.py                # CLI commands (grouped structure)
│   ├── config.py             # ConfigManager
│   ├── daemon.py             # Daemon service with parallel workers
│   ├── executor.py           # Claude Agent SDK executor, lock file handling
│   ├── models.py             # Pydantic models (v2.0)
│   └── task_runner.py        # Task execution logic
├── tests/                    # Unit tests
│   └── test_cli_grouped_commands.py  # CLI test suite
├── README.md                 # This file
└── task-queue.service       # Systemd service file
```

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest --cov=task_queue tests/

# Run CLI tests
python tests/test_cli_grouped_commands.py
```

## License

MIT License - See LICENSE file for details.
