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
- **Single instance enforcement**: File-based lock prevents multiple instances from running simultaneously

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

### CLI Setup (Wrapper Script Method)

Create a wrapper script at `~/.local/bin/task-monitor` (XDG standard location):

```bash
cat > ~/.local/bin/task-monitor << 'EOF'
#!/bin/bash
/home/admin/workspaces/task-monitor/.venv/bin/python -m task_monitor.cli "$@"
EOF

chmod +x ~/.local/bin/task-monitor
```

**Why this approach:**
- Uses `python -m` to run the module directly (avoids import path issues)
- No pip installation required
- Changes to source code take effect immediately
- Standard XDG user-bin location

### Systemd Service Setup

Create user-level systemd service at `~/.config/systemd/user/task-monitor.service`:

```ini
[Unit]
Description=Task Monitor Daemon
After=network.target

[Service]
Type=exec
WorkingDirectory=/home/admin/workspaces/task-monitor
ExecStart=/home/admin/workspaces/task-monitor/.venv/bin/python -m task_monitor.monitor_daemon
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Then enable and start:
```bash
systemctl --user daemon-reload
systemctl --user enable task-monitor.service
systemctl --user start task-monitor.service
```

### What Gets Installed

| Component | Location | Type |
|-----------|----------|------|
| **Source code** | `/home/admin/workspaces/task-monitor/task_monitor/` | Directory |
| **CLI command** | `~/.local/bin/task-monitor` | Wrapper script |
| **Virtual environment** | `/home/admin/workspaces/task-monitor/.venv/` | Directory |
| **Systemd service** | `~/.config/systemd/user/task-monitor.service` | Service unit |
| **Environment variable** | `~/.bashrc` or `~/.zshrc` (`TASK_MONITOR_PROJECT`) | Shell env var |
| **Lock file** | `~/.config/task-monitor/task-monitor.lock` | Instance lock |

### Current Installation Details

**CLI Wrapper Script** (`~/.local/bin/task-monitor`):
```bash
#!/bin/bash
/home/admin/workspaces/task-monitor/.venv/bin/python -m task_monitor.cli "$@"
```

**Systemd Service** (`~/.config/systemd/user/task-monitor.service`):
```ini
[Unit]
Description=Task Monitor Daemon
After=network.target

[Service]
Type=exec
WorkingDirectory=/home/admin/workspaces/task-monitor
ExecStart=/home/admin/workspaces/task-monitor/.venv/bin/python -m task_monitor.monitor_daemon
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

**Verification Commands:**
```bash
# Verify CLI wrapper exists and is executable
ls -la ~/.local/bin/task-monitor

# Verify CLI works
task-monitor --help

# Verify service status
systemctl --user status task-monitor.service

# View service logs
journalctl --user -u task-monitor.service -f
```

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
# Show daemon status
task-monitor status

# Show queue status
task-monitor queue

# Show current project
task-monitor current

# Set current project
task-monitor use /path/to/project

# Load existing task files from pending directory
task-monitor load
```

### Project Management

```bash
# Set current project (updates .env file in source directory)
task-monitor use /path/to/project

# Show current project
task-monitor current

# Override project for specific command
task-monitor -p /path/to/project status
task-monitor -p /path/to/project queue
```

**How it works:**

When you run `task-monitor use <path>`, it updates the `.env` file in the task-monitor source directory:
```bash
export TASK_MONITOR_PROJECT="/path/to/project"
```

The CLI wrapper script (`~/.local/bin/task-monitor`) sources this `.env` file before running Python, so the environment variable is automatically available. No shell reload needed.

### Loading Existing Tasks

```bash
# Load existing task files from pending directory
task-monitor load

# With project override
task-monitor -p /path/to/project load
```

**How it works:**

The `load` command scans the `tasks/task-monitor/pending/` directory for existing task files matching the pattern `task-YYYYMMDD-HHMMSS-*.md` and triggers the watchdog to queue them.

**When to use:**
- After creating task files before starting the daemon
- After restarting the daemon when tasks were left in pending
- To manually trigger queueing of existing tasks

**Note:** Tasks created while the daemon is running are automatically detected by the watchdog. The `load` command is only needed for files that existed before the daemon started.

**Task Status Output:**

| Status | Meaning | Shown Information |
|--------|---------|-------------------|
| **waiting** | Task is queued, not yet started | Created time, file size |
| **processing** | Task is currently being executed | Task ID, start time |
| **completed** | Task finished (success or failure) | Status, duration, summary, token usage |
| **not_found** | Task doesn't exist in any stage | Lists checked locations |

## Process Management

### Single Instance Protection

The task-monitor service uses **file-based locking** to prevent multiple instances from running simultaneously. This prevents race conditions and duplicate task execution.

**Lock file location:** `~/.config/task-monitor/task-monitor.lock`

When you try to start a second instance while one is already running:
```bash
$ python -m task_monitor.monitor_daemon
Starting Multi-Project Task Monitor
Another instance is already running (lock file: /home/admin/.config/task-monitor/task-monitor.lock). Exiting.
```

The lock is automatically released when the service stops.

---

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

# Check lock file status
ls -la ~/.config/task-monitor/task-monitor.lock

# Start daemon manually (will exit if already running)
/home/admin/workspaces/task-monitor/.venv/bin/python -m task_monitor.monitor_daemon

# Stop daemon
pkill -f monitor_daemon

# View logs
journalctl --user -u task-monitor -f
```

## Files

| File | Purpose |
|------|---------|
| `task_monitor/monitor_daemon.py` | Main daemon - manages observers and queue processors with instance lock protection |
| `task_monitor/task_executor.py` | Executes tasks using Claude Agent SDK |
| `task_monitor/models.py` | Data models (TaskResult, TaskStatus) |
| `task_monitor/cli.py` | Status query CLI source code |
| `pyproject.toml` | Package configuration |
| `~/.config/systemd/user/task-monitor.service` | Systemd service unit (includes PIDFile directive) |
| `~/.bashrc` or `~/.zshrc` | Shell environment variable: `TASK_MONITOR_PROJECT` |
| `~/.config/task-monitor/task-monitor.lock` | Instance lock file (prevents multiple instances) |

## Configuration

### Current Project

The CLI uses the `TASK_MONITOR_PROJECT` environment variable to determine the current project.

Set the current project with:
```bash
task-monitor use /path/to/project
source ~/.bashrc  # or ~/.zshrc
```

Show the current project with:
```bash
task-monitor current
```

**Environment variable:**
```bash
$TASK_MONITOR_PROJECT
```

**Added to shell rc file:**
```bash
export TASK_MONITOR_PROJECT="/path/to/project"
```

### Lock File

| File | Purpose |
|------|---------|
| `~/.config/task-monitor/task-monitor.lock` | Prevents multiple instances from running (uses fcntl file locking) |

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

### Multiple instances won't start (expected behavior)

If you see "Another instance is already running" when starting the service:
- This is **normal** - the lock prevents duplicate instances
- Check if service is already running: `systemctl --user status task-monitor`
- If you believe it's a stale lock, remove it manually: `rm ~/.config/task-monitor/task-monitor.lock`

### Tasks not being detected

1. Verify task name matches pattern `task-????????-??????-*.md`
2. Check daemon is running: `systemctl --user status task-monitor`
3. Check observer started: `journalctl --user -u task-monitor | grep "Observer started"`
4. Verify current project: `task-monitor current`

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
