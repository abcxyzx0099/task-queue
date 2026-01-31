# Task Monitor System

Multi-project task monitoring daemon that watches project `tasks/pending/` directories and executes tasks sequentially within each project (parallel across projects).

## Installation Location

`/home/admin/workspaces/task-monitor/` - User-local workspace installation (parallel to all projects)

## Architecture

```
/home/admin/workspaces/
├── datachat/              # Project 1
├── agent-api/             # Project 2
├── other-project/         # Project 3
└── task-monitor/           # ← Cross-project tool (shared by all projects)
    ├── task_monitor/       # Python package
    ├── .venv/             # Virtual environment
    ├── pyproject.toml     # Package configuration
    └── monitor_daemon.py  # Main daemon
```

## Functionality

The Task Monitor System provides:

- **Multi-project monitoring**: Watch multiple project directories simultaneously
- **Automatic task detection**: Detects new task files matching `task-????????-??????-*.md`
- **Sequential execution**: Tasks execute one at a time within each project
- **Parallel processing**: Different projects run independently
- **Watchdog monitoring**: File system observers detect new tasks immediately
- **Claude Agent SDK integration**: Executes tasks using task-coordination skill
- **Result tracking**: Saves execution results to JSON files
- **Enhanced CLI**: Check task status by ID across all stages (waiting, processing, completed)

## Installation

### Quick Install

```bash
cd /home/admin/workspaces/task-monitor

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install package in editable mode
pip install -e .

# Install dependencies
pip install claude-agent-sdk watchdog
```

### CLI Setup

Add to `~/.bashrc`:

```bash
# Task Monitor CLI
export PATH="$HOME/workspaces/task-monitor/.venv/bin:$PATH"
```

Then reload: `source ~/.bashrc`

### What Gets Installed

| Component | Location |
|-----------|----------|
| **Source code** | `/home/admin/workspaces/task-monitor/task_monitor/` |
| **CLI command** | `/home/admin/workspaces/task-monitor/.venv/bin/task-monitor` (via PATH) |
| **Virtual environment** | `/home/admin/workspaces/task-monitor/.venv/` |
| **Systemd service** | `~/.config/systemd/user/task-monitor.service` |

## Usage

### 1. Creating Tasks

Create task files in your project's `tasks/pending/` directory with the naming pattern:

```
task-YYYYMMDD-HHMMSS-<description>.md
```

Example:

```bash
tasks/pending/task-20260130-143000-fix-bug.md
tasks/pending/task-20260130-150000-analyze-data.md
```

### 2. Task Execution Flow

```
1. Create task file in tasks/pending/
       ↓
2. Watchdog detects new file
       ↓
3. Task queued (in-memory FIFO queue)
       ↓
4. Task executor runs /task-coordination
       ↓
5. Worker + Auditor execute task
       ↓
6. Result saved to tasks/results/
       ↓
7. Next task processes automatically
```

## CLI Commands

### task-monitor (Status Query)

Check queue and execution status:

```bash
# Show queue status
task-monitor queue

# Show specific task status (by ID)
task-monitor task-20260131-045746-test-new-cli-feature

# Show all completed tasks
task-monitor status
```

**Task Status Output:**

| Status | Meaning | Shown Information |
|--------|---------|-------------------|
| **waiting** | Task is queued, not yet started | Created time, file size |
| **processing** | Task is currently being executed | Task ID, start time |
| **completed** | Task finished (success or failure) | Status, duration, summary, token usage |
| **not_found** | Task doesn't exist in any stage | Lists checked locations |

## Service Management

### Using Systemd Service (Recommended)

```bash
# Enable service (start on login)
systemctl --user enable task-monitor

# Start service
systemctl --user start task-monitor

# Check status
systemctl --user status task-monitor

# Restart service
systemctl --user restart task-monitor

# Stop service
systemctl --user stop task-monitor

# View logs
journalctl --user -u task-monitor -f
```

### Manual Service Management

```bash
# Check if running
ps aux | grep monitor_daemon

# Start daemon manually
nohup /home/admin/workspaces/task-monitor/.venv/bin/python -m task_monitor.monitor_daemon > ~/task-monitor.log 2>&1 &

# Stop daemon
pkill -f monitor_daemon

# View logs
tail -f ~/task-monitor.log
```

## Files

| File | Purpose |
|------|---------|
| `task_monitor/monitor_daemon.py` | Main daemon - manages observers and queue processors |
| `task_monitor/task_executor.py` | Executes tasks using Claude Agent SDK |
| `task_monitor/models.py` | Data models (TaskResult, TaskStatus) |
| `task_monitor/cli.py` | Status query CLI source code |
| `pyproject.toml` | Package configuration |

## Configuration

### Project Registry

Location: `~/.config/task-monitor/registered.json`

```json
{
  "projects": {
    "datachat": {
      "path": "/home/admin/workspaces/datachat",
      "enabled": true,
      "registered_at": "2026-01-30T12:00:00"
    }
  }
}
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MONITOR_SYSTEM_ROOT` | `/home/admin/workspaces/task-monitor` | System root directory |

## Making Changes

Since the package is installed in **editable mode**, changes to source code take effect immediately:

```bash
# Edit source
vim /home/admin/workspaces/task-monitor/task_monitor/cli.py

# Restart service to apply changes
systemctl --user restart task-monitor

# Test CLI (changes apply immediately)
task-monitor queue
```

## Troubleshooting

### Tasks not being detected

1. Verify task name matches pattern `task-????????-??????-*.md`
2. Check daemon is running: `systemctl --user status task-monitor`
3. Check observer started: `journalctl --user -u task-monitor | grep "Observer started"`
4. Verify project is registered: `cat ~/.config/task-monitor/registered.json`

### CLI shows "Task not found"

The CLI checks in this order:
1. **Currently processing** - from queue state
2. **Waiting in queue** - from `tasks/pending/` directory
3. **Completed** - from `tasks/results/` directory

Use the task ID with or without `.md` extension:
```bash
task-monitor task-20260131-045746-test-new-cli-feature
task-monitor task-20260131-045746-test-new-cli-feature.md
```

### Service won't start

1. Check Python dependencies are installed:
   ```bash
   /home/admin/workspaces/task-monitor/.venv/bin/pip list
   ```
2. Check service logs: `journalctl --user -u task-monitor -n 50`
3. Install missing dependencies:
   ```bash
   /home/admin/workspaces/task-monitor/.venv/bin/pip install claude-agent-sdk watchdog
   ```
