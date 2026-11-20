//! Application state, events and actions.

use std::collections::HashMap;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::time::{Duration, Instant};

use ratatui::DefaultTerminal;
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
use ratatui::layout::Rect;

use crate::browser::{Browser, Console, Pane, RecState, TransferRec};
use crate::clipboard::Clipboard;
use crate::config::{self, Host, SshConfig, State, find_keys, home_dir, localize_identity, parse_ssh_config};
use crate::modal::*;
use crate::quickselect::QuickSelect;
use crate::remote::{Connection, Entry, Progress, join_path, perms_to_octal, run_transfer, valid_mode};
use crate::terminal::{TermEvent, Terminal};
use crate::ui;

const PROMPT_HINTS: [&str; 4] = ["permission denied", "passphrase", "password", "host key verification"];
const DOUBLE_CLICK: Duration = Duration::from_millis(450);

pub enum Msg {
    Master { rc: i32, err: String },
    Listing { path: String, res: Result<Vec<Entry>, String> },
    Info { path: String, res: Result<Vec<(String, String)>, String> },
    Server(Result<HashMap<String, String>, String>),
    Op(Result<String, String>),
    View { title: String, res: Result<String, String> },
    Progress(usize, Progress),
    TransferDone { idx: usize, rc: i32 },
}

#[derive(Clone, Debug, PartialEq)]
pub enum Action {
    Quit,
    Palette,
    NewHost,
    EditHost,
    DeleteHost,
    DuplicateHost,
    ImportHosts,
    Connect(String),
    Filter,
    Upload,
    Download,
    Remove,
    Rename,
    Mkdir,
    Chmod,
    Sync,
    Split,
    SftpTerm,
    Shell,
    View,
    ToggleHidden,
    Refresh,
    Back,
    CopyId,
    Reconnect,
}

#[derive(Clone, Copy, PartialEq)]
pub enum Screen {
    Picker,
    Browser,
}

pub enum Purpose {
    Connect(Host),
    Plain,
}

pub struct Overlay {
    pub title: String,
    pub term: Terminal,
    pub purpose: Purpose,
}

#[derive(Default)]
pub struct Picker {
    pub cursor: usize,
    pub filter: String,
    pub filtering: bool,
    pub quick: QuickSelect,
    pub cards: Vec<(Rect, usize)>,
    pub last_click: Option<(Instant, usize)>,
}

pub struct PaletteItem {
    pub label: String,
    pub help: String,
    pub keys: &'static str,
    pub action: Action,
}

pub struct App {
    pub config: SshConfig,
    pub state: State,
    pub clip: Clipboard,
    pub screen: Screen,
    pub picker: Picker,
    pub browser: Option<Browser>,
    pub modal: Option<Modal>,
    pub overlay: Option<Overlay>,
    pub toast: Option<(String, bool, Instant)>,
    pub connecting: Option<(Host, Connection)>,
    pub quit: bool,
    pub tx: Sender<Msg>,
    rx: Receiver<Msg>,
}

fn fuzzy(query: &str, text: &str) -> Option<i32> {
    let (q, t) = (query.to_lowercase(), text.to_lowercase());
    if q.is_empty() {
        return Some(0);
    }
    if let Some(pos) = t.find(&q) {
        return Some(1000 - pos as i32);
    }
    let mut it = t.chars();
    q.chars().all(|c| it.any(|x| x == c)).then_some(1)
}

impl App {
    pub fn new() -> Self {
        let (tx, rx) = channel();
        App {
            config: SshConfig::new(None),
            state: State::new(None),
            clip: Clipboard::new(),
            screen: Screen::Picker,
            picker: Picker::default(),
            browser: None,
            modal: None,
            overlay: None,
            toast: None,
            connecting: None,
            quit: false,
            tx,
            rx,
        }
    }

    pub fn toast(&mut self, msg: impl Into<String>, err: bool) {
        self.toast = Some((msg.into(), err, Instant::now()));
    }

    pub fn run(&mut self, terminal: &mut DefaultTerminal) -> io::Result<()> {
        while !self.quit {
            terminal.draw(|f| ui::draw(self, f))?;
            if event::poll(Duration::from_millis(40))? {
                loop {
                    match event::read()? {
                        Event::Key(k) if k.kind != KeyEventKind::Release => self.on_key(k),
                        Event::Mouse(m) => self.on_mouse(m),
                        Event::Paste(t) => self.on_paste(&t),
                        _ => {}
                    }
                    if !event::poll(Duration::ZERO)? {
                        break;
                    }
                }
            }
            while let Ok(m) = self.rx.try_recv() {
                self.on_msg(m);
            }
            self.tick();
        }
        if let Some(b) = &self.browser {
            b.conn.close();
        }
        Ok(())
    }

    // --- helpers --------------------------------------------------------------------
    fn job(&self, f: impl FnOnce(Connection) -> Msg + Send + 'static) {
        if let Some(b) = &self.browser {
            let (conn, tx) = (b.conn.clone(), self.tx.clone());
            std::thread::spawn(move || {
                let _ = tx.send(f(conn));
            });
        }
    }

    pub fn visible_hosts(&self) -> Vec<usize> {
        let f = self.picker.filter.to_lowercase();
        self.config
            .hosts
            .iter()
            .enumerate()
            .filter(|(_, h)| f.is_empty() || format!("{} {} {}", h.name, h.hostname, h.user).to_lowercase().contains(&f))
            .map(|(i, _)| i)
            .collect()
    }

    fn current_host(&self) -> Option<Host> {
        let v = self.visible_hosts();
        v.get(self.picker.cursor).map(|&i| self.config.hosts[i].clone())
    }

    fn term_size() -> (u16, u16) {
        ratatui::crossterm::terminal::size().unwrap_or((100, 30))
    }

    // --- messages & ticking ---------------------------------------------------------------
    fn on_msg(&mut self, msg: Msg) {
        match msg {
            Msg::Master { rc, err } => self.on_master(rc, err),
            Msg::Listing { path, res } => {
                let Some(b) = self.browser.as_mut() else { return };
                if path != b.cwd {
                    return;
                }
                b.loading = false;
                match res {
                    Ok(entries) => {
                        b.entries = entries;
                        b.error.clear();
                    }
                    Err(e) => {
                        b.entries.clear();
                        b.error = e;
                    }
                }
                b.selected.retain(|n| b.entries.iter().any(|e| &e.name == n));
                if let Some(name) = b.pending_focus.take() {
                    if let Some(i) = b.visible().iter().position(|e| e.name == name) {
                        b.cursor = i;
                    }
                }
                b.clamp();
                b.info_for = None;
            }
            Msg::Info { path, res } => {
                if let Some(b) = self.browser.as_mut() {
                    if b.info_for.as_deref() == Some(&path) {
                        b.info = res.unwrap_or_default();
                    }
                }
            }
            Msg::Server(res) => {
                if let Some(b) = self.browser.as_mut() {
                    b.server = Some(res);
                }
            }
            Msg::Op(res) => {
                match res {
                    Ok(m) => self.toast(m, false),
                    Err(e) => self.toast(e, true),
                }
                self.load();
            }
            Msg::View { title, res } => match res {
                Ok(body) => self.modal = Some(Modal::Text { title, body, scroll: 0 }),
                Err(e) => self.toast(e, true),
            },
            Msg::Progress(idx, p) => {
                if let Some(r) = self.browser.as_mut().and_then(|b| b.records.get_mut(idx)) {
                    r.state = RecState::Running(p);
                }
            }
            Msg::TransferDone { idx, rc } => {
                let mut label = String::new();
                if let Some(b) = self.browser.as_mut() {
                    b.running = false;
                    if let Some(r) = b.records.get_mut(idx) {
                        r.state = RecState::Done(rc == 0);
                        label = r.label.clone();
                    }
                    b.reload_local();
                }
                if rc == 0 {
                    self.toast(format!("Transfer complete: {label}"), false);
                } else {
                    self.toast(format!("Transfer failed: {label}"), true);
                }
                self.load();
                self.pump();
            }
        }
    }

