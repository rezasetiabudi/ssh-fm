//! Drawing.

use ratatui::Frame;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Paragraph, Row, Table, Widget};

use crate::app::{App, Purpose, Screen};
use crate::browser::{Browser, Pane, RecState};
use crate::config::parse_ssh_config;
use crate::modal::*;
use crate::remote::human;

const CURSOR_FOCUS: Color = Color::Rgb(0x3d, 0x59, 0xa1);
const CURSOR_DIM: Color = Color::Rgb(0x29, 0x35, 0x59);

fn dim() -> Style {
    Style::default().fg(DIM)
}

fn hints(items: &[(&str, &str)]) -> Line<'static> {
    let mut spans = vec![];
    for (k, label) in items {
        spans.push(Span::styled(format!(" {k}"), Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)));
        spans.push(Span::styled(format!(" {label} "), dim()));
    }
    Line::from(spans)
}

fn pane_block(title: String, focused: bool) -> Block<'static> {
    let color = if focused { ACCENT } else { DIM };
    Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(color))
        .title(Span::styled(title, Style::default().fg(color).add_modifier(Modifier::BOLD)))
}

pub fn draw(app: &mut App, f: &mut Frame) {
    let area = f.area();
    let [header, body, footer] = Layout::vertical([Constraint::Length(1), Constraint::Min(1), Constraint::Length(1)]).areas(area);

    // header
    let mut spans = vec![Span::styled(" ssh-fm ", Style::default().bg(ACCENT).fg(Color::Black).add_modifier(Modifier::BOLD))];
    if let Some(ov) = &app.overlay {
        spans.push(Span::raw(format!("  {}", ov.title)));
        let status = match ov.term.exit {
            Some(rc) if rc != 0 => Span::styled(format!("   exited with status {rc} — press any key to close"), Style::default().fg(ERR).add_modifier(Modifier::BOLD)),
            Some(_) => Span::styled("   finished — press any key to close", dim()),
            None => Span::styled("   Ctrl+] or Ctrl+C twice to close · drag to copy · right-click to paste", dim()),
        };
        spans.push(status);
    } else if let (Screen::Browser, Some(b)) = (app.screen, &app.browser) {
        let user = if b.host.user.is_empty() { String::new() } else { format!("{}@", b.host.user) };
        spans.push(Span::raw(format!("  {user}{}:{}  ", if b.host.hostname.is_empty() { &b.host.name } else { &b.host.hostname }, b.host.port)));
        spans.push(Span::styled(b.cwd.clone(), Style::default().fg(ACCENT)));
        if !b.host.proxy_jump.is_empty() {
            spans.push(Span::styled(format!("  via {}", b.host.proxy_jump), dim()));
        }
    } else {
        spans.push(Span::styled("  SSH connection manager & SFTP browser", dim()));
    }
    f.render_widget(Paragraph::new(Line::from(spans)), header);

    // body
    if app.overlay.is_some() {
        let ov = app.overlay.as_mut().unwrap();
        ov.term.resize(body.height, body.width);
        ov.term.render(body, f.buffer_mut(), true);
    } else if app.screen == Screen::Picker {
        draw_picker(app, f, body);
    } else if app.browser.is_some() {
        draw_browser(app, f, body);
    }

    // footer
    let line = match (&app.toast, app.overlay.is_some()) {
        (Some((msg, err, _)), _) => Line::styled(format!(" {msg}"), Style::default().fg(if *err { ERR } else { OK }).add_modifier(Modifier::BOLD)),
        (None, true) => Line::raw(""),
        (None, false) if app.screen == Screen::Picker => hints(&[
            ("Enter", "Connect"),
            ("alt+n", "New"),
            ("alt+e", "Edit"),
            ("alt+d", "Delete"),
            ("alt+i", "Import"),
            ("/", "Filter"),
            ("alt+p", "Palette"),
            ("alt+q", "Quit"),
        ]),
        (None, false) => match app.browser.as_ref() {
            Some(b) if b.console.is_some() => hints(&[("Ctrl+]", "close"), ("Ctrl+C ×2", "close"), ("drag", "copy"), ("right-click", "paste")]),
            _ => hints(&[
                ("Enter", "Open"),
                ("space", "Select"),
                ("alt+u", "Upload"),
                ("alt+d", "Download"),
                ("alt+v", "View"),
                ("alt+t", "Split"),
                ("alt+h", "Shell"),
                ("alt+x", "Delete"),
                ("alt+p", "Palette"),
                ("esc", "Hosts"),
            ]),
        },
    };
    f.render_widget(Paragraph::new(line), footer);

    draw_modal(app, f, area);
}

