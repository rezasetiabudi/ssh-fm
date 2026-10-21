"""Embedded terminal: runs a command on a pty and renders it inside Textual (pyte emulation)"""

import codecs
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import threading
from functools import lru_cache

import pyte
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.app import ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

CLOSE_KEY = "ctrl+right_square_bracket"  # Ctrl+]
KEYS = {
    "enter": "\r", "tab": "\t", "shift+tab": "\x1b[Z", "backspace": "\x7f", "escape": "\x1b", "space": " ",
    "up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D", "home": "\x1b[H", "end": "\x1b[F",
    "pageup": "\x1b[5~", "pagedown": "\x1b[6~", "delete": "\x1b[3~", "insert": "\x1b[2~",
    **{f"f{i}": seq for i, seq in enumerate(["\x1bOP", "\x1bOQ", "\x1bOR", "\x1bOS", "\x1b[15~", "\x1b[17~",
                                            "\x1b[18~", "\x1b[19~", "\x1b[20~", "\x1b[21~", "\x1b[23~", "\x1b[24~"], 1)},
}
NAMES = {"brown": "yellow"}


@lru_cache(maxsize=512)
def _color(name):
    if name == "default":
        return None
    name = NAMES.get(name, name)
    if len(name) == 6 and all(c in "0123456789abcdef" for c in name):
        return "#" + name
    return name.replace("bright", "bright_") if name.startswith("bright") else name


@lru_cache(maxsize=2048)
def _style(fg, bg, bold, italics, underscore, reverse):
    return Style(color=_color(fg), bgcolor=_color(bg), bold=bold, italic=italics, underline=underscore, reverse=reverse)


class _Failed:
    """Stand-in for a process that could not be started."""
    returncode = 127

    def poll(self):
        return self.returncode

    wait = poll


class TerminalView(Widget, can_focus=True):
    DEFAULT_CSS = "TerminalView { background: #1a1b26; }"

    class Exited(Message):
        def __init__(self, returncode):
            super().__init__()
            self.returncode = returncode

    def __init__(self, cmd, **kw):
        super().__init__(**kw)
        self.cmd = cmd
        self.proc = None
        self.fd = None
        self._screen = None
        self._stream = None
        self._lock = threading.Lock()
        self._pending = False

    # --- process ----------------------------------------------------------------
    def check_consume_key(self, key, character):
        return key != CLOSE_KEY  # everything (ctrl+c, ctrl+q, ctrl+p, …) goes to the remote program

    def on_resize(self, event):
        cols, rows = max(event.size.width, 1), max(event.size.height, 1)
        if self.proc is None:
            self._start(cols, rows)
        else:
            with self._lock:
                self._screen.resize(rows, cols)
            self._set_winsize(cols, rows)

    def _set_winsize(self, cols, rows):
        if self.fd is not None:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _start(self, cols, rows):
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)
        master, slave = pty.openpty()
        self.fd = master
        self._set_winsize(cols, rows)
        self._screen.write_process_input = lambda data: os.write(master, data.encode())
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True,
                preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0), close_fds=True)
        except OSError as e:
            os.close(slave)
            self._feed(f"\r\n{self.cmd[0]}: {e.strerror or e}\r\n")
            self.proc = _Failed()
            return self.post_message(self.Exited(127))
        os.close(slave)
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _feed(self, text):
        with self._lock:
            self._stream.feed(text)
        if not self._pending:
            self._pending = True
            try:
                self.app.call_from_thread(self._flush)
            except RuntimeError:
                self._pending = False

    def _flush(self):
        self._pending = False
        self.refresh()

    def _read_loop(self):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        fd = self.fd
        while True:
            try:
                ready, _, _ = select.select([fd], [], [], 0.1)
            except (OSError, ValueError):  # closed by terminate()
                break
            if ready:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                self._feed(decoder.decode(data))
            elif self.proc.poll() is not None:  # exited; backgrounded children may still hold the pty open
                break
        rc = self.proc.wait()
        try:
            self.app.call_from_thread(self.post_message, self.Exited(rc))
        except RuntimeError:
            pass

    def terminate(self):
        proc, fd, self.fd = self.proc, self.fd, None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGHUP)
            except OSError:
                pass
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def on_unmount(self):
        self.terminate()

    # --- input ------------------------------------------------------------------
    def send(self, text):
        if self.fd is not None and self.proc is not None and self.proc.poll() is None:
            os.write(self.fd, text.encode())

    def on_key(self, event: events.Key):
        if event.key == CLOSE_KEY or (self.proc is not None and self.proc.poll() is not None):
            return  # bubbles to the screen
        event.stop()
        event.prevent_default()
        if event.key in KEYS:
            self.send(KEYS[event.key])
        elif event.character:
            self.send(("\x1b" if event.key.startswith("alt+") else "") + event.character)

    def on_paste(self, event: events.Paste):
        event.stop()
        self.send(event.text)

    # --- rendering ----------------------------------------------------------------
    def text(self):
        with self._lock:
            return "\n".join(line.rstrip() for line in self._screen.display) if self._screen else ""

    def render_line(self, y):
        width = self.size.width
        with self._lock:
            if self._screen is None or y >= self._screen.lines:
                return Strip.blank(width)
            line, cur, cols = self._screen.buffer[y], self._screen.cursor, self._screen.columns
            show_cursor = self.has_focus and not cur.hidden and cur.y == y
            segments, run, run_style = [], "", None
            for x in range(min(cols, width)):
                ch = line[x]
                if not ch.data:
                    continue  # right half of a wide character
                reverse = ch.reverse != (show_cursor and cur.x == x)
                style = _style(ch.fg, ch.bg, ch.bold, ch.italics, ch.underscore, reverse)
                if style is not run_style and run:
                    segments.append(Segment(run, run_style))
                    run = ""
                run_style = style
                run += ch.data
            if run:
                segments.append(Segment(run, run_style))
        return Strip(segments).adjust_cell_length(width)


class TerminalScreen(Screen):
    """Full-screen embedded terminal. Dismisses with the process's exit status."""

    def __init__(self, title, cmd):
        super().__init__()
        self.title_text = title
        self.cmd = cmd
        self.finished = None

    def compose(self) -> ComposeResult:
        yield Static(f" {self.title_text}   [dim]Ctrl+] to close[/dim]", id="term-title")
        yield TerminalView(self.cmd, id="term")

    def on_mount(self):
        self.query_one("#term").focus()

    def on_terminal_view_exited(self, event):
        if event.returncode == 0:
            self.dismiss(0)
        else:
            self.finished = event.returncode
            self.query_one("#term-title", Static).update(
                f" {self.title_text}   [b red]exited with status {event.returncode}[/] — press any key to close")

    def on_key(self, event: events.Key):
        if event.key == CLOSE_KEY or self.finished is not None:
            event.stop()
            self.query_one("#term", TerminalView).terminate()
            self.dismiss(self.finished or 0)