    fn tick(&mut self) {
        if let Some((_, _, at)) = &self.toast {
            if at.elapsed() > Duration::from_secs(4) {
                self.toast = None;
            }
        }
        // overlay terminal exit
        let mut finished = None;
        if let Some(ov) = self.overlay.as_mut() {
            if let Some(rc) = ov.term.poll_exit() {
                finished = Some(rc);
            }
        }
        if let Some(rc) = finished {
            if rc == 0 {
                let ov = self.overlay.take().unwrap();
                match ov.purpose {
                    Purpose::Connect(host) => {
                        if let Some((_, conn)) = self.connecting.take() {
                            self.enter_browser(host, conn);
                        }
                    }
                    Purpose::Plain => self.toast("Command finished", false),
                }
            }
        }
        if let Some(b) = self.browser.as_mut() {
            // console exit
            if let Some(c) = b.console.as_mut() {
                if c.term.poll_exit() == Some(0) {
                    self.close_console();
                    return;
                }
            }
            // debounced file info
            let cur = b.current().filter(|e| e.name != "..").map(|e| join_path(&b.cwd, &e.name));
            match cur {
                Some(path) if b.info_for.as_deref() != Some(&path) => match &b.info_wanted {
                    Some((p, at)) if *p == path => {
                        if at.elapsed() > Duration::from_millis(150) {
                            b.info_wanted = None;
                            b.info_for = Some(path.clone());
                            b.info.clear();
                            self.job(move |c| Msg::Info { path: path.clone(), res: c.file_info(&path) });
                        }
                    }
                    _ => b.info_wanted = Some((path, Instant::now())),
                },
                None => {
                    b.info.clear();
                    b.info_for = None;
                }
                _ => {}
            }
        }
    }

    // --- connection -----------------------------------------------------------------------
    pub fn connect(&mut self, host: Host) {
        let conn = Connection::new(&host.name, None);
        self.modal = Some(Modal::Message { text: format!("Connecting to {}…", host.name) });
        self.connecting = Some((host.clone(), conn.clone()));
        if host.password_auth {
            return self.open_connect_terminal();
        }
        let tx = self.tx.clone();
        std::thread::spawn(move || {
            if conn.is_alive() {
                return drop(tx.send(Msg::Master { rc: 0, err: String::new() }));
            }
            let (rc, err) = conn.try_master();
            let _ = tx.send(Msg::Master { rc, err });
        });
    }

    fn on_master(&mut self, rc: i32, err: String) {
        let Some((host, conn)) = self.connecting.clone() else { return };
        if rc == 0 {
            self.connecting = None;
            self.enter_browser(host, conn);
        } else if PROMPT_HINTS.iter().any(|h| err.to_lowercase().contains(h)) {
            self.open_connect_terminal();
        } else {
            self.connecting = None;
            self.modal = None;
            let err = err.trim();
            self.toast(if err.is_empty() { "Connection failed".to_string() } else { err.to_string() }, true);
        }
    }

    /// ssh asks for password / passphrase / host key confirmation inside an embedded terminal.
    fn open_connect_terminal(&mut self) {
        let Some((host, conn)) = self.connecting.clone() else { return };
        let (w, h) = Self::term_size();
        self.modal = None;
        self.overlay = Some(Overlay {
            title: format!("ssh {}", host.name),
            term: Terminal::spawn(&conn.master_cmd(false), h.saturating_sub(2), w),
            purpose: Purpose::Connect(host),
        });
    }

    fn open_plain_overlay(&mut self, title: &str, cmd: Vec<String>) {
        let (w, h) = Self::term_size();
        self.overlay = Some(Overlay { title: title.into(), term: Terminal::spawn(&cmd, h.saturating_sub(2), w), purpose: Purpose::Plain });
    }

    fn enter_browser(&mut self, host: Host, conn: Connection) {
        let saved = self.state.get(&format!("local_cwd:{}", host.name)).map(PathBuf::from).filter(|p| p.is_dir());
        let mut b = Browser::new(host, conn, saved.unwrap_or_else(home_dir));
        b.reload_local();
        self.browser = Some(b);
        self.screen = Screen::Browser;
        self.modal = None;
        self.load();
    }

    fn leave_browser(&mut self) {
        if let Some(mut b) = self.browser.take() {
            if let Some(c) = b.console.as_mut() {
                c.term.terminate();
            }
            let conn = b.conn.clone();
            std::thread::spawn(move || conn.close());
        }
        self.screen = Screen::Picker;
    }

    // --- browser loading ---------------------------------------------------------------------
    pub fn load(&mut self) {
        let Some(b) = self.browser.as_mut() else { return };
        b.loading = true;
        let path = b.cwd.clone();
        self.job(move |c| Msg::Listing { path: path.clone(), res: c.list_dir(&path) });
    }

    fn go(&mut self, path: String) {
        if let Some(b) = self.browser.as_mut() {
            b.cwd = path;
            b.selected.clear();
            b.filter.clear();
            b.filtering = false;
            b.cursor = 0;
            b.entries.clear();
        }
        self.load();
    }

    fn go_up(&mut self) {
        let Some(b) = self.browser.as_mut() else { return };
        let from = b.cwd.trim_end_matches('/').rsplit('/').next().unwrap_or("").to_string();
        b.pending_focus = Some(from);
        let up = join_path(&b.cwd, "..");
        self.go(up);
    }

    fn go_local(&mut self, dir: PathBuf) {
        let Some(b) = self.browser.as_mut() else { return };
        let from = b.local_cwd.file_name().map(|n| n.to_string_lossy().into_owned());
        b.local_cwd = dir;
        b.local_selected.clear();
        b.local_cursor = 0;
        b.reload_local();
        if let Some(name) = from {
            if let Some(i) = b.visible_local().iter().position(|e| e.name == name) {
                b.local_cursor = i;
            }
        }
        let (name, cwd) = (b.host.name.clone(), b.local_cwd.to_string_lossy().into_owned());
        self.state.set(&format!("local_cwd:{name}"), &cwd);
    }

    fn open_entry(&mut self) {
        let Some(b) = self.browser.as_ref() else { return };
        if b.focus == Pane::Local {
            if let Some(e) = b.current_local() {
                if e.is_dir {
                    let dir = if e.name == ".." { b.local_cwd.parent().map(Path::to_path_buf).unwrap_or_default() } else { b.local_cwd.join(&e.name) };
                    self.go_local(dir);
                }
            }
            return;
        }
        match b.current() {
            Some(e) if e.name == ".." => self.go_up(),
            Some(e) if e.is_dir || e.is_link => {
                let p = join_path(&b.cwd, &e.name);
                self.go(p)
            }
            Some(_) => self.run_action(Action::View),
            None => {}
        }
    }

    // --- transfers -------------------------------------------------------------------------
    fn up_item(&self, path: &Path) -> TransferItem {
        let b = self.browser.as_ref().unwrap();
        let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        TransferItem {
            label: format!("↑ {name}"),
            up: true,
            local: path.to_string_lossy().into_owned(),
            remote: format!("{}/", b.cwd.trim_end_matches('/')),
            exists: b.entries.iter().any(|e| e.name == name),
        }
    }

