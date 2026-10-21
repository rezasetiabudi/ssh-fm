"""Model for hosts stored in ~/.ssh/config"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Host:
    name: str
    hostname: str = ""
    port: str = "22"
    user: str = ""
    identity_file: str = ""
    password_auth: bool = False


class SSHConfig:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home() / ".ssh" / "config"
        self.hosts = {}
        self.load()

    def load(self):
        self.hosts = {}
        if not self.path.exists():
            return
        current = None
        for line in self.path.read_text().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("host "):
                name = line.split()[1]
                current = None if name == "*" else Host(name)
                if current:
                    self.hosts[name] = current
                continue
            if current is None:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            key, value = parts[0].lower(), parts[1]
            if key == "hostname":
                current.hostname = value
            elif key == "port":
                current.port = value
            elif key == "user":
                current.user = value
            elif key == "identityfile":
                value = value.strip('"')
                if value.startswith("~"):
                    value = value.replace("~", str(Path.home()), 1)
                current.identity_file = value
            elif key == "passwordauthentication":
                current.password_auth = value.lower() == "yes"

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
