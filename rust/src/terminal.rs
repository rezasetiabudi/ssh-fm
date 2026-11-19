//! Embedded terminal: a command on a pty, emulated by vt100 and drawn into a ratatui buffer.
//!
//! Mouse: drag selects text and copies it on release; right click pastes the clipboard.

use std::io::{Read, Write};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use portable_pty::{Child, CommandBuilder, MasterPty, PtySize, native_pty_system};
use ratatui::buffer::Buffer;
use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};

use crate::clipboard::Clipboard;

const DOUBLE_CTRL_C: Duration = Duration::from_millis(600);
const SCROLL_LINES: usize = 3;

#[derive(Debug, PartialEq)]
pub enum TermEvent {
    None,
    /// Ctrl+C pressed twice in quick succession.
    CloseRequested,
    /// Ctrl+] pressed.
    Close,
}

/// A selection in terminal-local cells (row, col), inclusive, anchor first.
#[derive(Clone, Copy, Debug, PartialEq)]
struct Selection {
    anchor: (u16, u16),
    head: (u16, u16),
}

impl Selection {
    fn ordered(&self) -> ((u16, u16), (u16, u16)) {
        if self.anchor <= self.head { (self.anchor, self.head) } else { (self.head, self.anchor) }
    }

    fn contains(&self, row: u16, col: u16) -> bool {
        let (a, b) = self.ordered();
        (row, col) >= a && (row, col) <= b
    }
}

pub struct Terminal {
    parser: Arc<Mutex<vt100::Parser>>,
    writer: Option<Box<dyn Write + Send>>,
    master: Option<Box<dyn MasterPty + Send>>,
    child: Option<Box<dyn Child + Send + Sync>>,
    pub exit: Option<i32>,
    size: (u16, u16),
    selection: Option<Selection>,
    selecting: bool,
    last_ctrl_c: Option<Instant>,
    scrollback: usize,
}

