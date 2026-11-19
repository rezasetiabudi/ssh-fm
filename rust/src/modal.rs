//! Modal dialogs: forms, confirmations, choices and a text viewer.

use ratatui::buffer::Buffer;
use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Paragraph, Widget, Wrap};

pub const ACCENT: Color = Color::Rgb(0x7a, 0xa2, 0xf7);
pub const DIM: Color = Color::Rgb(0x6b, 0x72, 0x8e);
pub const ERR: Color = Color::Rgb(0xf7, 0x76, 0x8e);
pub const OK: Color = Color::Rgb(0x9e, 0xce, 0x6a);

/// A transfer waiting to be queued.
#[derive(Clone, Debug)]
pub struct TransferItem {
    pub label: String,
    pub up: bool,
    pub local: String,
    pub remote: String,
    /// The destination name already exists.
    pub exists: bool,
}

#[derive(Clone, Debug)]
pub enum FormKind {
    HostNew,
    HostEdit(String),
    Mkdir,
    Rename(String),
    Chmod(Vec<String>),
    Upload,
    DownloadTo(Vec<String>),
    Sync,
}

#[derive(Clone, Debug)]
pub enum ConfirmKind {
    DeleteHost(String),
    DeleteRemote(Vec<String>),
}

pub enum Modal {
    Confirm { msg: String, kind: ConfirmKind },
    Form(Form),
    Overwrite { items: Vec<TransferItem>, sel: usize },
    Text { title: String, body: String, scroll: u16 },
    Palette { query: String, sel: usize },
    Import { text: String },
    Message { text: String },
}

#[derive(Clone)]
pub enum FieldKind {
    Text,
    Cycle(Vec<String>),
}

#[derive(Clone)]
pub struct Field {
    pub label: String,
    pub value: String,
    pub cursor: usize,
    pub kind: FieldKind,
    pub hint: String,
}

impl Field {
    pub fn text(label: &str, value: &str, hint: &str) -> Self {
        Field { label: label.into(), value: value.into(), cursor: value.chars().count(), kind: FieldKind::Text, hint: hint.into() }
    }

    pub fn cycle(label: &str, options: Vec<String>, current: &str) -> Self {
        let value = if options.iter().any(|o| o == current) { current } else { &options[0] };
        Field { label: label.into(), value: value.into(), cursor: 0, kind: FieldKind::Cycle(options), hint: String::new() }
    }

    fn byte_idx(&self) -> usize {
        self.value.char_indices().nth(self.cursor).map_or(self.value.len(), |(i, _)| i)
    }

    pub fn insert(&mut self, text: &str) {
        let text: String = text.chars().filter(|c| !c.is_control()).collect();
        let i = self.byte_idx();
        self.value.insert_str(i, &text);
        self.cursor += text.chars().count();
    }

    /// Edit with a key. Returns true if the key was consumed.
    pub fn key(&mut self, key: KeyEvent) -> bool {
        match &self.kind {
            FieldKind::Cycle(opts) => {
                let n = opts.len();
                let cur = opts.iter().position(|o| *o == self.value).unwrap_or(0);
                let next = match key.code {
                    KeyCode::Left => (cur + n - 1) % n,
                    KeyCode::Right | KeyCode::Char(' ') => (cur + 1) % n,
                    _ => return false,
                };
                self.value = opts[next].clone();
                true
            }
            FieldKind::Text => {
                let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
                match key.code {
                    KeyCode::Char('u') if ctrl => {
                        let i = self.byte_idx();
                        self.value.drain(..i);
                        self.cursor = 0;
                    }
                    KeyCode::Char('a') if ctrl => self.cursor = 0,
                    KeyCode::Char('e') if ctrl => self.cursor = self.value.chars().count(),
                    KeyCode::Char(c) if !ctrl && !key.modifiers.contains(KeyModifiers::ALT) => self.insert(&c.to_string()),
                    KeyCode::Backspace if self.cursor > 0 => {
                        self.cursor -= 1;
                        let i = self.byte_idx();
                        self.value.remove(i);
                    }
                    KeyCode::Delete if self.cursor < self.value.chars().count() => {
                        let i = self.byte_idx();
                        self.value.remove(i);
                    }
                    KeyCode::Left => self.cursor = self.cursor.saturating_sub(1),
                    KeyCode::Right => self.cursor = (self.cursor + 1).min(self.value.chars().count()),
                    KeyCode::Home => self.cursor = 0,
                    KeyCode::End => self.cursor = self.value.chars().count(),
                    _ => return false,
                }
                true
            }
        }
    }
}

