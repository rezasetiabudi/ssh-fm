# ssh-fm TUI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the numbered-menu `ssh-fm.py` with a full-screen Textual TUI (host card picker, then 3-column browser with file-info panel and live transfer bar) keeping every existing feature.

**Architecture:** A small package `ssh_fm/` split by responsibility: `config.py` (ssh config model), `remote.py` (all ssh/scp/rsync access, UI-free, testable), `app.py` + `screens.py` + `app.tcss` (Textual UI). `ssh-fm.py` stays the entry point. One ssh ControlMaster connection per host is opened interactively (so password/passphrase prompts work) and reused by every later `ssh`/`rsync` call.

**Tech Stack:** Python 3.10+, Textual (pin `textual>=0.80,<2`), Rich, pytest + pytest-asyncio (`asyncio_mode = auto`) for tests; system `ssh`, `rsync`.

**Spec:** `docs/superpowers/specs/2026-10-21-tui-redesign-design.md`

## Global Constraints

- Source of truth stays `~/.ssh/config`; same file format as today's `save_config` (`IgnoreUnknown UseKeychain`, per-host `IdentitiesOnly yes`, trailing `Host *` block, `UseKeychain yes` only on darwin, quoted `IdentityFile` when path has spaces, `~` collapsed on write).
- Shell out to `ssh`/`scp`/`rsync`/`sftp`; no paramiko/asyncssh.
- All remote work off the UI thread (Textual workers); UI never blocks.
- Every old feature remains: list/add/edit/delete host, ssh shell, browse, upload/download single+multiple, rsync dir sync, terminal SFTP, file info, view content (<=10000 bytes, first 50 lines), `.pem`/`.key` identities with chmod 600.
- No file-content preview panel; right panel is file info only.
- `install.sh` must work from a clone (copies package + creates launcher in `~/bin/ssh-fm`).

## Review Focus

- Filenames with spaces, quotes, `$`, unicode, or `->` (symlinks) must list, download and open correctly (no shell injection from remote names).
- Password-auth host: connect must prompt in the terminal, not hang the TUI.
- Connect failure / wrong key / timeout: toast with the ssh error, stay on picker.
- Permission-denied or empty directory: show message in the listing, don't crash or drop the connection.
- Very narrow terminal (<80 cols): info panel collapses instead of garbling layout.

---

### Task 1: Package scaffold + config model

**Files:**
- Create: `ssh_fm/__init__.py`, `ssh_fm/config.py`, `tests/test_config.py`, `pyproject.toml` (pytest config + deps), `requirements.txt`
- Modify: `ssh-fm.py` (becomes thin entry; old code deleted in Task 7)