    fn down_item(&self, name: &str, dest: &Path) -> TransferItem {
        let b = self.browser.as_ref().unwrap();
        TransferItem {
            label: format!("↓ {name}"),
            up: false,
            local: format!("{}/", dest.to_string_lossy().trim_end_matches('/')),
            remote: join_path(&b.cwd, name),
            exists: dest.join(name).exists(),
        }
    }

    fn submit(&mut self, items: Vec<TransferItem>) {
        if items.iter().any(|i| i.exists) {
            self.modal = Some(Modal::Overwrite { items, sel: 0 });
        } else {
            self.enqueue(items);
        }
    }

    fn enqueue(&mut self, items: Vec<TransferItem>) {
        if let Some(b) = self.browser.as_mut() {
            for it in items {
                b.records.push(TransferRec { label: it.label.clone(), state: RecState::Queued });
                let idx = b.records.len() - 1;
                b.queue.push_back((idx, it));
            }
        }
        self.pump();
    }

    fn pump(&mut self) {
        let Some(b) = self.browser.as_mut() else { return };
        if b.running {
            return;
        }
        let Some((idx, item)) = b.queue.pop_front() else { return };
        b.running = true;
        b.records[idx].state = RecState::Running(Progress { percent: 0, speed: String::new(), eta: String::new() });
        let (conn, tx) = (b.conn.clone(), self.tx.clone());
        std::thread::spawn(move || {
            let rc = match conn.expand(&item.remote) {
                Ok(remote) => {
                    let cmd = conn.transfer_cmd(item.up, &item.local, &remote);
                    run_transfer(&cmd, |p| drop(tx.send(Msg::Progress(idx, p))))
                }
                Err(_) => 1,
            };
            let _ = tx.send(Msg::TransferDone { idx, rc });
        });
    }

    fn do_download(&mut self, names: Vec<String>, dest: PathBuf) {
        if let Err(e) = std::fs::create_dir_all(&dest) {
            return self.toast(format!("{}: {e}", dest.display()), true);
        }
        let items = names.iter().map(|n| self.down_item(n, &dest)).collect();
        self.submit(items);
    }

    // --- actions --------------------------------------------------------------------------
    fn remote_only(&mut self) -> bool {
        if self.browser.as_ref().is_some_and(|b| b.focus == Pane::Local) {
            self.toast("Focus the remote pane first (Tab)", true);
            return false;
        }
        true
    }

    pub fn run_action(&mut self, action: Action) {
        let in_browser = self.screen == Screen::Browser && self.browser.is_some();
        match action {
            Action::Quit => self.quit = true,
            Action::Palette => self.modal = Some(Modal::Palette { query: String::new(), sel: 0 }),
            Action::NewHost => self.modal = Some(Modal::Form(self.host_form(None))),
            Action::EditHost => {
                if let Some(h) = self.current_host() {
                    self.modal = Some(Modal::Form(self.host_form(Some(&h))));
                }
            }
            Action::DuplicateHost => {
                if let Some(mut h) = self.current_host() {
                    h.name = format!("{}-copy", h.name);
                    let mut form = self.host_form(Some(&h));
                    form.kind = FormKind::HostNew;
                    form.title = "Duplicate host".into();
                    self.modal = Some(Modal::Form(form));
                }
            }
            Action::DeleteHost => {
                if let Some(h) = self.current_host() {
                    self.modal = Some(Modal::Confirm { msg: format!("Delete '{}'?", h.name), kind: ConfirmKind::DeleteHost(h.name) });
                }
            }
            Action::ImportHosts => self.modal = Some(Modal::Import { text: String::new() }),
            Action::Connect(name) => {
                if in_browser {
                    self.leave_browser();
                }
                if let Some(h) = self.config.get(&name).cloned() {
                    self.connect(h);
                }
            }
            Action::Filter => {
                if in_browser {
                    if let Some(b) = self.browser.as_mut() {
                        b.filtering = true;
                    }
                } else {
                    self.picker.filtering = true;
                }
            }
            Action::CopyId => {
                let (host, conn) = match self.browser.as_ref() {
                    Some(b) => (b.host.clone(), b.conn.clone()),
                    None => match self.current_host() {
                        Some(h) => (h.clone(), Connection::new(&h.name, None)),
                        None => return,
                    },
                };
                let pubkey = (!host.identity_file.is_empty()).then(|| format!("{}.pub", host.identity_file)).filter(|p| Path::new(p).exists());
                self.open_plain_overlay(&format!("ssh-copy-id {}", host.name), conn.copy_id_cmd(pubkey.as_deref()));
            }
            _ if !in_browser => {}
            Action::Back => self.leave_browser(),
            Action::Refresh => {
                self.load();
                if let Some(b) = self.browser.as_mut() {
                    b.reload_local();
                }
            }
            Action::ToggleHidden => {
                if let Some(b) = self.browser.as_mut() {
                    b.show_hidden = !b.show_hidden;
                    b.clamp();
                }
            }
            Action::Reconnect => {
                if let Some(b) = self.browser.as_ref() {
                    let (host, conn) = (b.host.clone(), b.conn.clone());
                    conn.close();
                    self.leave_browser();
                    self.connect(host);
                }
            }
            Action::Split => {
                if let Some(b) = self.browser.as_mut() {
                    b.split = !b.split;
                    b.focus = Pane::Remote;
                    b.reload_local();
                }
            }
            Action::SftpTerm => {
                let cwd = self.browser.as_ref().map(|b| b.cwd.clone()).unwrap_or_default();
                let conn = self.browser.as_ref().unwrap().conn.clone();
                match conn.sftp_cmd(Some(&cwd)) {
                    Ok(cmd) => self.open_console("sftp", cmd),
                    Err(e) => self.toast(e, true),
                }
            }
            Action::Shell => {
                let b = self.browser.as_ref().unwrap();
                let (title, cmd) = (format!("ssh {}", b.host.name), b.conn.shell_cmd());
                self.open_console(&title, cmd);
            }
            Action::View => {
                if !self.remote_only() {
                    return;
                }
                let b = self.browser.as_ref().unwrap();
                match b.current() {
                    Some(e) if !e.is_dir && e.name != ".." => {
                        let (path, title) = (join_path(&b.cwd, &e.name), format!("{} (first 50 lines)", e.name));
                        self.job(move |c| Msg::View { title, res: c.read_head(&path) });
                    }
                    _ => self.toast("Select a file to view", true),
                }
            }
            Action::Upload => {
                let b = self.browser.as_ref().unwrap();
                if b.focus == Pane::Local {
                    let names = b.local_targets();
                    if names.is_empty() {
                        return self.toast("Select a local file first", true);
                    }
                    let items = names.iter().map(|n| self.up_item(&b.local_cwd.join(n))).collect();
                    return self.submit(items);
                }
                let start = format!("{}/", b.local_cwd.display());
                self.modal = Some(Modal::Form(Form::new(
                    &format!("Upload to {}", b.cwd),
                    "Local file(s) or folder(s), separated by commas",
                    FormKind::Upload,
                    vec![Field::text("Local path", &start, "")],
                )));
            }
            Action::Download => {
                let b = self.browser.as_ref().unwrap();
                let names = b.targets();
                if names.is_empty() {
                    return self.toast("Select a file first", true);
                }
                if b.focus == Pane::Local || b.split {
                    let dest = b.local_cwd.clone();
                    return self.do_download(names, dest);
                }
                let default = self.state.get("download_dir").unwrap_or_else(|| {
                    let d = home_dir().join("Downloads");
                    if d.is_dir() { d } else { home_dir() }.to_string_lossy().into_owned()
                });
                self.modal = Some(Modal::Form(Form::new(
                    "Download to…",
                    &format!("{} item(s)", names.len()),
                    FormKind::DownloadTo(names),
                    vec![Field::text("Local folder", &default, "")],
                )));
            }
            Action::Sync => {
                if !self.remote_only() {
                    return;
                }
                let b = self.browser.as_ref().unwrap();
                let local = format!("{}", b.local_cwd.display());
                self.modal = Some(Modal::Form(Form::new(
                    "Directory sync (rsync)",
                    "Contents of one directory are mirrored into the other",
                    FormKind::Sync,
                    vec![
                        Field::text("Local directory", &local, ""),
                        Field::text("Remote directory", &b.cwd, ""),
                        Field::cycle("Direction", vec!["Upload (local → remote)".into(), "Download (remote → local)".into()], ""),
                    ],
                )));
            }
            Action::Remove => {
                if !self.remote_only() {
                    return;
                }
                let names = self.browser.as_ref().unwrap().targets();
                if names.is_empty() {
                    return self.toast("Select something first", true);
                }
                let msg = if names.len() == 1 { format!("Delete '{}' on the server?", names[0]) } else { format!("Delete {} items on the server?", names.len()) };
                self.modal = Some(Modal::Confirm { msg, kind: ConfirmKind::DeleteRemote(names) });
            }
            Action::Rename => {
                if !self.remote_only() {
                    return;
                }
                match self.browser.as_ref().unwrap().current() {
                    Some(e) if e.name != ".." => {
                        self.modal = Some(Modal::Form(Form::new("Rename", "", FormKind::Rename(e.name.clone()), vec![Field::text("New name", &e.name, "")])))
                    }
                    _ => self.toast("Select a file first", true),
                }
            }
            Action::Mkdir => {
                if self.remote_only() {
                    self.modal = Some(Modal::Form(Form::new("New folder", "", FormKind::Mkdir, vec![Field::text("Name", "", "")])));
                }
            }
            Action::Chmod => {
                if !self.remote_only() {
                    return;
                }
                let b = self.browser.as_ref().unwrap();
                let names = b.targets();
                if names.is_empty() {
                    return self.toast("Select something first", true);
                }
                let init = if names.len() == 1 { b.entries.iter().find(|e| e.name == names[0]).map(|e| perms_to_octal(&e.perms)).unwrap_or_default() } else { String::new() };
                self.modal = Some(Modal::Form(Form::new(
                    "Permissions",
                    "Octal (755) or symbolic (u+x,go-w)",
                    FormKind::Chmod(names),
                    vec![Field::text("Mode", &init, "")],
                )));
            }
        }
    }

