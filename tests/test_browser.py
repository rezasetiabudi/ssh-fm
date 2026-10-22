from ssh_fm.app import SshFmApp
from ssh_fm.config import Host, SSHConfig, State
from ssh_fm.screens import BrowserScreen, HostPickerScreen
from tests.fakes import FakeConnection, e


def make_app(tmp_path, conn=FakeConnection):
    cfg = SSHConfig(tmp_path / "config")
    cfg.add(Host("web", "web.example.com", user="deploy"))
    cfg.add(Host("db", "db.example.com", user="deploy"))
    return SshFmApp(config=cfg, connection_factory=conn, state=State(tmp_path / "state.json"))


async def settle(pilot):
    for _ in range(3):
        await pilot.pause()
        await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def open_browser(app, pilot):
    await pilot.press("enter")
    await settle(pilot)
    assert isinstance(app.screen, BrowserScreen)
    return app.screen


def rows(screen):
    return [k.value for k in screen.query_one("#files").rows]


def go_to(screen, name):
    table = screen.query_one("#files")
    table.move_cursor(row=table.get_row_index(name))


async def test_connect_opens_browser_on_success(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        assert "index.php" in rows(screen)
        assert rows(screen)[0] == "app"  # dirs first, no ".." at home


async def test_connect_failure_stays_on_picker(tmp_path):
    class Refused(FakeConnection):
        master = (255, "ssh: connect to host web port 22: Connection refused")
    app = make_app(tmp_path, Refused)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, HostPickerScreen)


async def test_enter_descends_and_backspace_ascends(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "app")
        await pilot.press("enter")
        await settle(pilot)
        assert screen.cwd == "~/app" and "boot.php" in rows(screen) and ".." in rows(screen)
        await pilot.press("backspace")
        await settle(pilot)
        assert screen.cwd == "~"


async def test_cursor_move_updates_info_panel(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "index.php")
        await settle(pilot)
        text = screen.query_one("#info").text
        assert "index.php" in text and "ASCII text" in text and "deploy" in text


async def test_hidden_toggle(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        assert ".env" in rows(screen)
        await pilot.press("full_stop")
        await settle(pilot)
        assert ".env" not in rows(screen)


async def test_filenames_with_spaces_and_unicode_listed(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        assert "my file.txt" in rows(screen) and "naïve é.txt" in rows(screen)


async def test_listing_error_shows_message_row(tmp_path):
    class Denied(FakeConnection):
        denied = ("~/app",)
    app = make_app(tmp_path, Denied)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        go_to(screen, "app")
        await pilot.press("enter")
        await settle(pilot)
        assert screen.cwd == "~/app" and "__msg__" in rows(screen) and ".." in rows(screen)
        assert isinstance(app.screen, BrowserScreen)


async def test_narrow_terminal_hides_info(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(70, 24)) as pilot:
        screen = await open_browser(app, pilot)
        assert screen.query_one("#info").display is False
    app = make_app(tmp_path / "wide")
    async with app.run_test(size=(120, 30)) as pilot:
        screen = await open_browser(app, pilot)
        assert screen.query_one("#info").display is True


async def test_escape_returns_to_picker_and_closes_connection(tmp_path):
    created = []

    class Tracked(FakeConnection):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self)
    app = make_app(tmp_path, Tracked)
    async with app.run_test() as pilot:
        await open_browser(app, pilot)
        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(app.screen, HostPickerScreen)
        assert "close" in created[0].calls


async def test_quick_select_jumps_by_initial_and_prefix(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        table = screen.query_one("#files")

        def cur():
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        await pilot.press("i")
        assert cur() == "index.php"
        await pilot.press("l")  # prefix "il" has no match: stay
        assert cur() == "index.php"
        screen.quick.buf = ""
        await pilot.press("l")
        assert cur() == "logs"
        screen.quick.buf = ""
        await pilot.press("M")  # case-insensitive
        assert cur() == "my file.txt"


async def test_quick_select_repeat_cycles(tmp_path):
    class Many(FakeConnection):
        tree = {"~": [e("alpha"), e("apple"), e("avocado"), e("beta")]}
    app = make_app(tmp_path, Many)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        table = screen.query_one("#files")
        key = lambda: table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        await pilot.press("a", "a")
        assert key() == "apple"
        await pilot.press("a")  # still within the typing window: "aaa" -> next
        assert key() == "avocado"


async def test_letters_no_longer_trigger_actions(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_browser(app, pilot)
        await pilot.press("d", "u", "x", "s")
        await pilot.pause()
        assert app.screen is screen  # no dialogs opened


async def test_quick_select_in_host_picker(tmp_path):
    from tests.test_picker import make_app as picker_app
    app, _ = picker_app(tmp_path, hosts=("web", "db", "mail"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        assert app.focused.host.name == "mail"
        app.screen.quick.buf = ""
        await pilot.press("d")
        assert app.focused.host.name == "db"


async def test_cursor_style_is_white_on_blue(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = await open_browser(app, pilot)
        await pilot.pause(0.3)
        # the very first row must be blue too (a stale render cache used to leave it dim)
        assert screen.query_one("#files").cursor_row == 0
        assert "#3d59a1" in app.export_screenshot().lower()
        go_to(screen, "logs")
        await pilot.pause(0.3)
        assert "#3d59a1" in app.export_screenshot().lower()
        row = screen.query_one("#files").get_component_rich_style("datatable--cursor")
        assert (row.color.name, row.bgcolor.name) == ("#ffffff", "#3d59a1")
