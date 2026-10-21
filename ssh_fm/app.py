"""Textual application entry"""

from textual.app import App

from .config import SSHConfig
from .remote import Connection
from .screens import HostPickerScreen


class SshFmApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "ssh-fm"
    SUB_TITLE = "SSH file manager"

    def __init__(self, config=None, connection_factory=Connection):
        super().__init__()
        self.config = config or SSHConfig()
        self.connection_factory = connection_factory

    def on_mount(self):
        self.push_screen(HostPickerScreen())

    def connect(self, host):
        """Replaced in Task 4"""
        self.notify(f"connect {host.name}")


def main():
    SshFmApp().run()
