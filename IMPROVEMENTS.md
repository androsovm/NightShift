# NightShift — Improvement Ideas

Analysis as of 2026-03-22. Grouped by category, effort estimated as S (< 1 day), M (1–3 days), L (3–7 days), XL (> 1 week).

---

## 1. Reliability

### 1.1 File locking for tasks.yaml — S
**Problem:** `task_queue.py` uses atomic `os.replace`, but no file lock. If two processes (e.g. `nightshift run` and `nightshift sync`) run simultaneously, one overwrites the other's changes — classic lost update.
**Solution:** Use `fcntl.flock` (Unix) or `portalocker` for advisory locking on `tasks.yaml` reads/writes.

### 1.2 Graceful shutdown and SIGTERM handling — M
**Problem:** If `nightshift run` is killed (OOM, kill, reboot), the task stays `pending` and the repo may be in a dirty state (uncommitted branch, uncommitted changes).
**Solution:** Signal handler for SIGTERM/SIGINT: mark current task as `failed`, return repo to main, save partial result.

### 1.3 Retry with exponential backoff — S
**Problem:** Retry delay is fixed at 30 seconds (`_RETRY_DELAY_SECONDS = 30`). During prolonged outages, 3 retries at 30s is insufficient.
**Solution:** Exponential backoff: 30s → 60s → 120s. Optionally increase `_MAX_RETRIES` to 5 for network errors.

### 1.4 Check working tree cleanliness before start — S
**Problem:** `prepare_repo` runs `fetch + checkout main + pull` but doesn't check for uncommitted or stashed changes from a previous interrupted run.
**Solution:** Add `git status --porcelain` + `git stash` or `git reset --hard` with logging.

### 1.5 Heartbeat / watchdog — M
**Problem:** If Claude hangs or `subprocess.run` doesn't return (edge case), there is no external mechanism to detect stuck runs.
**Solution:** Write a heartbeat file (`~/.nightshift/heartbeat`) every N minutes. A separate `nightshift watchdog` command or check in `doctor`.

### 1.6 Default branch fallback — S
**Problem:** `prepare_repo` and `cleanup_branch` hardcode `main`. Some repos use `master`, `develop`, or other branches.
**Solution:** Auto-detect via `git symbolic-ref refs/remotes/origin/HEAD` or a `default_branch` config option in `.nightshift.yaml`.

