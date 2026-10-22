from pathlib import Path

from textual.widgets import Checkbox, TextArea

from ssh_fm.config import Host, localize_identity, parse_ssh_config
from tests.test_picker import make_app

FRIEND = """\
# my servers
Host prod staging
    HostName 10.0.0.5     # shared box
    User deploy
    Port 2222
    IdentityFile ~/.ssh/friend_key
    ProxyJump bastion
    ForwardAgent yes

Host db1
HostName=db.example.com
  User = admin
  PasswordAuthentication yes

Host *.internal *
    User nobody
Match host foo
    User ignored
Host bastion
    HostName "203.0.113.9"
"""


def test_parse_friend_config():
    hosts, ignored = parse_ssh_config(FRIEND)
    assert list(hosts) == ["prod", "staging", "db1", "bastion"]
    assert (hosts["prod"].hostname, hosts["prod"].user, hosts["prod"].port) == ("10.0.0.5", "deploy", "2222")
    assert hosts["staging"].hostname == "10.0.0.5"
    assert hosts["prod"].identity_file == str(Path.home() / ".ssh/friend_key")
    assert ignored["prod"] == ["proxyjump", "forwardagent"]
    assert hosts["db1"].hostname == "db.example.com" and hosts["db1"].user == "admin" and hosts["db1"].password_auth
    assert hosts["bastion"].hostname == "203.0.113.9"
    assert all(h.user != "nobody" and h.user != "ignored" for h in hosts.values())


def test_parse_empty_and_garbage():
    assert parse_ssh_config("")[0] == {}
    assert parse_ssh_config("just some text\nnot a config")[0] == {}


def test_localize_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".ssh").mkdir()
    h, note = localize_identity(Host("a", identity_file="/their/home/.ssh/missing"))
    assert h.identity_file == "" and "not found" in note
    (tmp_path / ".ssh" / "k").write_text("x")
    h, note = localize_identity(Host("a", identity_file="/their/home/.ssh/k"))
    assert h.identity_file == str(tmp_path / ".ssh" / "k") and note
    h, note = localize_identity(Host("a"))
    assert note == ""


async def paste(app, pilot, text):
    await pilot.press("alt+i")
    await pilot.pause()
    app.screen.query_one(TextArea).text = text
    await pilot.pause()


async def test_import_screen_adds_hosts_and_skips_existing(tmp_path):
    app, cfg = make_app(tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await paste(app, pilot, FRIEND + "\nHost web\n  HostName 9.9.9.9\n")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert set(cfg.hosts) >= {"prod", "staging", "db1", "bastion", "web", "db"}
        assert cfg.hosts["web"].hostname == "web.example.com"  # existing one untouched
        assert cfg.hosts["prod"].port == "2222" and cfg.hosts["prod"].identity_file == ""  # key not on this machine
        assert len(app.screen.query("HostCard")) == 6


async def test_import_overwrite_checkbox(tmp_path):
    app, cfg = make_app(tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await paste(app, pilot, "Host web\n  HostName 9.9.9.9\n  User root\n")
        app.screen.query_one(Checkbox).value = True
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert (cfg.hosts["web"].hostname, cfg.hosts["web"].user) == ("9.9.9.9", "root")
        reloaded = type(cfg)(cfg.path)
        assert reloaded.hosts["web"].hostname == "9.9.9.9"


async def test_import_nothing_recognised_stays_open(tmp_path):
    app, cfg = make_app(tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await paste(app, pilot, "hello")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert type(app.screen).__name__ == "ImportHostsScreen"
