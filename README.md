# Task Queue

A task monitoring and execution system that processes task specifications using the Claude Agent SDK. Designed for single-project workflows with multiple task specification directories.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Task Queue System                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐         ┌──────────────┐                  │
│  │   Project   │         │ Spec Dirs    │                  │
│  │   (single)  │────────▶│ (multiple)   │                  │
│  │  /datachat  │         │ - main       │                  │
│  └─────────────┘         │ - experimental│              │
│                          └──────────────┘                  │
│                                   │                         │
│                                   ▼                         │
│                          ┌──────────────┐                  │
│                          │ Task Scanner │                  │
│                          │ (task-*.md)  │                  │
│                          └──────────────┘                  │
│                                   │                         │
│                                   ▼                         │
│                          ┌──────────────┐                  │
│                          │    Queue     │                  │
│                          │  (FIFO)      │                  │
│                          └──────────────┘                  │
│                                   │                         │
│                                   ▼                         │
│                          ┌──────────────┐                  │
│                          │   Executor   │                  │
│                          │ Claude SDK   │                  │
│                          │ /task-worker │                  │
│                          └──────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

## Features

### Core Features

| Feature | Description |
|---------|-------------|
| **Single Project Path** | One project path serves as the working directory for all tasks |
| **Multiple Spec Directories** | Configure multiple task specification sources with add/remove |
| **Manual Load Trigger** | No auto-scanning by daemon; explicit `load` command required |
| **Sequential FIFO Execution** | Tasks execute in first-in-first-out order |
| **Multiple Loads Supported** | Run `load` command multiple times even while processing |
| **Atomic State Persistence** | Safe concurrent access with atomic file operations |
| **File Locking** | Prevents duplicate processing with fcntl-based locks |
| **Claude Agent SDK Integration** | Executes tasks via `/task-worker` skill with two-agent workflow |
| **Daemon Service** | Runs as systemd user service for continuous processing |
| **Task Archiving** | Completed task specs moved to archive directory |

### Safety Features

- **Atomic Writes**: State files use temporary file + atomic replacement
- **File Locking**: fcntl-based locks prevent concurrent modification
- **State Recovery**: Queue state persists across daemon restarts
- **Error Handling**: Failed tasks are tracked with error messages
- **Archive Preservation**: Completed task specs preserved in archive

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

### 1. Set the project path

```bash
task-queue set-project /home/admin/workspaces/datachat
# Output: ✅ Project path set: /home/admin/workspaces/datachat
```

### 2. Add a spec directory

```bash
task-queue add-spec /home/admin/workspaces/datachat/tasks/task-documents --id main
# Output: ✅ Added spec directory: main
```

### 3. Create a task specification

Create a file in your spec directory following the naming pattern:
```
task-YYYYMMDD-HHMMSS-description.md
```

Example: `task-20260204-120000-fix-auth-timeout.md`

### 4. Load tasks

```bash
task-queue load
# Output: 📥 Loaded 1 new tasks
```

### 5. Process tasks (manual or daemon)

```bash
# Manual processing
task-queue process

# Or start the daemon
systemctl --user start task-queue
```

## CLI Commands

### Project Management

```bash
# Set project path
task-queue set-project <path>

# Clear project path
task-queue clear-project

# Show current project
task-queue show-project
```

### Spec Directory Management

```bash
# Add a spec directory
task-queue add-spec <path> --id <id> [--description "desc"]

# Remove a spec directory
task-queue remove-spec <id>

# List spec directories
task-queue list-specs
```

### Task Operations

```bash
# Load tasks from spec directories
task-queue load

# Process pending tasks
task-queue process [--max-tasks N]

# Show queue status
task-queue queue
```

### Status & Monitoring

```bash
# Show system status
task-queue status [-v]

# Show detailed spec directory status
task-queue status --verbose
```

### Interactive Mode

```bash
# Run monitor interactively
task-queue run [--cycles N]

# Cycles: 0 = infinite, N = specific number
```

## Configuration

Configuration file: `~/.config/task-queue/config.json`

```json
{
  "version": "1.0",
  "settings": {
    "processing_interval": 10,
    "batch_size": 10,
    "task_spec_pattern": "task-*.md",
    "max_attempts": 3,
    "enable_file_hash": true
  },
  "project_path": "/home/admin/workspaces/datachat",
  "spec_directories": [
    {
      "id": "main",
      "path": "/home/admin/workspaces/datachat/tasks/task-documents",
      "description": "Main task specifications",
      "added_at": "2026-02-04T12:00:00.000000"
    }
  ],
  "created_at": "2026-02-04T12:00:00.000000",
  "updated_at": "2026-02-04T12:00:00.000000"
}
```

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `processing_interval` | 10 | Seconds between daemon processing cycles |
| `batch_size` | 10 | Max tasks to process per cycle |
| `task_spec_pattern` | `task-*.md` | Glob pattern for task files |
| `max_attempts` | 3 | Max execution attempts per task |
| `enable_file_hash` | true | Track file hashes for change detection |

## Directory Structure

