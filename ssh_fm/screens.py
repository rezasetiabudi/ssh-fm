"""Main screens: host picker (start) and remote browser"""

import asyncio
import subprocess
import threading
from collections import deque
from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, LoadingIndicator, OptionList, Static
from textual.widgets.option_list import Option

from .modals import (ConfirmScreen, DestinationScreen, HostFormScreen, PathPromptScreen, SyncScreen,
                     TextViewScreen)
from .remote import RemoteError, join_path, run_transfer
from .widgets import TransferPanel

PROMPT_HINTS = ("permission denied", "passphrase", "password", "host key verification")


def human(n):
    n = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


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


class ConnectingScreen(ModalScreen):
    """Opens the ssh master connection. Dismisses with None on success, else an error string."""

    def __init__(self, host, connection):
        super().__init__()
        self.host = host
        self.conn = connection

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(f"Connecting to [b]{escape(self.host.name)}[/b]…", classes="title")
            yield LoadingIndicator()

    def on_mount(self):
        self.run_worker(self._connect(), exclusive=True)

    async def _connect(self):
        rc, err = 1, ""
        if not self.host.password_auth:
            rc, err = await asyncio.to_thread(self.conn.try_master)
        if rc != 0 and (self.host.password_auth or any(h in err.lower() for h in PROMPT_HINTS)):
            with self.app.suspend():  # let ssh prompt for password / passphrase / host key
                rc = self.conn.open_master()
            err = "" if rc == 0 else f"ssh exited with status {rc}"
        self.dismiss(None if rc == 0 else (err.strip() or "Connection failed"))


class InfoPanel(Static):
    text = ""

    def show(self, markup):
        self.text = markup
        self.update(markup)


