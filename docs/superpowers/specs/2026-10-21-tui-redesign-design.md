# ssh-fm TUI redesign

## Intent
ssh-fm is a Python CLI for managing `~/.ssh/config` hosts and moving files over ssh/scp/rsync. Today it is a numbered-menu script (`ssh-fm.py`, ~950 lines, stdlib only) that feels stiff. The goal is a better-looking layout and a less rigid UX, with animation where it helps. Not a feature expansion.

## Goals
- Full-screen TUI built on **Textual** (Rich for styling). Stays Python; no rewrite to Go.
- Replace every numbered menu with interactive lists, key bindings, modals and a command palette.
- Keep every existing feature: list/add/edit/delete host, SSH connect, browse remote, upload/download (single + multiple), rsync directory sync, terminal SFTP session, view file info and content, `.pem`/`.key` identity files.
- Animation: connect spinner, screen transition, live transfer progress.

## Non-goals
- No new protocols or libraries for transfer (no paramiko/asyncssh). Keep shelling out to `ssh`, `scp`, `rsync`, so `~/.ssh/config` and the user's keys/agent keep working.
- No file preview panel (the user explicitly chose file *info* instead).
- No config format change: `~/.ssh/config` stays the source of truth.

## Anti-goals
- A TUI that is prettier but loses a feature the old menu had.
- Dependencies that make `install.sh` fragile.

## Screens

### 1. Host picker (start screen)
Cards in a grid: name, `user@host:port`, key name (or "password"). Connected-state dot. Keys: `enter` connect, `n` new host, `e` edit, `d` delete (confirm modal), `/` filter, `ctrl+p` palette, `q` quit.
Connecting shows a spinner, then a transition into the browser screen. Failure shows a toast and stays on the picker.

### 2. Browser screen (after connect)
Three columns plus a bottom bar:
- **Left:** host list. Selecting another host reconnects without going back to the picker.
- **Center:** remote directory listing (dirs first, size, permissions). `enter` opens a dir, `backspace` goes up, `/` searches, `space` multi-selects.
- **Right:** file info panel for the highlighted entry: name, size, permissions, owner, modified time, type. Updates as the cursor moves.
- **Bottom:** transfer panel with per-transfer progress bar, speed and ETA; queue when several run.
- Footer shows active key bindings.

Actions on a file/selection: `u` upload, `d` download (destination chosen in a modal: cwd / Desktop / Downloads / custom path with completion), `v` view content (small files, in a modal), `s` rsync sync, `t` open terminal SFTP, `S` open a plain ssh shell. `esc` back to the picker.

### 3. Forms
Add/edit host is a modal form (hostname, port, user, auth: key or password, identity file via the existing `select_identity_file` logic as a list, rename). Validation inline. No sequential `input()` prompts.

## Constraints and decisions
- **Textual + Rich** is a hard new dependency. `install.sh` must install it (use `uv` if present, else `pip --user`; fall back to a venv if the system Python is externally managed). README gets updated.
- Remote listing: `ssh host ls -la` (as today), run in a worker thread so the UI never blocks. File info via `stat`.
- Transfer progress: `rsync --info=progress2` parsed from stdout, `scp` fallback without percentage. *(Builder's call; revisit if rsync is absent on a remote.)*
- Interactive handoffs (ssh shell, SFTP session) use Textual's `App.suspend()` so the terminal is restored cleanly, then return to the app.
- Code layout *(my call)*: split `ssh-fm.py` into a small package (`config.py` for ssh config parse/save, `remote.py` for ssh/scp/rsync wrappers, `app.py` + `screens/` for Textual) with `ssh-fm.py` kept as the thin entry point so `install.sh` and the PATH setup keep working.
- Existing config parsing/saving, identity-file selection and chmod 600 logic is reused, not rewritten.

## Left to the builder
Exact colors/theme (suggest a dark theme with one accent), animation timings, CSS details, key binding conflicts, test strategy for the ssh wrapper (mock subprocess).

## Open assumptions to confirm
- `d` on the picker = delete host, `d` in the browser = download. Context-dependent keys are intentional. *(my guess)*
- Hidden files shown by default, toggle with `.`. *(my guess)*
