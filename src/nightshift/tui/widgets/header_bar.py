"""Header bar widget — branding + countdown + summary counts."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.widgets import Static

from nightshift.tui.constants import BRAILLE_SPINNER, CYAN, DIM, GREEN, GREY, RED, YELLOW


class HeaderBar(Static):
    """Top bar: NIGHTSHIFT brand + countdown + pending count + last run summary."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 3;
        padding: 1 1;
        text-style: bold;
        dock: top;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="header-bar")
        self._pending_count = 0
        self._last_run_passed = 0
        self._last_run_failed = 0
        self._last_run_skipped = 0
        self._project_count = 0
        self._schedule_time: str = ""
        self._schedule_tz: str = ""
        self._running_label: str = ""
        self._spinner_frame: int = 0

    def update_data(
        self,
        *,
        pending_count: int = 0,
        project_count: int = 0,
        last_run_passed: int = 0,
        last_run_failed: int = 0,
        last_run_skipped: int = 0,
        schedule_time: str = "",
        schedule_tz: str = "",
    ) -> None:
        self._pending_count = pending_count
        self._project_count = project_count
        self._last_run_passed = last_run_passed
        self._last_run_failed = last_run_failed
        self._last_run_skipped = last_run_skipped
        self._schedule_time = schedule_time
        self._schedule_tz = schedule_tz
        # Don't render here — countdown timer handles it

    def set_running(self, label: str) -> None:
        """Show a running indicator in the header."""
        self._running_label = label
        self._spinner_frame = 0

    def set_idle(self) -> None:
        """Clear the running indicator."""
        self._running_label = ""

    def on_mount(self) -> None:
        self._render_header()
        # Update countdown every second
        self.set_interval(1.0, self._render_header)

    def _compute_countdown(self) -> str:
        """Compute time remaining until next scheduled run."""
        if not self._schedule_time:
            return ""
        try:
            h, m = map(int, self._schedule_time.split(":"))
        except (ValueError, AttributeError):
            return ""

        try:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(self._schedule_tz) if self._schedule_tz else None
        except Exception:
            tz = None

        now = datetime.now(tz=tz or timezone.utc)
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target = target.replace(day=target.day + 1)

        delta = target - now
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        mins, secs = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}h {mins:02d}m"
        return f"{mins}m {secs:02d}s"

    def _render_header(self) -> None:
        text = Text()
        text.append("  NIGHTSHIFT", style=f"bold {GREEN}")
        text.append("   ", style="default")

        # Running indicator
        if self._running_label:
            spinner = BRAILLE_SPINNER[self._spinner_frame % len(BRAILLE_SPINNER)]
            self._spinner_frame += 1
            text.append(f"{spinner} ", style=f"bold {YELLOW}")
            text.append(f"{self._running_label}", style=f"{YELLOW}")
            text.append("   ", style="default")
        else:
            # Countdown (only when idle)
            countdown = self._compute_countdown()
            if countdown:
                text.append(f"next run in {countdown}", style=f"{YELLOW}")
                text.append("   ", style="default")

        text.append(f"{self._pending_count} pending", style=f"{CYAN}")
        text.append("  ", style="default")
        text.append(f"{self._project_count} projects", style=f"{GREY}")

        text.append("   │   ", style=f"{GREY}")

        if self._last_run_passed or self._last_run_failed or self._last_run_skipped:
            text.append("last: ", style=f"{GREY}")
            if self._last_run_passed:
                text.append(f"{self._last_run_passed}✓", style=f"{GREEN}")
                text.append(" ", style="default")
            if self._last_run_failed:
                text.append(f"{self._last_run_failed}✗", style=f"{RED}")
                text.append(" ", style="default")
            if self._last_run_skipped:
                text.append(f"{self._last_run_skipped}—", style=f"{YELLOW}")
        else:
            text.append("no runs yet", style=f"{GREY}")

        self.update(text)