    fn open_console(&mut self, title: &str, cmd: Vec<String>) {
        let (w, h) = Self::term_size();
        let Some(b) = self.browser.as_mut() else { return };
        if b.console.is_some() {
            return;
        }
        b.server = None;
        b.console = Some(Console { title: title.into(), term: Terminal::spawn(&cmd, h.saturating_sub(4), (w * 2 / 3).saturating_sub(2)) });
        self.job(|c| Msg::Server(c.server_info()));
    }

    fn close_console(&mut self) {
        if let Some(b) = self.browser.as_mut() {
            if let Some(mut c) = b.console.take() {
                c.term.terminate();
            }
        }
        self.load();
    }

    // --- forms -----------------------------------------------------------------------------
    fn host_form(&self, old: Option<&Host>) -> Form {
        let h = old.cloned().unwrap_or_else(|| Host::new(""));
        let keys = find_keys(None);
        let key_name = |p: &Path| p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let mut opts = vec!["(default)".to_string()];
        opts.extend(keys.iter().map(|k| key_name(k)));
        opts.push("custom path".into());
        let current = if h.identity_file.is_empty() {
            "(default)".to_string()
        } else {
            keys.iter().find(|k| k.to_string_lossy() == h.identity_file).map(|k| key_name(k)).unwrap_or_else(|| "custom path".into())
        };
        let custom = if current == "custom path" { h.identity_file.as_str() } else { "" };
        let mut form = Form::new(
            if old.is_some() { "Edit host" } else { "New host" },
            "",
            match old {
                Some(o) => FormKind::HostEdit(o.name.clone()),
                None => FormKind::HostNew,
            },
            vec![
                Field::text("Name (alias)", &h.name, "prod-web"),
                Field::text("Hostname / IP", &h.hostname, "10.0.0.5"),
                Field::text("Port", &h.port, "22"),
                Field::text("User", &h.user, ""),
                Field::cycle("Authentication", vec!["SSH key".into(), "Password".into()], if h.password_auth { "Password" } else { "SSH key" }),
                Field::cycle("Key file", opts, &current),
                Field::text("Custom key path", custom, "~/keys/server.pem (used when Key file = custom path)"),
                Field::text("Jump host (ProxyJump)", &h.proxy_jump, "user@bastion:22"),
                Field::text("Port forwards", &h.local_forwards.join(", "), "8080 localhost:80, 5432 db:5432"),
            ],
        );
        form.hint = "Saved to ~/.ssh/config".into();
        form
    }

    fn build_host(&mut self, f: &Form) -> Result<Host, String> {
        let mut h = Host::new(&f.value("Name (alias)"));
        h.hostname = f.value("Hostname / IP");
        h.port = f.value("Port");
        if h.port.is_empty() {
            h.port = "22".into();
        }
        if h.port.parse::<u16>().is_err() {
            return Err("Port must be a number (1-65535)".into());
        }
        h.user = f.value("User");
        h.proxy_jump = f.value("Jump host (ProxyJump)");
        h.local_forwards = f.value("Port forwards").split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
        if f.value("Authentication") == "Password" {
            h.password_auth = true;
        } else {
            let choice = f.value("Key file");
            let path = match choice.as_str() {
                "(default)" => String::new(),
                "custom path" => {
                    let p = f.value("Custom key path");
                    match p.strip_prefix("~/") {
                        Some(rest) => home_dir().join(rest).to_string_lossy().into_owned(),
                        None => p,
                    }
                }
                name => home_dir().join(".ssh").join(name).to_string_lossy().into_owned(),
            };
            if !path.is_empty() {
                if !Path::new(&path).is_file() {
                    return Err(format!("Key file not found: {path}"));
                }
                if config::ensure_key_permissions(Path::new(&path)) {
                    self.toast("Key permissions set to 600", false);
                }
            }
            h.identity_file = path;
        }
        Ok(h)
    }

