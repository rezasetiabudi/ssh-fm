"""Command palette (ctrl+p)"""

from textual.command import DiscoveryHit, Hit, Provider

from .screens import BrowserScreen, HostPickerScreen

PICKER = [("New host", "action_new", "Add a host to ~/.ssh/config"),
          ("Edit host", "action_edit", "Edit the highlighted host"),
          ("Delete host", "action_delete", "Remove the highlighted host")]
BROWSER = [("Upload", "action_upload", "Upload local files to this folder"),
           ("Download", "action_download", "Download the selected files"),
           ("Sync directory", "action_sync", "rsync a directory up or down"),
           ("SFTP session", "action_sftp", "Open a terminal sftp session"),
           ("SSH shell", "action_shell", "Open an ssh shell on this host"),
           ("Toggle hidden files", "action_toggle_hidden", "Show or hide dotfiles"),
           ("Refresh", "action_refresh", "Reload this folder"),
           ("Back to hosts", "action_back", "Return to the host list")]


class SshFmCommands(Provider):
    def commands(self):
        """[(label, callback, help)] for the screen the palette was opened from"""
        screen, out = self.screen, []
        table = PICKER if isinstance(screen, HostPickerScreen) else BROWSER if isinstance(screen, BrowserScreen) else []
        out += [(label, getattr(screen, action), help_) for label, action, help_ in table]
        for host in self.app.config.hosts.values():
            out.append((f"Connect to {host.name}", lambda h=host: self.app.connect(h, replace=isinstance(screen, BrowserScreen)),
                        f"{host.user + '@' if host.user else ''}{host.hostname or host.name}:{host.port}"))
        return out

    async def discover(self):
        for label, callback, help_ in self.commands():
            yield DiscoveryHit(label, callback, help=help_)

    async def search(self, query):
        matcher = self.matcher(query)
        for label, callback, help_ in self.commands():
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, matcher.highlight(label), callback, help=help_)