pub struct Form {
    pub title: String,
    pub hint: String,
    pub fields: Vec<Field>,
    pub focus: usize,
    pub kind: FormKind,
    pub error: String,
}

impl Form {
    pub fn new(title: &str, hint: &str, kind: FormKind, fields: Vec<Field>) -> Self {
        Form { title: title.into(), hint: hint.into(), fields, focus: 0, kind, error: String::new() }
    }

    pub fn value(&self, label: &str) -> String {
        self.fields.iter().find(|f| f.label == label).map(|f| f.value.trim().to_string()).unwrap_or_default()
    }

    pub fn next(&mut self, delta: isize) {
        let n = self.fields.len() as isize;
        self.focus = ((self.focus as isize + delta).rem_euclid(n)) as usize;
    }
}

pub fn centered(area: Rect, width: u16, height: u16) -> Rect {
    let w = width.min(area.width);
    let h = height.min(area.height);
    Rect::new(area.x + (area.width - w) / 2, area.y + (area.height - h) / 2, w, h)
}

pub fn dialog_block(title: &str) -> Block<'_> {
    Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(ACCENT))
        .title(Span::styled(format!(" {title} "), Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)))
}

pub fn render_form(form: &Form, area: Rect, buf: &mut Buffer) {
    let height = (form.fields.len() as u16 * 2 + 5 + (!form.hint.is_empty()) as u16).min(area.height);
    let r = centered(area, 64, height);
    Clear.render(r, buf);
    let block = dialog_block(&form.title);
    let inner = block.inner(r);
    block.render(r, buf);
    let mut lines: Vec<Line> = vec![];
    if !form.hint.is_empty() {
        lines.push(Line::styled(form.hint.clone(), Style::default().fg(DIM)));
    }
    for (i, f) in form.fields.iter().enumerate() {
        let focused = i == form.focus;
        lines.push(Line::styled(f.label.clone(), Style::default().fg(if focused { ACCENT } else { DIM })));
        let shown = match f.kind {
            FieldKind::Cycle(_) => format!("◀ {} ▶", f.value),
            FieldKind::Text if f.value.is_empty() && !focused => f.hint.clone(),
            FieldKind::Text => f.value.clone(),
        };
        let style = if f.value.is_empty() && matches!(f.kind, FieldKind::Text) {
            Style::default().fg(DIM)
        } else {
            Style::default()
        };
        lines.push(Line::styled(format!("{shown} "), if focused { style.add_modifier(Modifier::UNDERLINED) } else { style }));
    }
    lines.push(Line::raw(""));
    if form.error.is_empty() {
        lines.push(Line::styled("Enter: OK   Tab/↑↓: field   ←→: change   Esc: cancel", Style::default().fg(DIM)));
    } else {
        lines.push(Line::styled(form.error.clone(), Style::default().fg(ERR)));
    }
    Paragraph::new(lines).render(inner, buf);
    // text cursor
    let hint_rows = (!form.hint.is_empty()) as u16;
    let f = &form.fields[form.focus];
    if matches!(f.kind, FieldKind::Text) {
        let (x, y) = (inner.x + f.cursor as u16, inner.y + hint_rows + form.focus as u16 * 2 + 1);
        if x < inner.x + inner.width && y < inner.y + inner.height {
            buf[(x, y)].set_style(Style::default().add_modifier(Modifier::REVERSED));
        }
    }
}

