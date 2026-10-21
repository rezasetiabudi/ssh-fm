import asyncio

from textual.app import App

from ssh_fm.terminal import TerminalScreen, TerminalView


class Host(App):
    def __init__(self, cmd):
        super().__init__()
        self.cmd, self.result = cmd, "unset"

    def on_mount(self):
        self.push_screen(TerminalScreen("test", self.cmd), lambda rc: setattr(self, "result", rc))


async def wait_for(pilot, cond, tries=60):
    for _ in range(tries):
        await pilot.pause(0.05)
        if cond():
            return True
    return False


async def test_output_is_rendered_and_clean_exit_dismisses():
    app = Host(["sh", "-c", "printf 'hello \\033[31mred\\033[0m'; sleep 0.3"])
    async with app.run_test(size=(60, 12)) as pilot:
        view = app.screen.query_one(TerminalView)
        assert await wait_for(pilot, lambda: "hello red" in view.text())
        assert await wait_for(pilot, lambda: app.result == 0)


async def test_keys_go_to_process_not_to_app():
    app = Host(["sh", "-c", "read x; echo got:$x"])
    async with app.run_test(size=(60, 12)) as pilot:
        view = app.screen.query_one(TerminalView)
        await pilot.pause(0.2)
        await pilot.press("h", "i", "ctrl+p", "enter")  # ctrl+p must not open the command palette
        assert await wait_for(pilot, lambda: "got:hi" in view.text())
        assert app.screen.__class__ is TerminalScreen or app.result == 0


async def test_failure_waits_for_key_and_reports_status():
    app = Host(["sh", "-c", "echo boom; exit 3"])
    async with app.run_test(size=(60, 12)) as pilot:
        assert await wait_for(pilot, lambda: app.screen.finished == 3)
        assert app.result == "unset"
        await pilot.press("q")
        assert await wait_for(pilot, lambda: app.result == 3)


async def test_ctrl_bracket_closes_and_kills_process():
    app = Host(["sh", "-c", "sleep 30"])
    async with app.run_test(size=(60, 12)) as pilot:
        view = app.screen.query_one(TerminalView)
        await pilot.pause(0.2)
        proc = view.proc
        await pilot.press("ctrl+right_square_bracket")
        assert await wait_for(pilot, lambda: app.result == 0)
        assert await wait_for(pilot, lambda: proc.poll() is not None)