    fn submit_form(&mut self, mut form: Form) {
        let result: Result<(), String> = match form.kind.clone() {
            FormKind::HostNew | FormKind::HostEdit(_) => match self.build_host(&form) {
                Err(e) => Err(e),
                Ok(host) => {
                    let name = host.name.clone();
                    let r = match &form.kind {
                        FormKind::HostEdit(old) => self.config.update(old, host).map(|_| format!("Host '{name}' updated")),
                        _ => self.config.add(host).map(|_| format!("Host '{name}' added")),
                    };
                    r.map(|msg| {
                        self.toast(msg, false);
                        self.picker.filter.clear();
                        if let Some(i) = self.visible_hosts().iter().position(|&i| self.config.hosts[i].name == name) {
                            self.picker.cursor = i;
                        }
                    })
                }
            },
            FormKind::Mkdir => {
                let name = form.value("Name");
                if name.is_empty() || name.contains('/') {
                    Err("Enter a folder name (no /)".into())
                } else {
                    let path = join_path(&self.browser.as_ref().unwrap().cwd, &name);
                    self.job(move |c| Msg::Op(c.mkdir(&path).map(|_| format!("Created {name}"))));
                    Ok(())
                }
            }
            FormKind::Rename(old) => {
                let new = form.value("New name");
                if new.is_empty() || new.contains('/') {
                    Err("Enter a new name (no /)".into())
                } else if new != old {
                    let cwd = self.browser.as_ref().unwrap().cwd.clone();
                    let (from, to) = (join_path(&cwd, &old), join_path(&cwd, &new));
                    self.job(move |c| Msg::Op(c.rename(&from, &to).map(|_| format!("Renamed to {new}"))));
                    Ok(())
                } else {
                    Ok(())
                }
            }
            FormKind::Chmod(names) => {
                let mode = form.value("Mode");
                if !valid_mode(&mode) {
                    Err(format!("Invalid mode: {mode}"))
                } else {
                    let cwd = self.browser.as_ref().unwrap().cwd.clone();
                    self.job(move |c| {
                        for n in &names {
                            if let Err(e) = c.chmod(&join_path(&cwd, n), &mode) {
                                return Msg::Op(Err(e));
                            }
                        }
                        Msg::Op(Ok(format!("chmod {mode} on {} item(s)", names.len())))
                    });
                    Ok(())
                }
            }
            FormKind::Upload => {
                let paths: Vec<PathBuf> = form
                    .value("Local path")
                    .split(',')
                    .map(str::trim)
                    .filter(|p| !p.is_empty())
                    .map(|p| match p.strip_prefix("~/") {
                        Some(rest) => home_dir().join(rest),
                        None => PathBuf::from(p),
                    })
                    .collect();
                match paths.iter().find(|p| !p.exists()) {
                    Some(missing) => Err(format!("Local path not found: {}", missing.display())),
                    None if paths.is_empty() => Err("Enter a path".into()),
                    None => {
                        let items = paths.iter().map(|p| self.up_item(p)).collect();
                        self.submit(items);
                        Ok(())
                    }
                }
            }
            FormKind::DownloadTo(names) => {
                let d = form.value("Local folder");
                let dest = match d.strip_prefix("~/") {
                    Some(rest) => home_dir().join(rest),
                    None if d == "~" => home_dir(),
                    None => PathBuf::from(&d),
                };
                if d.is_empty() {
                    Err("Enter a folder".into())
                } else {
                    self.state.set("download_dir", &dest.to_string_lossy());
                    self.do_download(names, dest);
                    Ok(())
                }
            }
            FormKind::Sync => {
                let (local, remote) = (form.value("Local directory"), form.value("Remote directory"));
                let up = form.value("Direction").starts_with("Upload");
                if !Path::new(&local).is_dir() {
                    Err(format!("Local directory not found: {local}"))
                } else if remote.is_empty() {
                    Err("Enter a remote directory".into())
                } else {
                    let with_slash = |s: &str| format!("{}/", s.trim_end_matches('/'));
                    let label = format!("{} sync {}", if up { "↑" } else { "↓" }, local);
                    self.enqueue(vec![TransferItem { label, up, local: with_slash(&local), remote: with_slash(&remote), exists: false }]);
                    Ok(())
                }
            }
        };
        if let Err(e) = result {
            form.error = e;
            self.modal = Some(Modal::Form(form));
        }
    }

    fn confirm(&mut self, kind: ConfirmKind) {
        match kind {
            ConfirmKind::DeleteHost(name) => {
                match self.config.delete(&name) {
                    Ok(_) => self.toast(format!("Host '{name}' deleted"), false),
                    Err(e) => self.toast(e, true),
                }
                self.picker.cursor = self.picker.cursor.min(self.visible_hosts().len().saturating_sub(1));
            }
            ConfirmKind::DeleteRemote(names) => {
                let cwd = self.browser.as_ref().unwrap().cwd.clone();
                if let Some(b) = self.browser.as_mut() {
                    b.selected.clear();
                }
                self.job(move |c| {
                    for n in &names {
                        if let Err(e) = c.remove(&join_path(&cwd, n)) {
                            return Msg::Op(Err(e));
                        }
                    }
                    Msg::Op(Ok(format!("Deleted {} item(s)", names.len())))
                });
            }
        }
    }

    pub fn palette_items(&self, query: &str) -> Vec<PaletteItem> {
        let item = |label: &str, help: &str, keys: &'static str, action: Action| PaletteItem { label: label.into(), help: help.into(), keys, action };
        let mut v = vec![];
        if self.screen == Screen::Picker {
            v.push(item("New host", "Add a host to ~/.ssh/config", "alt+n", Action::NewHost));
            v.push(item("Import hosts", "Paste ssh config text to add several hosts", "alt+i", Action::ImportHosts));
            v.push(item("Edit host", "Edit the highlighted host", "alt+e", Action::EditHost));
            v.push(item("Duplicate host", "Copy the highlighted host under a new name", "alt+y", Action::DuplicateHost));
            v.push(item("Delete host", "Remove the highlighted host", "alt+d", Action::DeleteHost));
            v.push(item("Copy SSH key to server", "Run ssh-copy-id for the highlighted host", "alt+k", Action::CopyId));
        } else {
            v.push(item("Upload", "Upload local files to this folder", "alt+u", Action::Upload));
            v.push(item("Download", "Download the selected files", "alt+d", Action::Download));
            v.push(item("View file", "First 50 lines of the highlighted file", "alt+v", Action::View));
            v.push(item("Delete", "Delete the selected remote files", "alt+x", Action::Remove));
            v.push(item("Rename", "Rename the highlighted remote file", "alt+r", Action::Rename));
            v.push(item("New folder", "Create a folder in this remote directory", "alt+n", Action::Mkdir));
            v.push(item("Permissions", "chmod the selected remote files", "alt+m", Action::Chmod));
            v.push(item("Sync directory", "rsync a directory up or down", "alt+s", Action::Sync));
            v.push(item("SFTP split view", "Local files below; drag rows between panes", "alt+t", Action::Split));
            v.push(item("SFTP terminal", "Open a terminal sftp session", "alt+f", Action::SftpTerm));
            v.push(item("SSH shell", "Open an ssh shell on this host", "alt+h", Action::Shell));
            v.push(item("Copy SSH key to server", "Run ssh-copy-id for this host", "alt+k", Action::CopyId));
            v.push(item("Reconnect", "Drop and re-open the connection", "alt+c", Action::Reconnect));
            v.push(item("Toggle hidden files", "Show or hide dotfiles", ".", Action::ToggleHidden));
            v.push(item("Refresh", "Reload this folder", "F5", Action::Refresh));
            v.push(item("Back to hosts", "Return to the host list", "esc", Action::Back));
        }
        for h in &self.config.hosts {
            v.push(item(&format!("Connect to {}", h.name), &h.target(), "", Action::Connect(h.name.clone())));
        }
        v.push(item("Quit", "Exit ssh-fm", "alt+q", Action::Quit));
        let mut scored: Vec<(i32, PaletteItem)> = v.into_iter().filter_map(|i| fuzzy(query, &i.label).map(|s| (s, i))).collect();
        scored.sort_by_key(|(s, _)| -*s);
        scored.into_iter().map(|(_, i)| i).collect()
    }

