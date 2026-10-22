"""Main screens: host picker (start) and remote browser"""

import asyncio
import os
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

from .modals import (ConfirmScreen, ConflictScreen, DestinationScreen, HostFormScreen, PathPromptScreen,
                     ImportHostsScreen, SyncScreen, TextViewScreen)
from .quickselect import QuickSelect
from .remote import MODE_RE, RemoteError, join_path, perms_to_octal, run_transfer
from .terminal import TerminalScreen
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
        Binding("alt+n", "new", "New"),
        Binding("alt+e", "edit", "Edit"),
        Binding("alt+d", "delete", "Delete"),
        Binding("slash", "filter", "Filter"),
        Binding("left", "move(-1)", show=False),
        Binding("right", "move(1)", show=False),
        Binding("up", "move(-2)", show=False),
        Binding("down", "move(2)", show=False),
        Binding("escape", "clear_filter", show=False),
        Binding("alt+i", "import_hosts", "Import"),
        Binding("alt+q", "app.quit", "Quit"),
    ]

    quick = QuickSelect()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter hosts…", id="filter")
        yield Static("No hosts yet — press [b]alt+n[/b] to add one or [b]alt+i[/b] to import from ssh config", id="empty")
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

    def on_key(self, event):
        char = quick_char(event)
        cards = self._visible()
        if char and cards:
            names = [c.host.name for c in cards]
            cur = cards.index(self.app.focused) if self.app.focused in cards else -1
            idx = self.quick.feed(char, names, cur)
            event.stop()
            if idx is not None:
                cards[idx].focus()

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

    def action_import_hosts(self):
        async def done(chosen):
            if not chosen:
                return
            added = 0
            for host, exists in chosen:
                try:
                    self.app.config.update(host.name, host) if exists else self.app.config.add(host)
                    added += 1
                except ValueError as e:
                    self.notify(str(e), severity="error")
            if added:
                self.notify(f"Imported {added} host(s)")
                await self.refresh_cards(chosen[0][0].name)
        self.app.push_screen(ImportHostsScreen(), done)

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
            # ssh prompts for password / passphrase / host key inside an embedded terminal
            rc = await self.app.push_screen_wait(TerminalScreen(f"ssh {self.host.name}", self.conn.master_cmd()))
            err = "" if rc == 0 else f"ssh exited with status {rc}"
        self.dismiss(None if rc == 0 else (err.strip() or "Connection failed"))