impl Terminal {
    pub fn spawn(cmd: &[String], rows: u16, cols: u16) -> Self {
        let (rows, cols) = (rows.max(1), cols.max(1));
        let parser = Arc::new(Mutex::new(vt100::Parser::new(nz(rows), nz(cols), 5000)));
        let mut term = Terminal {
            parser: parser.clone(),
            writer: None,
            master: None,
            child: None,
            exit: None,
            size: (rows, cols),
            selection: None,
            selecting: false,
            last_ctrl_c: None,
            scrollback: 0,
        };
        let started = (|| -> Result<(), String> {
            let pair = native_pty_system()
                .openpty(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 })
                .map_err(|e| e.to_string())?;
            let mut builder = CommandBuilder::new(&cmd[0]);
            builder.args(&cmd[1..]);
            builder.env("TERM", "xterm-256color");
            builder.env("COLORTERM", "truecolor");
            if let Some(home) = std::env::var_os("HOME") {
                builder.cwd(home);
            }
            let child = pair.slave.spawn_command(builder).map_err(|e| e.to_string())?;
            drop(pair.slave);
            let mut reader = pair.master.try_clone_reader().map_err(|e| e.to_string())?;
            term.writer = Some(pair.master.take_writer().map_err(|e| e.to_string())?);
            term.master = Some(pair.master);
            term.child = Some(child);
            std::thread::spawn(move || {
                let mut buf = [0u8; 16384];
                while let Ok(n) = reader.read(&mut buf) {
                    if n == 0 {
                        break;
                    }
                    if let Ok(mut p) = parser.lock() {
                        p.process(&buf[..n]);
                    }
                }
            });
            Ok(())
        })();
        if let Err(e) = started {
            let msg = format!("\r\n{}: {e}\r\n", cmd[0]);
            term.parser.lock().unwrap().process(msg.as_bytes());
            term.exit = Some(127);
        }
        term
    }

    pub fn resize(&mut self, rows: u16, cols: u16) {
        let (rows, cols) = (rows.max(1), cols.max(1));
        if (rows, cols) == self.size {
            return;
        }
        self.size = (rows, cols);
        self.parser.lock().unwrap().set_size(nz(rows), nz(cols));
        if let Some(m) = &self.master {
            let _ = m.resize(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 });
        }
        self.selection = None;
    }

    /// Exit status once the process has ended (checked without blocking).
    pub fn poll_exit(&mut self) -> Option<i32> {
        if self.exit.is_none() {
            if let Some(Ok(Some(status))) = self.child.as_mut().map(|c| c.try_wait()) {
                self.exit = Some(status.exit_code() as i32);
            }
        }
        self.exit
    }

    pub fn terminate(&mut self) {
        if let Some(c) = self.child.as_mut() {
            let _ = c.kill();
        }
        self.writer = None;
        self.master = None;
    }

    pub fn send(&mut self, bytes: &[u8]) {
        if self.exit.is_some() {
            return;
        }
        if let Some(w) = self.writer.as_mut() {
            let _ = w.write_all(bytes);
            let _ = w.flush();
        }
    }

    pub fn paste(&mut self, text: &str) {
        let bracketed = self.parser.lock().unwrap().screen().bracketed_paste();
        if bracketed {
            self.send(format!("\x1b[200~{text}\x1b[201~").as_bytes());
        } else {
            self.send(text.replace("\r\n", "\r").replace('\n', "\r").as_bytes());
        }
    }

    // --- input ------------------------------------------------------------------
    pub fn handle_key(&mut self, key: KeyEvent) -> TermEvent {
        if key.code == KeyCode::Char(']') && key.modifiers.contains(KeyModifiers::CONTROL) {
            return TermEvent::Close;
        }
        if self.exit.is_some() {
            return TermEvent::None;
        }
        self.selection = None;
        self.scrollback = 0;
        self.parser.lock().unwrap().screen_mut().set_scrollback(0);
        let mut event = TermEvent::None;
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
            let now = Instant::now();
            if self.last_ctrl_c.is_some_and(|t| now.duration_since(t) <= DOUBLE_CTRL_C) {
                self.last_ctrl_c = None;
                return TermEvent::CloseRequested;
            }
            self.last_ctrl_c = Some(now);
            event = TermEvent::None;
        }
        let app_cursor = self.parser.lock().unwrap().screen().application_cursor();
        let bytes = key_to_bytes(key, app_cursor);
        self.send(&bytes);
        event
    }

    /// Handle a mouse event inside `area`. Returns a status message when something was copied / pasted.
    pub fn handle_mouse(&mut self, ev: MouseEvent, area: Rect, clip: &mut Clipboard) -> Option<String> {
        let inside = ev.column >= area.x && ev.row >= area.y && ev.column < area.x + area.width && ev.row < area.y + area.height;
        let cell = (
            ev.row.saturating_sub(area.y).min(self.size.0.saturating_sub(1)),
            ev.column.saturating_sub(area.x).min(self.size.1.saturating_sub(1)),
        );
        match ev.kind {
            MouseEventKind::Down(MouseButton::Left) if inside => {
                self.selection = None;
                self.selecting = true;
                self.selection = Some(Selection { anchor: cell, head: cell });
                None
            }
            MouseEventKind::Drag(MouseButton::Left) if self.selecting => {
                if let Some(s) = self.selection.as_mut() {
                    s.head = cell;
                }
                None
            }
            MouseEventKind::Up(MouseButton::Left) if self.selecting => {
                self.selecting = false;
                let sel = self.selection?;
                if sel.anchor == sel.head {
                    self.selection = None; // a plain click, not a selection
                    return None;
                }
                let text = self.selected_text()?;
                if text.is_empty() {
                    return None;
                }
                let native = clip.set(&text);
                let n = text.chars().count();
                Some(if native { format!("Copied {n} chars") } else { format!("Copied {n} chars (terminal clipboard)") })
            }
            MouseEventKind::Down(MouseButton::Right) if inside => {
                self.selection = None;
                match clip.get() {
                    Some(text) => {
                        self.paste(&text);
                        Some(format!("Pasted {} chars", text.chars().count()))
                    }
                    None => Some("Clipboard is empty".into()),
                }
            }
            MouseEventKind::ScrollUp if inside => {
                self.scroll(SCROLL_LINES as isize);
                None
            }
            MouseEventKind::ScrollDown if inside => {
                self.scroll(-(SCROLL_LINES as isize));
                None
            }
            _ => None,
        }
    }

    fn scroll(&mut self, delta: isize) {
        let mut p = self.parser.lock().unwrap();
        self.scrollback = (self.scrollback as isize + delta).max(0) as usize;
        p.screen_mut().set_scrollback(self.scrollback);
        self.scrollback = p.screen().scrollback(); // clamped to what exists
        self.selection = None;
    }

    pub fn selected_text(&self) -> Option<String> {
        let sel = self.selection?;
        let p = self.parser.lock().unwrap();
        let screen = p.screen();
        let ((r0, c0), (r1, c1)) = sel.ordered();
        let cols = self.size.1;
        let mut lines = vec![];
        for row in r0..=r1 {
            let (from, to) = (if row == r0 { c0 } else { 0 }, if row == r1 { c1 } else { cols - 1 });
            let mut line = String::new();
            for col in from..=to {
                if let Some(cell) = screen.cell(row, col) {
                    if cell.is_wide_continuation() {
                        continue;
                    }
                    line.push_str(if cell.has_contents() { cell.contents() } else { " " });
                }
            }
            lines.push(line.trim_end().to_string());
        }
        Some(lines.join("\n"))
    }

    /// All visible text (used by tests and for diagnostics).
    #[allow(dead_code)]
    pub fn text(&self) -> String {
        self.parser.lock().unwrap().screen().contents()
    }

    // --- rendering ----------------------------------------------------------------
    pub fn render(&self, area: Rect, buf: &mut Buffer, focused: bool) {
        let p = self.parser.lock().unwrap();
        let screen = p.screen();
        let (rows, cols) = (screen.size().0.get(), screen.size().1.get());
        let cursor = (!screen.hide_cursor() && focused && screen.scrollback() == 0).then(|| screen.cursor_position());
        for row in 0..rows.min(area.height) {
            for col in 0..cols.min(area.width) {
                let Some(cell) = screen.cell(row, col) else { continue };
                if cell.is_wide_continuation() {
                    continue;
                }
                let mut style = Style::default().fg(map_color(cell.fgcolor())).bg(map_color(cell.bgcolor()));
                let mut mods = Modifier::empty();
                if cell.bold() { mods |= Modifier::BOLD }
                if cell.italic() { mods |= Modifier::ITALIC }
                if cell.underline() { mods |= Modifier::UNDERLINED }
                let mut reverse = cell.inverse();
                if cursor == Some((row, col)) { reverse = !reverse }
                if self.selection.is_some_and(|s| s.contains(row, col)) { reverse = !reverse }
                if reverse { mods |= Modifier::REVERSED }
                style = style.add_modifier(mods);
                let out = &mut buf[(area.x + col, area.y + row)];
                out.set_style(style);
                out.set_symbol(if cell.has_contents() { cell.contents() } else { " " });
            }
        }
    }
}