// --- host picker ----------------------------------------------------------------------------
fn draw_picker(app: &mut App, f: &mut Frame, area: Rect) {
    let mut area = area;
    if app.picker.filtering || !app.picker.filter.is_empty() {
        let [bar, rest] = Layout::vertical([Constraint::Length(1), Constraint::Min(1)]).areas(area);
        let cursor = if app.picker.filtering { "▏" } else { "" };
        f.render_widget(Paragraph::new(Line::from(vec![Span::styled(" / ", Style::default().fg(ACCENT)), Span::raw(format!("{}{cursor}", app.picker.filter))])), bar);
        area = rest;
    }
    let visible = app.visible_hosts();
    app.picker.cards.clear();
    if app.config.hosts.is_empty() {
        let msg = Paragraph::new(vec![
            Line::raw(""),
            Line::raw("No hosts yet").centered(),
            Line::styled("press alt+n to add one, or alt+i to import from an ssh config", dim()).centered(),
        ]);
        return f.render_widget(msg, area);
    }
    let card_h = 5u16;
    let rows_visible = (area.height / card_h).max(1) as usize;
    let cursor_row = app.picker.cursor / 2;
    let first_row = cursor_row.saturating_sub(rows_visible - 1);
    let half = area.width / 2;
    for (pos, &host_idx) in visible.iter().enumerate() {
        let row = pos / 2;
        if row < first_row || row >= first_row + rows_visible {
            continue;
        }
        let rect = Rect::new(area.x + (pos % 2) as u16 * half, area.y + (row - first_row) as u16 * card_h, if pos % 2 == 1 { area.width - half } else { half }, card_h);
        let h = &app.config.hosts[host_idx];
        let focused = pos == app.picker.cursor;
        let mut third = format!("{} {}", if h.password_auth { "🔒" } else { "🔑" }, h.auth_label());
        if !h.proxy_jump.is_empty() {
            third.push_str(&format!("  ↪ {}", h.proxy_jump));
        }
        if !h.local_forwards.is_empty() {
            third.push_str(&format!("  ⇄ {}", h.local_forwards.len()));
        }
        let block = pane_block(String::new(), focused);
        let inner = block.inner(rect);
        f.render_widget(block, rect);
        f.render_widget(
            Paragraph::new(vec![
                Line::styled(format!(" {}", h.name), Style::default().add_modifier(Modifier::BOLD)),
                Line::styled(format!(" {}", h.target()), dim()),
                Line::raw(format!(" {third}")),
            ]),
            inner,
        );
        app.picker.cards.push((rect, pos));
    }
}

// --- browser --------------------------------------------------------------------------------
fn entry_rows(b: &Browser) -> Vec<Row<'static>> {
    b.visible()
        .into_iter()
        .map(|e| {
            let mark = if b.selected.contains(&e.name) { "● " } else { "  " };
            let name = if e.is_dir && e.name != ".." { format!("{}/", e.name) } else if e.is_link { format!("{} →", e.name) } else { e.name.clone() };
            let style = if e.is_dir { Style::default().fg(ACCENT).add_modifier(Modifier::BOLD) } else if e.is_link { Style::default().fg(Color::Cyan) } else { Style::default() };
            let size = if e.is_dir { String::new() } else { human(e.size) };
            Row::new(vec![format!("{mark}{name}"), size, e.mtime]).style(style)
        })
        .collect()
}

fn local_rows(b: &Browser) -> Vec<Row<'static>> {
    b.visible_local()
        .into_iter()
        .map(|e| {
            let mark = if b.local_selected.contains(&e.name) { "● " } else { "  " };
            let name = if e.is_dir && e.name != ".." { format!("{}/", e.name) } else { e.name.clone() };
            let style = if e.is_dir { Style::default().fg(ACCENT).add_modifier(Modifier::BOLD) } else { Style::default() };
            Row::new(vec![format!("{mark}{name}"), if e.is_dir { String::new() } else { human(e.size) }, String::new()]).style(style)
        })
        .collect()
}

