import pytest
from textual.widgets import Input

from ssh_fm.app import SshFmApp
from ssh_fm.config import State
from ssh_fm.remote import MODE_RE, Connection, RemoteError, perms_to_octal
from tests.fakes import FakeConnection
from tests.test_browser import go_to, make_app, open_browser, settle
from tests.test_transfers import patch_transfer


def test_perms_to_octal():
    assert perms_to_octal("-rw-r--r--") == "644"
    assert perms_to_octal("drwxr-xr-x") == "755"
    assert perms_to_octal("-rwsr-xr-t") == "755"
    assert perms_to_octal("") == ""


@pytest.mark.parametrize("mode,ok", [("644", True), ("0755", True), ("u+x", True), ("go-w,u+r", True),
                                     ("999", False), ("rm -rf /", False), ("+x;ls", False), ("", False)])
def test_mode_validation(mode, ok):
    assert bool(MODE_RE.match(mode)) is ok


def test_remove_refuses_dangerous_paths(tmp_path):
    c = Connection("web", control_dir=tmp_path)
    for p in ("/", "~", "", "~/"):
        with pytest.raises(RemoteError):
            c.remove(p)
    with pytest.raises(RemoteError):
        c.chmod("~/x", "$(reboot)")


async def test_delete_with_confirmation(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "index.php")
        await pilot.press("alt+x")
        await pilot.pause()
        await pilot.press("n")  # decline
        await settle(pilot)
        assert ("rm", "~/index.php") not in screen.conn.calls
        await pilot.press("alt+x")
        await pilot.pause()
        await pilot.press("y")
        await settle(pilot)
        assert ("rm", "~/index.php") in screen.conn.calls
        assert "index.php" not in [e.name for e in screen.entries]


async def test_rename_mkdir_chmod(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "index.php")
        await pilot.press("alt+r")
        await pilot.pause()
        app.screen.query_one(Input).value = "home.php"
        await pilot.press("enter")
        await settle(pilot)
        assert ("mv", "~/index.php", "~/home.php") in screen.conn.calls
        await pilot.press("alt+n")
        await pilot.pause()
        app.screen.query_one(Input).value = "newdir"
        await pilot.press("enter")
        await settle(pilot)
        assert ("mkdir", "~/newdir") in screen.conn.calls and "newdir" in screen._by_name
        go_to(screen, "home.php")
        await pilot.press("alt+m")
        await pilot.pause()
        assert app.screen.query_one(Input).value == "644"
        app.screen.query_one(Input).value = "600"
        await pilot.press("enter")
        await settle(pilot)
        assert ("chmod", "~/home.php", "600") in screen.conn.calls


async def test_rename_rejects_existing_name(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "index.php")
        await pilot.press("alt+r")
        await pilot.pause()
        app.screen.query_one(Input).value = "logs"
        await pilot.press("enter")
        await settle(pilot)
        assert not [c for c in screen.conn.calls if c[0] == "mv"]


async def conflict_setup(app, pilot, tmp_path):
    (tmp_path / "index.php").write_text("local")
    screen = await open_browser(app, pilot)
    screen.local_cwd = tmp_path
    await pilot.press("alt+t")
    await settle(pilot)
    local = screen.query_one("#local-files")
    local.move_cursor(row=local.get_row_index("index.php"))
    return screen


async def test_overwrite_conflict_prompt_overwrite(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        await conflict_setup(app, pilot, tmp_path)
        await pilot.press("alt+u")
        await pilot.pause()
        assert type(app.screen).__name__ == "ConflictScreen"
        await pilot.press("o")
        await settle(pilot)
        assert [c[1] for c in calls] == ["up"]


async def test_overwrite_conflict_prompt_skip_and_cancel(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        await conflict_setup(app, pilot, tmp_path)
        await pilot.press("alt+u")
        await pilot.pause()
        await pilot.press("s")
        await settle(pilot)
        await pilot.press("alt+u")
        await pilot.pause()
        await pilot.press("escape")
        await settle(pilot)
        assert calls == []


async def test_local_folder_is_remembered_per_host(tmp_path):
    sub = tmp_path / "work"
    sub.mkdir()
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_browser(app, pilot)
        await pilot.press("alt+t")
        screen.go_local(sub)
    assert State(tmp_path / "state.json").get("local_cwd:web") == str(sub)
    app2 = SshFmApp(config=app.config, connection_factory=FakeConnection, state=State(tmp_path / "state.json"))
    async with app2.run_test(size=(140, 50)) as pilot:
        screen = await open_browser(app2, pilot)
        assert screen.local_cwd == sub
