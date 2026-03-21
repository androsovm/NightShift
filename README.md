# NightShift

CLI tool that runs [Claude Code](https://docs.anthropic.com/en/docs/claude-code) overnight to automatically close tech debt. While you sleep, NightShift collects tasks from various sources, runs Claude Code in isolated sessions, validates results through quality gates, and opens draft PRs. In the morning you get a digest with results.

## Features

- **Multiple task sources** — YAML files, GitHub Issues, YouTrack, Trello (and extensible via plugins)
- **Quality gates** — blast radius checks, linter auto-detection, test regression detection
- **Safe by design** — draft PRs only, never force-pushes, never touches main
- **Scheduling** — launchd (macOS) / systemd (Linux) integration
- **Rich CLI** — interactive setup wizard, status dashboard, run history

## Installation

```bash
# Requires Python 3.13+, uv recommended
uv tool install .

# Or for development
git clone https://github.com/user/nightshift.git
cd nightshift
uv sync --extra dev
```

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI (`claude`)
- [GitHub CLI](https://cli.github.com/) (`gh`) — for creating PRs
- Git with push access to your repositories

## Quick Start

```bash
# Interactive setup — picks projects, sources, tokens
nightshift init

# Verify environment
nightshift doctor

# Preview what would happen (no changes)
nightshift run --dry-run

# Execute for real
nightshift run

# Check results
nightshift status
nightshift log
```

## Configuration

### Global config (`~/.nightshift/config.yaml`)

```yaml
schedule:
  time: "04:00"
  timezone: UTC
  max_duration_hours: 4
projects:
  - path: /home/user/projects/myapp
    sources: [yaml, github]
max_prs_per_night: 10
```

### Project config (`.nightshift.yaml` in project root)

```yaml
sources:
  - type: yaml
  - type: github
    repo: user/myapp
    labels: [nightshift]

limits:
  max_tasks_per_run: 5
  task_timeout_minutes: 45
  max_files_changed: 20
  max_lines_changed: 500

# YAML tasks (inline source)
tasks:
  - id: remove-dead-code
    title: Remove dead code in utils.py
    intent: Find and remove unused functions
    scope: [src/utils.py]
    priority: medium
    status: pending
```

### Secrets (`~/.nightshift/.env`)

API tokens are stored in `~/.nightshift/.env` with `chmod 600`:

```
GITHUB_TOKEN=ghp_...
YOUTRACK_TOKEN=perm:...
TRELLO_KEY=...
TRELLO_TOKEN=...
```

## Task Sources

| Source | Filter | mark_done |
|--------|--------|-----------|
| YAML | `tasks:` in `.nightshift.yaml`, status: pending | Sets status to done |
| GitHub Issues | label: `nightshift`, state: open | Closes issue + comment with PR |
| YouTrack | tag: `nightshift` | Removes tag + comment |
| Trello | list: "NightShift Queue" | Moves card to "Done" |

## Writing a Plugin

NightShift supports third-party task sources via Python entry points.

### 1. Create an adapter class

```python
# nightshift_jira/source.py
from nightshift.models.config import SourceConfig
from nightshift.models.task import Task

class JiraSource:
    async def fetch_tasks(self, project_path: str, config: SourceConfig) -> list[Task]:
        jira_url = config.options["url"]
        project_key = config.options["project_key"]
        # ... fetch from Jira API, return Task objects
        return tasks

    async def mark_done(self, task: Task, pr_url: str) -> None:
        # ... transition issue, post comment
        pass
```

### 2. Register via entry point

```toml
# In your plugin's pyproject.toml
[project.entry-points."nightshift.sources"]
jira = "nightshift_jira.source:JiraSource"
```

### 3. Configure in project

```yaml
# .nightshift.yaml
sources:
  - type: jira
    options:
      url: https://mycompany.atlassian.net
      project_key: PROJ
      jql: "label = nightshift AND status = Open"
```

Once the plugin is installed (`pip install nightshift-jira`), it will be automatically discovered and available in `nightshift init`.

## CLI Commands

| Command | Description |
|---------|-------------|
| `nightshift init` | Interactive setup wizard |
| `nightshift run [--dry-run] [--project=X]` | Execute a run |
| `nightshift status` | Show latest run results |
| `nightshift log [N]` | Run history / task details |
| `nightshift doctor` | Environment health check |
| `nightshift install` | Set up scheduled runs (launchd/systemd) |
| `nightshift uninstall` | Remove scheduled runs |

### Sleep Prevention

For NightShift to run on schedule, the machine must stay awake overnight.

- **macOS**: Go to System Settings → Energy → Options → enable "Prevent automatic
  sleeping when the display is off". Or run: `sudo pmset -c disablesleep 1`
- **Linux**: Mask the sleep/suspend targets: `systemctl mask sleep.target suspend.target`

`nightshift doctor` will warn if sleep prevention is not configured.

## Security Considerations

- **Claude Code runs with `--dangerously-skip-permissions`** — this allows Claude to execute commands, edit files, and make commits without interactive confirmation. This is required for unattended overnight operation. Only run NightShift on repositories you trust, and always review the draft PRs it creates before merging.
- **Draft PRs only** — NightShift never pushes to `main` or merges anything. All changes go through draft PRs for human review.
- **GPG signing is disabled** for NightShift commits (`git -c commit.gpgsign=false`) to avoid blocking on passphrase prompts during unattended runs.
- **API tokens** are stored in `~/.nightshift/.env` with `chmod 600` (owner read/write only). Tokens are never logged or included in commits.
- **Blast radius limits** prevent runaway changes — configurable caps on files changed and lines modified per task.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## License

MIT