class BrowserScreen(Screen):
    BINDINGS = [
        Binding("backspace", "up", "Up"),
        Binding("space", "toggle_select", "Select"),
        Binding("full_stop", "toggle_hidden", "Hidden", show=False),
        Binding("slash", "filter", "Filter"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("u", "upload", "Upload"),
        Binding("d", "download", "Download"),
        Binding("v", "view", "View"),
        Binding("s", "sync", "Sync"),
        Binding("t", "sftp", "SFTP"),
        Binding("S", "shell", "Shell"),
        Binding("escape", "back", "Hosts"),
    ]

    def __init__(self, host, connection):
        super().__init__()
        self.host = host
        self.conn = connection
        self.cwd = "~"
        self.entries = []
        self.error = ""
        self.show_hidden = True
        self.selected = set()
        self._by_name = {}
        self.queue = deque()
        self.running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="browser"):
            yield OptionList(*[Option(h.name, id=h.name) for h in self.app.config.hosts.values()], id="hosts")
            with Vertical(id="center"):
                yield Static(id="path")
                yield Input(placeholder="filter files…", id="file-filter")
                yield DataTable(id="files", cursor_type="row", zebra_stripes=True)
            yield InfoPanel(id="info")
        yield TransferPanel(id="transfers")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#files", DataTable)
        table.add_columns(" ", "Name", "Size", "Perms")
        table.focus()
        hosts = self.query_one("#hosts", OptionList)
        names = list(self.app.config.hosts)
        if self.host.name in names:
            hosts.highlighted = names.index(self.host.name)
        self.query_one("#file-filter").display = False
        self.query_one("#info").display = self.size.width >= 80
        fade_in(self)
        self.load()

    def on_unmount(self):
        threading.Thread(target=self.conn.close, daemon=True).start()

    def on_resize(self, event):
        self.query_one("#info").display = event.size.width >= 80

    # --- listing --------------------------------------------------------------
    @work(thread=True, exclusive=True, group="list")
    def load(self):
        try:
            entries, error = self.conn.list_dir(self.cwd), ""
        except RemoteError as e:
            entries, error = [], str(e)
        self.app.call_from_thread(self._show, entries, error)

    def _show(self, entries, error):
        self.entries, self.error = entries, error
        self._by_name = {e.name: e for e in entries}
        self.selected &= set(self._by_name)
        self.render_table()

    def render_table(self):
        table = self.query_one("#files", DataTable)
        needle = self.query_one("#file-filter", Input).value.strip().lower()
        table.clear()
        self.query_one("#path", Static).update(f"[b]{escape(self.host.name)}[/b]:{escape(self.cwd)}")
        if self.cwd not in ("/", "~"):
            table.add_row("", "[dim]..[/dim]", "", "", key="..")
        shown = [e for e in self.entries
                 if (self.show_hidden or not e.name.startswith(".")) and needle in e.name.lower()]
        for e in shown:
            name = escape(e.name) + ("/" if e.is_dir else "")
            table.add_row("✓" if e.name in self.selected else "", f"[b #7aa2f7]{name}[/]" if e.is_dir else name,
                          "" if e.is_dir else human(e.size), e.perms, key=e.name)
        if self.error or not shown:
            msg = self.error or ("(no matches)" if needle else "(empty)")
            table.add_row("", f"[dim]{escape(msg)}[/dim]", "", "", key="__msg__")
        if self.error:
            self.notify(self.error, severity="error")

    def current_entry(self):
        table = self.query_one("#files", DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self._by_name.get(key)

    # --- navigation -------------------------------------------------------------
    def go(self, path):
        self.cwd = path
        self.selected.clear()
        self.load()

    def on_data_table_row_selected(self, event):
        key = event.row_key.value
        if key == "..":
            self.action_up()
        elif key in self._by_name and self._by_name[key].is_dir:
            self.go(join_path(self.cwd, key))

    def action_up(self):
        if self.cwd not in ("/", "~"):
            self.go(join_path(self.cwd, ".."))

    def action_refresh(self):
        self.load()

    def action_toggle_hidden(self):
        self.show_hidden = not self.show_hidden
        self.render_table()

    def action_toggle_select(self):
        entry = self.current_entry()
        if entry:
            self.selected ^= {entry.name}
            table = self.query_one("#files", DataTable)
            row = table.cursor_row
            self.render_table()
            table.move_cursor(row=min(row + 1, table.row_count - 1))

    def action_filter(self):
        box = self.query_one("#file-filter", Input)
        box.display = True
        box.focus()

    def on_input_changed(self, event):
        if event.input.id == "file-filter":
            self.render_table()

    def on_input_submitted(self, event):
        if event.input.id == "file-filter":
            self.query_one("#files").focus()

    def action_back(self):
        box = self.query_one("#file-filter", Input)
        if box.display:
            box.value = ""
            box.display = False
            self.query_one("#files").focus()
        else:
            self.app.pop_screen()

    def on_option_list_option_selected(self, event):
        if event.option.id != self.host.name:
            self.app.connect(self.app.config.hosts[event.option.id], replace=True)

    # --- info panel ---------------------------------------------------------------
    def on_data_table_row_highlighted(self, event):
        key = event.row_key.value if event.row_key else None
        entry = self._by_name.get(key)
        info = self.query_one("#info", InfoPanel)
        if key == "..":
            info.show("[b]..[/b]\n[dim]Parent directory[/dim]")
        elif entry is None:
            info.show("")
        else:
            info.show(self.format_info(entry, ""))
            self.fetch_info(entry)

    def format_info(self, e, kind):
        rows = [("Type", kind or ("directory" if e.is_dir else "…")), ("Size", f"{human(e.size)} ({e.size} B)"),
                ("Perms", e.perms), ("Owner", f"{e.owner}:{e.group}"), ("Modified", e.mtime)]
        body = "\n".join(f"[dim]{k:<9}[/dim]{escape(str(v))}" for k, v in rows)
        return f"[b]{escape(e.name)}[/b]\n\n{body}"

    @work(thread=True, exclusive=True, group="info")
    def fetch_info(self, entry):
        if entry.is_dir:
            return
        try:
            kind = self.conn.file_info(join_path(self.cwd, entry.name))["type"]
        except RemoteError:
            return
        self.app.call_from_thread(self._set_info, entry, kind)

    def _set_info(self, entry, kind):
        current = self.current_entry()
        if current and current.name == entry.name:
            self.query_one("#info", InfoPanel).show(self.format_info(entry, kind))

    # --- actions: transfers ---------------------------------------------------------
    def targets(self):
        names = [n for n in self._by_name if n in self.selected]
        if not names:
            entry = self.current_entry()
            names = [entry.name] if entry else []
        return names

    def enqueue(self, label, direction, local, remote):
        row = self.query_one("#transfers", TransferPanel).add(label)
        self.queue.append((row, label, direction, local, remote))
        self._pump()

    def _pump(self):
        if not self.running and self.queue:
            self.running = True
            self._drain(self.query_one("#transfers", TransferPanel))

    @work(thread=True, group="transfer")
    def _drain(self, panel):
        call = self.app.call_from_thread
        while self.queue:
            row, label, direction, local, remote = self.queue.popleft()
            call(panel.mark_running, row)
            try:
                cmd = self.conn.transfer_cmd(direction, local, self.conn.expand(remote))
                rc = run_transfer(cmd, lambda p, r=row: call(panel.update_progress, r, p))
            except (RemoteError, OSError) as e:
                call(self.notify, f"{label}: {e}", severity="error")
                rc = 1
            call(panel.finish, row, rc == 0)
            if rc != 0:
                call(self.notify, f"Transfer failed: {label}", severity="error")
            elif not self.queue:
                call(self.notify, f"Transfer complete: {label}")
        call(self._drain_done)

    def _drain_done(self):
        self.running = False
        self._pump()
        self.load()

    def action_download(self):
        names = self.targets()
        if not names:
            return self.notify("Select a file first", severity="warning")

        def chosen(dest):
            if dest is None:
                return
            dest.mkdir(parents=True, exist_ok=True)
            for n in names:
                self.enqueue(f"↓ {n}", "down", str(dest) + "/", join_path(self.cwd, n))
        self.app.push_screen(DestinationScreen(), chosen)

    def action_upload(self):
        def chosen(text):
            if not text:
                return
            paths = [Path(p.strip()).expanduser() for p in text.replace("\n", ",").split(",") if p.strip()]
            missing = [p for p in paths if not p.exists()]
            if missing:
                return self.notify(f"Local path not found: {missing[0]}", severity="error")
            for p in paths:
                self.enqueue(f"↑ {p.name}", "up", str(p), self.cwd.rstrip("/") + "/")
        self.app.push_screen(PathPromptScreen("Upload to " + self.cwd, "Local file(s) or folder(s), separated by commas",
                                              str(Path.cwd()) + "/"), chosen)

    def action_sync(self):
        def chosen(result):
            if result:
                direction, local, remote = result
                arrow = "↑" if direction == "up" else "↓"
                self.enqueue(f"{arrow} sync {local}", direction, local, remote)
        self.app.push_screen(SyncScreen(self.cwd), chosen)

    # --- actions: view / handoff --------------------------------------------------------
    def action_view(self):
        entry = self.current_entry()
        if not entry or entry.is_dir:
            return self.notify("Select a file to view", severity="warning")
        self.read_file(entry.name)

    @work(thread=True, exclusive=True, group="view")
    def read_file(self, name):
        try:
            text = self.conn.read_head(join_path(self.cwd, name))
        except RemoteError as e:
            return self.app.call_from_thread(self.notify, str(e), severity="warning")
        self.app.call_from_thread(self.app.push_screen, TextViewScreen(f"{name} (first 50 lines)", text))

    def _handoff(self, cmd):
        with self.app.suspend():
            subprocess.run(cmd)
        self.load()

    def action_sftp(self):
        self._handoff(self.conn.sftp_cmd())

    def action_shell(self):
        self._handoff(self.conn.shell_cmd())
