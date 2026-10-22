"""All access to remote hosts (ssh / rsync). UI-free so it can be tested."""

import os
import posixpath
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_VIEW_BYTES = 10000


class RemoteError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    is_link: bool
    size: int
    perms: str
    owner: str
    group: str
    mtime: str


@dataclass
class Progress:
    percent: int
    speed: str
    eta: str


def parse_ls(output):
    dirs, files = [], []
    for line in output.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9 or line.startswith("total"):
            continue
        perms, _, owner, group, size, mon, day, tm, name = parts
        is_link = perms.startswith("l")
        if is_link and " -> " in name:
            name = name.split(" -> ", 1)[0]
        if name in (".", ".."):
            continue
        entry = Entry(name, perms.startswith("d"), is_link,
                      int(size) if size.isdigit() else 0, perms, owner, group, f"{mon} {day} {tm}")
        (dirs if entry.is_dir else files).append(entry)
    key = lambda e: e.name.lower()
    return sorted(dirs, key=key) + sorted(files, key=key)


def join_path(base, name):
    if name == "..":
        if base == "~" or base.endswith("/.."):
            return base.rstrip("/") + "/.."
        if base.startswith("~/") and base.count("/") == 1:
            return "~"
        return posixpath.dirname(base.rstrip("/")) or "/"
    return base.rstrip("/") + "/" + name


_PROGRESS = re.compile(r"(\d+)%\s+(\S+/s)\s+(\d+:\d+:\d+)")


def parse_progress(line):
    matches = _PROGRESS.findall(line)
    if not matches:
        return None
    pct, speed, eta = matches[-1]
    return Progress(int(pct), speed, eta)


INFO_SCRIPT = (
    'echo "ssh_conn=$SSH_CONNECTION"; echo "hostname=$(hostname)"; '
    'echo "os=$( . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -s)"; '
    'echo "kernel=$(uname -r)"; echo "arch=$(uname -m)"; echo "user=$(id -un)"; '
    'echo "uptime=$(uptime -p 2>/dev/null || uptime)"; echo "load=$(cut -d" " -f1-3 /proc/loadavg 2>/dev/null)"; '
    'echo "cpus=$(nproc 2>/dev/null)"; '
    'echo "memory=$(free -h 2>/dev/null | awk \'/^Mem:/{print $3 " / " $2}\')"; '
    'echo "disk=$(df -h ~ 2>/dev/null | awk \'NR==2{print $3 " / " $2 " (" $5 ")"}\')"'
)
MODE_RE = re.compile(r"^([0-7]{3,4}|[ugoa]*[-+=][rwxXst]+(,[ugoa]*[-+=][rwxXst]+)*)$")


def perms_to_octal(perms):
    """'-rwxr-xr--' / 'drwxr-xr-x' -> '754' / '755' ('' if unparsable)."""
    bits = perms[-9:]
    if len(bits) != 9:
        return ""
    out = ""
    for i in range(0, 9, 3):
        r, w, x = bits[i:i + 3]
        out += str((r == "r") * 4 + (w == "w") * 2 + (x in "xst") * 1)
    return out


def quote_path(path):
    """Quote for a remote shell while keeping a leading ~ expandable."""
    if path == "~":
        return "~"
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)


def run_transfer(cmd, on_progress):
    """Run rsync/scp, streaming progress. Returns the exit code."""
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    buf = ""
    for chunk in iter(lambda: proc.stdout.read(64), ""):
        buf += chunk
        *done, buf = re.split(r"[\r\n]", buf)
        for part in done:
            p = parse_progress(part)
            if p:
                on_progress(p)
    proc.wait()
    return proc.returncode