    // --- input ---------------------------------------------------------------------------------
    fn on_key(&mut self, key: KeyEvent) {
        if self.modal.is_some() {
            return self.modal_key(key);
        }
        if self.overlay.is_some() {
            return self.overlay_key(key);
        }
        if self.screen == Screen::Browser && self.browser.as_ref().is_some_and(|b| b.console.is_some()) {
            return self.console_key(key);
        }
        let alt = key.modifiers.contains(KeyModifiers::ALT);
        let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
        let sup = key.modifiers.contains(KeyModifiers::SUPER);
        match key.code {
            KeyCode::Char('q') if alt || ctrl => return self.run_action(Action::Quit),
            KeyCode::Char('p') if alt || ctrl || sup => return self.run_action(Action::Palette),
            _ => {}
        }
        if self.screen == Screen::Picker {
            self.picker_key(key)
        } else {
            self.browser_key(key)
        }
    }

    fn picker_key(&mut self, key: KeyEvent) {
        let alt = key.modifiers.contains(KeyModifiers::ALT);
        let n = self.visible_hosts().len();
        if self.picker.filtering {
            match key.code {
                KeyCode::Esc => {
                    self.picker.filter.clear();
                    self.picker.filtering = false;
                }
                KeyCode::Enter => self.picker.filtering = false,
                KeyCode::Backspace => drop(self.picker.filter.pop()),
                KeyCode::Char(c) if !alt => self.picker.filter.push(c),
                _ => {}
            }
            self.picker.cursor = self.picker.cursor.min(self.visible_hosts().len().saturating_sub(1));
            return;
        }
        let cur = self.picker.cursor;
        match key.code {
            KeyCode::Enter => {
                if let Some(h) = self.current_host() {
                    self.connect(h)
                }
            }
            KeyCode::Left => self.picker.cursor = cur.saturating_sub(1),
            KeyCode::Right => self.picker.cursor = (cur + 1).min(n.saturating_sub(1)),
            KeyCode::Up => self.picker.cursor = cur.saturating_sub(2),
            KeyCode::Down => self.picker.cursor = (cur + 2).min(n.saturating_sub(1)),
            KeyCode::Home => self.picker.cursor = 0,
            KeyCode::End => self.picker.cursor = n.saturating_sub(1),
            KeyCode::Esc => self.picker.filter.clear(),
            KeyCode::Char('/') => self.picker.filtering = true,
            KeyCode::Char('n') if alt => self.run_action(Action::NewHost),
            KeyCode::Char('e') if alt => self.run_action(Action::EditHost),
            KeyCode::Char('d') if alt => self.run_action(Action::DeleteHost),
            KeyCode::Char('i') if alt => self.run_action(Action::ImportHosts),
            KeyCode::Char('y') if alt => self.run_action(Action::DuplicateHost),
            KeyCode::Char('k') if alt => self.run_action(Action::CopyId),
            KeyCode::Char(c) if quick_char(&key) => {
                let names: Vec<String> = self.visible_hosts().iter().map(|&i| self.config.hosts[i].name.clone()).collect();
                if let Some(i) = self.picker.quick.feed(c, &names, cur) {
                    self.picker.cursor = i;
                }
            }
            _ => {}
        }
    }

    fn browser_key(&mut self, key: KeyEvent) {
        let alt = key.modifiers.contains(KeyModifiers::ALT);
        let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
        let b = self.browser.as_mut().unwrap();
        if b.filtering {
            match key.code {
                KeyCode::Esc => {
                    b.filter.clear();
                    b.filtering = false;
                }
                KeyCode::Enter => b.filtering = false,
                KeyCode::Backspace => drop(b.filter.pop()),
                KeyCode::Char(c) if !alt && !ctrl => b.filter.push(c),
                _ => {}
            }
            b.cursor = 0;
            b.clamp();
            return;
        }
        let local = b.focus == Pane::Local;
        let len = if local { b.visible_local().len() } else { b.visible().len() };
        let cursor = if local { &mut b.local_cursor } else { &mut b.cursor };
        match key.code {
            KeyCode::Up => *cursor = cursor.saturating_sub(1),
            KeyCode::Down => *cursor = (*cursor + 1).min(len.saturating_sub(1)),
            KeyCode::PageUp => *cursor = cursor.saturating_sub(10),
            KeyCode::PageDown => *cursor = (*cursor + 10).min(len.saturating_sub(1)),
            KeyCode::Home => *cursor = 0,
            KeyCode::End => *cursor = len.saturating_sub(1),
            KeyCode::Tab if b.split => b.focus = if local { Pane::Remote } else { Pane::Local },
            KeyCode::Enter => self.open_entry(),
            KeyCode::Backspace => {
                if local {
                    if let Some(p) = b.local_cwd.parent().map(Path::to_path_buf) {
                        self.go_local(p);
                    }
                } else {
                    self.go_up();
                }
            }
            KeyCode::Esc => {
                if !b.filter.is_empty() {
                    b.filter.clear();
                    b.clamp();
                } else {
                    self.run_action(Action::Back)
                }
            }
            KeyCode::Char(' ') => {
                if local {
                    if let Some(e) = b.current_local().filter(|e| e.name != "..") {
                        if !b.local_selected.remove(&e.name) {
                            b.local_selected.insert(e.name);
                        }
                        b.local_cursor += 1;
                    }
                } else if let Some(e) = b.current().filter(|e| e.name != "..") {
                    if !b.selected.remove(&e.name) {
                        b.selected.insert(e.name);
                    }
                    b.cursor = (b.cursor + 1).min(len.saturating_sub(1));
                }
                b.clamp();
            }
            KeyCode::Char('.') if !alt => self.run_action(Action::ToggleHidden),
            KeyCode::Char('/') if !alt => self.run_action(Action::Filter),
            KeyCode::F(5) => self.run_action(Action::Refresh),
            KeyCode::F(2) => self.run_action(Action::Rename),
            KeyCode::Delete => self.run_action(Action::Remove),
            KeyCode::Char('r') if ctrl => self.run_action(Action::Refresh),
            KeyCode::Char(c) if alt => {
                let a = match c {
                    'u' => Action::Upload,
                    'd' => Action::Download,
                    'v' => Action::View,
                    's' => Action::Sync,
                    't' => Action::Split,
                    'f' => Action::SftpTerm,
                    'h' => Action::Shell,
                    'x' => Action::Remove,
                    'n' => Action::Mkdir,
                    'r' => Action::Rename,
                    'm' => Action::Chmod,
                    'k' => Action::CopyId,
                    'c' => Action::Reconnect,
                    _ => return,
                };
                self.run_action(a)
            }
            KeyCode::Char(c) if quick_char(&key) => {
                let (names, cur): (Vec<String>, usize) = if local {
                    (b.visible_local().into_iter().map(|e| e.name).collect(), b.local_cursor)
                } else {
                    (b.visible().into_iter().map(|e| e.name).collect(), b.cursor)
                };
                if let Some(i) = b.quick.feed(c, &names, cur) {
                    if local { b.local_cursor = i } else { b.cursor = i }
                }
            }
            _ => {}
        }
    }

    fn console_key(&mut self, key: KeyEvent) {
        let b = self.browser.as_mut().unwrap();
        let Some(c) = b.console.as_mut() else { return };
        if c.term.exit.is_some() && key.code != KeyCode::Char(']') {
            return self.close_console(); // any key closes a finished console
        }
        match c.term.handle_key(key) {
            TermEvent::Close | TermEvent::CloseRequested => self.close_console(),
            TermEvent::None => {}
        }
    }