### 1.7 Auto-retry for failed tasks — M
**Problem:** Once a task fails, it moves to `failed` and is never automatically retried. No mechanism for auto-retry on the next night.
**Solution:** Configurable `max_attempts` (default: 1). If attempts < max_attempts, the task remains `pending`. Also: cooldown between attempts (don't retry the same night).

---

## 2. Security

### 2.1 Prompt validation from external sources — M
**Problem:** Issue bodies from GitHub/YouTrack/Trello are inserted directly into the Claude prompt (`task.intent = issue.get("body")`). An attacker could create an issue with prompt injection, causing Claude to execute arbitrary commands.
**Solution:** Sanitization: strip code blocks with shell/bash, limit length, add explicit prohibitions to the system prompt. Optionally — a separate "review" pass where Claude checks the intent for safety before execution.

### 2.2 Sandboxing Claude execution — L
**Problem:** `--dangerously-skip-permissions` gives Claude full filesystem access. If a task is poorly described, Claude can delete files, modify configs outside the project, etc.
**Solution:** Explore running in a Docker container or with restricted PATH/chroot. At minimum — verify all changed files are within `project_path`.

### 2.3 Action audit log — M
**Problem:** No detailed log of which files were changed or which commands ran during each task. Hard to investigate when something goes wrong.
**Solution:** Save full git diff for each task, list of changed files, Claude output. Structured report in `~/.nightshift/audit/`.

### 2.4 Log rotation and size limits — S
**Problem:** Logs in `~/.nightshift/logs/` and `~/.nightshift/runs/` grow indefinitely. Over time — tens of gigabytes.
**Solution:** Configurable `log_retention_days` (default: 30). A `nightshift cleanup` command or auto-cleanup at startup.

### 2.5 Check .env file permissions on every read — S
**Problem:** `secrets.py` sets chmod 600 on creation and write, but doesn't check on read. Someone could accidentally make the file world-readable.
**Solution:** On `load_secrets()`, check `stat.S_IMODE` and warn (or refuse to read) if permissions are too open.

---

## 3. Features

### 3.1 Result notifications — M
**Problem:** After a nightly run, results are only visible via `nightshift status` or checking GitHub. No push notifications.
**Solution:** Plugin-based notification system: Telegram bot, Slack webhook, email, macOS notifications. Send a digest: N passed, M failed, PR links.

### 3.2 Web dashboard — XL
**Problem:** The entire UI is CLI-based. Inconvenient for quick project status overview.
**Solution:** Lightweight web server (FastAPI + htmx) with dashboard: run history, charts, PR links. `nightshift dashboard` starts on localhost.

### 3.3 Linear as a task source — M
**Problem:** Linear is a popular task tracker, but there's no adapter.
**Solution:** Implement `LinearSource` similar to `GitHubSource`. Linear has a convenient GraphQL API.

### 3.4 Jira as a task source — M
**Problem:** Jira is the most common enterprise task tracker.
**Solution:** Implement `JiraSource`. Jira REST API v3. Document as an example plugin adapter.

### 3.5 Parallel task execution for different projects — L
**Problem:** Projects are processed sequentially. If a user has 5 projects with 3 tasks each — everything runs linearly, which may consume the entire night window.
**Solution:** `asyncio.gather` or `ProcessPoolExecutor` for parallel processing of different projects (not tasks within one project — they modify the same repo).

### 3.6 Monorepo support — L
**Problem:** One project = one git repo. In a monorepo, multiple "logical projects" live in one repo, each with its own test suite.
**Solution:** A `working_dir` option in `.nightshift.yaml` to specify a subdirectory. Quality gates run within it.

### 3.7 Custom quality gates — M
**Problem:** Quality gates are hardcoded (blast radius, linter, tests). Can't add custom checks (type checker, security scan, custom script).
**Solution:** A `quality_gates` config in `.nightshift.yaml` with a list of shell commands. Each gate: name, command, exit code 0 = pass.

### 3.8 Auto-close issues after PR merge — M
**Problem:** In the MVP, a human closes the task in the source manually. This is tedious.
**Solution:** GitHub webhook listener or periodic check: if PR merged → call `adapter.mark_done()`. Or use "Closes #N" in the PR body (for GitHub).

### 3.9 Support for multiple LLM providers — L
**Problem:** Hard dependency on the `claude` CLI. Can't use other models or API directly.
**Solution:** An `LLMExecutor` abstraction with implementations: `ClaudeCLI`, `ClaudeAPI`, `OpenAI`, `Ollama`. Configured in `.nightshift.yaml`.

### 3.10 Task dependencies — M
**Problem:** Tasks are independent. Can't say "first do the refactor, then add the feature on top of it."
**Solution:** A `depends_on: [task-id]` field in `QueuedTask`. Task waits until dependencies reach `passed`.

### 3.11 Template prompts for common task types — S
**Problem:** For similar tasks (bugfix, refactoring, adding tests), the user writes the prompt from scratch each time.
**Solution:** Templates in `.nightshift.yaml` (`prompt_templates`): `bugfix`, `refactor`, `add-tests`, `docs`. A `template` field in the task for selection.

### 3.12 Run cost estimation — S
**Problem:** The user doesn't know how much a nightly run costs in money (Claude API tokens).
**Solution:** Parse usage from Claude output (or query via API), calculate approximate cost, display in `nightshift status`.

---

## 4. Developer Experience (DX)

### 4.1 `nightshift config show` — S
**Problem:** No command to view the current configuration in a readable format. Have to manually read YAML files.
**Solution:** A command that shows merged view of global + project config as a formatted table.

### 4.2 `nightshift config edit` — S
**Problem:** Changing config requires manually editing YAML. Easy to make formatting mistakes.
**Solution:** A command that opens the config in `$EDITOR` and validates after saving.

### 4.3 Shell auto-completion — S
**Problem:** Typer supports shell completion, but it's not configured.
**Solution:** Add `app.command("completion")` or instructions in `nightshift install` for installing completions.

### 4.4 `nightshift test` — run a single task in foreground — M
**Problem:** To debug a prompt you need to create a task, add it to the queue, run. Slow.
**Solution:** `nightshift test --task "Fix the login bug" --project ./my-app` — one-shot execution with terminal output, no queue entry or PR creation.

### 4.5 Dry-run with complexity estimation — S
**Problem:** `--dry-run` only shows the task list. Doesn't estimate time/resources needed.
**Solution:** Show estimated_minutes, total time, warning if it exceeds max_duration_hours.

### 4.6 Progress bar during execution — S
**Problem:** During `nightshift run` there is no visual progress. Hard to tell what's happening.
**Solution:** Rich progress bar: `[2/5] Running "Fix login bug"... 3m elapsed`.

### 4.7 `nightshift diff <task-id>` — S
**Problem:** To see what Claude did for a specific task, you need to switch branches.
**Solution:** A command that shows `git diff main...branch` for the task directly in the terminal.

### 4.8 Validate `.nightshift.yaml` on load — S
**Problem:** `load_project_config` silently ignores unknown fields and doesn't report typos.
**Solution:** Pydantic `model_config = ConfigDict(extra="forbid")` or at least a warning for unknown keys.

---

## 5. UX

### 5.1 Colored quality gate output — S
**Problem:** When quality gates fail, the error is displayed as plain text. Hard to quickly understand what went wrong.
**Solution:** Format gates_msg with Rich: red for failed, green for passed, table with checkmarks.

### 5.2 `nightshift sync --auto` without interactive prompts — S
**Problem:** `sync` uses `questionary.select` on conflicts. In automatic mode (cron) this will hang.
**Solution:** An `--auto` flag (or `--non-interactive`): on conflict, automatically `skip`. Check `sys.stdin.isatty()`.

### 5.3 CLI output internationalization — L
**Problem:** All messages are in English. May be inconvenient for non-English users.
**Solution:** Not a priority, but strings could be extracted to separate files with i18n support via `gettext`.

### 5.4 Group `tasks list` output by project — S
**Problem:** `nightshift tasks list` shows a flat list. With 20+ tasks from different projects, it's hard to navigate.
**Solution:** Group by project_path with headers. Add `--group-by project|status|priority`.

### 5.5 Smart task sorting — S
**Problem:** Sorting is by priority only. No consideration of estimated_minutes, attempt count, or age.
**Solution:** Configurable sort strategy: default `priority, -added_at`. A `--sort` option in CLI.

---

## 6. Architecture and Extensibility

### 6.1 Plugin hooks (lifecycle events) — L
**Problem:** Plugins can only add source adapters. Can't add hooks for "before execution", "after PR", "on error".
**Solution:** Event system: `on_task_start`, `on_task_complete`, `on_task_fail`, `on_run_complete`. Entry point `nightshift.hooks`. Enables notifications, metrics, and custom actions as plugins.

### 6.2 Migrate from YAML to SQLite for the queue — L
**Problem:** `tasks.yaml` is a single file, linear search O(n), no indexes, no concurrent access. Will be slow with hundreds of tasks.
**Solution:** SQLite with `aiosqlite`. Atomic transactions, indexes on status/project/priority. Migration on first run.

### 6.3 Configuration via environment variables — S
**Problem:** All settings are YAML-only. In CI/CD and Docker, env vars are more convenient.
**Solution:** Pydantic settings: `NIGHTSHIFT_MAX_PRS=5`, `NIGHTSHIFT_SCHEDULE_TIME=03:00`. Env vars override YAML.

### 6.4 Typed config for `claude_system_prompt` — S
**Problem:** `claude_system_prompt` is just a string. No structure.
**Solution:** Support file references: `claude_system_prompt: file://CLAUDE.md`. Easier to edit, can be shared across projects.

### 6.5 Extract git_ops into an abstract layer — M
**Problem:** `git_ops.py` contains both git operations and `gh pr create`. Hard to test: everything goes through subprocess.
**Solution:** A `VCSProvider` protocol with a `GitProvider` implementation. Simplifies testing (mock) and potential support for other VCS.

### 6.6 Separate `create_pr` into VCS and platform layers — S
**Problem:** `create_pr` in `git_ops.py` directly calls `gh`. Tied to GitHub. For GitLab or Bitbucket, the logic would need to be duplicated.
**Solution:** A `PlatformProvider` abstraction with `GitHubProvider`, `GitLabProvider` implementations. Detect by remote URL.

---

## 7. Testing

### 7.1 Integration tests with a real git repo — M
**Problem:** Tests in `test_git_ops.py` and `test_runner.py` mock subprocess. Real git scenarios (merge conflicts, detached HEAD) are not covered.
**Solution:** Pytest fixtures that create temporary git repos with commits. Test prepare_repo, create_branch, cleanup on real repos.

### 7.2 Tests for CLI commands — M
**Problem:** There are tests for `sync_cmd` and `tasks_cmd`, but none for `run`, `doctor`, `install`, `init`.
**Solution:** Use `typer.testing.CliRunner` to test all commands. Mock external dependencies.

### 7.3 Property-based tests for task_queue — S
**Problem:** CRUD operations in `task_queue.py` are only tested on happy paths.
**Solution:** Hypothesis for generating arbitrary tasks and CRUD operation sequences. Check invariants: no duplicate IDs, save+load = identity.

### 7.4 Tests for source adapters with recorded HTTP — M
**Problem:** GitHub/YouTrack/Trello sources require real API tokens for testing.
**Solution:** `pytest-recording` (VCR.py) for recording and replaying HTTP responses. Record once, then tests work offline.

### 7.5 Mutation testing — S
**Problem:** Code coverage doesn't guarantee test quality.
**Solution:** `mutmut` or `cosmic-ray` to verify that tests actually catch bugs. Target: > 80% mutation score for core logic.

---

## 8. Performance and Scalability

### 8.1 Lazy task loading — S
**Problem:** `load_tasks()` loads ALL tasks from `tasks.yaml` on every operation (even for `get_task` by ID). Will be slow with 1000+ tasks.
**Solution:** At minimum — caching within a single invocation. Ideally — migrate to SQLite (see 6.2).

### 8.2 Streaming Claude output — M
**Problem:** `subprocess.run` with `capture_output=True` buffers all output. For long tasks (30+ minutes) — no progress, high memory usage.
**Solution:** `subprocess.Popen` with real-time stdout/stderr reading. Stream to log file. Show last lines in progress bar.

### 8.3 Incremental pytest baseline — S
**Problem:** Baseline tests run the ENTIRE test suite. For large projects (1000+ tests) this takes 5-10 minutes, twice per task.
**Solution:** `pytest --co -q` to count tests without running (baseline). Or cache baseline between tasks within a single run.

---

## 9. Documentation and Onboarding

### 9.1 README with quick start — S
**Problem:** There is an MVP doc, but no README.md with a quick start for new users.
**Solution:** README with: what it is, installation via `pip/pipx`, `nightshift init`, first run.

### 9.2 Example `.nightshift.yaml` for different stacks — S
**Problem:** No example configs for Python, Node.js, Go, Rust projects.
**Solution:** An `examples/` directory with ready-made configs and explanations.

### 9.3 Troubleshooting guide — S
**Problem:** When something breaks, there is no diagnostic guide.
**Solution:** A section in README or a separate file: common errors, how to read logs, how to restart.

---

## 10. Quick Wins (can be done in a couple of hours)

| # | Idea | Effort |
|---|------|--------|
| 10.1 | Add `--version` flag to CLI | S |
| 10.2 | Show branch name when creating PR in console | S |
| 10.3 | Add `nightshift tasks count` for quick counting | S |
| 10.4 | Add `--json` flag to `status` and `tasks list` for machine parsing | S |
| 10.5 | Show estimated total time in dry-run | S |
| 10.6 | Add `"Closes #N"` to PR body for GitHub source for auto-close | S |
| 10.7 | Support `NIGHTSHIFT_CONFIG_DIR` env var for custom config location | S |
| 10.8 | Validate schedule.time format in config (HH:MM) | S |
| 10.9 | Add `--force` flag to `sync` for auto-update without prompts | S |
| 10.10 | Log nightshift version at run start for debugging | S |
