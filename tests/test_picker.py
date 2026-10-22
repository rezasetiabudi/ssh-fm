import pytest

from ssh_fm.app import SshFmApp
from ssh_fm.config import Host, SSHConfig, State
from tests.fakes import FakeConnection


def make_app(tmp_path, hosts=("web", "db")):
    cfg = SSHConfig(tmp_path / "config")
    for h in hosts:
        cfg.add(Host(h, f"{h}.example.com", user="deploy"))
    return SshFmApp(config=cfg, connection_factory=FakeConnection, state=State(tmp_path / "state.json")), cfg


async def test_picker_lists_cards_for_each_host(tmp_path):
    app, _ = make_app(tmp_path)
    async with app.run_test() as pilot:
        assert len(app.screen.query("HostCard")) == 2


async def test_empty_config_shows_hint(tmp_path):
    app, _ = make_app(tmp_path, hosts=())
    async with app.run_test() as pilot:
        assert app.screen.query("#empty")
        assert not app.screen.query("HostCard")


async def test_n_opens_form_and_saves_host(tmp_path):
    app, cfg = make_app(tmp_path, hosts=())
    async with app.run_test() as pilot:
        await pilot.press("alt+n")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#f-name").value = "prod"
        screen.query_one("#f-hostname").value = "10.0.0.5"
        screen.query_one("#f-port").value = "2222"
        screen.query_one("#f-user").value = "root"
        await pilot.click("#save")
        await pilot.pause()
        assert cfg.hosts["prod"].port == "2222"
        assert "Host prod" in cfg.path.read_text()
        assert len(app.screen.query("HostCard")) == 1


async def test_form_rejects_bad_port(tmp_path):
    app, cfg = make_app(tmp_path, hosts=())
    async with app.run_test() as pilot:
        await pilot.press("alt+n")
        await pilot.pause()
        app.screen.query_one("#f-name").value = "prod"
        app.screen.query_one("#f-port").value = "abc"
        await pilot.click("#save")
        await pilot.pause()
        assert "prod" not in cfg.hosts
        assert app.screen.query("#save")  # still in the form


async def test_delete_requires_confirm(tmp_path):
    app, cfg = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("alt+d", "n")
        await pilot.pause()
        assert "web" in cfg.hosts
        await pilot.press("alt+d", "y")
        await pilot.pause()
        assert "web" not in cfg.hosts and "db" in cfg.hosts


async def test_edit_renames_host(tmp_path):
    app, cfg = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("alt+e")
        await pilot.pause()
        app.screen.query_one("#f-name").value = "web2"
        await pilot.click("#save")
        await pilot.pause()
        assert "web2" in cfg.hosts and "web" not in cfg.hosts


async def test_filter_hides_non_matching_cards(tmp_path):
    app, _ = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("slash")
        await pilot.press("d", "b")
        await pilot.pause()
        visible = [c for c in app.screen.query("HostCard") if c.display]
        assert [c.host.name for c in visible] == ["db"]