    fn overlay_key(&mut self, key: KeyEvent) {
        let ov = self.overlay.as_mut().unwrap();
        let finished = ov.term.exit.is_some();
        let ev = if finished { TermEvent::Close } else { ov.term.handle_key(key) };
        if matches!(ev, TermEvent::Close | TermEvent::CloseRequested) {
            let mut ov = self.overlay.take().unwrap();
            ov.term.terminate();
            if matches!(ov.purpose, Purpose::Connect(_)) {
                self.connecting = None;
                if ov.term.exit.map_or(true, |rc| rc != 0) {
                    self.toast("Connection cancelled or failed", true);
                }
            }
        }
    }

    fn modal_key(&mut self, key: KeyEvent) {
        let Some(modal) = self.modal.take() else { return };
        match modal {
            Modal::Message { .. } => {
                if key.code == KeyCode::Esc {
                    self.connecting = None;
                } else {
                    self.modal = Some(modal);
                }
            }
            Modal::Confirm { msg, kind } => match key.code {
                KeyCode::Char('y') | KeyCode::Char('Y') | KeyCode::Enter => self.confirm(kind),
                KeyCode::Char('n') | KeyCode::Char('N') | KeyCode::Esc => {}
                _ => self.modal = Some(Modal::Confirm { msg, kind }),
            },
            Modal::Form(mut form) => match key.code {
                KeyCode::Esc => {}
                KeyCode::Enter => self.submit_form(form),
                KeyCode::Tab | KeyCode::Down => {
                    form.next(1);
                    self.modal = Some(Modal::Form(form));
                }
                KeyCode::BackTab | KeyCode::Up => {
                    form.next(-1);
                    self.modal = Some(Modal::Form(form));
                }
                _ => {
                    let i = form.focus;
                    form.fields[i].key(key);
                    form.error.clear();
                    self.modal = Some(Modal::Form(form));
                }
            },
            Modal::Overwrite { items, sel } => match key.code {
                KeyCode::Up => self.modal = Some(Modal::Overwrite { items, sel: sel.saturating_sub(1) }),
                KeyCode::Down | KeyCode::Tab => self.modal = Some(Modal::Overwrite { items, sel: (sel + 1).min(2) }),
                KeyCode::Char('o') => self.enqueue(items),
                KeyCode::Char('s') => self.enqueue(items.into_iter().filter(|i| !i.exists).collect()),
                KeyCode::Enter => match sel {
                    0 => self.enqueue(items),
                    1 => self.enqueue(items.into_iter().filter(|i| !i.exists).collect()),
                    _ => {}
                },
                KeyCode::Esc | KeyCode::Char('c') => {}
                _ => self.modal = Some(Modal::Overwrite { items, sel }),
            },
            Modal::Text { title, body, scroll } => {
                let lines = body.lines().count() as u16;
                let scroll = match key.code {
                    KeyCode::Esc | KeyCode::Char('q') | KeyCode::Enter => return,
                    KeyCode::Up => scroll.saturating_sub(1),
                    KeyCode::Down => (scroll + 1).min(lines.saturating_sub(1)),
                    KeyCode::PageUp => scroll.saturating_sub(10),
                    KeyCode::PageDown => (scroll + 10).min(lines.saturating_sub(1)),
                    _ => scroll,
                };
                self.modal = Some(Modal::Text { title, body, scroll });
            }
            Modal::Palette { mut query, sel } => {
                let items = self.palette_items(&query);
                match key.code {
                    KeyCode::Esc => {}
                    KeyCode::Enter => {
                        if let Some(it) = items.into_iter().nth(sel) {
                            self.run_action(it.action);
                        }
                    }
                    KeyCode::Up => self.modal = Some(Modal::Palette { query, sel: sel.saturating_sub(1) }),
                    KeyCode::Down => self.modal = Some(Modal::Palette { query, sel: (sel + 1).min(items.len().saturating_sub(1)) }),
                    KeyCode::Backspace => {
                        query.pop();
                        self.modal = Some(Modal::Palette { query, sel: 0 });
                    }
                    KeyCode::Char(c) if !key.modifiers.contains(KeyModifiers::CONTROL) => {
                        query.push(c);
                        self.modal = Some(Modal::Palette { query, sel: 0 });
                    }
                    _ => self.modal = Some(Modal::Palette { query, sel }),
                }
            }
            Modal::Import { mut text } => match key.code {
                KeyCode::Esc => {}
                KeyCode::Backspace => {
                    text.clear();
                    self.modal = Some(Modal::Import { text });
                }
                KeyCode::Enter => self.import_hosts(&text),
                _ => self.modal = Some(Modal::Import { text }),
            },
        }
    }

    fn import_hosts(&mut self, text: &str) {
        let (hosts, _) = parse_ssh_config(text);
        let (mut added, mut skipped) = (0, 0);
        for h in hosts {
            if self.config.get(&h.name).is_some() {
                skipped += 1;
                continue;
            }
            let (h, _) = localize_identity(h);
            if self.config.add(h).is_ok() {
                added += 1;
            }
        }
        self.toast(format!("Imported {added} host(s){}", if skipped > 0 { format!(", skipped {skipped} existing") } else { String::new() }), false);
    }

    fn on_paste(&mut self, text: &str) {
        match self.modal.as_mut() {
            Some(Modal::Form(f)) => {
                let i = f.focus;
                f.fields[i].insert(text.lines().next().unwrap_or(""));
            }
            Some(Modal::Import { text: t }) => t.push_str(text),
            Some(Modal::Palette { query, .. }) => query.push_str(text.lines().next().unwrap_or("")),
            Some(_) => {}
            None => {
                if let Some(ov) = self.overlay.as_mut() {
                    ov.term.paste(text);
                } else if let Some(c) = self.browser.as_mut().and_then(|b| b.console.as_mut()) {
                    c.term.paste(text);
                } else if self.screen == Screen::Picker && self.picker.filtering {
                    self.picker.filter.push_str(text.lines().next().unwrap_or(""));
                } else if let Some(b) = self.browser.as_mut().filter(|b| b.filtering) {
                    b.filter.push_str(text.lines().next().unwrap_or(""));
                }
            }
        }
    }

    fn on_mouse(&mut self, ev: MouseEvent) {
        // Modals: right click pastes into the focused input
        if self.modal.is_some() {
            if matches!(ev.kind, MouseEventKind::Down(MouseButton::Right)) {
                if let Some(t) = self.clip.get() {
                    self.on_paste(&t);
                }
            }
            return;
        }
        if self.overlay.is_some() {
            let area = Rect::new(0, 1, Self::term_size().0, Self::term_size().1.saturating_sub(2));
            let ov = self.overlay.as_mut().unwrap();
            if let Some(msg) = ov.term.handle_mouse(ev, area, &mut self.clip) {
                self.toast(msg, false);
            }
            return;
        }
        if self.screen == Screen::Picker {
            return self.picker_mouse(ev);
        }
        if self.browser.is_some() {
            self.browser_mouse(ev);
        }
    }

