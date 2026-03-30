"""Main Textual TUI dashboard application for NightShift."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from nightshift.models.config import CLAUDE_MODELS, DEFAULT_CLAUDE_MODEL
from nightshift.tui.constants import CYAN, DIM, GREEN, GREY, PINK, POLL_INTERVAL, RED, YELLOW
from nightshift.tui.widgets.context_footer import ContextFooter
from nightshift.tui.widgets.header_bar import HeaderBar
from nightshift.tui.widgets.project_list import ProjectListPanel
from nightshift.tui.widgets.run_detail_panel import RunDetailPanel
from nightshift.tui.widgets.run_history_panel import RunHistoryPanel
from nightshift.tui.widgets.task_detail_panel import TaskDetailPanel
from nightshift.tui.widgets.task_queue_panel import TaskQueuePanel


class HelpScreen(ModalScreen[None]):
    """Modal overlay showing keybinding help."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Vertical {
        width: 60;
        height: auto;
        max-height: 30;
        border: solid #4C566A;
        background: #2E3440;
        padding: 1 2;
    }
    HelpScreen Static {
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        from rich.text import Text

        text = Text()
        text.append("NIGHTSHIFT HELP\n\n", style=f"bold {CYAN}")

        text.append("NAVIGATION\n", style=f"bold {YELLOW}")
        text.append("  j / ↓       Move down\n", style=f"{GREY}")
        text.append("  k / ↑       Move up\n", style=f"{GREY}")
        text.append("  Tab         Next panel\n", style=f"{GREY}")
        text.append("  Shift+Tab   Previous panel\n\n", style=f"{GREY}")

        text.append("ACTIONS\n", style=f"bold {GREEN}")
        text.append("  r           Run selected task\n", style=f"{GREY}")
        text.append("  R           Run all pending tasks\n", style=f"{GREY}")
        text.append("  a           Add project\n", style=f"{GREY}")
        text.append("  t           Add built-in task\n", style=f"{GREY}")
        text.append("  m           Change task model\n", style=f"{GREY}")
        text.append("  x           Toggle active/inactive, remove built-in\n", style=f"{GREY}")
        text.append("  s           Sync tasks from sources\n", style=f"{GREY}")
        text.append("  d           Run doctor check\n\n", style=f"{GREY}")

        text.append("GENERAL\n", style=f"bold {RED}")
        text.append("  ?           Toggle this help\n", style=f"{GREY}")
        text.append("  q           Quit\n", style=f"{GREY}")

        with Vertical():
            yield Static(text)

    def on_key(self, event: Key) -> None:
        if event.key in ("escape", "question_mark", "q"):
            self.dismiss(None)
            event.prevent_default()


class ConfirmScreen(ModalScreen[bool]):
    """Modal confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen > Vertical {
        width: 50;
        height: auto;
        border: solid #4C566A;
        background: #2E3440;
        padding: 1 2;
    }
    ConfirmScreen Label {
        margin-bottom: 1;
        text-style: bold;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        from rich.text import Text

        text = Text()
        text.append(self._message, style=f"{CYAN}")
        text.append("\n\n", style="default")
        text.append("[y] Yes  [n] No", style=f"{GREY}")

        with Vertical():
            yield Label(text)

    def on_key(self, event: Key) -> None:
        if event.key == "y":
            self.dismiss(True)
            event.prevent_default()
        elif event.key in ("n", "escape"):
            self.dismiss(False)
            event.prevent_default()


class AddTaskScreen(ModalScreen[str | None]):
    """Two-step modal: pick a template, then pick project(s). Returns None on cancel."""

    DEFAULT_CSS = """
    AddTaskScreen {
        align: center middle;
    }
    AddTaskScreen > Vertical {
        width: 80;
        height: auto;
        max-height: 40;
        border: solid #4C566A;
        background: #2E3440;
        padding: 1 2;
    }
    AddTaskScreen .atm-title {
        text-style: bold;
        margin-bottom: 1;
    }
    AddTaskScreen .atm-desc {
        color: #616E88;
        margin-bottom: 1;
    }
    AddTaskScreen ListView {
        height: auto;
        max-height: 30;
        background: #2E3440;
    }
    AddTaskScreen ListView > ListItem.-highlight {
        background: #242933;
    }
    AddTaskScreen ListView:focus > ListItem.-highlight {
        background: #20252E;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._phase = "template"  # "template" -> "project" -> "model" -> "frequency"
        self._selected_template_key: str | None = None
        self._selected_project_paths: list[str] = []
        self._selected_model: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Add built-in task", classes="atm-title")
            yield Label(
                "Select a task template, then choose which project(s) to add it to.",
                classes="atm-desc",
            )
            yield ListView(id="atm-list")

    BINDINGS = [
        Binding("enter", "select_item", "Select", show=False),
    ]

    def _focus_list(self) -> None:
        """Focus the list and ensure first item is highlighted."""
        lv = self.query_one("#atm-list", ListView)
        lv.focus()
        self.call_after_refresh(self._ensure_cursor)

    def _ensure_cursor(self) -> None:
        lv = self.query_one("#atm-list", ListView)
        if lv.index is None and len(list(lv.children)) > 0:
            lv.index = 0

    def action_select_item(self) -> None:
        """Forward Enter to the ListView's select action."""
        lv = self.query_one("#atm-list", ListView)
        if lv.index is not None:
            lv.action_select_cursor()

    def on_mount(self) -> None:
        self._rebuild_template_list()
        self._focus_list()

    def _get_selected_index(self, event: ListView.Selected) -> int | None:
        """Get the index of the selected item from its position in the list."""
        lv = event.list_view
        children = list(lv.children)
        try:
            return children.index(event.item)
        except ValueError:
            return None

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        from nightshift.config.loader import load_global_config
        from nightshift.tui.task_templates import TEMPLATES

        idx = self._get_selected_index(event)
        if idx is None:
            return

        if self._phase == "template":
            if 0 <= idx < len(TEMPLATES):
                self._selected_template_key = TEMPLATES[idx].key
                self._show_project_picker()

        elif self._phase == "project":
            config = load_global_config()
            projects = config.projects

            if idx == 0:
                self._selected_project_paths = [str(p.path) for p in projects]
            elif 1 <= idx <= len(projects):
                self._selected_project_paths = [str(projects[idx - 1].path)]
            else:
                return
            self._show_model_picker()

        elif self._phase == "model":
            if 0 <= idx < len(CLAUDE_MODELS):
                self._selected_model = CLAUDE_MODELS[idx]
                self._show_frequency_picker()

        elif self._phase == "frequency":
            from nightshift.models.task import TaskFrequency

            frequencies = [TaskFrequency.ONCE, TaskFrequency.WEEKLY, TaskFrequency.MONTHLY]
            if 0 <= idx < len(frequencies):
                self._add_tasks_for_projects(
                    self._selected_project_paths,
                    model=self._selected_model,
                    frequency=frequencies[idx],
                )

    def _show_project_picker(self) -> None:
        """Replace list contents with project selection."""
        from rich.text import Text

        from nightshift.config.loader import load_global_config
        from nightshift.tui.task_templates import TEMPLATE_BY_KEY

        self._phase = "project"
        tmpl = TEMPLATE_BY_KEY[self._selected_template_key]

        # Update title
        title_label = self.query_one(".atm-title", Label)
        title_label.update(f"Add: {tmpl.title}")

        desc_label = self.query_one(".atm-desc", Label)
        desc_label.update(tmpl.description)

        lv = self.query_one("#atm-list", ListView)
        lv.clear()

        config = load_global_config()
        projects = config.projects

        # "All projects" option
        all_text = Text()
        all_text.append("  All projects", style=f"bold {GREEN}")
        all_text.append(f"  ({len(projects)} projects)", style=f"{GREY}")
        lv.mount(ListItem(Label(all_text)))

        for ref in projects:
            row = Text()
            row.append(f"  {ref.path.name}", style=f"{CYAN}")
            path_str = str(ref.path).replace(str(ref.path.home()), "~")
            row.append(f"  {path_str}", style=f"{PINK}")
            lv.mount(ListItem(Label(row)))

        self._focus_list()

    def _show_model_picker(self) -> None:
        """Replace list contents with model selection."""
        from rich.text import Text

        self._phase = "model"

        title_label = self.query_one(".atm-title", Label)
        title_label.update("Select model")

        desc_label = self.query_one(".atm-desc", Label)
        desc_label.update("Which Claude model should execute this task?")

        lv = self.query_one("#atm-list", ListView)
        lv.clear()

        for m in CLAUDE_MODELS:
            row = Text()
            if m == DEFAULT_CLAUDE_MODEL:
                row.append(f"  {m}", style=f"bold {GREEN}")
                row.append("  (default)", style=f"{GREY}")
            else:
                row.append(f"  {m}", style=f"{CYAN}")
            lv.mount(ListItem(Label(row)))

        self._focus_list()

    def _show_frequency_picker(self) -> None:
        """Replace list contents with frequency selection."""
        from rich.text import Text

        self._phase = "frequency"

        title_label = self.query_one(".atm-title", Label)
        title_label.update("Select frequency")

        desc_label = self.query_one(".atm-desc", Label)
        desc_label.update("How often should this task run?")

        lv = self.query_one("#atm-list", ListView)
        lv.clear()

        options = [
            ("Once", "Run once, then done", GREEN),
            ("Weekly", "Auto-requeue every 7 days after completion", CYAN),
            ("Monthly", "Auto-requeue every 30 days after completion", CYAN),
        ]
        for label, desc, color in options:
            row = Text()
            row.append(f"  {label}", style=f"bold {color}")
            row.append(f"  {desc}", style=f"{GREY}")
            lv.mount(ListItem(Label(row)))

        self._focus_list()

    def _add_tasks_for_projects(
        self,
        project_paths: list[str],
        *,
        model: str | None = None,
        frequency: object = None,
    ) -> None:
        """Create QueuedTasks and save them."""
        from slugify import slugify

        from nightshift.models.task import QueuedTask, TaskCategory, TaskFrequency, TaskPriority, TaskStatus
        from nightshift.storage.task_queue import add_task, find_by_source_ref, update_task
        from nightshift.tui.task_templates import TEMPLATE_BY_KEY

        tmpl = TEMPLATE_BY_KEY[self._selected_template_key]
        added = 0

        for project_path in project_paths:
            project_name = Path(project_path).name
            source_ref = f"builtin:{tmpl.key}:{project_name}"

            # Check if already in queue
            existing = find_by_source_ref("builtin", source_ref)
            if existing:
                if existing.status not in (
                    TaskStatus.PASSED, TaskStatus.DONE, TaskStatus.SKIPPED,
                ):
                    # Active task exists — skip
                    continue
                # Terminal task exists — update in-place instead of creating duplicate
                freq = frequency if isinstance(frequency, TaskFrequency) else TaskFrequency.ONCE
                update_task(
                    existing.id,
                    status=TaskStatus.PENDING,
                    intent=tmpl.intent,
                    scope=list(tmpl.scope),
                    constraints=list(tmpl.constraints),
                    frequency=freq,
                    model=model,
                )
                added += 1
                continue

            task_id = slugify(f"{tmpl.key}-{project_name}")
            task = QueuedTask(
                id=task_id,
                title=f"{tmpl.title} ({project_name})",
                source_type="builtin",
                source_ref=source_ref,
                project_path=project_path,
                priority=TaskPriority(tmpl.priority),
                category=TaskCategory.BUILTIN,
                frequency=frequency if isinstance(frequency, TaskFrequency) else TaskFrequency.ONCE,
                intent=tmpl.intent,
                scope=list(tmpl.scope),
                constraints=list(tmpl.constraints),
                estimated_minutes=tmpl.estimated_minutes,
                model=model,
            )
            add_task(task)
            added += 1

        self.dismiss(f"Added {added} task(s): {tmpl.title}" if added else "Already in queue")

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            if self._phase == "frequency":
                self._show_model_picker()
                event.prevent_default()
            elif self._phase == "model":
                self._show_project_picker()
                event.prevent_default()
            elif self._phase == "project":
                self._phase = "template"
                self._rebuild_template_list()
                event.prevent_default()
            else:
                self.dismiss(None)
                event.prevent_default()

    def _rebuild_template_list(self) -> None:
        """Restore the template list (back from project picker)."""
        from rich.text import Text

        from nightshift.tui.task_templates import TEMPLATES

        title_label = self.query_one(".atm-title", Label)
        title_label.update("Add built-in task")

        desc_label = self.query_one(".atm-desc", Label)
        desc_label.update(
            "Select a task template, then choose which project(s) to add it to."
        )

        lv = self.query_one("#atm-list", ListView)
        lv.clear()
        for tmpl in TEMPLATES:
            row = Text()
            row.append(f"  {tmpl.key}", style=f"bold {CYAN}")
            row.append(f"  {tmpl.title}", style="default")
            if tmpl.wip:
                row.append("  [wip]", style="bold yellow")
            row.append("\n")
            row.append(f"    {tmpl.description}", style=f"{PINK}")
            lv.mount(ListItem(Label(row)))

        self._focus_list()


class ModelPickerScreen(ModalScreen[str | None]):
    """Modal to change the model of a selected task."""

    DEFAULT_CSS = """
    ModelPickerScreen {
        align: center middle;
    }
    ModelPickerScreen > Vertical {
        width: 55;
        height: auto;
        max-height: 20;
        border: solid #4C566A;
        background: #2E3440;
        padding: 1 2;
    }
    ModelPickerScreen .mp-title {
        text-style: bold;
        margin-bottom: 1;
    }
    ModelPickerScreen ListView {
        height: auto;
        max-height: 12;
        background: #2E3440;
    }
    ModelPickerScreen ListView > ListItem.-highlight {
        background: #242933;
    }
    ModelPickerScreen ListView:focus > ListItem.-highlight {
        background: #20252E;
    }
    """

    def __init__(self, task_id: str, current_model: str | None) -> None:
        super().__init__()
        self._task_id = task_id
        self._current_model = current_model

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Change model", classes="mp-title")
            yield ListView(id="mp-list")

    def on_mount(self) -> None:
        from rich.text import Text

        lv = self.query_one("#mp-list", ListView)
        for m in CLAUDE_MODELS:
            row = Text()
            is_current = m == self._current_model
            if is_current:
                row.append(f"  {m}", style=f"bold {GREEN}")
                row.append("  (current)", style=f"{GREY}")
            elif m == DEFAULT_CLAUDE_MODEL:
                row.append(f"  {m}", style=f"{CYAN}")
                row.append("  (default)", style=f"{GREY}")
            else:
                row.append(f"  {m}", style=f"{CYAN}")
            lv.mount(ListItem(Label(row)))

        lv.focus()
        self.call_after_refresh(self._ensure_cursor)

    def _ensure_cursor(self) -> None:
        lv = self.query_one("#mp-list", ListView)
        if lv.index is None and len(list(lv.children)) > 0:
            lv.index = 0

    BINDINGS = [
        Binding("enter", "select_item", "Select", show=False),
    ]

    def action_select_item(self) -> None:
        lv = self.query_one("#mp-list", ListView)
        if lv.index is not None:
            lv.action_select_cursor()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        children = list(event.list_view.children)
        try:
            idx = children.index(event.item)
        except ValueError:
            return
        if 0 <= idx < len(CLAUDE_MODELS):
            selected = CLAUDE_MODELS[idx]
            if selected != self._current_model:
                from nightshift.storage.task_queue import update_task

                update_task(self._task_id, model=selected)
                self.dismiss(selected)
            else:
                self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.prevent_default()


class AddProjectScreen(ModalScreen[str | None]):
    """Multi-phase modal to add a new project: pick repo → pick source → configure → save."""

    DEFAULT_CSS = """
    AddProjectScreen {
        align: center middle;
    }
    AddProjectScreen > Vertical {
        width: 80;
        height: auto;
        max-height: 40;
        border: solid #4C566A;
        background: #2E3440;
        padding: 1 2;
    }
    AddProjectScreen .ap-title {
        text-style: bold;
        margin-bottom: 1;
    }
    AddProjectScreen .ap-desc {
        color: #616E88;
        margin-bottom: 1;
    }
    AddProjectScreen ListView {
        height: auto;
        max-height: 30;
        background: #2E3440;
    }
    AddProjectScreen ListView > ListItem.-highlight {
        background: #242933;
    }
    AddProjectScreen ListView:focus > ListItem.-highlight {
        background: #20252E;
    }
    AddProjectScreen Input {
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._phase = "repo"  # "repo" -> "custom_path" -> "source" -> "source_config" -> "confirm"
        self._selected_path: Path | None = None
        self._selected_source: str | None = None
        self._source_config_fields: dict[str, str] = {}
        self._repos: list[Path] = []
        self._existing_paths: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Add project", classes="ap-title")
            yield Label(
                "Select a git repository to add to NightShift.",
                classes="ap-desc",
            )
            yield ListView(id="ap-list")

    BINDINGS = [
        Binding("enter", "select_item", "Select", show=False),
    ]

    def _focus_list(self) -> None:
        lv = self.query_one("#ap-list", ListView)
        lv.focus()
        self.call_after_refresh(self._ensure_cursor)

    def _ensure_cursor(self) -> None:
        lv = self.query_one("#ap-list", ListView)
        if lv.index is None and len(list(lv.children)) > 0:
            lv.index = 0

    def action_select_item(self) -> None:
        lv = self.query_one("#ap-list", ListView)
        if lv.index is not None:
            lv.action_select_cursor()

    def on_mount(self) -> None:
        from nightshift.config.loader import load_global_config

        config = load_global_config()
        self._existing_paths = {str(ref.path.resolve()) for ref in config.projects}
        self._rebuild_repo_list()
        self._focus_list()

    def _scan_git_repos(self, base: Path) -> list[Path]:
        repos: list[Path] = []
        if not base.is_dir():
            return repos
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            if (entry / ".git").is_dir():
                repos.append(entry)
            else:
                # Check one level deeper (e.g. Projects/otonfm/otonfm/.git)
                for sub in sorted(entry.iterdir()):
                    if sub.is_dir() and (sub / ".git").is_dir():
                        repos.append(sub)
        return repos

    def _detect_github_remote(self, project_path: Path) -> str | None:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "-C", str(project_path), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            url = result.stdout.strip()
            if not url:
                return None
            if url.startswith("git@"):
                parts = url.split(":")[-1]
                return parts.removesuffix(".git")
            if "github.com" in url:
                parts = url.split("github.com/")[-1]
                return parts.removesuffix(".git")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def _rebuild_repo_list(self) -> None:
        from rich.text import Text

        self._phase = "repo"
        default_dir = Path.home() / "Projects"
        self._repos = [
            r for r in self._scan_git_repos(default_dir)
            if str(r.resolve()) not in self._existing_paths
        ]

        title_label = self.query_one(".ap-title", Label)
        title_label.update("Add project")

        desc_label = self.query_one(".ap-desc", Label)
        if self._repos:
            desc_label.update(f"Found {len(self._repos)} new repos in ~/Projects")
        else:
            desc_label.update("No new repos found in ~/Projects. Enter a custom path.")

        lv = self.query_one("#ap-list", ListView)
        lv.clear()

        for repo in self._repos:
            row = Text()
            row.append(f"  {repo.name}", style=f"bold {CYAN}")
            path_str = str(repo).replace(str(Path.home()), "~")
            row.append(f"  {path_str}", style=f"{PINK}")
            lv.mount(ListItem(Label(row)))

        # Custom path option
        custom = Text()
        custom.append("  + Enter custom path...", style=f"{GREEN}")
        lv.mount(ListItem(Label(custom)))

        # Remove any leftover Input
        for inp in self.query("Input"):
            inp.remove()

        self._focus_list()

    def _show_custom_path_input(self) -> None:
        self._phase = "custom_path"
        title_label = self.query_one(".ap-title", Label)
        title_label.update("Enter project path")
        desc_label = self.query_one(".ap-desc", Label)
        desc_label.update("Path to a git repository directory")

        lv = self.query_one("#ap-list", ListView)
        lv.clear()

        container = self.query_one("Vertical")
        inp = Input(placeholder="~/Projects/my-repo", id="ap-path-input")
        container.mount(inp)
        inp.focus()

    def _show_source_picker(self) -> None:
        from rich.text import Text

        from nightshift.sources import available_sources

        self._phase = "source"

        title_label = self.query_one(".ap-title", Label)
        title_label.update(f"Task source for {self._selected_path.name}")

        desc_label = self.query_one(".ap-desc", Label)
        desc_label.update("Where should NightShift find tasks for this project?")

        lv = self.query_one("#ap-list", ListView)
        lv.clear()

        labels = {
            "yaml": "YAML — local task list in .nightshift.yaml",
            "github": "GitHub Issues — fetch from labeled issues",
            "youtrack": "YouTrack — fetch tasks by tag",
            "trello": "Trello — fetch from a board list",
        }

        for name in available_sources():
            row = Text()
            row.append(f"  {name}", style=f"bold {CYAN}")
            desc = labels.get(name, f"Plugin: {name}")
            row.append(f"  {desc}", style=f"{GREY}")
            lv.mount(ListItem(Label(row)))

        # Remove any leftover Input
        for inp in self.query("Input"):
            inp.remove()

        self._focus_list()

    def _show_source_config(self) -> None:
        """Show Input fields for source-specific configuration."""
        self._phase = "source_config"
        self._source_config_fields = {}

        title_label = self.query_one(".ap-title", Label)
        title_label.update(f"Configure {self._selected_source}")

        lv = self.query_one("#ap-list", ListView)
        lv.clear()

        container = self.query_one("Vertical")

        # Remove any leftover Input widgets
        for inp in self.query("Input"):
            inp.remove()

        if self._selected_source == "github":
            detected = self._detect_github_remote(self._selected_path)
            desc_label = self.query_one(".ap-desc", Label)
            if detected:
                desc_label.update(f"Detected remote: {detected}")
            else:
                desc_label.update("Enter GitHub repository details")

            inp_repo = Input(
                placeholder="owner/repo",
                value=detected or "",
                id="ap-github-repo",
            )
            inp_label = Input(
                placeholder="Issue label filter",
                value="nightshift",
                id="ap-github-label",
            )
            container.mount(inp_repo)
            container.mount(inp_label)
            inp_repo.focus()

        elif self._selected_source == "youtrack":
            desc_label = self.query_one(".ap-desc", Label)
            desc_label.update("Enter YouTrack connection details")

            container.mount(Input(placeholder="Base URL (e.g. https://youtrack.example.com)", id="ap-yt-url"))
            container.mount(Input(placeholder="Project ID", id="ap-yt-project"))
            container.mount(Input(placeholder="Tag (default: nightshift)", value="nightshift", id="ap-yt-tag"))
            self.query_one("#ap-yt-url").focus()

        elif self._selected_source == "trello":
            desc_label = self.query_one(".ap-desc", Label)
            desc_label.update("Enter Trello board details")

            container.mount(Input(placeholder="Board ID", id="ap-trello-board"))
            container.mount(Input(placeholder="List name (default: NightShift Queue)", value="NightShift Queue", id="ap-trello-list"))
            self.query_one("#ap-trello-board").focus()

    def _collect_source_config(self) -> "SourceConfig | None":
        """Collect source config from Input fields. Returns None if required fields missing."""
        from nightshift.models.config import SourceConfig

        if self._selected_source == "yaml":
            return SourceConfig(type="yaml")

        if self._selected_source == "github":
            repo = self.query_one("#ap-github-repo", Input).value.strip()
            label = self.query_one("#ap-github-label", Input).value.strip()
            if not repo:
                self.notify("Repository is required", severity="error", timeout=2)
                return None
            return SourceConfig(
                type="github",
                repo=repo,
                labels=[label] if label else ["nightshift"],
            )

        if self._selected_source == "youtrack":
            url = self.query_one("#ap-yt-url", Input).value.strip()
            project = self.query_one("#ap-yt-project", Input).value.strip()
            tag = self.query_one("#ap-yt-tag", Input).value.strip()
            if not url or not project:
                self.notify("URL and project ID are required", severity="error", timeout=2)
                return None
            return SourceConfig(
                type="youtrack",
                base_url=url,
                project_id=project,
                tag=tag or "nightshift",
            )

        if self._selected_source == "trello":
            board = self.query_one("#ap-trello-board", Input).value.strip()
            list_name = self.query_one("#ap-trello-list", Input).value.strip()
            if not board:
                self.notify("Board ID is required", severity="error", timeout=2)
                return None
            return SourceConfig(
                type="trello",
                board_id=board,
                list_name=list_name or "NightShift Queue",
            )

        # Plugin source — no config fields, just save with empty options
        return SourceConfig(type=self._selected_source)

    def _show_confirm(self) -> None:
        """Show confirmation screen with summary."""
        from rich.text import Text

        self._phase = "confirm"

        title_label = self.query_one(".ap-title", Label)
        title_label.update("Confirm")

        desc_label = self.query_one(".ap-desc", Label)
        needs_token = self._selected_source in ("github", "youtrack", "trello")
        if needs_token:
            desc_label.update("Press Enter to save. Configure API tokens in ~/.nightshift/.env")
        else:
            desc_label.update("Press Enter to save")

        lv = self.query_one("#ap-list", ListView)
        lv.clear()

        # Remove Input widgets
        for inp in self.query("Input"):
            inp.remove()

        text = Text()
        path_str = str(self._selected_path).replace(str(Path.home()), "~")
        text.append(f"  Project:  ", style=f"{GREY}")
        text.append(f"{self._selected_path.name}", style=f"bold {CYAN}")
        text.append(f"\n  Path:     ", style=f"{GREY}")
        text.append(f"{path_str}", style=f"{PINK}")
        text.append(f"\n  Source:   ", style=f"{GREY}")
        text.append(f"{self._selected_source}", style=f"bold {GREEN}")

        lv.mount(ListItem(Label(text)))

        self._focus_list()

    def _save_project(self) -> None:
        """Save project config and update global config."""
        from nightshift.config.loader import (
            load_global_config,
            load_project_config,
            save_global_config,
            save_project_config,
        )
        from nightshift.models.config import ProjectConfig, ProjectLimits, ProjectRef

        src = self._collect_source_config()
        if src is None:
            return

        global_config = load_global_config()

        # Copy limits from first existing project, or use defaults
        if global_config.projects:
            existing_pc = load_project_config(global_config.projects[0].path)
            limits = existing_pc.limits
        else:
            limits = ProjectLimits()

        pc = ProjectConfig(sources=[src], limits=limits)
        ref = ProjectRef(path=self._selected_path, sources=[self._selected_source])
        global_config.projects.append(ref)

        save_global_config(global_config)
        save_project_config(self._selected_path, pc)

        self.dismiss(f"Added project: {self._selected_path.name}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        from nightshift.sources import available_sources

        children = list(event.list_view.children)
        try:
            idx = children.index(event.item)
        except ValueError:
            return

        if self._phase == "repo":
            if idx < len(self._repos):
                self._selected_path = self._repos[idx].resolve()
                self._show_source_picker()
            elif idx == len(self._repos):
                # Custom path
                self._show_custom_path_input()

        elif self._phase == "source":
            sources = available_sources()
            if 0 <= idx < len(sources):
                self._selected_source = sources[idx]
                if self._selected_source == "yaml":
                    self._show_confirm()
                else:
                    self._show_source_config()

        elif self._phase == "confirm":
            self._save_project()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._phase == "custom_path":
            raw = event.value.strip()
            if not raw:
                return
            path = Path(raw).expanduser().resolve()
            if not (path / ".git").is_dir():
                self.notify(f"Not a git repository: {path}", severity="error", timeout=3)
                return
            if str(path) in self._existing_paths:
                self.notify(f"Already configured: {path.name}", severity="warning", timeout=2)
                return
            self._selected_path = path
            self._show_source_picker()

        elif self._phase == "source_config":
            # Enter on any config Input → try to proceed to confirm
            src = self._collect_source_config()
            if src is not None:
                self._show_confirm()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            if self._phase == "confirm":
                if self._selected_source == "yaml":
                    self._show_source_picker()
                else:
                    self._show_source_config()
                event.prevent_default()
            elif self._phase == "source_config":
                self._show_source_picker()
                event.prevent_default()
            elif self._phase == "source":
                self._rebuild_repo_list()
                event.prevent_default()
            elif self._phase == "custom_path":
                self._rebuild_repo_list()
                event.prevent_default()
            else:
                self.dismiss(None)
                event.prevent_default()


class RunConfirmScreen(ModalScreen[str | None]):
    """Confirmation screen before running tasks. Shows task list and run mode."""

    DEFAULT_CSS = """
    RunConfirmScreen {
        align: center middle;
    }
    RunConfirmScreen > Vertical {
        width: 75;
        height: auto;
        max-height: 35;
        border: solid #4C566A;
        background: #2E3440;
        padding: 1 2;
    }
    RunConfirmScreen .rc-title {
        text-style: bold;
        margin-bottom: 1;
    }
    RunConfirmScreen .rc-tasks {
        margin-bottom: 1;
        max-height: 15;
    }
    RunConfirmScreen .rc-footer {
        color: #616E88;
    }
    """

    def __init__(self, tasks: list, *, single: bool = False) -> None:
        super().__init__()
        self._tasks = tasks
        self._single = single

    def compose(self) -> ComposeResult:
        from rich.text import Text

        with Vertical():
            if self._single:
                title = f"Run 1 task"
            else:
                title = f"Run all {len(self._tasks)} pending tasks"
            yield Label(title, classes="rc-title")

            # Task list preview
            task_text = Text()
            for task in self._tasks[:15]:
                project_name = Path(task.project_path).name
                task_text.append(f"  {task.priority.value[0].upper()} ", style=f"{GREY}")
                task_text.append(f"{task.title[:45]}", style=f"{CYAN}")
                task_text.append(f"  {project_name}", style=f"{PINK}")
                if task.model:
                    task_text.append(f"  [{task.model}]", style=f"{DIM}")
                task_text.append("\n")
            if len(self._tasks) > 15:
                task_text.append(f"  ... and {len(self._tasks) - 15} more\n", style=f"{GREY}")

            yield Label(task_text, classes="rc-tasks")

            footer = Text()
            footer.append("[enter] ", style=f"bold {GREEN}")
            footer.append("Run now", style=f"{GREEN}")
            footer.append("    ", style="default")
            footer.append("[d] ", style=f"bold {YELLOW}")
            footer.append("Dry run", style=f"{YELLOW}")
            footer.append("    ", style="default")
            footer.append("[esc] ", style=f"bold {GREY}")
            footer.append("Cancel", style=f"{GREY}")
            yield Label(footer, classes="rc-footer")

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.dismiss("live")
            event.prevent_default()
        elif event.key == "d":
            self.dismiss("dry")
            event.prevent_default()
        elif event.key == "escape":
            self.dismiss(None)
            event.prevent_default()


class NightShiftApp(App):
    """NightShift TUI dashboard — Clorch-style."""

    CSS_PATH = "app.tcss"
    TITLE = "NightShift"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("question_mark", "help", "Help", show=False),
        Binding("t", "add_task", "Add task", show=False),
        Binding("m", "change_model", "Change model", show=False),
        Binding("x", "remove_task", "Remove task", show=False),
        Binding("r", "run_selected", "Run task", show=False),
        Binding("R", "run_all", "Run all", show=False),
        Binding("s", "trigger_sync", "Sync", show=False),
        Binding("d", "trigger_doctor", "Doctor", show=False),
        Binding("e", "retry_task", "Retry failed", show=False),
        Binding("p", "cycle_priority", "Priority", show=False),
        Binding("a", "add_project", "Add project", show=False),
    ]

    # Task IDs that the TUI has launched but the executor hasn't picked up yet.
    # Used purely for visual feedback — never written to disk.
    _launched_task_ids: set[str] = set()

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Horizontal(id="main-split"):
            with Vertical(id="left-column"):
                yield TaskQueuePanel()
                yield ProjectListPanel()
            with Vertical(id="right-column"):
                yield TaskDetailPanel()
                yield RunDetailPanel()
                yield RunHistoryPanel()
        yield ContextFooter()

    def on_mount(self) -> None:
        from nightshift.storage.task_queue import recover_stale_running

        recovered = recover_stale_running()
        if recovered:
            self.notify(f"Recovered {recovered} stale running task(s)", timeout=3)

        self._poll_data()
        self.set_interval(POLL_INTERVAL, self._poll_data)

    def _poll_data(self) -> None:
        """Refresh all panels from disk storage."""
        from nightshift.config.loader import load_global_config
        from nightshift.models.task import TaskCategory, TaskStatus
        from nightshift.storage.store import load_latest_run, load_runs
        from nightshift.storage.task_queue import load_tasks, requeue_recurring_builtins

        # Auto-requeue recurring built-in tasks whose interval has elapsed
        requeue_recurring_builtins()

        # Load ALL tasks — the panel handles grouping by category
        all_tasks = load_tasks()

        # Overlay in-memory "launched" state: show pending tasks as running
        # if TUI launched them but executor hasn't updated the file yet.
        # Clear IDs once the executor has set a real terminal status.
        for task in all_tasks:
            if task.id in self._launched_task_ids:
                if task.status.value in ("passed", "failed", "skipped"):
                    self._launched_task_ids.discard(task.id)
                else:
                    task.status = TaskStatus.RUNNING

        # Compute pending counts (only active + builtin, not inactive)
        active_pending = [
            t for t in all_tasks
            if t.status == TaskStatus.PENDING
            and t.category in (TaskCategory.ACTIVE, TaskCategory.BUILTIN)
        ]

        # Projects
        config = load_global_config()
        projects = config.projects

        # Task counts per project (active pending only)
        task_counts: dict[str, int] = {}
        for task in active_pending:
            task_counts[task.project_path] = task_counts.get(task.project_path, 0) + 1

        # Runs
        runs = load_runs(limit=15)
        latest = runs[0] if runs else None

        # Update header
        last_passed = last_failed = last_skipped = 0
        if latest:
            last_passed = sum(1 for t in latest.task_results if t.status == "passed")
            last_failed = sum(1 for t in latest.task_results if t.status == "failed")
            last_skipped = sum(1 for t in latest.task_results if t.status == "skipped")

        running_count = sum(
            1 for t in all_tasks
            if t.status == TaskStatus.RUNNING
            and t.category in (TaskCategory.ACTIVE, TaskCategory.BUILTIN)
        )

        header = self.query_one(HeaderBar)
        header.update_data(
            pending_count=len(active_pending),
            running_count=running_count,
            project_count=len(projects),
            last_run_passed=last_passed,
            last_run_failed=last_failed,
            last_run_skipped=last_skipped,
            schedule_time=config.schedule.time,
            schedule_tz=config.schedule.timezone,
        )

        # Update panels — pass ALL tasks, panel groups by category
        self.query_one(TaskQueuePanel).update_tasks(all_tasks)
        self.query_one(ProjectListPanel).update_projects(projects, task_counts)
        history = self.query_one(RunHistoryPanel)
        history.update_runs(runs)

        # Update task detail for currently selected task
        selected_task = self.query_one(TaskQueuePanel).get_selected_task()
        if selected_task:
            self.query_one(TaskDetailPanel).update_task(selected_task)

        # Keep run detail pinned to the selected history row.
        detail = self.query_one(RunDetailPanel)
        selected_run = history.get_selected_run()
        if selected_run:
            detail.update_run(selected_run)
        elif latest:
            detail.update_run(latest)
        else:
            detail.update_run(None)

    def on_list_view_highlighted(self, event) -> None:
        """When cursor moves in any list, update corresponding detail panel."""
        # Task queue → task detail
        task_queue = self.query_one(TaskQueuePanel)
        task = task_queue.get_selected_task()
        if task:
            self.query_one(TaskDetailPanel).update_task(task)

        # Run history → run detail
        history = self.query_one(RunHistoryPanel)
        run = history.get_selected_run()
        if run:
            self.query_one(RunDetailPanel).update_run(run)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_add_task(self) -> None:
        def _on_result(result: str | None) -> None:
            if result:
                self.notify(result, timeout=3)
            self._poll_data()

        self.push_screen(AddTaskScreen(), callback=_on_result)

    def action_add_project(self) -> None:
        def _on_result(result: str | None) -> None:
            if result:
                self.notify(result, timeout=3)
            self._poll_data()

        self.push_screen(AddProjectScreen(), callback=_on_result)

    def action_change_model(self) -> None:
        task_queue = self.query_one(TaskQueuePanel)
        task = task_queue.get_selected_task()
        if not task:
            self.notify("No task selected", timeout=2)
            return

        def _on_result(result: str | None) -> None:
            if result:
                self.notify(f"{task.id} → {result}", timeout=3)
                self._poll_data()
                # Refresh task detail with updated data
                from nightshift.storage.task_queue import get_task

                updated = get_task(task.id)
                if updated:
                    self.query_one(TaskDetailPanel).update_task(updated)

        self.push_screen(
            ModelPickerScreen(task.id, task.model), callback=_on_result
        )

    def action_cycle_priority(self) -> None:
        task_queue = self.query_one(TaskQueuePanel)
        task = task_queue.get_selected_task()
        if not task:
            self.notify("No task selected", timeout=2)
            return

        from nightshift.models.task import TaskPriority
        from nightshift.storage.task_queue import get_task, update_task

        cycle = {
            TaskPriority.LOW: TaskPriority.MEDIUM,
            TaskPriority.MEDIUM: TaskPriority.HIGH,
            TaskPriority.HIGH: TaskPriority.LOW,
        }
        new_priority = cycle[task.priority]
        update_task(task.id, priority=new_priority)
        self._poll_data()
        updated = get_task(task.id)
        if updated:
            self.query_one(TaskDetailPanel).update_task(updated)
        self.notify(f"{task.title}: {new_priority.value}", timeout=2)

    def action_remove_task(self) -> None:
        from nightshift.models.task import TaskCategory
        from nightshift.storage.task_queue import activate_task, deactivate_task

        task_queue = self.query_one(TaskQueuePanel)
        task = task_queue.get_selected_task()
        if not task:
            self.notify("No task selected", timeout=2)
            return

        if task.category == TaskCategory.ACTIVE:
            # Source-received active task → deactivate
            deactivate_task(task.id)
            self.notify(f"Deactivated: {task.title}. Для удаления закройте в источнике", timeout=3)
            self._poll_data()

        elif task.category == TaskCategory.INACTIVE:
            # Inactive → toggle back to active
            activate_task(task.id)
            self.notify(f"Activated: {task.title}", timeout=2)
            self._poll_data()

        elif task.category == TaskCategory.BUILTIN:
            # Built-in → confirm and remove
            def _on_confirm(confirmed: bool) -> None:
                if confirmed:
                    from nightshift.storage.task_queue import remove_task

                    removed = remove_task(task.id)
                    if removed:
                        self.notify(f"Removed: {task.title}", timeout=2)
                        self._poll_data()

            self.push_screen(
                ConfirmScreen(f"Remove \"{task.title}\"?"), callback=_on_confirm
            )

    def action_run_all(self) -> None:
        """Run all pending tasks with confirmation."""
        from nightshift.storage.task_queue import get_pending_tasks

        pending = get_pending_tasks()

        if not pending:
            self.notify("No pending tasks", timeout=2)
            return

        def _on_result(mode: str | None) -> None:
            if mode == "live":
                self._mark_tasks_running([t.id for t in pending])
                self._run_command("nightshift", "run", label=f"Running {len(pending)} tasks")
            elif mode == "dry":
                self._run_command("nightshift", "run", "--dry-run", label=f"Dry run ({len(pending)} tasks)")

        self.push_screen(RunConfirmScreen(pending), callback=_on_result)

    def action_run_selected(self) -> None:
        """Run the selected task with confirmation. Auto-requeues failed tasks."""
        from nightshift.models.task import TaskCategory

        task_queue = self.query_one(TaskQueuePanel)
        task = task_queue.get_selected_task()
        if not task:
            return
        if task.category == TaskCategory.INACTIVE:
            self.notify("Activate task first (press x)", timeout=2)
            return

        def _on_result(mode: str | None) -> None:
            # Requeue non-pending tasks so the runner can pick them up
            if task.status.value in ("failed", "passed", "done", "skipped") and mode in ("live", "dry"):
                from nightshift.models.task import TaskStatus
                from nightshift.storage.task_queue import update_task

                updates: dict[str, object] = {"status": TaskStatus.PENDING}

                # For builtin tasks, refresh intent/constraints from the latest template
                if task.source_type == "builtin" and task.source_ref:
                    from nightshift.tui.task_templates import TEMPLATE_BY_KEY

                    # source_ref format: "builtin:{key}:{project}"
                    parts = task.source_ref.split(":", 2)
                    if len(parts) >= 2:
                        tmpl = TEMPLATE_BY_KEY.get(parts[1])
                        if tmpl:
                            updates["intent"] = tmpl.intent
                            updates["scope"] = list(tmpl.scope)
                            updates["constraints"] = list(tmpl.constraints)

                update_task(task.id, **updates)

            project = Path(task.project_path).name
            if mode == "live":
                self._mark_tasks_running([task.id])
                self._run_command("nightshift", "run", "-p", project, "-t", task.id, label=f"Running: {task.title}")
            elif mode == "dry":
                self._run_command("nightshift", "run", "--dry-run", "-p", project, "-t", task.id, label=f"Dry run: {task.title}")

        self.push_screen(RunConfirmScreen([task], single=True), callback=_on_result)

    def action_retry_task(self) -> None:
        """Requeue a failed task back to pending."""
        task_queue = self.query_one(TaskQueuePanel)
        task = task_queue.get_selected_task()
        if not task:
            self.notify("No task selected", timeout=2)
            return
        if task.status.value != "failed":
            self.notify("Task is not failed", timeout=2)
            return

        from nightshift.models.task import TaskStatus
        from nightshift.storage.task_queue import update_task

        update_task(task.id, status=TaskStatus.PENDING)
        self.notify(f"Requeued: {task.title}", timeout=2)
        self._poll_data()
        # Refresh detail panel with updated task
        from nightshift.storage.task_queue import get_task
        updated = get_task(task.id)
        if updated:
            self.query_one(TaskDetailPanel).update_task(updated)

    def action_trigger_sync(self) -> None:
        def _on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._run_command("nightshift", "sync", label="Syncing tasks")

        self.push_screen(
            ConfirmScreen("Sync tasks from all sources?"), callback=_on_confirm
        )

    def action_trigger_doctor(self) -> None:
        def _on_confirm(confirmed: bool) -> None:
            if confirmed:
                self._run_command("nightshift", "doctor", label="Doctor check")

        self.push_screen(
            ConfirmScreen("Run environment health check?"), callback=_on_confirm
        )

    _run_label: str = ""

    def _mark_tasks_running(self, task_ids: list[str]) -> None:
        """Mark tasks as visually running in the TUI (in-memory only).

        The actual status in tasks.yaml stays pending so the executor
        subprocess can pick them up via ``get_pending_tasks()``.
        """
        self._launched_task_ids.update(task_ids)
        self._poll_data()

    def _run_command(self, *args: str, label: str = "Running...") -> None:
        """Run a CLI command in background with live feedback."""
        import subprocess

        self._run_label = label
        self.query_one(HeaderBar).set_running(label)
        self.query_one(RunHistoryPanel).set_running(label)
        self._poll_data()

        def _work() -> int:
            try:
                proc = subprocess.run(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return proc.returncode
            except FileNotFoundError:
                return -1

        self.run_worker(_work, name="nightshift-run", group="run", thread=True, exclusive=True, exit_on_error=False)

    def on_worker_state_changed(self, event) -> None:
        """Handle worker completion — update header and show result."""
        from textual.worker import WorkerState

        if event.worker.name != "nightshift-run":
            return
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._launched_task_ids.clear()
            self.query_one(HeaderBar).set_idle()
            self.query_one(RunHistoryPanel).set_idle()
            self._poll_data()

            label = self._run_label
            self._run_label = ""

            if event.state == WorkerState.SUCCESS:
                returncode = event.worker.result
                if returncode == 0:
                    self.notify(f"Done: {label}", timeout=3)
                else:
                    self.notify(f"Failed: {label} (exit {returncode})", severity="error", timeout=5)
            elif event.state == WorkerState.ERROR:
                self.notify(f"Error: {label}", severity="error", timeout=5)


def run_dashboard() -> None:
    """Launch the NightShift TUI dashboard."""
    app = NightShiftApp()
    app.run()