**Interfaces:**
- Produces:
  - `@dataclass Host(name: str, hostname: str = "", port: str = "22", user: str = "", identity_file: str = "", password_auth: bool = False)`
  - `SSHConfig(path: Path | None = None)` with `.hosts: dict[str, Host]`, `.load() -> None`, `.save() -> None`, `.add(host: Host) -> None`, `.update(old_name: str, host: Host) -> None`, `.delete(name: str) -> None`; `add`/`update` raise `ValueError` on empty or duplicate name.
  - `find_keys(ssh_dir: Path | None = None) -> list[Path]` (files named `id_*`, `*.pem`, `*.key`; never `*.pub`), `ensure_key_permissions(path: Path) -> bool` (True if it chmod'ed to 600).

- [ ] **Step 1: Failing tests** in `tests/test_config.py`: `test_roundtrip_preserves_fields` (write/load a host with port 2222, user, identity `~/k.pem`, password_auth), `test_save_format_matches_legacy` (output contains `IgnoreUnknown UseKeychain`, `  IdentitiesOnly yes`, ends with `Host *` block), `test_quoted_identity_with_space`, `test_wildcard_host_skipped`, `test_duplicate_and_empty_name_rejected`, `test_rename_via_update`, `test_find_keys_includes_pem_excludes_pub`, `test_ensure_key_permissions_sets_600`.
- [ ] **Step 2:** `pytest tests/test_config.py -v` — FAIL (import error).
- [ ] **Step 3:** Implement `ssh_fm/config.py` by moving the logic of `load_config`/`save_config`/`select_identity_file`/`ensure_key_permissions` from `ssh-fm.py` (no `print`/`input`). Add `pyproject.toml` with `[tool.pytest.ini_options] asyncio_mode = "auto"`, `requirements.txt` with `textual>=0.80,<2`.
- [ ] **Step 4:** `pytest tests/test_config.py -v` — PASS.
- [ ] **Step 5:** Commit `feat: extract ssh config model into ssh_fm.config`.

### Task 2: Remote access layer

**Files:**
- Create: `ssh_fm/remote.py`, `tests/test_remote.py`

**Interfaces:**
- Produces:
  - `class RemoteError(Exception)`
  - `@dataclass(frozen=True) Entry(name: str, is_dir: bool, is_link: bool, size: int, perms: str, owner: str, group: str, mtime: str)`
  - `parse_ls(output: str) -> list[Entry]` — input is `LC_ALL=C ls -la` output; skips `total`, `.`, `..`; name = everything after the 8th field, symlink ` -> target` stripped; dirs first then files, each sorted case-insensitively.
  - `join_path(base: str, name: str) -> str` (`~` base stays `~/name`; `/` base gives `/name`; `..` resolves to parent via `posixpath`).
  - `@dataclass Progress(percent: int, speed: str, eta: str)`; `parse_progress(line: str) -> Progress | None` handles rsync `--info=progress2` lines like `  1,234,567  68%   12.40MB/s    0:00:04 (xfr#1, to-chk=0/1)` (and carriage-return separated chunks).
  - `class Connection(host: str, control_dir: Path | None = None)` with: `ssh_opts() -> list[str]` (`["-o", "ControlPath=<dir>/%C"]`), `master_cmd() -> list[str]` (`ssh -o ControlMaster=yes -o ControlPersist=10m -fN ... host`), `open_master() -> int` (runs `master_cmd` inheriting the terminal, returns returncode; caller must run it inside `app.suspend()`), `is_alive() -> bool` (`ssh -O check`), `close() -> None` (`ssh -O exit`), `run(command: str, timeout: float = 15) -> str` (raises `RemoteError` with stderr), `list_dir(path: str) -> list[Entry]`, `file_info(path: str) -> dict[str, str]` (keys `name,size,perms,owner,group,mtime,type`), `read_head(path: str) -> str` (raises `RemoteError` if >10000 bytes), `transfer_cmd(direction: Literal["up","down"], local: str, remote: str) -> list[str]` (rsync `-az -s --info=progress2 -e "ssh <opts>"`), `shell_cmd() -> list[str]`, `sftp_cmd() -> list[str]`.
  - `run_transfer(cmd: list[str], on_progress: Callable[[Progress], None]) -> int` — streams stdout, calls `on_progress`, returns exit code.
  - All remote paths embedded in command strings use `shlex.quote`; `~` prefix is expanded by passing `~/` outside the quotes.

- [ ] **Step 1: Failing tests:** `test_parse_ls_basic` (dirs first, sorted), `test_parse_ls_name_with_spaces_and_arrow_text`, `test_parse_ls_symlink_strips_target`, `test_parse_ls_ignores_total_dot_dotdot`, `test_join_path_cases` (`("~","a")->"~/a"`, `("/","a")->"/a"`, `("/var/www","..")->"/var"`, `("~","..")->"~/.."` is fine to leave as `/`-less: assert it returns `".."`-free parent handled by caller — choose: `("~","..")->"/home"` is NOT computed; return `"~/.."`), `test_parse_progress_variants` (progress2 line, per-file `--progress` line, garbage → None), `test_quote_prevents_injection` (name `a; rm -rf ~` ends up inside one shell-quoted arg of the built command), `test_transfer_cmd_uses_control_path_and_protect_args`.
- [ ] **Step 2:** run — FAIL.
- [ ] **Step 3:** Implement. Use `subprocess.run(["ssh", *self.ssh_opts(), host, command], capture_output=True, text=True, timeout=timeout)`; add `-o BatchMode=yes` for non-master calls so a dead master fails fast instead of prompting. `file_info` tries `stat -c '%s|%A|%U|%G|%y'` then falls back to `stat -f '%z|%Sp|%Su|%Sg|%Sm'`, plus `file -b`.
- [ ] **Step 4:** run — PASS.
- [ ] **Step 5:** Commit `feat: add remote access layer (ssh/rsync wrappers, ls parser)`.

### Task 3: App shell + host picker + modals

**Files:**
- Create: `ssh_fm/app.py`, `ssh_fm/screens.py`, `ssh_fm/app.tcss`, `tests/test_picker.py`
- Modify: `ssh-fm.py` → `from ssh_fm.app import main; main()` (keep shebang; insert own directory into `sys.path`)

**Interfaces:**
- Consumes: `SSHConfig`, `Host`, `find_keys`, `ensure_key_permissions` (Task 1).
- Produces:
  - `SshFmApp(config: SSHConfig | None = None, connection_factory: Callable[[str], Connection] = Connection)`; `main() -> None`.
  - `HostPickerScreen(Screen)`: grid of `HostCard(Static)`; bindings `enter` connect, `n` new, `e` edit, `d` delete, `/` filter, `q` quit; posts `HostPickerScreen.Connect(host_name)`.
  - `HostFormScreen(ModalScreen[Host | None])(host: Host | None)` — fields hostname, port, user, auth `Select` (key / password), identity `Select` fed by `find_keys` plus a "custom path…" `Input`; validates port digits and non-empty name; `ensure_key_permissions` on submit and toast if changed.
  - `ConfirmScreen(ModalScreen[bool])(message: str)`.
- Theme: dark, one accent (`#7aa2f7`), rounded borders; screen fade-in via `styles.animate("opacity", ...)` on mount.

- [ ] **Step 1: Failing pilot tests** (`App.run_test()`): `test_picker_lists_cards_for_each_host`, `test_n_opens_form_and_saves_host` (fills inputs, host appears in `config.hosts` and file), `test_delete_requires_confirm` (press `d`, `n` → host kept; `d`, `y` → removed), `test_edit_renames_host`, `test_empty_config_shows_hint`.
- [ ] **Step 2:** `pytest tests/test_picker.py -v` — FAIL.
- [ ] **Step 3:** Implement screens/app per Interfaces. `ConfirmScreen` binds `y`/`n`/`escape`.
- [ ] **Step 4:** run — PASS; manually `python ssh-fm.py` with `textual run`-free launch to eyeball.
- [ ] **Step 5:** Commit `feat: textual host picker with add/edit/delete modals`.

### Task 4: Connect flow + browser screen

**Files:**
- Modify: `ssh_fm/screens.py`, `ssh_fm/app.py`, `ssh_fm/app.tcss`
- Create: `tests/test_browser.py`, `tests/fakes.py` (`FakeConnection` implementing the Task 2 `Connection` surface with an in-memory tree)

**Interfaces:**
- Consumes: `Connection`, `Entry`, `join_path` (Task 2); picker `Connect` message (Task 3).
- Produces:
  - `ConnectingScreen(ModalScreen[bool])` — animated spinner (`LoadingIndicator`), runs `connection.open_master()` inside `app.suspend()` only when the host uses password auth or master check fails with a prompt need; otherwise silent in a worker. Dismisses `True` on success; on failure the app toasts the error and stays on the picker.
  - `BrowserScreen(Screen)(host: Host, connection: Connection)` with widgets: `OptionList#hosts` (left), `DataTable#files` (center: name, size, perms), `Static#info` (right, file info), `TransferPanel#transfers` (bottom). Reactive `cwd: str` starting `~`. Bindings: `enter` open dir / select, `backspace` up, `/` filter files, `space` toggle multi-select, `.` toggle hidden (shown by default), `escape` back to picker, `r` refresh.
  - Highlighting a row updates `#info` via a worker calling `connection.file_info`; permission-denied or empty dirs render a dim message row instead of raising.
  - Layout below 80 columns hides `#info`.

- [ ] **Step 1: Failing tests:** `test_connect_opens_browser_on_success`, `test_connect_failure_toasts_and_stays`, `test_enter_descends_and_backspace_ascends`, `test_cursor_move_updates_info_panel`, `test_hidden_toggle`, `test_filenames_with_spaces_and_unicode_listed`, `test_listing_error_shows_message_row`, `test_narrow_terminal_hides_info` (`run_test(size=(70, 24))`).
- [ ] **Step 2:** run — FAIL.
- [ ] **Step 3:** Implement. Listing and info calls run in `@work(thread=True)` workers and post results via `call_from_thread`/messages. Selecting another host in `#hosts` closes the old connection and opens the new one.
- [ ] **Step 4:** run — PASS.
- [ ] **Step 5:** Commit `feat: connect flow and 3-column remote browser`.

### Task 5: Transfers, sync, view content, shell/SFTP handoff

**Files:**
- Modify: `ssh_fm/screens.py`, `ssh_fm/app.tcss`
- Create: `tests/test_transfers.py`

**Interfaces:**
- Consumes: `Connection.transfer_cmd`, `run_transfer`, `read_head`, `shell_cmd`, `sftp_cmd` (Task 2); `BrowserScreen` (Task 4).
- Produces:
  - `TransferPanel(Widget)`: `add(label: str) -> int` (returns row id), `update(row_id: int, progress: Progress) -> None`, `finish(row_id: int, ok: bool) -> None`; each row = spinner + `ProgressBar` + speed/ETA; transfers run sequentially from a queue.
  - `PathPromptScreen(ModalScreen[str | None])(title: str, initial: str = "")` for local paths (supports `~`, shows error if upload source missing).
  - `DestinationScreen(ModalScreen[Path | None])` — list: current dir / Desktop / Downloads / custom path.
  - `TextViewScreen(ModalScreen[None])(title: str, text: str)`.
  - Browser bindings: `u` upload (path prompt; multiple paths separated by newline/comma), `d` download selected (multi-select aware; directories use rsync recursively), `v` view content, `s` rsync sync (direction + two paths via prompts), `t` SFTP, `S` ssh shell (the last two via `app.suspend()` then refresh).

- [ ] **Step 1: Failing tests:** `test_download_queue_runs_sequentially_and_reports_progress` (monkeypatch `run_transfer` to emit `Progress(50,...)` then return 0), `test_failed_transfer_marks_row_failed_and_toasts`, `test_view_content_too_large_toasts`, `test_upload_missing_local_path_errors_without_running`, `test_multiselect_download_builds_one_cmd_per_file`, `test_ssh_shell_uses_suspend` (patch `subprocess.run` and `app.suspend`).
- [ ] **Step 2:** run — FAIL.
- [ ] **Step 3:** Implement. Transfers use `@work(thread=True, exclusive=False)` consuming the queue; progress callbacks marshalled with `call_from_thread`.
- [ ] **Step 4:** run — PASS.
- [ ] **Step 5:** Commit `feat: transfer queue with live progress, sync, view, shell/sftp`.

### Task 6: Command palette and polish

**Files:**
- Modify: `ssh_fm/app.py`, `ssh_fm/screens.py`, `ssh_fm/app.tcss`
- Create: `tests/test_palette.py`

**Interfaces:**
- Produces: `SshFmCommands(Provider)` registered via `SshFmApp.COMMANDS`, exposing: New host, Edit host, Delete host, Connect to <each host>, and (in browser) Upload, Download, Sync, SFTP, SSH shell, Toggle hidden files, Refresh. Footer shows live bindings. Toasts for success/failure everywhere that previously `print`ed.

- [ ] **Step 1: Failing tests:** `test_palette_lists_hosts_and_actions`, `test_palette_connect_triggers_connect`, `test_browser_only_commands_hidden_on_picker`.
- [ ] **Step 2:** run — FAIL. **Step 3:** implement. **Step 4:** run full suite `pytest -q` — PASS.
- [ ] **Step 5:** Commit `feat: command palette and polish`.

### Task 7: Install, docs, cleanup

**Files:**
- Modify: `install.sh`, `README.md`, `CHANGELOG.md`, `.gitignore` (add `.superpowers/`)
- Delete: legacy code inside `ssh-fm.py` (already replaced in Task 3)

- [ ] **Step 1:** `install.sh`: copy `ssh-fm.py` + `ssh_fm/` to `~/.local/share/ssh-fm/`, create a venv there (`uv venv` if `uv` exists, else `python3 -m venv`), install `requirements.txt` (`uv pip install` or `pip install`), write launcher `~/bin/ssh-fm` that execs the venv python on `ssh-fm.py`. Keep the existing PATH logic.
- [ ] **Step 2:** Verify: run the installer with `HOME` pointed at a temp dir, then run `~/bin/ssh-fm --help` equivalent (`python -c "import ssh_fm"` via the launcher) — exits 0.
- [ ] **Step 3:** README: new screenshots-free feature list, keybindings table, install notes; CHANGELOG entry `2.0.0`.
- [ ] **Step 4:** Commit `feat: ssh-fm 2.0 textual TUI (install, docs)`.
