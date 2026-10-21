from pathlib import Path

from ssh_fm.remote import Connection, Progress, join_path, parse_ls, parse_progress

LS = """total 20
drwxr-xr-x  5 deploy www  4096 Oct 21 10:00 .
drwxr-xr-x  3 root   root 4096 Oct 20 09:00 ..
-rw-r--r--  1 deploy www  4200 Oct 21 10:00 index.php
drwxr-xr-x  2 deploy www  4096 Oct 21 10:00 logs
drwxr-xr-x  2 deploy www  4096 Oct 21 10:00 App
-rw-------  1 deploy www   312 Oct 21 10:00 my file -> not a link.txt
lrwxrwxrwx  1 deploy www    11 Oct 21 10:00 current -> releases/42
"""


def test_parse_ls_basic_dirs_first_sorted():
    names = [e.name for e in parse_ls(LS)]
    assert names == ["App", "logs", "current", "index.php", "my file -> not a link.txt"]
    first = parse_ls(LS)[0]
    assert first.is_dir and first.owner == "deploy" and first.group == "www"


def test_parse_ls_name_with_spaces_and_arrow_text():
    e = [e for e in parse_ls(LS) if e.name.startswith("my file")][0]
    assert e.name == "my file -> not a link.txt" and not e.is_link and e.size == 312


def test_parse_ls_symlink_strips_target():
    e = [e for e in parse_ls(LS) if e.name == "current"][0]
    assert e.is_link and e.perms.startswith("l")


def test_parse_ls_ignores_total_dot_dotdot():
    assert all(e.name not in (".", "..") for e in parse_ls(LS))
    assert parse_ls("") == []


def test_join_path_cases():
    assert join_path("~", "a") == "~/a"
    assert join_path("/", "a") == "/a"
    assert join_path("/var/www", "..") == "/var"
    assert join_path("~", "..") == "~/.."
    assert join_path("/var/www/", "x y") == "/var/www/x y"


def test_parse_progress_variants():
    p = parse_progress("  1,234,567  68%   12.40MB/s    0:00:04 (xfr#1, to-chk=0/1)")
    assert p == Progress(68, "12.40MB/s", "0:00:04")
    assert parse_progress("\r  100%  1.00kB/s  0:00:00\r  200  50%  2.00MB/s  0:00:09").percent == 50
    assert parse_progress("sending incremental file list") is None


def test_quote_prevents_injection(tmp_path):
    c = Connection("web", tmp_path)
    cmd = c.list_cmd("/srv/a; rm -rf ~")
    assert cmd == "LC_ALL=C ls -la -- '/srv/a; rm -rf ~'"
    assert c.list_cmd("~/my dir") == "LC_ALL=C ls -la -- ~/'my dir'"


def test_transfer_cmd_uses_control_path_and_protect_args(tmp_path):
    c = Connection("web", tmp_path)
    cmd = c.transfer_cmd("down", "/tmp/out", "~/a b.txt")
    assert cmd[0] == "rsync" and "-s" in cmd and "--info=progress2" in cmd
    assert any("ControlPath=" in part for part in cmd)
    assert cmd[-2:] == ["web:~/a b.txt", "/tmp/out"]
    up = c.transfer_cmd("up", "/tmp/in", "~/dest")
    assert up[-2:] == ["/tmp/in", "web:~/dest"]
