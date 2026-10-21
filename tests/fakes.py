from ssh_fm.remote import Entry, RemoteError, join_path


def e(name, is_dir=False, size=0, perms=None):
    return Entry(name, is_dir, False, size, perms or ("drwxr-xr-x" if is_dir else "-rw-r--r--"),
                 "deploy", "www", "Oct 21 10:00")


class FakeConnection:
    """In-memory stand-in for ssh_fm.remote.Connection."""
    tree = {
        "~": [e("app", True), e("logs", True), e("index.php", size=4200), e("my file.txt", size=12), e("naïve é.txt", size=3), e(".env", size=312)],
        "~/app": [e("boot.php", size=100)],
        "~/logs": [],
    }
    master = (0, "")
    denied = ()

    def __init__(self, host, control_dir=None):
        self.host = host
        self.calls = []

    def try_master(self):
        return self.master

    def master_cmd(self, batch=False):
        return ["true"]

    def close(self):
        self.calls.append("close")

    def expand(self, path):
        return path.replace("~", "/home/deploy", 1) if path.startswith("~") else path

    def list_dir(self, path):
        if path in self.denied:
            raise RemoteError("Permission denied")
        return list(self.tree.get(path, []))

    def file_info(self, path):
        return {"name": path.rsplit("/", 1)[-1], "size": "42", "perms": "-rw-r--r--", "owner": "deploy",
                "group": "www", "mtime": "2026-10-21 10:00:00", "type": "ASCII text"}

    def read_head(self, path):
        if path.endswith("big.bin"):
            raise RemoteError("File is too large (99999 bytes). Use download instead.")
        return "hello\nworld\n"

    def transfer_cmd(self, direction, local, remote):
        return ["fake-transfer", direction, local, self.host + ":" + remote]

    def shell_cmd(self):
        return ["fake-ssh", self.host]

    def sftp_cmd(self, path=None):
        return ["fake-sftp", self.host] + ([path] if path else [])
