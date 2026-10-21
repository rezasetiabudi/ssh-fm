from textual.command import CommandPalette

from ssh_fm.commands import SshFmCommands
from ssh_fm.screens import BrowserScreen
from tests.test_browser import make_app, open_browser, settle


def labels(provider):
    return [c[0] for c in provider.commands()]


async def test_palette_lists_hosts_and_actions(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        got = labels(SshFmCommands(app.screen))
        assert "New host" in got and "Connect to web" in got and "Connect to db" in got
        assert "Edit host" in got and "Delete host" in got


async def test_palette_connect_triggers_connect(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        cmds = dict((c[0], c[1]) for c in SshFmCommands(app.screen).commands())
        cmds["Connect to db"]()
        await settle(pilot)
        assert isinstance(app.screen, BrowserScreen) and app.screen.host.name == "db"


async def test_browser_only_commands_hidden_on_picker(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        assert "Upload" not in labels(SshFmCommands(app.screen))
        screen = await open_browser(app, pilot)
        got = labels(SshFmCommands(screen))
        assert {"Upload", "Download", "Sync directory", "SFTP session", "SSH shell", "Toggle hidden files",
                "Refresh", "Back to hosts"} <= set(got)
        assert "New host" not in got


async def test_ctrl_p_opens_palette(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)
