"""Model for hosts stored in ~/.ssh/config"""

import json
import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass
class Host:
    name: str
    hostname: str = ""
    port: str = "22"
    user: str = ""
    identity_file: str = ""
    password_auth: bool = False


SUPPORTED = {"hostname", "port", "user", "identityfile", "passwordauthentication"}


def _split_option(line):
    """'Key value', 'Key=value' or 'Key = value' -> (key, value) with trailing # comment and quotes removed."""
    m = re.match(r"^(\S+?)\s*(?:=|\s)\s*(.*)$", line)
    if not m:
        return None, ""
    key, value = m.group(1), m.group(2).strip()
    if not value.startswith('"'):
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    return key.lower(), value.strip('"')


def parse_ssh_config(text, expand_home=True):
    """Parse ssh_config text -> ({name: Host}, {name: [unsupported option names]}).

    `Host a b` yields both hosts; wildcard patterns (`Host *`, `Host *.example.com`) and `Match` blocks are skipped.
    """
    hosts, ignored, current = {}, {}, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, value = _split_option(line)
        if key == "host":
            current = []
            for name in value.split():
                if not any(c in name for c in "*?!") and name not in hosts:
                    hosts[name] = Host(name)
                    ignored[name] = []
                    current.append(hosts[name])
            continue
        if key == "match":
            current = []
            continue
        if not current or not key:
            continue
        for h in current:
            if key == "hostname":
                h.hostname = value
            elif key == "port":
                h.port = value
            elif key == "user":
                h.user = value
            elif key == "identityfile":
                if not h.identity_file:  # ssh tries them in order; we keep the first
                    h.identity_file = str(Path(value).expanduser()) if expand_home and value.startswith("~") else value
            elif key == "passwordauthentication":
                h.password_auth = value.lower() == "yes"
            elif key not in SUPPORTED and key not in ignored[h.name]:
                ignored[h.name].append(key)
    return hosts, ignored


def localize_identity(host):
    """A key path copied from someone else's config rarely exists here. Returns (host, note):
    uses ~/.ssh/<same filename> if present, otherwise clears the path (note explains)."""
    if not host.identity_file or Path(host.identity_file).expanduser().exists():
        return host, ""
    local = Path.home() / ".ssh" / Path(host.identity_file).name
    if local.exists():
        return replace(host, identity_file=str(local)), f"key → {local}"
    return replace(host, identity_file=""), f"key {host.identity_file} not found here — set one with Edit"


class State:
    """Small JSON store for UI memory (e.g. last local folder per host)."""

    def __init__(self, path=None):
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
        self.path = Path(path) if path else base / "ssh-fm" / "state.json"
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1))
        except OSError:
            pass


class SSHConfig:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home() / ".ssh" / "config"
        self.hosts = {}
        self.load()

    def load(self):
        self.hosts = {}
        if self.path.exists():
            self.hosts, _ = parse_ssh_config(self.path.read_text())

    def save(self):
        lines = ["IgnoreUnknown UseKeychain"]
        for host in self.hosts.values():
            lines.append(f"Host {host.name}")
            if host.hostname:
                lines.append(f"  HostName {host.hostname}")
            if host.port != "22":
                lines.append(f"  Port {host.port}")
            if host.user:
                lines.append(f"  User {host.user}")
            if host.identity_file:
                ident = host.identity_file.replace(str(Path.home()), "~")
                if " " in ident:
                    ident = f'"{ident}"'
                lines.append(f"  IdentityFile {ident}")
            lines.append("  IdentitiesOnly yes")
            if host.password_auth:
                lines.append("  PasswordAuthentication yes")
            lines.append("")
        lines.extend(["Host *", "  AddKeysToAgent yes", "  ServerAliveInterval 60", "  ServerAliveCountMax 3"])
        if sys.platform == "darwin":
            lines.append("  UseKeychain yes")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines))

    def _check(self, host, old_name=None):
        name = host.name.strip()
        if not name or (name != old_name and name in self.hosts):
            raise ValueError(f"Invalid or duplicate host name: {host.name!r}")
        host.name = name

    def add(self, host):
        self._check(host)
        self.hosts[host.name] = host
        self.save()

    def update(self, old_name, host):
        self._check(host, old_name)
        # rebuild to keep ordering when renaming
        self.hosts = {(host.name if k == old_name else k): (host if k == old_name else v)
                      for k, v in self.hosts.items()}
        self.save()

    def delete(self, name):
        self.hosts.pop(name, None)
        self.save()


def find_keys(ssh_dir=None):
    ssh_dir = Path(ssh_dir) if ssh_dir else Path.home() / ".ssh"
    if not ssh_dir.is_dir():
        return []
    return [p for p in sorted(ssh_dir.iterdir())
            if p.is_file() and p.suffix != ".pub"
            and (p.name.startswith("id_") or p.suffix in (".pem", ".key"))]


def ensure_key_permissions(path):
    """ssh rejects private keys readable by group/others. Returns True if changed."""
    if os.name == "nt":
        return False
    path = Path(path)
    if path.stat().st_mode & 0o077:
        path.chmod(0o600)
        return True
    return False
