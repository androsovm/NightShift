# NightShift MVP

An autonomous overnight task runner: collects tasks from external sources into a local queue, executes them through Claude Code, runs quality gates, and creates draft PRs. A human reviews the PR and closes the task in the source manually.

## CLI

| Command | Description |
|---------|-------------|
| `nightshift init` | Interactive wizard: scans `~/Projects` + custom paths, selects projects, task sources, global limits, tokens, schedule. Creates `~/.nightshift/config.yaml` and `.nightshift.yaml` in each project |
| `nightshift add` | Add a project to an existing configuration. Picks up limits from already-configured projects, checks for duplicates, only asks for tokens for new sources |
| `nightshift sync` | Import tasks from configured sources into the local queue (`~/.nightshift/tasks.yaml`). Deduplicates by `source_ref` — on conflict, prompts the user (skip/update/duplicate). Flag: `--project / -p` |
| `nightshift tasks` | Manage the local task queue (details below) |
| `nightshift run` | Execute tasks from the local queue. Doesn't access sources directly. Flags: `--dry-run` (show plan), `--project / -p` (single project) |
| `nightshift status` | Last run status: task table, PRs, change counts |
| `nightshift log` | Run history. `nightshift log N` — task N details with last 50 log lines |
| `nightshift install` | Install into system scheduler: launchd (macOS) / systemd (Linux). Shows sleep prevention warning. PATH includes `/opt/homebrew/bin` |
| `nightshift uninstall` | Remove from scheduler |
| `nightshift doctor` | Environment check: claude CLI, gh, git, push access, GPG, API tokens, configs, sleep prevention |

Global flag: `--verbose / -v` — DEBUG-level logging.

## Task Management — `nightshift tasks`

| Subcommand | Description |
|------------|-------------|
| `nightshift tasks list` | List tasks with filters: `--status`, `--project`, `--priority` |
| `nightshift tasks add` | Add a task manually (interactive input: title, project, priority, intent, scope, constraints). `source_type=manual` |
| `nightshift tasks remove <id>` | Remove a task from the queue |
| `nightshift tasks edit <id>` | Edit task fields (interactively or via flags `--title`, `--intent`, `--priority`) |
| `nightshift tasks prioritize <id> <priority>` | Change priority (high / medium / low) |
| `nightshift tasks skip <id>` | Mark a task as skipped |
| `nightshift tasks requeue <id>` | Return a task to pending status |
| `nightshift tasks history <id>` | Attempt history: date, status, branch, PR, error, duration |

## Local Task Queue

Tasks are stored in `~/.nightshift/tasks.yaml` — a single file for all projects. Atomic writes (temp file + `os.replace`).

Tasks are organized into three categories:

| Category | Description |
|----------|-------------|
| **Active** | Source-received and manual tasks in the execution queue |
| **Built-in** | Template-based tasks with frequency: once, weekly, or monthly. Recurring tasks auto-requeue after their interval upon successful completion (PASSED/DONE only, not FAILED) |
| **Inactive** | Deferred tasks — won't run until reactivated |

TUI `[x]` key behavior:
- **Active task** → moves to Inactive (toggle)
- **Inactive task** → moves back to Active (toggle)
- **Built-in task** → removes permanently (with confirmation)

Workflow:
1. `nightshift sync` — import tasks from sources (GitHub, YouTrack, Trello, YAML) into the queue
2. User manages tasks: sets priorities, deactivates unwanted ones with `[x]`, adds their own
3. `nightshift run` — executes pending tasks from the queue (Active + Built-in only, not Inactive), records results (attempt) in task history
4. User reviews PR and closes the task in the source manually

Each task stores its full attempt history (`TaskAttempt`): timestamp, status, run_id, branch, PR URL, error, duration.

## Task Sources

Sources are only used for importing via `nightshift sync`. After import, tasks live in the local queue. External sources are not modified automatically.

| Source | Where tasks come from | Default tag/label |
|--------|-----------------------|-------------------|
| **YAML** | `tasks:` section in `.nightshift.yaml`, status `pending` | — |
| **GitHub Issues** | Issues with a configurable label. Auto-detects repo from git remote | `nightshift` |
| **YouTrack** | Issues with a configurable tag. Requires `base_url` and `project_id` | `nightshift` |
| **Trello** | Cards from a configurable list. Requires `board_id` | list "NightShift Queue" |
| **Built-in** | Added via TUI `[t]` with frequency (once/weekly/monthly) | — |

