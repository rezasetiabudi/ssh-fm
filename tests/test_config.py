import os
import stat
from pathlib import Path

import pytest

from ssh_fm.config import Host, SSHConfig, ensure_key_permissions, find_keys


def make(tmp_path):
    return SSHConfig(tmp_path / "config")


def test_roundtrip_preserves_fields(tmp_path):
    cfg = make(tmp_path)
    cfg.add(Host("web", "10.0.0.5", "2222", "deploy", str(Path.home() / "k.pem"), True))
    again = make(tmp_path)
    again.load()
    h = again.hosts["web"]
    assert (h.hostname, h.port, h.user) == ("10.0.0.5", "2222", "deploy")
    assert h.identity_file == str(Path.home() / "k.pem")
    assert h.password_auth is True


def test_save_format_matches_legacy(tmp_path):
    cfg = make(tmp_path)
    cfg.add(Host("web", "h", user="u"))
    text = (tmp_path / "config").read_text()
    assert text.startswith("IgnoreUnknown UseKeychain")
    assert "  IdentitiesOnly yes" in text
    assert "Host *\n  AddKeysToAgent yes" in text


def test_quoted_identity_with_space(tmp_path):
    cfg = make(tmp_path)
    path = str(tmp_path / "my keys" / "a.pem")
    cfg.add(Host("web", "h", identity_file=path))
    assert f'IdentityFile "{path}"' in (tmp_path / "config").read_text()
    again = make(tmp_path)
    again.load()
    assert again.hosts["web"].identity_file == path


def test_wildcard_host_skipped(tmp_path):
    cfg = make(tmp_path)
    cfg.add(Host("web", "h"))
    again = make(tmp_path)
    again.load()
    assert list(again.hosts) == ["web"]


def test_duplicate_and_empty_name_rejected(tmp_path):
    cfg = make(tmp_path)
    cfg.add(Host("web", "h"))
    with pytest.raises(ValueError):
        cfg.add(Host("web", "h2"))
    with pytest.raises(ValueError):
        cfg.add(Host("  ", "h"))


def test_rename_via_update(tmp_path):
    cfg = make(tmp_path)
    cfg.add(Host("web", "h"))
    cfg.update("web", Host("prod", "h"))
    assert list(cfg.hosts) == ["prod"]
    cfg.add(Host("other", "h"))
    with pytest.raises(ValueError):
        cfg.update("prod", Host("other", "h"))


def test_delete(tmp_path):
    cfg = make(tmp_path)
    cfg.add(Host("web", "h"))
    cfg.delete("web")
    assert cfg.hosts == {}


def test_find_keys_includes_pem_excludes_pub(tmp_path):
    for n in ["id_rsa", "id_rsa.pub", "srv.pem", "x.key", "config", "known_hosts"]:
        (tmp_path / n).write_text("x")
    names = [p.name for p in find_keys(tmp_path)]
    assert sorted(names) == ["id_rsa", "srv.pem", "x.key"]


def test_ensure_key_permissions_sets_600(tmp_path):
    k = tmp_path / "a.pem"
    k.write_text("x")
    k.chmod(0o644)
    assert ensure_key_permissions(k) is True
    assert stat.S_IMODE(k.stat().st_mode) == 0o600
    assert ensure_key_permissions(k) is False
