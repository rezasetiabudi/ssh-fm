"""Small modal dialogs"""

import os
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, OptionList
from textual.widgets.option_list import Option

from .config import Host, ensure_key_permissions, find_keys

CUSTOM = "__custom__"


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No")]

    def __init__(self, message):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.message, classes="title")
            with Horizontal(classes="buttons"):
                yield Button("Yes (y)", variant="error", id="yes")
                yield Button("No (n)", id="no")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool):
        self.dismiss(value)


class HostFormScreen(ModalScreen["Host | None"]):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]

    def __init__(self, host=None, keys_dir=None):
        super().__init__()
        self.host = host
        self.keys = find_keys(keys_dir)

    def compose(self) -> ComposeResult:
        h = self.host or Host("")
        key_options = [("Default key", "")] + [(k.name, str(k)) for k in self.keys] + [("Custom path…", CUSTOM)]
        known = {v for _, v in key_options}
        key_value = h.identity_file if h.identity_file in known else (CUSTOM if h.identity_file else "")
        with Vertical(classes="dialog form"):
            yield Label("Edit host" if self.host else "New host", classes="title")
            with VerticalScroll():
                yield from self._fields(h, key_options, key_value)
            with Horizontal(classes="buttons"):
                yield Button("Save (ctrl+s)", variant="primary", id="save")
                yield Button("Cancel (esc)", id="cancel")

    def _fields(self, h, key_options, key_value):
        yield Label("Name (alias)")
        yield Input(h.name, id="f-name", placeholder="prod-web")
        yield Label("Hostname / IP")
        yield Input(h.hostname, id="f-hostname", placeholder="10.0.0.5")
        yield Label("Port")
        yield Input(h.port, id="f-port")
        yield Label("User")
        yield Input(h.user, id="f-user")
        yield Label("Authentication")
        yield Select([("SSH key", "key"), ("Password", "password")], value="password" if h.password_auth else "key",
                     allow_blank=False, id="f-auth")
        yield Label("Key file", id="l-key")
        yield Select(key_options, value=key_value, allow_blank=False, id="f-key")
        yield Input(h.identity_file if key_value == CUSTOM else "", id="f-custom",
                    placeholder="~/Downloads/server.pem")

    def on_mount(self):
        self._sync_visibility()
        self.query_one("#f-name").focus()

    def on_select_changed(self, event):
        self._sync_visibility()

    def _sync_visibility(self):
        key_auth = self.query_one("#f-auth", Select).value == "key"
        for sel in ("#l-key", "#f-key"):
            self.query_one(sel).display = key_auth
        self.query_one("#f-custom").display = key_auth and self.query_one("#f-key", Select).value == CUSTOM

    def on_button_pressed(self, event):
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)

    def action_save(self):
        val = lambda i: self.query_one(i, Input).value.strip()
        port = val("#f-port") or "22"
        if not val("#f-name"):
            return self.notify("Name is required", severity="error")
        if not port.isdigit():
            return self.notify("Port must be a number", severity="error")
        password = self.query_one("#f-auth", Select).value == "password"
        identity = ""
        if not password:
            choice = self.query_one("#f-key", Select).value
            identity = val("#f-custom") if choice == CUSTOM else choice
            if identity:
                path = Path(identity).expanduser()
                if not path.is_file():
                    return self.notify(f"Key file not found: {path}", severity="error")
                if ensure_key_permissions(path):
                    self.notify(f"Permissions on {path.name} set to 600")
                identity = str(path.resolve())
        self.dismiss(Host(val("#f-name"), val("#f-hostname"), port, val("#f-user"), identity, password))


class PathPromptScreen(ModalScreen["str | None"]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title, hint="", initial=""):
        super().__init__()
        self.title_text, self.hint, self.initial = title, hint, initial

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title")
            if self.hint:
                yield Label(self.hint, classes="hint")
            yield Input(self.initial, id="path-input")

    def on_input_submitted(self, event):
        self.dismiss(event.value.strip() or None)

    def action_cancel(self):
        self.dismiss(None)


class DestinationScreen(ModalScreen["Path | None"]):
    """Where to save downloads: cwd / Desktop / Downloads / custom"""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        home = Path.home()
        self.choices = [("Current directory", Path(os.getcwd())), ("Desktop", home / "Desktop"),
                        ("Downloads", home / "Downloads")]
        with Vertical(classes="dialog"):
            yield Label("Download to…", classes="title")
            yield OptionList(*[Option(f"{n}  [dim]{p}[/dim]") for n, p in self.choices], Option("Custom path…"))
            yield Input(placeholder="~/some/folder", id="custom")

    def on_mount(self):
        self.query_one("#custom").display = False
        self.query_one(OptionList).highlighted = 0

    def on_option_list_option_selected(self, event):
        if event.option_index < len(self.choices):
            self.dismiss(self.choices[event.option_index][1])
        else:
            box = self.query_one("#custom")
            box.display = True
            box.focus()

    def on_input_submitted(self, event):
        if event.value.strip():
            self.dismiss(Path(event.value.strip()).expanduser())

    def action_cancel(self):
        self.dismiss(None)


class SyncScreen(ModalScreen["tuple | None"]):
    """rsync a directory: returns (direction, local, remote)"""
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "go", "Sync")]

    def __init__(self, remote_default):
        super().__init__()
        self.remote_default = remote_default

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Directory sync (rsync)", classes="title")
            yield Select([("Upload local → remote", "up"), ("Download remote → local", "down")],
                         value="up", allow_blank=False, id="s-dir")
            yield Label("Local directory")
            yield Input(os.getcwd(), id="s-local")
            yield Label("Remote directory")
            yield Input(self.remote_default, id="s-remote")
            with Horizontal(classes="buttons"):
                yield Button("Sync (ctrl+s)", variant="primary", id="go")
                yield Button("Cancel (esc)", id="cancel")

    def on_button_pressed(self, event):
        self.action_go() if event.button.id == "go" else self.dismiss(None)

    def action_go(self):
        local = self.query_one("#s-local", Input).value.strip()
        remote = self.query_one("#s-remote", Input).value.strip()
        if not local or not remote:
            return self.notify("Both paths are required", severity="error")
        self.dismiss((self.query_one("#s-dir", Select).value, str(Path(local).expanduser()), remote))

    def action_cancel(self):
        self.dismiss(None)


class TextViewScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q", "close", "Close")]

    def __init__(self, title, text):
        super().__init__()
        self.title_text, self.text = title, text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog viewer"):
            yield Label(self.title_text, classes="title")
            with VerticalScroll():
                yield Static(escape(self.text) or "[dim](empty)[/dim]")

    def action_close(self):
        self.dismiss(None)
