# NightShift

CLI tool that runs [Claude Code](https://docs.anthropic.com/en/docs/claude-code) overnight to automatically close tech debt. While you sleep, NightShift picks tasks from your queue, runs Claude Code in isolated sessions, validates changes through quality gates, and opens draft PRs for your review.

```
nightshift
```

```
  NIGHTSHIFT   next run in 5h 12m   4 pending  2 projects   |   last: 3✓ 1✗

┌─ TASK QUEUE ────────────────┬─ TASK DETAIL ──────────────────────┐
│ ● [high] Security audit     │ Title:    Security audit           │
│ ○ [med]  Write missing tests│ Project:  myapp                    │
│ ○ [med]  Resolve TODOs      │ Priority: ● high                   │
│ · [low]  Update docs        │ Intent:   Audit the codebase for   │
│                             │           common security issues...│
├─ PROJECTS ──────────────────┤─ RUN DETAIL ───────────────────────│
│ myapp   ~/Projects/myapp    │ Run 20260322  03:00  6m 47s        │
│ api     ~/Projects/api      │ ✓ Fix imports         2m 10s       │
│                             │ ✓ Remove dead code    1m 17s       │
│                             │ ✗ Add type hints      3m 20s       │
│                             ├─ RUN HISTORY ───────────────────────│
│                             │ 20260322  3/22 03:00  2✓ 1✗  6m    │
│                             │ 20260321  3/21 03:00  4✓ 0✗  8m    │
│                             │ ▁▃▅▇█▅▃ pass rate                  │
├─────────────────────────────┴────────────────────────────────────┤
│ [q] Quit [t] Add [x] Remove [r] Run [s] Sync [m] Model [?] Help│
└──────────────────────────────────────────────────────────────────┘
```

## Features

- **TUI dashboard** -- real-time overview with Nord Aurora theme, countdown to next run, task/run detail panels
- **Interactive setup wizard** -- step-by-step `nightshift init` with back navigation, validation, local timezone detection
- **Built-in task templates** -- docs, tests, types, lint, todos, dead-code, deps, security, refactor -- add with `[t]` in TUI
- **Multiple task sources** -- YAML files, GitHub Issues, YouTrack, Trello (extensible via plugins)
- **Quality gates** -- blast radius checks, linter auto-detection, test regression detection
- **Safe by design** -- draft PRs only, never force-pushes, never touches main
- **Scheduling** -- launchd (macOS) / systemd (Linux) integration
- **Model selection** -- choose Claude model per task (Sonnet, Opus, Haiku)

## Installation

```bash
# Requires Python 3.13+, uv recommended
uv tool install .

# Or for development
git clone https://github.com/androsovm/NightShift.git
cd NightShift
uv sync --extra dev
```

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI (`claude`)
- [GitHub CLI](https://cli.github.com/) (`gh`) -- for creating PRs
- Git with push access to your repositories

## Quick Start

```bash
# Interactive setup wizard (5 steps with back navigation)
nightshift init

# Verify environment
nightshift doctor

# Open TUI dashboard
nightshift

# Or run directly
nightshift run --dry-run   # preview
nightshift run             # execute
```

### Setup Wizard

`nightshift init` walks you through 5 steps:

1. **Select projects** -- scans `~/Projects` for git repos, add custom paths
2. **Configure sources** -- YAML, GitHub Issues, YouTrack, or Trello per project
3. **Safety limits** -- max tasks, timeout, file/line limits
4. **API tokens** -- with links to where to create them, skippable
5. **Schedule** -- auto-detects your timezone, configurable run time

You can go back at any step.

## TUI Dashboard

Run `nightshift` with no arguments to launch the dashboard:

| Key | Action |
|-----|--------|
| `t` | Add built-in task (docs, tests, lint, etc.) |
| `x` | Remove built-in task |
| `m` | Change model for selected task |
| `r` | Trigger a dry run |
| `s` | Sync tasks from sources |
| `d` | Run doctor health check |
| `j/k` | Navigate lists |
| `Tab` | Switch panels |
| `?` | Help |
| `q` | Quit |

### Built-in Task Templates

Press `[t]` in the TUI to add maintenance tasks:

| Template | What it does |
|----------|-------------|
| `docs` | Update README, docstrings, inline comments |
| `tests` | Write unit tests for uncovered code paths |
| `types` | Add type annotations to functions |
| `lint` | Fix all ruff/eslint/flake8 warnings |
| `todos` | Implement TODO/FIXME comments |
| `dead-code` | Remove unused imports, functions, files |
| `deps` | Update minor/patch dependency versions |
| `security` | Audit for OWASP top-10 vulnerabilities |
| `refactor` | Simplify functions >50 lines |

Each template comes with a pre-filled intent, scope, and constraints so Claude gets a clear, focused assignment.

## Configuration

### Global config (`~/.nightshift/config.yaml`)

```yaml
schedule:
  time: "03:00"
  timezone: Europe/Berlin
  max_duration_hours: 4
projects:
  - path: /home/user/projects/myapp
    sources: [yaml]
max_prs_per_night: 10
```

### Project config (`.nightshift.yaml` in project root)

```yaml
sources:
  - type: github
    repo: user/myapp
    labels: [nightshift]

limits:
  max_tasks_per_run: 5
  task_timeout_minutes: 45
  max_files_changed: 20
  max_lines_changed: 500

default_model: claude-sonnet-4-6

# Inline YAML tasks
tasks:
  - id: remove-dead-code
    title: Remove dead code in utils.py
    intent: Find and remove unused functions
    scope: [src/utils.py]
    priority: medium
```

### Task example: adding a feature

A task with all fields filled in -- Claude gets a focused assignment with clear boundaries:

```yaml
tasks:
  - id: add-health-endpoint
    title: Add /healthz endpoint
    priority: high
    model: claude-sonnet-4-6
    estimated_minutes: 20
    intent: |
      Add a GET /healthz endpoint that returns {"status": "ok", "version": "..."}
      reading the version from pyproject.toml. Include a test that checks
      the response status and JSON schema.
    scope:
      - src/api/routes.py
      - tests/test_routes.py
    constraints:
      - Do not add new dependencies
      - Follow the existing route registration pattern in routes.py
      - Version must be read at import time, not on every request
```

### Secrets (`~/.nightshift/.env`)

API tokens stored with `chmod 600`:

```
GITHUB_TOKEN=ghp_...
YOUTRACK_TOKEN=perm:...
TRELLO_KEY=...
TRELLO_TOKEN=...
```

## Task Sources

| Source | Filter | On completion |
|--------|--------|--------------|
| YAML | `tasks:` in `.nightshift.yaml`, status: pending | Sets status to done |
| GitHub Issues | label: `nightshift`, state: open | Closes issue + comment with PR link |
| YouTrack | tag: `nightshift` | Removes tag + posts comment |
| Trello | list: "NightShift Queue" | Moves card to "Done" |
| Built-in | Added via TUI `[t]` | Removed from queue |

## CLI Commands

| Command | Description |
|---------|-------------|
| `nightshift` | Launch TUI dashboard |
| `nightshift init` | Interactive setup wizard |
| `nightshift add` | Add a project to existing config |
| `nightshift sync` | Import tasks from configured sources |
| `nightshift run [--dry-run] [-p PROJECT]` | Execute a run |
| `nightshift status` | Show latest run results |
| `nightshift log [N]` | Run history / task details |
| `nightshift tasks list` | Show task queue |
| `nightshift tasks add` | Add a task manually |
| `nightshift doctor` | Environment health check |
| `nightshift install` | Set up scheduled runs (launchd/systemd) |
| `nightshift uninstall` | Remove scheduled runs |

## Writing a Plugin

NightShift supports third-party task sources via Python entry points.

```python
# nightshift_jira/source.py
from nightshift.models.config import SourceConfig
from nightshift.models.task import Task

class JiraSource:
    async def fetch_tasks(self, project_path: str, config: SourceConfig) -> list[Task]:
        # ... fetch from Jira API
        return tasks

    async def mark_done(self, task: Task, pr_url: str) -> None:
        # ... transition issue, post comment
        pass
```

```toml
# In your plugin's pyproject.toml
[project.entry-points."nightshift.sources"]
jira = "nightshift_jira.source:JiraSource"
```

```yaml
# .nightshift.yaml
sources:
  - type: jira
    options:
      url: https://mycompany.atlassian.net
      project_key: PROJ
```

## Sleep Prevention

For NightShift to run on schedule, the machine must stay awake overnight.

- **macOS**: System Settings > Energy > Options > "Prevent automatic sleeping when the display is off". Or: `sudo pmset -c disablesleep 1`
- **Linux**: `systemctl mask sleep.target suspend.target`

`nightshift doctor` will warn if sleep prevention is not configured.

## Security

- **Claude Code runs with `--dangerously-skip-permissions`** -- required for unattended operation. Only run on repositories you trust. Always review draft PRs before merging.
- **Draft PRs only** -- never pushes to main or merges anything.
- **API tokens** stored in `~/.nightshift/.env` with `chmod 600`. Never logged or committed.
- **Blast radius limits** prevent runaway changes -- configurable caps on files and lines per task.

## Development

```bash
git clone https://github.com/androsovm/NightShift.git
cd NightShift
uv sync --extra dev
uv run pytest          # 206 tests
```

## License

MIT