fn render_table(f: &mut Frame, area: Rect, rows: Vec<Row<'static>>, title: String, state: &mut ratatui::widgets::TableState, cursor: usize, focused: bool, header: [&'static str; 3]) {
    state.select(Some(cursor));
    let table = Table::new(rows, [Constraint::Min(10), Constraint::Length(8), Constraint::Length(13)])
        .header(Row::new(header.to_vec()).style(dim()))
        .block(pane_block(title, focused))
        .row_highlight_style(Style::default().bg(if focused { CURSOR_FOCUS } else { CURSOR_DIM }).fg(Color::White));
    f.render_stateful_widget(table, area, state);
}

fn draw_browser(app: &mut App, f: &mut Frame, area: Rect) {
    let host_names: Vec<String> = app.config.hosts.iter().map(|h| h.name.clone()).collect();
    let b = app.browser.as_mut().unwrap();

    if b.console.is_some() {
        return draw_console(b, f, area);
    }

    let transfer_h = if b.records.is_empty() { 0 } else { (b.records.len().min(4) + 2) as u16 };
    let [main, transfers] = Layout::vertical([Constraint::Min(5), Constraint::Length(transfer_h)]).areas(area);
    let [hosts, files, info] = Layout::horizontal([Constraint::Length(18), Constraint::Percentage(55), Constraint::Min(20)]).areas(main);

    // hosts column
    b.hosts_area = hosts;
    let lines: Vec<Line> = host_names
        .iter()
        .map(|n| {
            if *n == b.host.name {
                Line::styled(format!("▶ {n}"), Style::default().fg(ACCENT).add_modifier(Modifier::BOLD))
            } else {
                Line::styled(format!("  {n}"), dim())
            }
        })
        .collect();
    f.render_widget(Paragraph::new(lines).block(pane_block(" Hosts ".into(), false)), hosts);

    // files
    let (remote_area, local_area) = if b.split {
        let (a, c) = split_vertical(files, 55);
        (a, Some(c))
    } else {
        (files, None)
    };
    b.remote_area = remote_area;
    let mut title = format!(" {} ", b.cwd);
    if !b.filter.is_empty() || b.filtering {
        title.push_str(&format!("/{}{} ", b.filter, if b.filtering { "▏" } else { "" }));
    }
    if !b.selected.is_empty() {
        title.push_str(&format!("[{} selected] ", b.selected.len()));
    }
    if b.loading {
        title.push_str("… ");
    }
    let remote_focused = b.focus == Pane::Remote;
    if !b.error.is_empty() {
        let p = Paragraph::new(b.error.clone()).style(Style::default().fg(ERR)).wrap(ratatui::widgets::Wrap { trim: true }).block(pane_block(title, remote_focused));
        f.render_widget(p, remote_area);
    } else {
        let rows = entry_rows(b);
        let cursor = b.cursor;
        render_table(f, remote_area, rows, title, &mut b.state, cursor, remote_focused, ["Name", "Size", "Modified"]);
    }
    if let Some(la) = local_area {
        b.local_area = la;
        let rows = local_rows(b);
        let mut title = format!(" local: {} ", b.local_cwd.display());
        if !b.local_selected.is_empty() {
            title.push_str(&format!("[{} selected] ", b.local_selected.len()));
        }
        let cursor = b.local_cursor;
        if b.local_error.is_empty() {
            render_table(f, la, rows, title, &mut b.local_state, cursor, !remote_focused, ["Name", "Size", ""]);
        } else {
            f.render_widget(Paragraph::new(b.local_error.clone()).style(Style::default().fg(ERR)).block(pane_block(title, !remote_focused)), la);
        }
    }

    // info
    let mut lines: Vec<Line> = vec![];
    if let Some(e) = b.current().filter(|e| e.name != "..") {
        lines.push(Line::styled(e.name.clone(), Style::default().add_modifier(Modifier::BOLD)));
        lines.push(Line::raw(""));
        let rows: Vec<(String, String)> = if b.info.is_empty() {
            vec![("Size".into(), human(e.size)), ("Perms".into(), e.perms.clone()), ("Owner".into(), e.owner.clone()), ("Group".into(), e.group.clone()), ("Modified".into(), e.mtime.clone())]
        } else {
            b.info.clone()
        };
        for (k, v) in rows.into_iter().filter(|(_, v)| !v.is_empty()) {
            lines.push(Line::from(vec![Span::styled(format!("{k:<9}"), dim()), Span::raw(v)]));
        }
    }
    if !b.host.local_forwards.is_empty() {
        lines.push(Line::raw(""));
        lines.push(Line::styled("Port forwards", Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)));
        for fw in &b.host.local_forwards {
            lines.push(Line::raw(format!("  localhost:{}", fw.replace(' ', " → "))));
        }
    }
    f.render_widget(Paragraph::new(lines).wrap(ratatui::widgets::Wrap { trim: false }).block(pane_block(" Info ".into(), false)), info);

    // transfers
    if transfer_h > 0 {
        let n = (transfer_h - 2) as usize;
        let start = b.records.len().saturating_sub(n);
        let lines: Vec<Line> = b.records[start..]
            .iter()
            .map(|r| {
                let label = format!("{:<28.28}", r.label);
                match &r.state {
                    RecState::Queued => Line::styled(format!(" {label} queued"), dim()),
                    RecState::Done(true) => Line::styled(format!(" {label} ✔ done"), Style::default().fg(OK)),
                    RecState::Done(false) => Line::styled(format!(" {label} ✘ failed"), Style::default().fg(ERR)),
                    RecState::Running(p) => {
                        let filled = (p.percent as usize * 20) / 100;
                        Line::from(vec![
                            Span::raw(format!(" {label} ")),
                            Span::styled("█".repeat(filled), Style::default().fg(ACCENT)),
                            Span::styled("░".repeat(20 - filled), dim()),
                            Span::raw(format!(" {:>3}% {} ETA {}", p.percent, p.speed, p.eta)),
                        ])
                    }
                }
            })
            .collect();
        f.render_widget(Paragraph::new(lines).block(pane_block(" Transfers ".into(), false)), transfers);
    }
}