class Connection:
    def __init__(self, host, control_dir=None):
        self.host = host
        self.control_dir = Path(control_dir) if control_dir else Path(tempfile.gettempdir()) / f"ssh-fm-{os.getuid()}"
        self.control_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._home = None

    # --- command builders -------------------------------------------------
    def ssh_opts(self):
        return ["-o", f"ControlPath={self.control_dir}/%C"]

    def master_cmd(self, batch=False):
        extra = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"] if batch else []
        return ["ssh", *self.ssh_opts(), *extra, "-o", "ControlMaster=yes", "-o", "ControlPersist=10m", "-fN", self.host]

    def shell_cmd(self):
        return ["ssh", *self.ssh_opts(), self.host]

    def sftp_cmd(self, path=None):
        """sftp session; with `path` it starts in that remote directory (~ is expanded first)."""
        target = f"{self.host}:{self.expand(path)}" if path else self.host
        return ["sftp", *self.ssh_opts(), target]

    def list_cmd(self, path):
        return f"LC_ALL=C ls -la -- {quote_path(path)}"

    def transfer_cmd(self, direction, local, remote):
        ssh = "ssh " + " ".join(shlex.quote(o) for o in self.ssh_opts())
        base = ["rsync", "-az", "-s", "--info=progress2", "-e", ssh]
        remote = f"{self.host}:{remote}"
        return base + ([local, remote] if direction == "up" else [remote, local])

    # --- master connection ------------------------------------------------
    def try_master(self):
        """Silent attempt (no prompts). Returns (returncode, stderr)."""
        r = subprocess.run(self.master_cmd(batch=True), stdin=subprocess.DEVNULL, capture_output=True, text=True)
        return r.returncode, r.stderr

    def is_alive(self):
        r = subprocess.run(["ssh", *self.ssh_opts(), "-O", "check", self.host], stdin=subprocess.DEVNULL, capture_output=True)
        return r.returncode == 0

    def close(self):
        subprocess.run(["ssh", *self.ssh_opts(), "-O", "exit", self.host], stdin=subprocess.DEVNULL, capture_output=True)

    # --- remote commands --------------------------------------------------
    def run(self, command, timeout=15):
        try:
            r = subprocess.run(["ssh", *self.ssh_opts(), "-o", "BatchMode=yes", self.host, command],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RemoteError(f"Timed out running: {command}")
        if r.returncode != 0:
            raise RemoteError(r.stderr.strip() or f"exit status {r.returncode}")
        return r.stdout

    def home(self):
        if self._home is None:
            self._home = self.run("printf %s \"$HOME\"").strip()
        return self._home

    def expand(self, path):
        """Resolve a leading ~ (rsync -s does not expand it)."""
        if path == "~" or path.startswith("~/"):
            return self.home() + path[1:]
        return path

    def list_dir(self, path):
        return parse_ls(self.run(self.list_cmd(path)))

    def server_info(self):
        """Facts about the remote machine and about this SSH session, as a dict (missing keys are simply absent)."""
        out = self.run(INFO_SCRIPT)
        info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        parts = info.pop("ssh_conn", "").split()
        if len(parts) == 4:
            info["client_ip"], info["client_port"], info["server_ip"], info["server_port"] = parts
        return {k: v.strip() for k, v in info.items() if v.strip()}

    def file_info(self, path):
        q = quote_path(path)
        out = self.run(f"stat -c '%s|%A|%U|%G|%y' -- {q} 2>/dev/null || stat -f '%z|%Sp|%Su|%Sg|%Sm' -- {q}").strip()
        size, perms, owner, group, mtime = (out.split("|") + [""] * 5)[:5]
        try:
            kind = self.run(f"file -b -- {q}").strip()
        except RemoteError:
            kind = ""
        return {"name": posixpath.basename(path.rstrip("/")) or path, "size": size, "perms": perms,
                "owner": owner, "group": group, "mtime": mtime.split(".")[0], "type": kind}

    # --- file operations (one remote command each) --------------------------------
    def remove(self, path):
        if path.rstrip("/") in ("", "~", "/"):
            raise RemoteError(f"Refusing to delete {path or '(empty)'}")
        self.run(f"rm -rf -- {quote_path(path)}")

    def rename(self, old, new):
        self.run(f"mv -n -- {quote_path(old)} {quote_path(new)}")

    def mkdir(self, path):
        self.run(f"mkdir -- {quote_path(path)}")

    def chmod(self, path, mode):
        if not MODE_RE.match(mode):
            raise RemoteError(f"Invalid mode: {mode}")
        self.run(f"chmod {mode} -- {quote_path(path)}")

    def read_head(self, path):
        q = quote_path(path)
        size = self.run(f"stat -c%s -- {q} 2>/dev/null || stat -f%z -- {q}").strip()
        if size.isdigit() and int(size) > MAX_VIEW_BYTES:
            raise RemoteError(f"File is too large ({size} bytes). Use download instead.")
        return self.run(f"head -n 50 -- {q}")
