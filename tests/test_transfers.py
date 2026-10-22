import threading
import time
from contextlib import contextmanager

from textual.widgets import Input

from ssh_fm.modals import TextViewScreen
from ssh_fm.remote import Progress
from ssh_fm.screens import BrowserScreen
from ssh_fm.terminal import TerminalScreen
from tests.fakes import FakeConnection, e
from tests.test_browser import go_to, make_app, open_browser, settle


def patch_transfer(monkeypatch, rc=0):
    calls, active = [], []
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def fake(cmd, on_progress):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        calls.append(cmd)
        on_progress(Progress(50, "1.00MB/s", "0:00:01"))
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return rc

    monkeypatch.setattr("ssh_fm.screens.run_transfer", fake)
    return calls, state


async def select_two_and_download(app, pilot, screen):
    go_to(screen, "index.php")
    await pilot.press("space")
    go_to(screen, "my file.txt")
    await pilot.press("space")
    await pilot.press("alt+d")
    await pilot.pause()
    await pilot.press("enter")  # first destination: current directory
    await settle(pilot)


async def test_download_queue_runs_sequentially_and_reports_progress(tmp_path, monkeypatch):
    calls, state = patch_transfer(monkeypatch)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        await select_two_and_download(app, pilot, screen)
        assert [c[3] for c in calls] == ["web:/home/deploy/index.php", "web:/home/deploy/my file.txt"]
        assert all(c[1] == "down" for c in calls)
        assert state["max"] == 1
        assert screen.query_one("#transfers").states() == ["done", "done"]


async def test_multiselect_download_builds_one_cmd_per_file(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        await select_two_and_download(app, pilot, screen)
        assert len(calls) == 2 and calls[0] != calls[1]


async def test_failed_transfer_marks_row_failed_and_toasts(tmp_path, monkeypatch):
    patch_transfer(monkeypatch, rc=23)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "index.php")
        await pilot.press("alt+d")
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)
        assert screen.query_one("#transfers").states() == ["failed"]
        assert any("failed" in n.message.lower() for n in app._notifications)


async def test_view_content_shows_text(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "index.php")
        await pilot.press("alt+v")
        await settle(pilot)
        assert isinstance(app.screen, TextViewScreen) and "hello" in app.screen.text


async def test_view_content_too_large_toasts(tmp_path):
    class Big(FakeConnection):
        tree = {"~": [e("big.bin", size=99999)]}
    app = make_app(tmp_path, Big)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "big.bin")
        await pilot.press("alt+v")
        await settle(pilot)
        assert isinstance(app.screen, BrowserScreen)
        assert any("too large" in n.message for n in app._notifications)


async def test_upload_missing_local_path_errors_without_running(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        await pilot.press("alt+u")
        await pilot.pause()
        app.screen.query_one(Input).value = str(tmp_path / "nope.txt")
        await pilot.press("enter")
        await settle(pilot)
        assert calls == [] and isinstance(app.screen, BrowserScreen)
        assert any("not found" in n.message.lower() for n in app._notifications)


async def test_upload_existing_files_queues_each(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    a, b = tmp_path / "a.txt", tmp_path / "b b.txt"
    a.write_text("x"), b.write_text("y")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        await pilot.press("alt+u")
        await pilot.pause()
        app.screen.query_one(Input).value = f"{a}, {b}"
        await pilot.press("enter")
        await settle(pilot)
        assert [c[2] for c in calls] == [str(a), str(b)]
        assert all(c[1] == "up" and c[3].endswith("/") for c in calls)


async def test_ssh_shell_opens_embedded_terminal(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        await pilot.press("alt+h")
        await settle(pilot)
        assert isinstance(app.screen, TerminalScreen) and app.screen.cmd == ["fake-ssh", "web"]
        await pilot.press("x")  # process failed to start (no such command): any key closes
        await settle(pilot)
        assert app.screen is screen


async def test_sftp_opens_in_current_directory(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await open_browser(app, pilot)
        app.screen.cwd = "/srv/app"
        await pilot.press("alt+f")
        await settle(pilot)
        assert isinstance(app.screen, TerminalScreen) and app.screen.cmd == ["fake-sftp", "web", "/srv/app"]


async def test_drag_between_panes_transfers(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    (tmp_path / "local.txt").write_text("x")
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_browser(app, pilot)
        screen.local_cwd = tmp_path
        await pilot.press("alt+t")
        await settle(pilot)
        remote, local = screen.query_one("#files"), screen.query_one("#local-files")
        row = local.get_row_index("local.txt")
        await pilot.mouse_down(local, offset=(5, row + 1))
        await pilot.mouse_up(remote, offset=(5, 2))
        await settle(pilot)
        assert calls and calls[0][1] == "up" and calls[0][2] == str(tmp_path / "local.txt")
        row = remote.get_row_index("index.php")
        await pilot.mouse_down(remote, offset=(5, row + 1))
        await pilot.mouse_up(local, offset=(5, 2))
        await settle(pilot)
        assert calls[-1][1] == "down" and calls[-1][3] == "web:/home/deploy/index.php"


async def test_local_multiselect_upload_and_drag(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    for n in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / n).write_text(n)
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_browser(app, pilot)
        screen.local_cwd = tmp_path
        await pilot.press("alt+t")
        await settle(pilot)
        local = screen.query_one("#local-files")
        local.move_cursor(row=local.get_row_index("a.txt"))
        await pilot.press("space")
        local.move_cursor(row=local.get_row_index("c.txt"))
        await pilot.press("space")
        assert screen.local_selected == {"a.txt", "c.txt"}
        await pilot.press("alt+u")
        await settle(pilot)
        assert sorted(c[2] for c in calls) == [str(tmp_path / "a.txt"), str(tmp_path / "c.txt")]
        calls.clear()
        remote = screen.query_one("#files")
        row = local.get_row_index("a.txt")
        await pilot.mouse_down(local, offset=(5, row + 1))
        await pilot.mouse_up(remote, offset=(5, 2))
        await settle(pilot)
        assert sorted(c[2] for c in calls) == [str(tmp_path / "a.txt"), str(tmp_path / "c.txt")]
