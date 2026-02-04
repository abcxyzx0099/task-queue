# Task: Add high-priority CLI commands to task-monitor

**Status**: pending

---

## Task
Add four high-priority CLI commands to the task-monitor CLI: `show`, `result`, `history`, and `logs` to enable better task tracking and debugging.

## Context
The current task-monitor CLI only has 5 commands (status, queue, current, use, load). There is no way to check individual task status, view task results, see completed task history, or view task execution logs. This makes it difficult to track progress and debug issues with worker agent execution.

## Scope
- Directories: Task monitor source code location (TBD)
- Files: CLI entry point (cli.py or similar), command handlers
- Dependencies: argparse or click (CLI framework), JSON result files

## Requirements
1. Add `show <task-id>` command:
   - Accept partial task ID (timestamp or full ID)
   - Display task status (pending/processing/completed/failed)
   - Show task title/description
   - Display start time, end time (if available)
   - Show progress if processing
   - Display error message if failed

2. Add `result <task-id>` command:
   - Display task result JSON in readable format
   - Show summary field prominently
   - Display artifacts/files created
   - Show error details if failed
   - Format output for human readability

3. Add `history` command:
   - List all completed tasks from results directory
   - Show in reverse chronological order (newest first)
   - Display: task ID, title, status, completion time
   - Support optional `--limit N` flag for showing last N tasks
   - Support optional `--failed` flag to show only failed tasks

4. Add `logs <task-id>` command:
   - Display task execution logs
   - Read from log files or result JSON
   - Support `--tail` option for last N lines
   - Support `--follow` option for live log monitoring (if feasible)

## Deliverables
1. Updated CLI with 4 new commands implemented
2. Help text updated for all new commands
3. Unit tests for new CLI commands
4. Documentation of command usage (if doc system exists)

## Constraints
1. Maintain backward compatibility with existing commands
2. Follow existing CLI patterns and conventions
3. Handle missing task IDs gracefully with helpful error messages
4. Handle cases where task hasn't started/completed yet
5. Don't break existing task-monitor functionality

## Success Criteria
1. All 4 commands work correctly
2. Commands handle edge cases (missing IDs, non-existent tasks)
3. Output is human-readable and well-formatted
4. Commands work with both partial and full task IDs
5. No regressions in existing functionality
6. Code follows existing patterns in the codebase

## Worker Investigation Instructions
**CRITICAL**: Before implementing, you MUST do your own deep investigation:

1. **Find task-monitor source code**:
   - Search for task-monitor installation location
   - Check `~/.local/bin/task-monitor` or similar
   - Find the actual Python package location
   - Look for `cli.py` or main entry point

2. **Study existing CLI structure**:
   - Examine current command implementation
   - Note which CLI framework is used (argparse, click, typer?)
   - Find command registration pattern
   - Note how results directory is accessed

3. **Understand result JSON structure**:
   - Read example result files from `tasks/task-monitor/results/`
   - Note which fields are available (status, summary, artifacts, error)
   - Find log file location and format

4. **Identify helper functions**:
   - Find existing functions that read result files
   - Note how task IDs are formatted and matched
   - Find directory/path constants

5. **Plan implementation**:
   - Design command output format
   - Plan partial ID matching logic
   - Design error handling for missing/invalid IDs
   - Plan test approach
