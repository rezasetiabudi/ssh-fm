"""Main screens: host picker (start) and remote browser"""

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from .modals import ConfirmScreen, HostFormScreen


def fade_in(widget, duration=0.25):
    widget.styles.opacity = 0.0
    widget.styles.animate("opacity", 1.0, duration=duration)


class HostCard(Static, can_focus=True):
    def __init__(self, host):
        self.host = host
        auth = "🔒 password" if host.password_auth else f"🔑 {host.identity_file.rsplit('/', 1)[-1] or 'default key'}"
        target = f"{host.user + '@' if host.user else ''}{host.hostname or host.name}:{host.port}"
        super().__init__(f"[b]{escape(host.name)}[/b]\n[dim]{escape(target)}[/dim]\n{escape(auth)}")


class HostPickerScreen(Screen):
    AUTO_FOCUS = "HostCard"
    BINDINGS = [
        Binding("enter", "connect", "Connect"),
        Binding("n", "new", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("slash", "filter", "Filter"),
        Binding("left", "move(-1)", show=False),
        Binding("right", "move(1)", show=False),
        Binding("up", "move(-2)", show=False),
        Binding("down", "move(2)", show=False),
        Binding("escape", "clear_filter", show=False),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter hosts…", id="filter")
        yield Static("No hosts yet — press [b]n[/b] to add one", id="empty")
        yield Grid(id="cards")
        yield Footer()

    async def on_mount(self):
        self.query_one("#filter").display = False
        fade_in(self)
        await self.refresh_cards()

    async def refresh_cards(self, focus_name=None):
        grid = self.query_one("#cards")
        await grid.remove_children()
        hosts = list(self.app.config.hosts.values())
        cards = [HostCard(h) for h in hosts]
        await grid.mount(*cards)
        self.query_one("#empty").display = not hosts
        self._apply_filter()
        target = next((c for c in cards if c.host.name == focus_name), None) or (cards[0] if cards else None)
        if target:
            target.focus()

    def _visible(self):
        return [c for c in self.query(HostCard) if c.display]

    def _apply_filter(self):
        text = self.query_one("#filter", Input).value.strip().lower()
        for c in self.query(HostCard):
            h = c.host
            c.display = not text or text in f"{h.name} {h.hostname} {h.user}".lower()

    def _current(self):
        f = self.app.focused
        return f.host if isinstance(f, HostCard) else None

    def on_input_changed(self, event):
        if event.input.id == "filter":
            self._apply_filter()

    def on_input_submitted(self, event):
        if event.input.id == "filter" and self._visible():
            self._visible()[0].focus()

    def action_filter(self):
        box = self.query_one("#filter", Input)
        box.display = True
        box.focus()

    def action_clear_filter(self):
        box = self.query_one("#filter", Input)
        box.value = ""
        box.display = False
        self._apply_filter()
        if self._visible():
            self._visible()[0].focus()
        else:
            self.set_focus(None)

    def action_move(self, delta: int):
        cards = self._visible()
        if not cards:
            return
        cur = self.app.focused
        i = cards.index(cur) if cur in cards else 0
        cards[max(0, min(len(cards) - 1, i + delta))].focus()

    # --- host CRUD ----------------------------------------------------------
    def action_new(self):
        async def done(host):
            if host:
                try:
                    self.app.config.add(host)
                except ValueError as e:
                    return self.notify(str(e), severity="error")
                self.notify(f"Host '{host.name}' added")
                await self.refresh_cards(host.name)
        self.app.push_screen(HostFormScreen(), done)

    def action_edit(self):
        old = self._current()
        if not old:
            return

        async def done(host):
            if host:
                try:
                    self.app.config.update(old.name, host)
                except ValueError as e:
                    return self.notify(str(e), severity="error")
                self.notify(f"Host '{host.name}' updated")
                await self.refresh_cards(host.name)
        self.app.push_screen(HostFormScreen(old), done)

    def action_delete(self):
        host = self._current()
        if not host:
            return

        async def done(yes):
            if yes:
                self.app.config.delete(host.name)
                self.notify(f"Host '{host.name}' deleted")
                await self.refresh_cards()
        self.app.push_screen(ConfirmScreen(f"Delete '{host.name}'?"), done)

    def action_connect(self):
        host = self._current()
        if host:
            self.app.connect(host)