```
~/.config/task-queue/          # Configuration directory
├── config.json                  # Main configuration
└── state/                       # State directory
    └── queue_state.json        # Task queue state

{project-root}/                  # Your project directory
└── tasks/
    ├── task-documents/     # Task specification sources
    ├── task-archive/            # Completed task specs
    ├── task-queue/            # Result JSON files (flat)
    └── task-reports/     # Worker execution reports
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
- `description` - Hyphen-separated description

### Example

```markdown
# Task: Fix authentication timeout

**Status**: pending

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
Feb 04 20:38:45 task-queue: ============================================================
Feb 04 20:38:45 task-queue: Task Queue Daemon Starting
Feb 04 20:38:45 task-queue: Configuration loaded from: ~/.config/task-queue/config.json
Feb 04 20:38:45 task-queue: Project path: /home/admin/workspaces/datachat
Feb 04 20:38:45 task-queue: Spec directories: 1
Feb 04 20:38:45 task-queue:   - main: /home/admin/workspaces/datachat/tasks/task-documents
Feb 04 20:38:45 task-queue: Processing interval: 10s
Feb 04 20:38:45 task-queue: Processing loop started (no auto-scanning)
Feb 04 20:38:55 task-queue: Cycle 1 started at 2026-02-04T20:38:55.110539
Feb 04 20:38:55 task-queue: 🔧 Processing tasks...
Feb 04 20:38:55 task-queue:   🔧 Processing 1 tasks
Feb 04 20:38:55 task-queue: [task-20260204-203800-fixed-test] Task started
Feb 04 20:39:31 task-queue: [task-20260204-203800-fixed-test] Task completed in 36.3s
Feb 04 20:39:32 task-queue:   ✅ Processed: 1 completed, 0 failed
```

## Workflow Example

### Complete Workflow

```bash
# 1. Set project path
task-queue set-project /home/admin/workspaces/myproject

# 2. Add spec directories
task-queue add-spec /home/admin/workspaces/myproject/tasks/specs --id main
task-queue add-spec /home/admin/workspaces/myproject/tasks/experimental --id experimental

# 3. Create task specifications
# Create files like: task-20260204-120000-feature-x.md

# 4. Load tasks
task-queue load
# Output: 📥 Loaded 2 new tasks

# 5. Check queue
task-queue queue
# Output: 📋 Queue Statistics: Pending: 2

# 6. Process tasks (manual)
task-queue process

# OR start daemon for automatic processing
systemctl --user start task-queue

# 7. Monitor progress
journalctl --user -u task-queue -f
```

### Manual Processing vs Daemon

| Approach | When to Use |
|----------|-------------|
| **Manual** | One-off processing, testing, debugging |
| **Daemon** | Continuous processing, production environments |

## Task Execution

### Two-Agent Workflow

Each task is executed using a two-agent workflow via the `/task-worker` skill:

1. **Implementation Agent** - Executes the task specification
2. **Auditor Agent** - Reviews and verifies the implementation
3. **Automatic Iteration** - Re-runs if audit fails (max 3 iterations)
4. **Safety Checkpoint** - Git commit before starting
5. **Final Commit** - Commits approved work when complete

### Execution States

| State | Description |
|-------|-------------|
| `pending` | Task is queued, waiting to be processed |
| `running` | Task is currently being executed |
| `completed` | Task completed successfully |
| `failed` | Task failed after max attempts |
| `cancelled` | Task was cancelled |

### Result Files

Results are saved in `tasks/task-queue/` (in project root):

```json
{
  "task_id": "task-20260204-120000-example",
  "spec_file": "/path/to/task-document.md",
  "spec_dir_id": "main",
  "status": "completed",
  "started_at": "2026-02-04T12:00:00.000000",
  "completed_at": "2026-02-04T12:00:58.295574",
  "duration_seconds": 58.3,
  "cost_usd": 0.23,
  "stdout": "Task output...",
  "attempts": 1,
  "error": null
}
```

## Troubleshooting

### Common Issues

#### Issue: "No project path set"

```bash
# Solution: Set project path
task-queue set-project /path/to/project
```

#### Issue: "No spec directories configured"

```bash
# Solution: Add a spec directory
task-queue add-spec /path/to/specs --id main
```

#### Issue: Daemon shows "No pending tasks"

```bash
# Solution: Load tasks first
task-queue load
```

#### Issue: Task failed

```bash
# Check queue for error details
task-queue queue

# Check result file
cat tasks/task-queue/task-<id>.json

# View daemon logs
journalctl --user -u task-queue -n 50
```

### Resetting the Queue

```bash
# Stop daemon first
systemctl --user stop task-queue

# Clear state file
rm ~/.config/task-queue/state/queue_state.json

# Restart daemon
systemctl --user start task-queue
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
│   ├── daemon.py             # Daemon service
│   ├── executor.py           # Claude Agent SDK executor
│   ├── models.py             # Pydantic models
│   ├── monitor.py            # Main monitor orchestrator
│   ├── processor.py          # Task processor
│   └── scanner.py            # Task specification scanner
├── tests/                    # Unit tests
├── README.md                 # This file
├── pyproject.toml           # Python package config
└── task-queue.service     # Systemd service file
```

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest --cov=task_queue tests/

# Or use the test script
./run_tests.sh
```

## License

MIT License - See LICENSE file for details.

## Contributing

This is an internal project for the DataChat system. For questions or issues, please contact the development team.
