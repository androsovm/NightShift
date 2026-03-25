# NightShift

Every backlog has that pile of tasks nobody gets to. Missing tests, stale docs, TODO comments from 2024, a small feature that's been "next sprint" for three months. Important enough to track, never urgent enough to do.

I wanted Claude Code to just... do them. While I sleep. The machine is on anyway -- why should Claude sit idle all night?

NightShift pulls tasks from your issue tracker (GitHub Issues, YouTrack, Trello, or just a YAML file), feeds them to [Claude Code](https://docs.anthropic.com/en/docs/claude-code) one by one, runs quality gates on the result, and opens draft PRs. You wake up, review the PRs over coffee, merge the good ones.

That's it. You sleep, robots work.

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

## How it works

1. You label issues in GitHub/YouTrack/Trello with any tag you choose (or write tasks in YAML)
2. `nightshift sync` pulls them into a local queue
3. At 3 AM (or whenever you set it), NightShift wakes up and for each task:
   - creates a branch
   - runs baseline tests
   - hands the task to Claude Code
   - checks the result against quality gates (blast radius, linter, test regression)
   - opens a draft PR if everything passes
4. You review the PRs in the morning

Every change goes through quality gates before a PR is created. If Claude breaks tests or touches too many files -- the task fails, no PR is opened, you see the details in the dashboard.

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
nightshift init          # interactive setup wizard
nightshift doctor        # verify environment
nightshift               # open TUI dashboard
nightshift run --dry-run # preview what would happen
nightshift run           # let it rip
```

The setup wizard walks you through 5 steps: pick your projects, configure task sources, set safety limits, add API tokens, choose a schedule. You can go back at any step.

## TUI Dashboard

Run `nightshift` with no arguments. Everything is a keystroke away:

| Key | Action |
|-----|--------|
| `t` | Add a built-in task (docs, tests, lint, etc.) |
| `x` | Remove a task |
| `m` | Change model for selected task |
| `r` | Trigger a dry run |
| `s` | Sync tasks from sources |
| `d` | Run doctor health check |
| `j/k` | Navigate lists |
| `Tab` | Switch panels |
| `?` | Help |
| `q` | Quit |

### Built-in Task Templates (WIP)

Don't want to write tasks from scratch? Press `[t]` in the TUI -- there are templates for the most common maintenance work. Still a work in progress, more templates coming:

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

### Writing a good task

The more context you give Claude, the better the result. Here's a task with all the fields:

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

- **intent** -- what to do and why. Be specific.
- **scope** -- which files Claude should focus on. Keeps changes contained.
- **constraints** -- what NOT to do. Surprisingly important for good results.

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

## Safety

NightShift is paranoid by design:

- **Draft PRs only** -- never pushes to main, never merges anything. You always have the final say.
- **Quality gates** -- blast radius limits (max files/lines changed), linter checks, test regression detection. If anything looks off, the task fails and no PR is created.
- **Claude Code runs with `--dangerously-skip-permissions`** -- required for unattended operation. Only run on repositories you trust.
- **Tokens** stored in `~/.nightshift/.env` with `chmod 600`. Never logged, never committed.

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

## Development

```bash
git clone https://github.com/androsovm/NightShift.git
cd NightShift
uv sync --extra dev
uv run pytest          # 216 tests
```

## License

MIT
