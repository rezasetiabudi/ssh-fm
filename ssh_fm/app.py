"""Textual application entry"""

from textual.app import App
from textual.binding import Binding

from .commands import SshFmCommands
from .config import SSHConfig, State
from .remote import Connection
from .screens import BrowserScreen, ConnectingScreen, HostPickerScreen


class SshFmApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "ssh-fm"
    SUB_TITLE = "SSH file manager"
    COMMANDS = App.COMMANDS | {SshFmCommands}
    # plain letters are reserved for quick select, so shortcuts live on alt/ctrl/super
    BINDINGS = [Binding("alt+p,ctrl+p,super+p", "command_palette", "Palette", show=False, priority=True)]

    def __init__(self, config=None, connection_factory=Connection, state=None):
        super().__init__()
        self.config = config or SSHConfig()
        self.state = state or State()
        self.connection_factory = connection_factory

    def on_mount(self):
        self.push_screen(HostPickerScreen())

    def connect(self, host, replace=False):
        conn = self.connection_factory(host.name)

        def done(error):
            if error:
                return self.notify(f"{host.name}: {error}", severity="error", timeout=10)
            screen = BrowserScreen(host, conn)
            self.switch_screen(screen) if replace else self.push_screen(screen)

        self.push_screen(ConnectingScreen(host, conn), done)


def main():
    SshFmApp().run()
