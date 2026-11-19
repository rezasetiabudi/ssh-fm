# ssh-fm (Rust)

Rewrite of ssh-fm in Rust with [ratatui](https://ratatui.rs). Same idea as the Python version: host cards → 3-pane SFTP browser with rsync transfers, embedded ssh/sftp terminal, command palette. Hosts live in `~/.ssh/config`.

Needs `ssh`, `rsync`, `sftp` on the machine (same as before). Single binary, no Python/venv.

## Install

```bash
curl -sSf https://raw.githubusercontent.com/rezasetiabudi/ssh-fm/main/rust/install.sh | sh
```

Downloads the prebuilt binary for your OS/arch (Linux and macOS, x86_64 and arm64) into `~/.local/bin`, verifying its checksum. No Rust needed.

From source instead:

```bash
cargo install --git https://github.com/rezasetiabudi/ssh-fm --locked ssh-fm   # or: cd rust && cargo build --release
```

## Releasing (maintainers)

`git tag v3.0.0 && git push --tags` — GitHub Actions tests, builds the four targets and attaches the tarballs + checksums to the release.

## Terminal: mouse copy / paste

- **Drag with the left button** to select text in any embedded terminal (ssh shell, sftp, password prompts). The selection is **copied automatically** on release.
- **Right click** pastes the clipboard into the terminal (bracketed paste when the remote program asks for it). Right click also pastes into any text field / import dialog.
- Copy goes to the system clipboard and is also sent as OSC 52, so it works over ssh/tmux in terminals that support it.
- Mouse wheel scrolls the terminal's scrollback; typing jumps back to the bottom.
- `Ctrl+]` or `Ctrl+C` twice closes the terminal.

## New compared to the Python version

- **Jump host** (`ProxyJump`) and **port forwards** (`LocalForward`) per host, stored in `~/.ssh/config` and shown on the host card / info panel.
- **Copy SSH key to server** (`alt+k`, runs `ssh-copy-id` in the embedded terminal).
- **Duplicate host** (`alt+y`) and **Reconnect** (`alt+c`).
- Reuses an already-open ssh master instead of reconnecting.
- Mouse everywhere: click rows, double-click to open/connect, wheel to scroll, **drag & drop between the remote and local panes** in split view.
- Fuzzy command palette.

## Keys

Same as the Python version (see the top-level README): `alt+n/e/d/i` hosts, `alt+u/d/v/s/t/f/h/x/n/r/m` in the browser, `alt+p` palette, plain letters quick-select, `/` filter, `space` mark, `Tab` switch pane in split view.