pub fn render_confirm(msg: &str, area: Rect, buf: &mut Buffer) {
    let r = centered(area, 60, 6);
    Clear.render(r, buf);
    let block = dialog_block("Confirm");
    let inner = block.inner(r);
    block.render(r, buf);
    Paragraph::new(vec![
        Line::raw(msg.to_string()),
        Line::raw(""),
        Line::styled("y / Enter: yes      n / Esc: no", Style::default().fg(DIM)),
    ])
    .wrap(Wrap { trim: false })
    .render(inner, buf);
}

pub fn render_overwrite(items: &[TransferItem], sel: usize, area: Rect, buf: &mut Buffer) {
    let clashes: Vec<&str> = items.iter().filter(|i| i.exists).map(|i| i.label.as_str()).collect();
    let r = centered(area, 60, 10 + clashes.len().min(5) as u16);
    Clear.render(r, buf);
    let block = dialog_block("Already exists");
    let inner = block.inner(r);
    block.render(r, buf);
    let mut lines = vec![Line::styled(format!("{} item(s) already exist at the destination", clashes.len()), Style::default().add_modifier(Modifier::BOLD))];
    for c in clashes.iter().take(5) {
        lines.push(Line::styled(format!("  {c}"), Style::default().fg(DIM)));
    }
    lines.push(Line::raw(""));
    for (i, name) in ["Overwrite", "Skip existing", "Cancel"].iter().enumerate() {
        let style = if i == sel { Style::default().bg(ACCENT).fg(Color::White) } else { Style::default() };
        lines.push(Line::styled(format!(" {name} "), style));
    }
    Paragraph::new(lines).render(inner, buf);
}

pub fn render_text(title: &str, body: &str, scroll: u16, area: Rect, buf: &mut Buffer) {
    let r = centered(area, area.width.saturating_sub(8), area.height.saturating_sub(4));
    Clear.render(r, buf);
    let block = dialog_block(title);
    let inner = block.inner(r);
    block.render(r, buf);
    Paragraph::new(body.to_string()).scroll((scroll, 0)).render(inner, buf);
    let hint = Rect::new(r.x + 2, r.y + r.height - 1, r.width.saturating_sub(4), 1);
    Line::styled(" ↑↓ scroll · Esc close ", Style::default().fg(DIM)).render(hint, buf);
}

pub fn render_message(text: &str, area: Rect, buf: &mut Buffer) {
    let r = centered(area, 50, 5);
    Clear.render(r, buf);
    let block = dialog_block("ssh-fm");
    let inner = block.inner(r);
    block.render(r, buf);
    Paragraph::new(vec![Line::raw(""), Line::raw(text.to_string()).centered()]).render(inner, buf);
}

pub fn split_vertical(area: Rect, top_pct: u16) -> (Rect, Rect) {
    let [a, b] = Layout::vertical([Constraint::Percentage(top_pct), Constraint::Percentage(100 - top_pct)]).areas(area);
    (a, b)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(c: KeyCode) -> KeyEvent {
        KeyEvent::new(c, KeyModifiers::NONE)
    }

    #[test]
    fn field_editing() {
        let mut f = Field::text("x", "héllo", "");
        assert_eq!(f.cursor, 5);
        f.key(key(KeyCode::Backspace));
        f.key(key(KeyCode::Left));
        f.key(key(KeyCode::Char('Z')));
        assert_eq!(f.value, "hélZl");
        f.key(key(KeyCode::Home));
        f.key(key(KeyCode::Delete));
        assert_eq!(f.value, "élZl");
        f.insert("a\nb");
        assert_eq!(f.value, "abélZl");
    }

    #[test]
    fn cycle_wraps() {
        let mut f = Field::cycle("a", vec!["one".into(), "two".into()], "one");
        f.key(key(KeyCode::Right));
        assert_eq!(f.value, "two");
        f.key(key(KeyCode::Right));
        assert_eq!(f.value, "one");
        f.key(key(KeyCode::Left));
        assert_eq!(f.value, "two");
    }

    #[test]
    fn form_focus_wraps() {
        let mut form = Form::new("t", "", FormKind::Mkdir, vec![Field::text("a", "", ""), Field::text("b", "", "")]);
        form.next(-1);
        assert_eq!(form.focus, 1);
        form.next(1);
        assert_eq!(form.focus, 0);
    }
}