    fn picker_mouse(&mut self, ev: MouseEvent) {
        match ev.kind {
            MouseEventKind::Down(MouseButton::Left) => {
                let hit = self.picker.cards.iter().find(|(r, _)| contains(*r, ev.column, ev.row)).map(|(_, i)| *i);
                if let Some(i) = hit {
                    let double = self.picker.last_click.is_some_and(|(t, j)| j == i && t.elapsed() < DOUBLE_CLICK);
                    self.picker.cursor = i;
                    self.picker.last_click = Some((Instant::now(), i));
                    if double {
                        if let Some(h) = self.current_host() {
                            self.connect(h);
                        }
                    }
                }
            }
            MouseEventKind::ScrollUp => self.picker.cursor = self.picker.cursor.saturating_sub(2),
            MouseEventKind::ScrollDown => self.picker.cursor = (self.picker.cursor + 2).min(self.visible_hosts().len().saturating_sub(1)),
            _ => {}
        }
    }

    fn browser_mouse(&mut self, ev: MouseEvent) {
        let b = self.browser.as_mut().unwrap();
        if b.console.is_some() {
            let area = b.console_area;
            if let Some(c) = b.console.as_mut() {
                if let Some(msg) = c.term.handle_mouse(ev, area, &mut self.clip) {
                    self.toast(msg, false);
                }
            }
            return;
        }
        let row_at = |area: Rect, offset: usize, y: u16| -> Option<usize> {
            // border + header row
            (y >= area.y + 2).then(|| (y - area.y - 2) as usize + offset)
        };
        let pane_at = |b: &Browser, x: u16, y: u16| {
            if contains(b.remote_area, x, y) {
                Some(Pane::Remote)
            } else if b.split && contains(b.local_area, x, y) {
                Some(Pane::Local)
            } else {
                None
            }
        };
        match ev.kind {
            MouseEventKind::Down(MouseButton::Left) => {
                if contains(b.hosts_area, ev.column, ev.row) && ev.row > b.hosts_area.y {
                    let i = (ev.row - b.hosts_area.y - 1) as usize;
                    if let Some(h) = self.config.hosts.get(i).cloned() {
                        if h.name != b.host.name {
                            self.run_action(Action::Connect(h.name));
                        }
                    }
                    return;
                }
                let Some(pane) = pane_at(b, ev.column, ev.row) else { return };
                b.focus = pane;
                let (area, offset, len) = match pane {
                    Pane::Remote => (b.remote_area, b.state.offset(), b.visible().len()),
                    Pane::Local => (b.local_area, b.local_state.offset(), b.visible_local().len()),
                };
                let Some(i) = row_at(area, offset, ev.row).filter(|&i| i < len) else { return };
                let double = b.last_click.is_some_and(|(t, p, j)| p == pane && j == i && t.elapsed() < DOUBLE_CLICK);
                b.last_click = Some((Instant::now(), pane, i));
                let name = match pane {
                    Pane::Remote => {
                        b.cursor = i;
                        b.current().map(|e| e.name)
                    }
                    Pane::Local => {
                        b.local_cursor = i;
                        b.current_local().map(|e| e.name)
                    }
                };
                b.drag = name.filter(|n| n != "..").map(|n| (pane, n));
                if double {
                    b.drag = None;
                    self.open_entry();
                }
            }
            MouseEventKind::Up(MouseButton::Left) => {
                let Some((from, name)) = b.drag.take() else { return };
                let Some(to) = pane_at(b, ev.column, ev.row) else { return };
                if to == from {
                    return;
                }
                // drag & drop between panes: moves the marked rows if the dragged one is marked, else just that row
                match from {
                    Pane::Remote => {
                        let names = if b.selected.contains(&name) { b.targets() } else { vec![name] };
                        let dest = b.local_cwd.clone();
                        self.do_download(names, dest);
                    }
                    Pane::Local => {
                        let names = if b.local_selected.contains(&name) { b.local_targets() } else { vec![name] };
                        let items = names.iter().map(|n| self.up_item(&self.browser.as_ref().unwrap().local_cwd.join(n))).collect();
                        self.submit(items);
                    }
                }
            }
            MouseEventKind::ScrollUp | MouseEventKind::ScrollDown => {
                let Some(pane) = pane_at(b, ev.column, ev.row) else { return };
                let up = matches!(ev.kind, MouseEventKind::ScrollUp);
                let len = match pane {
                    Pane::Remote => b.visible().len(),
                    Pane::Local => b.visible_local().len(),
                };
                let cursor = if pane == Pane::Remote { &mut b.cursor } else { &mut b.local_cursor };
                *cursor = if up { cursor.saturating_sub(3) } else { (*cursor + 3).min(len.saturating_sub(1)) };
            }
            _ => {}
        }
    }
}

fn contains(r: Rect, x: u16, y: u16) -> bool {
    x >= r.x && y >= r.y && x < r.x + r.width && y < r.y + r.height
}

/// A typed character that should drive quick select (plain printable key, not a bound key).
fn quick_char(key: &KeyEvent) -> bool {
    match key.code {
        KeyCode::Char(c) => {
            !(key.modifiers.contains(KeyModifiers::CONTROL) || key.modifiers.contains(KeyModifiers::ALT) || key.modifiers.contains(KeyModifiers::SUPER))
                && !c.is_control()
                && !" ./".contains(c)
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn press(c: KeyCode, m: KeyModifiers) -> KeyEvent {
        KeyEvent::new(c, m)
    }

    #[test]
    fn fuzzy_matching() {
        assert!(fuzzy("", "anything").is_some());
        assert!(fuzzy("sync", "Sync directory").unwrap() > fuzzy("sd", "Sync directory").unwrap());
        assert!(fuzzy("sd", "Sync directory").is_some());
        assert!(fuzzy("zz", "Sync directory").is_none());
    }

    #[test]
    fn quick_char_excludes_bound_keys() {
        assert!(quick_char(&press(KeyCode::Char('a'), KeyModifiers::NONE)));
        assert!(quick_char(&press(KeyCode::Char('A'), KeyModifiers::SHIFT)));
        assert!(!quick_char(&press(KeyCode::Char('a'), KeyModifiers::ALT)));
        assert!(!quick_char(&press(KeyCode::Char('.'), KeyModifiers::NONE)));
        assert!(!quick_char(&press(KeyCode::Char('/'), KeyModifiers::NONE)));
        assert!(!quick_char(&press(KeyCode::Char(' '), KeyModifiers::NONE)));
    }

    #[test]
    fn palette_lists_actions_and_hosts() {
        let mut app = App::new();
        app.config = SshConfig { path: std::env::temp_dir().join("sshfm-pal"), hosts: vec![Host::new("web1")] };
        let items = app.palette_items("");
        assert!(items.iter().any(|i| i.action == Action::NewHost));
        assert!(items.iter().any(|i| i.action == Action::Connect("web1".into())));
        assert!(!items.iter().any(|i| i.action == Action::Upload), "browser actions hidden on picker");
        let only = app.palette_items("web1");
        assert_eq!(only[0].action, Action::Connect("web1".into()));
    }

    #[test]
    fn host_form_roundtrip() {
        let mut app = App::new();
        app.config = SshConfig { path: std::env::temp_dir().join("sshfm-hf"), hosts: vec![] };
        let mut h = Host::new("db");
        h.hostname = "10.1.1.1".into();
        h.user = "root".into();
        h.password_auth = true;
        h.proxy_jump = "bastion".into();
        h.local_forwards = vec!["5432 localhost:5432".into(), "8080 localhost:80".into()];
        let form = app.host_form(Some(&h));
        assert_eq!(app.build_host(&form).unwrap(), h);
        let mut bad = app.host_form(Some(&h));
        bad.fields[2].value = "abc".into();
        assert!(app.build_host(&bad).is_err());
    }
}
