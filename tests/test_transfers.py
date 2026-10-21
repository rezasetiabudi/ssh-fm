import threading
import time
from contextlib import contextmanager

from textual.widgets import Input

from ssh_fm.modals import TextViewScreen
from ssh_fm.remote import Progress
from ssh_fm.screens import BrowserScreen
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
    await pilot.press("d")
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
        await pilot.press("d")
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
        await pilot.press("v")
        await settle(pilot)
        assert isinstance(app.screen, TextViewScreen) and "hello" in app.screen.text


async def test_view_content_too_large_toasts(tmp_path):
    class Big(FakeConnection):
        tree = {"~": [e("big.bin", size=99999)]}
    app = make_app(tmp_path, Big)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "big.bin")
        await pilot.press("v")
        await settle(pilot)
        assert isinstance(app.screen, BrowserScreen)
        assert any("too large" in n.message for n in app._notifications)


async def test_upload_missing_local_path_errors_without_running(tmp_path, monkeypatch):
    calls, _ = patch_transfer(monkeypatch)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        await pilot.press("u")
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
        await pilot.press("u")
        await pilot.pause()
        app.screen.query_one(Input).value = f"{a}, {b}"
        await pilot.press("enter")
        await settle(pilot)
        assert [c[2] for c in calls] == [str(a), str(b)]
        assert all(c[1] == "up" and c[3].endswith("/") for c in calls)


async def test_ssh_shell_uses_suspend(tmp_path, monkeypatch):
    ran, entered = [], []

    @contextmanager
    def fake_suspend():
        entered.append(1)
        yield

    monkeypatch.setattr("ssh_fm.screens.subprocess.run", lambda cmd, *a, **k: ran.append(cmd))
    app = make_app(tmp_path)
    monkeypatch.setattr(app, "suspend", fake_suspend)
    async with app.run_test() as pilot:
        await open_browser(app, pilot)
        await pilot.press("S")
        await settle(pilot)
        assert ran == [["fake-ssh", "web"]] and entered