fn draw_console(b: &mut Browser, f: &mut Frame, area: Rect) {
    let [info, console] = Layout::horizontal([Constraint::Ratio(1, 3), Constraint::Ratio(2, 3)]).areas(area);
    let mut lines: Vec<Line> = vec![];
    let section = |lines: &mut Vec<Line>, title: &str, rows: Vec<(&str, String)>| {
        if !lines.is_empty() {
            lines.push(Line::raw(""));
        }
        lines.push(Line::styled(title.to_string(), Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)));
        for (k, v) in rows {
            lines.push(Line::from(vec![Span::styled(format!("{k:<10}"), dim()), Span::raw(if v.is_empty() { "—".to_string() } else { v })]));
        }
    };
    section(
        &mut lines,
        "Connection",
        vec![
            ("Alias", b.host.name.clone()),
            ("Host", if b.host.hostname.is_empty() { b.host.name.clone() } else { b.host.hostname.clone() }),
            ("Port", b.host.port.clone()),
            ("User", b.host.user.clone()),
            ("Auth", b.host.auth_label()),
            ("Via", b.host.proxy_jump.clone()),
        ],
    );
    match &b.server {
        None => lines.extend([Line::raw(""), Line::styled("Loading server info…", dim())]),
        Some(Err(e)) => lines.extend([Line::raw(""), Line::styled(e.clone(), Style::default().fg(ERR))]),
        Some(Ok(i)) => {
            let g = |keys: &[&str]| keys.iter().filter_map(|k| i.get(*k)).cloned().collect::<Vec<_>>().join(" · ");
            section(&mut lines, "Network", vec![("Server IP", g(&["server_ip"])), ("Your IP", g(&["client_ip"])), ("Your port", g(&["client_port"])), ("SSH port", g(&["server_port"]))]);
            section(
                &mut lines,
                "Server",
                vec![
                    ("Hostname", g(&["hostname"])),
                    ("OS", g(&["os"])),
                    ("Kernel", g(&["kernel", "arch"])),
                    ("Logged in", g(&["user"])),
                    ("Uptime", g(&["uptime"])),
                    ("Load", g(&["load"])),
                    ("CPUs", g(&["cpus"])),
                    ("Memory", g(&["memory"])),
                    ("Disk (~)", g(&["disk"])),
                ],
            );
        }
    }
    f.render_widget(Paragraph::new(lines).wrap(ratatui::widgets::Wrap { trim: false }).block(pane_block(" Server ".into(), false)), info);

    let c = b.console.as_mut().unwrap();
    let status = match c.term.exit {
        Some(rc) if rc != 0 => format!(" {} — exited with status {rc}, press any key ", c.title),
        Some(_) => format!(" {} — finished ", c.title),
        None => format!(" {} · Ctrl+] / Ctrl+C ×2 close · drag=copy · right-click=paste ", c.title),
    };
    let block = pane_block(status, true);
    let inner = block.inner(console);
    f.render_widget(block, console);
    b.console_area = inner;
    c.term.resize(inner.height, inner.width);
    c.term.render(inner, f.buffer_mut(), true);
}