Extensibility: entry point `nightshift.sources` for third-party adapters + `nightshift.sources.register()` for programmatic registration.

## Task Execution Pipeline

1. `prepare_repo` — fetch, checkout main, pull (fetch and pull are non-fatal on network errors)
2. Load pending tasks from the local queue, group by project
3. Sort by priority (high > medium > low), trim to `max_tasks_per_run`
4. For each task:
   - Create branch `nightshift/{slug}-{YYYYMMDD}`
   - Run baseline tests (`pytest`)
   - Invoke `claude -p <prompt> --dangerously-skip-permissions` with timeout
   - Retry up to 3 times on transient errors (529, overloaded, rate limit, connection, ECONNRESET, ETIMEDOUT)
   - Quality gates: blast radius, linter (ruff/flake8/eslint), test comparison with baseline
   - Push branch + create draft PR via `gh pr create`
   - Record result (attempt) in the task's queue history
   - Check `max_prs_per_night` limit — if reached, remaining tasks are marked `skipped`
   - Return to main

## Quality Gates

| Gate | What it checks |
|------|----------------|
| Blast radius | Number of changed files and lines doesn't exceed limits (`max_files_changed`, `max_lines_changed`) |
| Linter | Auto-detects ruff / flake8 / eslint, runs on the project |
| Test regression | Compares passed/failed test counts before and after changes. Fails if passing decreased or failing increased |

## Limits and Constraints

| Parameter | Default | Level |
|-----------|---------|-------|
| `max_tasks_per_run` | 5 | Project (configurable globally in wizard) |
| `task_timeout_minutes` | 45 | Project (configurable globally in wizard) |
| `max_files_changed` | 20 | Project (configurable globally in wizard) |
| `max_lines_changed` | 500 | Project (configurable globally in wizard) |
| `max_duration_hours` | 4 | Global |
| `max_prs_per_night` | 10 | Global |
| `schedule.time` | 04:00 | Global |
| `schedule.timezone` | UTC | Global |

## Error Resilience

- **Git network failures**: `fetch` and `pull` in `prepare_repo` are non-fatal — on error, a warning is logged and work continues with local state. Only `checkout main` is fatal
- **Claude API**: retry up to 3 times with 30-second delay on transient errors. Timeouts are not retried
- **Corrupted storage**: corrupted JSON files in `runs/` are skipped with a warning, don't crash the CLI
- **Event loop**: fallback via `asyncio.new_event_loop()` for environments with an already-running event loop
- **Sleep prevention**: `install` shows a warning, `doctor` checks sleep settings (macOS: `pmset`, Linux: `systemctl`)

## Configuration

- **Global**: `~/.nightshift/config.yaml` — schedule, project list, PR limit
- **Project**: `.nightshift.yaml` — sources, limits, custom system prompt for Claude, YAML tasks
- **Task queue**: `~/.nightshift/tasks.yaml` — all tasks from all projects with attempt history
- **Secrets**: `~/.nightshift/.env` (chmod 600) — GITHUB_TOKEN, YOUTRACK_TOKEN, TRELLO_API_KEY, TRELLO_TOKEN

## Storage and Logs

- Task queue: `~/.nightshift/tasks.yaml` (YAML, atomic writes)
- Run results: `~/.nightshift/runs/{run_id}.json` (Pydantic → JSON)
- Task logs: `~/.nightshift/logs/{run_id}/{task-slug}.log`
- Corrupted JSON in runs/ doesn't crash — skipped with warning (`JSONDecodeError` and `ValidationError` caught)
- Structured logging via structlog: JSON format for unattended, colored console for `--verbose`
- Run logs: `~/.nightshift/logs/{run_id}/run.log` (JSONL)

## Claude Prompt

Automatically assembled from task fields:
- Autonomous work context (no human present, must complete independently)
- Optional `claude_system_prompt` from project config
- Title, intent, scope (files), constraints
- Instructions: read files, implement, write tests, run lint, commit
- Prohibition on creating PRs and pushing (the runner handles that)

## Stack

- Python >= 3.13, MIT, `py.typed`
- CLI: typer + rich + questionary
- HTTP: httpx (async)
- Validation: pydantic v2
- Config: pyyaml + python-dotenv
- Logging: structlog (JSON for unattended, colored console for `--verbose`, JSONL to file)
- Tests: pytest + pytest-asyncio (170 tests)