def quick_char(event):
    """The typed character if it should drive quick select (plain printable key, no modifier, not a bound key)."""
    ch = event.character
    if not ch or not ch.isprintable() or ch in " ./" or "+" in event.key.replace("shift+", ""):
        return None
    return ch


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
        Binding("f5,ctrl+r", "refresh", "Refresh", show=False),
        Binding("alt+u", "upload", "Upload"),
        Binding("alt+d", "download", "Download"),
        Binding("alt+v", "view", "View"),
        Binding("alt+s", "sync", "Sync"),
        Binding("alt+t", "local", "SFTP split"),
        Binding("alt+f", "sftp", "sftp term", show=False),
        Binding("alt+h", "shell", "Shell"),
        Binding("alt+x,delete", "remove", "Delete"),
        Binding("alt+n", "mkdir", "New dir"),
        Binding("alt+r,f2", "rename", "Rename", show=False),
        Binding("alt+m", "chmod", "Perms", show=False),
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
        self.local_cwd = Path.home()
        saved = self.app.state.get(f"local_cwd:{host.name}")
        if saved and Path(saved).is_dir():
            self.local_cwd = Path(saved)
        self.local_selected = set()
        self._local_names = []
        self.quick = QuickSelect()
        self._drag = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="browser"):
            yield OptionList(*[Option(h.name, id=h.name) for h in self.app.config.hosts.values()], id="hosts")
            with Vertical(id="center"):
                yield Static(id="path")
                yield Input(placeholder="filter files…", id="file-filter")
                yield DataTable(id="files", cursor_type="row", zebra_stripes=True, cursor_background_priority="css")
                with Vertical(id="local-box"):
                    yield Static(id="local-path")
                    yield DataTable(id="local-files", cursor_type="row", zebra_stripes=True, cursor_background_priority="css")
            yield InfoPanel(id="info")
        yield TransferPanel(id="transfers")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#files", DataTable)
        table.add_columns(" ", "Name", "Size", "Perms")
        table.focus()
        self.query_one("#local-files", DataTable).add_columns(" ", "Name", "Size")
        self.query_one("#local-box").display = False
        hosts = self.query_one("#hosts", OptionList)
        names = list(self.app.config.hosts)
        if self.host.name in names:
            hosts.highlighted = names.index(self.host.name)
        self.query_one("#file-filter").display = False
        self.query_one("#info").display = self.size.width >= 80
        self.load()

    def on_unmount(self):
        threading.Thread(target=self.conn.close, daemon=True).start()

    def on_key(self, event):
        table = self.focused
        char = quick_char(event)
        if char and isinstance(table, DataTable):
            event.stop()
            keys = [r.key.value for r in table.ordered_rows]
            rows = [(i, k) for i, k in enumerate(keys) if k not in ("..", "__msg__")]
            hit = self.quick.feed(char, [k for _, k in rows], next((j for j, (i, _) in enumerate(rows) if i == table.cursor_row), -1))
            if hit is not None:
                table.move_cursor(row=rows[hit][0], scroll=True)

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
        if event.data_table.id == "local-files":
            if key == "..":
                self.go_local(self.local_cwd.parent)
            elif (self.local_cwd / key).is_dir():
                self.go_local(self.local_cwd / key)
            return
        if key == "..":
            self.action_up()
        elif key in self._by_name and self._by_name[key].is_dir:
            self.go(join_path(self.cwd, key))

    def action_up(self):
        if self.focused is self.query_one("#local-files"):
            return self.go_local(self.local_cwd.parent)
        if self.cwd not in ("/", "~"):
            self.go(join_path(self.cwd, ".."))

    def action_refresh(self):
        self.load()
        self.load_local()

    def action_toggle_hidden(self):
        self.show_hidden = not self.show_hidden
        self.render_table()
        self.load_local()

    def action_toggle_select(self):
        if self.focused is self.query_one("#local-files"):
            return self.toggle_local_select()
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
        if event.data_table.id != "files":
            return
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
        self.load_local()

    def _local_focused(self):
        return self.focused is self.query_one("#local-files")

    def up_item(self, path):
        return (f"↑ {path.name}", "up", str(path), self.cwd.rstrip("/") + "/", path.name in self._by_name)

    def down_item(self, name, dest):
        return (f"↓ {name}", "down", str(dest) + "/", join_path(self.cwd, name), (Path(dest) / name).exists())

    def submit(self, items):
        """Queue transfers; if destination names already exist ask: overwrite / skip existing / cancel."""
        def go(choice):
            for label, direction, local, remote, exists in items:
                if choice == "overwrite" or not exists:
                    self.enqueue(label, direction, local, remote)
        clashes = [i[0][2:] for i in items if i[4]]
        if clashes:
            self.app.push_screen(ConflictScreen(clashes), lambda c: go(c) if c else None)
        else:
            go("overwrite")

    def action_download(self):
        names = self.targets()
        if self._local_focused() and names:  # split view: no prompt, drop into the local pane's folder
            return self.submit([self.down_item(n, self.local_cwd) for n in names])
        if not names:
            return self.notify("Select a file first", severity="warning")

        def chosen(dest):
            if dest is None:
                return
            dest.mkdir(parents=True, exist_ok=True)
            self.submit([self.down_item(n, dest) for n in names])
        self.app.push_screen(DestinationScreen(), chosen)

    def action_upload(self):
        if self._local_focused():
            names = self.local_targets()
            if not names:
                return self.notify("Select a local file first", severity="warning")
            return self.submit([self.up_item(self.local_cwd / n) for n in names])

        def chosen(text):
            if not text:
                return
            paths = [Path(p.strip()).expanduser() for p in text.replace("\n", ",").split(",") if p.strip()]
            missing = [p for p in paths if not p.exists()]
            if missing:
                return self.notify(f"Local path not found: {missing[0]}", severity="error")
            self.submit([self.up_item(p) for p in paths])
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

    def _handoff(self, title, cmd):
        self.app.push_screen(TerminalScreen(title, cmd), lambda _: (self.load(), self.load_local()))

    # --- actions: remote file operations ------------------------------------------------
    def _remote_focus_or_warn(self):
        if self._local_focused():
            self.notify("Focus the server pane first (this acts on remote files)", severity="warning")
            return False
        return True

    @work(thread=True, group="fileops")
    def _run_ops(self, ops, done):
        call = self.app.call_from_thread
        for op in ops:
            try:
                op()
            except RemoteError as e:
                call(self.notify, str(e), severity="error")
                break
        else:
            call(self.notify, done)
        call(self.load)

    def action_remove(self):
        if not self._remote_focus_or_warn():
            return
        names = self.targets()
        if not names:
            return self.notify("Select a file first", severity="warning")
        shown = ", ".join(escape(n) for n in names[:3]) + (f" … +{len(names) - 3}" if len(names) > 3 else "")

        def confirmed(yes):
            if yes:
                self.selected.clear()
                self._run_ops([lambda n=n: self.conn.remove(join_path(self.cwd, n)) for n in names],
                              f"Deleted {len(names)} item(s)")
        self.app.push_screen(ConfirmScreen(f"Delete {shown} from {escape(self.host.name)}? This cannot be undone."), confirmed)

    def action_mkdir(self):
        if not self._remote_focus_or_warn():
            return

        def chosen(name):
            if not name:
                return
            if "/" in name or name in self._by_name:
                return self.notify(f"Invalid or existing name: {name}", severity="error")
            self._run_ops([lambda: self.conn.mkdir(join_path(self.cwd, name))], f"Created {name}/")
        self.app.push_screen(PathPromptScreen("New folder in " + self.cwd, "Folder name"), chosen)

    def action_rename(self):
        if not self._remote_focus_or_warn():
            return
        entry = self.current_entry()
        if not entry:
            return self.notify("Select a file first", severity="warning")

        def chosen(new):
            if not new or new == entry.name:
                return
            if "/" in new or new in self._by_name:
                return self.notify(f"Invalid or existing name: {new}", severity="error")
            self._run_ops([lambda: self.conn.rename(join_path(self.cwd, entry.name), join_path(self.cwd, new))],
                          f"Renamed to {new}")
        self.app.push_screen(PathPromptScreen("Rename " + entry.name, "New name", entry.name), chosen)

    def action_chmod(self):
        if not self._remote_focus_or_warn():
            return
        names = self.targets()
        if not names:
            return self.notify("Select a file first", severity="warning")
        initial = perms_to_octal(self._by_name[names[0]].perms) if len(names) == 1 else ""

        def chosen(mode):
            if not mode:
                return
            if not MODE_RE.match(mode):
                return self.notify("Use an octal mode (644) or symbolic (u+x,go-w)", severity="error")
            self._run_ops([lambda n=n: self.conn.chmod(join_path(self.cwd, n), mode) for n in names],
                          f"chmod {mode} on {len(names)} item(s)")
        self.app.push_screen(PathPromptScreen(f"Permissions for {len(names)} item(s)", "Octal (644) or symbolic (u+x)", initial), chosen)

    # --- local pane + drag & drop ----------------------------------------------------------
    def action_local(self):
        box = self.query_one("#local-box")
        box.display = not box.display
        if box.display:
            self.load_local()
            self.query_one("#local-files").focus()
            self.notify("Drag a row between the two panes to transfer it")
        else:
            self.query_one("#files").focus()

    def go_local(self, path):
        self.local_cwd = Path(path)
        self.app.state.set(f"local_cwd:{self.host.name}", str(self.local_cwd))
        self.local_selected.clear()
        self.load_local()

    def load_local(self):
        if not self.query_one("#local-box").display:
            return
        try:
            with os.scandir(self.local_cwd) as it:
                items = [(e.name, e.is_dir(), e.stat().st_size if e.is_file() else 0) for e in it]
        except OSError as e:
            items = []
            self.notify(f"{self.local_cwd}: {e.strerror or e}", severity="error")
        items = [i for i in items if self.show_hidden or not i[0].startswith(".")]
        items.sort(key=lambda i: (not i[1], i[0].lower()))
        table = self.query_one("#local-files", DataTable)
        self._local_names = [i[0] for i in items]
        self.local_selected &= set(self._local_names)
        table.clear()
        self.query_one("#local-path", Static).update(f"[b]local[/b]:{escape(str(self.local_cwd))}")
        if self.local_cwd.parent != self.local_cwd:
            table.add_row("", "[dim]..[/dim]", "", key="..")
        for name, is_dir, size in items:
            label = escape(name) + ("/" if is_dir else "")
            table.add_row("✓" if name in self.local_selected else "", f"[b #7aa2f7]{label}[/]" if is_dir else label,
                          "" if is_dir else human(size), key=name)

    def toggle_local_select(self):
        table = self.query_one("#local-files", DataTable)
        key = self._row_key(table, table.cursor_row)
        if key in self._local_names:
            self.local_selected ^= {key}
            row = table.cursor_row
            self.load_local()
            table.move_cursor(row=min(row + 1, table.row_count - 1))

    def local_targets(self):
        table = self.query_one("#local-files", DataTable)
        names = [n for n in self._local_names if n in self.local_selected]
        key = self._row_key(table, table.cursor_row)
        return names or ([key] if key in self._local_names else [])

    def _table_at(self, x, y):
        try:
            widget = self.get_widget_at(x, y)[0]
        except Exception:
            return None
        while widget is not None and widget is not self:
            if isinstance(widget, DataTable) and widget.id in ("files", "local-files"):
                return widget
            widget = widget.parent
        return None

    def _row_key(self, table, row):
        if row is None or not 0 <= row < table.row_count:
            return None
        return table.ordered_rows[row].key.value

    def on_mouse_down(self, event):
        self._drag = None
        table = self._table_at(event.screen_x, event.screen_y)
        key = self._row_key(table, event.style.meta.get("row")) if table else None
        if key not in (None, "..", "__msg__"):
            self._drag = (table.id, key)

    def on_mouse_up(self, event):
        drag, self._drag = self._drag, None
        target = self._table_at(event.screen_x, event.screen_y)
        if not drag or target is None or target.id == drag[0]:
            return
        source, key = drag
        if source == "files":
            names = [n for n in self._by_name if n in self.selected] if key in self.selected else [key]
            self.submit([self.down_item(n, self.local_cwd) for n in names])
        else:
            names = [n for n in self._local_names if n in self.local_selected] if key in self.local_selected else [key]
            self.submit([self.up_item(self.local_cwd / n) for n in names])

    @work(thread=True, exclusive=True, group="handoff")
    def action_sftp(self):
        try:
            cmd = self.conn.sftp_cmd(self.cwd)
        except RemoteError:
            cmd = self.conn.sftp_cmd()
        self.app.call_from_thread(self._handoff, f"sftp {self.host.name}", cmd)

    def action_shell(self):
        self._handoff(f"ssh {self.host.name}", self.conn.shell_cmd())
