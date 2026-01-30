# Job Monitor System

Multi-project job monitoring daemon that watches project `jobs/items/` directories and executes jobs sequentially within each project (parallel across projects).

## Installation Location

`/home/admin/workspaces/job-monitor/` - User-local workspace installation (parallel to all projects)

## Architecture

```
/home/admin/workspaces/
├── datachat/              # Project 1
├── agent-api/             # Project 2
├── other-project/         # Project 3
└── job-monitor/           # ← Cross-project tool (shared by all projects)
    ├── job_monitor/       # Python package
    ├── .venv/             # Virtual environment
    ├── pyproject.toml     # Package configuration
    └── monitor_daemon.py  # Main daemon
```

## Functionality

The Job Monitor System provides:

- **Multi-project monitoring**: Watch multiple project directories simultaneously
- **Automatic job detection**: Detects new job files matching `job-????????-??????-*.md`
- **Sequential execution**: Jobs execute one at a time within each project
- **Parallel processing**: Different projects run independently
- **Watchdog monitoring**: File system observers detect new jobs immediately
- **Claude Agent SDK integration**: Executes jobs using task-coordination skill
- **Result tracking**: Saves execution results to JSON files
- **Enhanced CLI**: Check job status by ID across all stages (waiting, processing, completed)

## Installation

### Quick Install

```bash
cd /home/admin/workspaces/job-monitor

# Install in editable mode (user-local)
pip install --break-system-packages --user -e .

# Start the daemon
nohup .venv/bin/python job_monitor/monitor_daemon.py > ~/job-monitor.log 2>&1 &
```

### What Gets Installed

| Component | Location |
|-----------|----------|
| **Source code** | `/home/admin/workspaces/job-monitor/job_monitor/` |
| **CLI command** | `~/.local/bin/job-monitor` |
| **Virtual environment** | `/home/admin/workspaces/job-monitor/.venv/` |
| **Systemd service** | `~/.config/systemd/user/job-monitor.service` |
| **Log file** | `~/job-monitor.log` |

## Usage

### 1. Creating Jobs

Create job files in your project's `jobs/items/` directory with the naming pattern:

```
job-YYYYMMDD-HHMMSS-<description>.md
```

Example:

```bash
jobs/items/job-20260130-143000-fix-bug.md
jobs/items/job-20260130-150000-analyze-data.md
```

### 2. Job Execution Flow

```
1. Create job file in jobs/items/
       ↓
2. Watchdog detects new file
       ↓
3. Job queued (in-memory FIFO queue)
       ↓
4. Job executor runs /task-coordination
       ↓
5. Worker + Auditor execute job
       ↓
6. Result saved to jobs/results/
       ↓
7. Next job processes automatically
```

## CLI Commands

### job-monitor (Status Query)

Check queue and execution status:

```bash
# Show queue status
job-monitor queue

# Show specific job status (by ID)
job-monitor job-20260131-045746-test-new-cli-feature

# Show all completed jobs
job-monitor status
```

**Job Status Output:**

| Status | Meaning | Shown Information |
|--------|---------|-------------------|
| **waiting** | Job is queued, not yet started | Created time, file size |
| **processing** | Job is currently being executed | Job ID, start time |
| **completed** | Job finished (success or failure) | Status, duration, summary, token usage |
| **not_found** | Job doesn't exist in any stage | Lists checked locations |

### Service Management

```bash
# Check daemon status
ps aux | grep monitor_daemon

# Start daemon
nohup /home/admin/workspaces/job-monitor/.venv/bin/python /home/admin/workspaces/job-monitor/job_monitor/monitor_daemon.py > ~/job-monitor.log 2>&1 &

# Stop daemon
pkill -f monitor_daemon

# View logs
tail -f ~/job-monitor.log
```

### Using Systemd Service (Optional)

If you prefer systemd service management:

```bash
# Enable service
systemctl --user enable job-monitor

# Start service
systemctl --user start job-monitor

# Check status
systemctl --user status job-monitor

# View logs
journalctl --user -u job-monitor -f
```

## Files

| File | Purpose |
|------|---------|
| `job_monitor/monitor_daemon.py` | Main daemon - manages observers and queue processors |
| `job_monitor/job_executor.py` | Executes jobs using Claude Agent SDK |
| `job_monitor/models.py` | Data models (JobResult, JobStatus) |
| `job_monitor/cli.py` | Status query CLI source code |
| `pyproject.toml` | Package configuration |

## Configuration

### Project Registry

Location: `~/.config/job-monitor/registered.json`

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
| `MONITOR_SYSTEM_ROOT` | `/home/admin/workspaces/job-monitor` | System root directory |

## Making Changes

Since the package is installed in **editable mode**, changes to source code take effect immediately:

```bash
# Edit source
vim /home/admin/workspaces/job-monitor/job_monitor/cli.py

# Restart daemon to apply changes
pkill -f monitor_daemon
nohup /home/admin/workspaces/job-monitor/.venv/bin/python /home/admin/workspaces/job-monitor/job_monitor/monitor_daemon.py > ~/job-monitor.log 2>&1 &

# Test CLI (changes apply immediately)
job-monitor queue
```

## Troubleshooting

### Jobs not being detected

1. Verify job name matches pattern `job-????????-??????-*.md`
2. Check daemon is running: `ps aux | grep monitor_daemon`
3. Check observer started: `tail ~/job-monitor.log | grep "Observer started"`
4. Verify project is registered: `cat ~/.config/job-monitor/registered.json`

### CLI shows "Job not found"

The CLI checks in this order:
1. **Currently processing** - from queue state
2. **Waiting in queue** - from `jobs/items/` directory
3. **Completed** - from `jobs/results/` directory

Use the job ID with or without `.md` extension:
```bash
job-monitor job-20260131-045746-test-new-cli-feature
job-monitor job-20260131-045746-test-new-cli-feature.md
```

### Daemon won't start

1. Check Python dependencies are installed:
   ```bash
   /home/admin/workspaces/job-monitor/.venv/bin/pip list
   ```
2. Check for missing modules in log: `cat ~/job-monitor.log`
3. Reinstall dependencies:
   ```bash
   /home/admin/workspaces/job-monitor/.venv/bin/pip install claude-agent-sdk watchdog
   ```