impl Drop for Terminal {
    fn drop(&mut self) {
        self.terminate();
    }
}

fn nz(n: u16) -> std::num::NonZeroU16 {
    std::num::NonZeroU16::new(n.max(1)).unwrap()
}

fn map_color(c: vt100::Color) -> Color {
    match c {
        vt100::Color::Default => Color::Reset,
        vt100::Color::Idx(i) => Color::Indexed(i),
        vt100::Color::Rgb(r, g, b) => Color::Rgb(r, g, b),
    }
}

pub fn key_to_bytes(key: KeyEvent, app_cursor: bool) -> Vec<u8> {
    let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
    let alt = key.modifiers.contains(KeyModifiers::ALT);
    let shift = key.modifiers.contains(KeyModifiers::SHIFT);
    let arrow = |c: char| -> Vec<u8> {
        let lead = if app_cursor { "\x1bO" } else { "\x1b[" };
        if ctrl || alt || shift {
            let m = 1 + shift as u8 + 2 * alt as u8 + 4 * ctrl as u8;
            format!("\x1b[1;{m}{c}").into_bytes()
        } else {
            format!("{lead}{c}").into_bytes()
        }
    };
    let bytes: Vec<u8> = match key.code {
        KeyCode::Char(c) if ctrl && c.is_ascii_alphabetic() => vec![c.to_ascii_lowercase() as u8 - b'a' + 1],
        KeyCode::Char(' ') if ctrl => vec![0],
        KeyCode::Char('[') if ctrl => vec![0x1b],
        KeyCode::Char('\\') if ctrl => vec![0x1c],
        KeyCode::Char(c) => c.to_string().into_bytes(),
        KeyCode::Enter => b"\r".to_vec(),
        KeyCode::Tab => b"\t".to_vec(),
        KeyCode::BackTab => b"\x1b[Z".to_vec(),
        KeyCode::Backspace => vec![0x7f],
        KeyCode::Esc => vec![0x1b],
        KeyCode::Up => arrow('A'),
        KeyCode::Down => arrow('B'),
        KeyCode::Right => arrow('C'),
        KeyCode::Left => arrow('D'),
        KeyCode::Home => b"\x1b[H".to_vec(),
        KeyCode::End => b"\x1b[F".to_vec(),
        KeyCode::PageUp => b"\x1b[5~".to_vec(),
        KeyCode::PageDown => b"\x1b[6~".to_vec(),
        KeyCode::Delete => b"\x1b[3~".to_vec(),
        KeyCode::Insert => b"\x1b[2~".to_vec(),
        KeyCode::F(n) => {
            let seq = match n {
                1 => "\x1bOP", 2 => "\x1bOQ", 3 => "\x1bOR", 4 => "\x1bOS",
                5 => "\x1b[15~", 6 => "\x1b[17~", 7 => "\x1b[18~", 8 => "\x1b[19~",
                9 => "\x1b[20~", 10 => "\x1b[21~", 11 => "\x1b[23~", 12 => "\x1b[24~",
                _ => "",
            };
            seq.as_bytes().to_vec()
        }
        _ => vec![],
    };
    let is_plain_char = matches!(key.code, KeyCode::Char(_)) && !ctrl;
    if alt && is_plain_char && !bytes.is_empty() {
        let mut v = vec![0x1b];
        v.extend(bytes);
        return v;
    }
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;

    fn k(code: KeyCode, m: KeyModifiers) -> KeyEvent {
        KeyEvent::new(code, m)
    }

    #[test]
    fn keys_translate() {
        assert_eq!(key_to_bytes(k(KeyCode::Char('c'), KeyModifiers::CONTROL), false), vec![3]);
        assert_eq!(key_to_bytes(k(KeyCode::Char('x'), KeyModifiers::ALT), false), b"\x1bx".to_vec());
        assert_eq!(key_to_bytes(k(KeyCode::Up, KeyModifiers::NONE), false), b"\x1b[A".to_vec());
        assert_eq!(key_to_bytes(k(KeyCode::Up, KeyModifiers::NONE), true), b"\x1bOA".to_vec());
        assert_eq!(key_to_bytes(k(KeyCode::Enter, KeyModifiers::NONE), false), b"\r".to_vec());
        assert_eq!(key_to_bytes(k(KeyCode::Char('é'), KeyModifiers::NONE), false), "é".as_bytes().to_vec());
    }

    #[test]
    fn selection_ordering() {
        let s = Selection { anchor: (2, 5), head: (1, 3) };
        assert_eq!(s.ordered(), ((1, 3), (2, 5)));
        assert!(s.contains(1, 10) && s.contains(2, 0) && !s.contains(0, 0) && !s.contains(2, 6));
    }

    fn run_echo(text: &str) -> Terminal {
        let mut t = Terminal::spawn(&["sh".into(), "-c".into(), format!("printf '%s' '{text}'; sleep 1")], 5, 40);
        for _ in 0..100 {
            if t.text().contains(text) {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        t
    }

    #[test]
    fn pty_output_and_selection_copy() {
        let mut t = run_echo("hello world");
        assert!(t.text().contains("hello world"));
        let area = Rect::new(0, 0, 40, 5);
        let mut clip = Clipboard::new();
        let ev = |kind, col| MouseEvent { kind, column: col, row: 0, modifiers: KeyModifiers::NONE };
        t.handle_mouse(ev(MouseEventKind::Down(MouseButton::Left), 0), area, &mut clip);
        t.handle_mouse(ev(MouseEventKind::Drag(MouseButton::Left), 4), area, &mut clip);
        assert_eq!(t.selected_text().as_deref(), Some("hello"));
        let msg = t.handle_mouse(ev(MouseEventKind::Up(MouseButton::Left), 4), area, &mut clip);
        assert!(msg.unwrap().starts_with("Copied 5"));
        t.terminate();
    }

    #[test]
    fn right_click_pastes_into_process() {
        let mut t = Terminal::spawn(&["cat".into()], 5, 40);
        let area = Rect::new(0, 0, 40, 5);
        let mut clip = Clipboard::new();
        if clip.inner_available() {
            clip.set("pasted-text\n");
            let ev = MouseEvent { kind: MouseEventKind::Down(MouseButton::Right), column: 1, row: 1, modifiers: KeyModifiers::NONE };
            assert!(t.handle_mouse(ev, area, &mut clip).unwrap().starts_with("Pasted"));
            for _ in 0..100 {
                if t.text().contains("pasted-text") {
                    break;
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            assert!(t.text().contains("pasted-text"));
        }
        t.terminate();
    }

    #[test]
    fn failed_spawn_reports_127() {
        let t = Terminal::spawn(&["/nonexistent/definitely-not-here".into()], 5, 40);
        assert_eq!(t.exit, Some(127));
    }

    #[test]
    fn exit_status_detected() {
        let mut t = Terminal::spawn(&["sh".into(), "-c".into(), "exit 3".into()], 5, 40);
        for _ in 0..100 {
            if t.poll_exit().is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        assert_eq!(t.exit, Some(3));
    }
}
