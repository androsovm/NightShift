"""Project list panel — configured projects overview."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Label, Static

from nightshift.models.config import ProjectRef
from nightshift.tui.constants import CYAN, GREEN, GREY


class ProjectListPanel(Static):
    """Bordered panel showing configured projects."""

    DEFAULT_CSS = """
    ProjectListPanel {
        height: auto;
        max-height: 10;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="projects-panel")
        self._content: Label | None = None
        self._fingerprint: str = ""

    def compose(self):
        self._content = Label("")
        yield self._content

    def on_mount(self) -> None:
        self.border_title = "PROJECTS"
        self.add_class("panel")

    def update_projects(
        self, projects: list[ProjectRef], task_counts: dict[str, int] | None = None
    ) -> None:
        if self._content is None:
            return

        counts = task_counts or {}
        fp = "|".join(
            f"{ref.path}:{counts.get(str(ref.path), 0)}" for ref in projects
        )
        if fp == self._fingerprint:
            return
        self._fingerprint = fp

        if not projects:
            self._content.update(Text("No projects configured", style=f"italic {GREY}"))
            return

        text = Text()
        for i, ref in enumerate(projects):
            if i > 0:
                text.append("\n")
            name = ref.path.name
            path_str = str(ref.path).replace(str(ref.path.home()), "~")
            pending = counts.get(str(ref.path), 0)

            text.append(f"  {name}", style=f"bold {CYAN}")
            text.append(f"  {path_str}", style=f"{GREY}")
            if ref.sources:
                text.append(f"  [{', '.join(ref.sources)}]", style=f"{GREY}")
            if pending:
                text.append(f"  {pending} pending", style=f"{GREEN}")

        self._content.update(text)
