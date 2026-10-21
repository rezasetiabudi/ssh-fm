"""Reusable widgets"""

from rich.markup import escape
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import ProgressBar, Static

ICONS = {"queued": "⏳", "running": "⠿", "done": "✅", "failed": "❌"}


class TransferRow(Horizontal):
    def __init__(self, label):
        super().__init__(classes="transfer-row")
        self.label = label
        self.state = "queued"
        self.status = Static(ICONS["queued"], classes="t-icon")
        self.bar = ProgressBar(total=100, show_eta=False, classes="t-bar")
        self.speed = Static("", classes="t-speed")

    def compose(self):
        yield self.status
        yield Static(escape(self.label), classes="t-label")
        yield self.bar
        yield self.speed

    def set_state(self, state):
        self.state = state
        self.status.update(ICONS[state])
        if state == "done":
            self.bar.update(progress=100)
            self.speed.update("")


class TransferPanel(VerticalScroll):
    """Bottom bar: one row per transfer with progress, speed and ETA."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._rows = []
        self.display = False

    def add(self, label):
        row = TransferRow(label)
        self._rows.append(row)
        self.display = True
        self.mount(row)
        self.scroll_end(animate=False)
        return len(self._rows) - 1

    def update_progress(self, row_id, progress):
        row = self._rows[row_id]
        row.set_state("running")
        row.bar.update(progress=progress.percent)
        row.speed.update(f"{progress.speed}  ETA {progress.eta}")

    def mark_running(self, row_id):
        self._rows[row_id].set_state("running")

    def finish(self, row_id, ok):
        self._rows[row_id].set_state("done" if ok else "failed")

    def states(self):
        return [r.state for r in self._rows]