// --- modals ---------------------------------------------------------------------------------
fn draw_modal(app: &App, f: &mut Frame, area: Rect) {
    let Some(modal) = &app.modal else { return };
    let buf = f.buffer_mut();
    match modal {
        Modal::Form(form) => render_form(form, area, buf),
        Modal::Confirm { msg, .. } => render_confirm(msg, area, buf),
        Modal::Overwrite { items, sel } => render_overwrite(items, *sel, area, buf),
        Modal::Text { title, body, scroll } => render_text(title, body, *scroll, area, buf),
        Modal::Message { text } => render_message(text, area, buf),
        Modal::Palette { query, sel } => {
            let items = app.palette_items(query);
            let h = (items.len() as u16 + 4).clamp(6, area.height.saturating_sub(2));
            let r = centered(area, 70, h);
            Clear.render(r, buf);
            let block = dialog_block("Command palette");
            let inner = block.inner(r);
            block.render(r, buf);
            let mut lines = vec![Line::from(vec![Span::styled("> ", Style::default().fg(ACCENT)), Span::raw(format!("{query}▏"))]), Line::raw("")];
            let room = inner.height.saturating_sub(2) as usize;
            let start = sel.saturating_sub(room.saturating_sub(1));
            for (i, it) in items.iter().enumerate().skip(start).take(room) {
                let style = if i == *sel { Style::default().bg(CURSOR_FOCUS).fg(Color::White) } else { Style::default() };
                let w = inner.width as usize;
                let keys = if it.keys.is_empty() { String::new() } else { format!("  {}", it.keys) };
                let label = format!(" {}  {}", it.label, it.help);
                let pad = w.saturating_sub(label.chars().count() + keys.chars().count());
                lines.push(Line::from(vec![Span::styled(format!("{label}{}", " ".repeat(pad)), style), Span::styled(keys, style.fg(if i == *sel { Color::White } else { ACCENT }))]));
            }
            Paragraph::new(lines).render(inner, buf);
        }
        Modal::Import { text } => {
            let r = centered(area, 72, 20.min(area.height));
            Clear.render(r, buf);
            let block = dialog_block("Import hosts from ssh config");
            let inner = block.inner(r);
            block.render(r, buf);
            let mut lines = vec![Line::styled("Paste the text of an ssh config (Host blocks): ctrl+shift+v or right-click", dim()), Line::raw("")];
            let (hosts, ignored) = parse_ssh_config(text);
            if text.trim().is_empty() {
                lines.push(Line::styled("(nothing pasted yet)", dim()));
            }
            for h in hosts.iter().take(10) {
                let exists = app.config.get(&h.name).is_some();
                let mut note = if exists { "exists - skipped".to_string() } else { "new".to_string() };
                if let Some(ig) = ignored.get(&h.name).filter(|v| !v.is_empty()) {
                    note.push_str(&format!(" · ignored: {}", ig.join(", ")));
                }
                lines.push(Line::from(vec![
                    Span::styled(format!("{:<18}", h.name), Style::default().add_modifier(Modifier::BOLD)),
                    Span::raw(format!("{:<26}", h.target())),
                    Span::styled(note, Style::default().fg(if exists { DIM } else { OK })),
                ]));
            }
            if hosts.len() > 10 {
                lines.push(Line::styled(format!("… and {} more", hosts.len() - 10), dim()));
            }
            lines.push(Line::raw(""));
            lines.push(Line::styled("Enter: import   Backspace: clear   Esc: cancel", dim()));
            Paragraph::new(lines).render(inner, buf);
        }
    }
    let _ = Purpose::Plain; // keep import used when overlay variants change
}
