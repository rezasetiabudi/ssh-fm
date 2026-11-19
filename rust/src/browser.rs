//! Data for the remote browser screen (no drawing, no I/O except local listing).

use std::collections::{HashMap, HashSet, VecDeque};
use std::path::{Path, PathBuf};
use std::time::Instant;

use ratatui::layout::Rect;
use ratatui::widgets::TableState;

use crate::config::Host;
use crate::quickselect::QuickSelect;
use crate::remote::{Connection, Entry, Progress};
use crate::terminal::Terminal;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Pane {
    Remote,
    Local,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LocalEntry {
    pub name: String,
    pub is_dir: bool,
    pub size: u64,
}

pub fn list_local(dir: &Path, show_hidden: bool) -> Result<Vec<LocalEntry>, String> {
    let rd = std::fs::read_dir(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    let mut out: Vec<LocalEntry> = rd
        .flatten()
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().into_owned();
            if !show_hidden && name.starts_with('.') {
                return None;
            }
            let md = e.metadata().ok()?; // follows nothing; fine for display
            let is_dir = md.is_dir() || (md.file_type().is_symlink() && e.path().is_dir());
            Some(LocalEntry { name, is_dir, size: md.len() })
        })
        .collect();
    out.sort_by_key(|e| (!e.is_dir, e.name.to_lowercase()));
    Ok(out)
}

pub enum RecState {
    Queued,
    Running(Progress),
    Done(bool),
}

pub struct TransferRec {
    pub label: String,
    pub state: RecState,
}

pub struct Console {
    pub title: String,
    pub term: Terminal,
}

pub struct Browser {
    pub host: Host,
    pub conn: Connection,
    pub cwd: String,
    pub entries: Vec<Entry>,
    pub loading: bool,
    pub error: String,
    pub show_hidden: bool,
    pub selected: HashSet<String>,
    pub cursor: usize,
    pub state: TableState,
    pub filter: String,
    pub filtering: bool,
    pub pending_focus: Option<String>,
    pub info: Vec<(String, String)>,
    pub info_for: Option<String>,
    pub info_wanted: Option<(String, Instant)>,
    pub quick: QuickSelect,
    // split view
    pub split: bool,
    pub focus: Pane,
    pub local_cwd: PathBuf,
    pub local_entries: Vec<LocalEntry>,
    pub local_selected: HashSet<String>,
    pub local_cursor: usize,
    pub local_state: TableState,
    pub local_error: String,
    // transfers
    pub records: Vec<TransferRec>,
    pub queue: VecDeque<(usize, crate::modal::TransferItem)>,
    pub running: bool,
    // console mode
    pub console: Option<Console>,
    pub server: Option<Result<HashMap<String, String>, String>>,
    // drawn geometry (for mouse)
    pub remote_area: Rect,
    pub local_area: Rect,
    pub console_area: Rect,
    pub hosts_area: Rect,
    pub drag: Option<(Pane, String)>,
    pub last_click: Option<(Instant, Pane, usize)>,
}

impl Browser {
    pub fn new(host: Host, conn: Connection, local_cwd: PathBuf) -> Self {
        Browser {
            host,
            conn,
            cwd: "~".into(),
            entries: vec![],
            loading: true,
            error: String::new(),
            show_hidden: true,
            selected: HashSet::new(),
            cursor: 0,
            state: TableState::default(),
            filter: String::new(),
            filtering: false,
            pending_focus: None,
            info: vec![],
            info_for: None,
            info_wanted: None,
            quick: QuickSelect::default(),
            split: false,
            focus: Pane::Remote,
            local_cwd,
            local_entries: vec![],
            local_selected: HashSet::new(),
            local_cursor: 0,
            local_state: TableState::default(),
            local_error: String::new(),
            records: vec![],
            queue: VecDeque::new(),
            running: false,
            console: None,
            server: None,
            remote_area: Rect::default(),
            local_area: Rect::default(),
            console_area: Rect::default(),
            hosts_area: Rect::default(),
            drag: None,
            last_click: None,
        }
    }

    /// Entries shown in the remote table: a synthetic `..`, then dirs/files after hidden + filter rules.
    pub fn visible(&self) -> Vec<Entry> {
        let f = self.filter.to_lowercase();
        let mut out = vec![];
        if self.cwd != "/" {
            out.push(Entry {
                name: "..".into(),
                is_dir: true,
                is_link: false,
                size: 0,
                perms: String::new(),
                owner: String::new(),
                group: String::new(),
                mtime: String::new(),
            });
        }
        out.extend(
            self.entries
                .iter()
                .filter(|e| (self.show_hidden || !e.name.starts_with('.')) && (f.is_empty() || e.name.to_lowercase().contains(&f)))
                .cloned(),
        );
        out
    }

    pub fn visible_local(&self) -> Vec<LocalEntry> {
        let mut out = vec![];
        if self.local_cwd.parent().is_some() {
            out.push(LocalEntry { name: "..".into(), is_dir: true, size: 0 });
        }
        out.extend(self.local_entries.iter().cloned());
        out
    }

    pub fn current(&self) -> Option<Entry> {
        self.visible().into_iter().nth(self.cursor)
    }

    pub fn current_local(&self) -> Option<LocalEntry> {
        self.visible_local().into_iter().nth(self.local_cursor)
    }

    /// Names to act on: the marked ones (in listing order), else the highlighted one.
    pub fn targets(&self) -> Vec<String> {
        let marked: Vec<String> = self.entries.iter().filter(|e| self.selected.contains(&e.name)).map(|e| e.name.clone()).collect();
        if !marked.is_empty() {
            return marked;
        }
        self.current().filter(|e| e.name != "..").map(|e| vec![e.name]).unwrap_or_default()
    }

    pub fn local_targets(&self) -> Vec<String> {
        let marked: Vec<String> =
            self.local_entries.iter().filter(|e| self.local_selected.contains(&e.name)).map(|e| e.name.clone()).collect();
        if !marked.is_empty() {
            return marked;
        }
        self.current_local().filter(|e| e.name != "..").map(|e| vec![e.name]).unwrap_or_default()
    }

    pub fn clamp(&mut self) {
        let n = self.visible().len();
        self.cursor = self.cursor.min(n.saturating_sub(1));
        let m = self.visible_local().len();
        self.local_cursor = self.local_cursor.min(m.saturating_sub(1));
    }

    pub fn reload_local(&mut self) {
        match list_local(&self.local_cwd, true) {
            Ok(v) => {
                self.local_entries = v;
                self.local_error.clear();
            }
            Err(e) => {
                self.local_entries.clear();
                self.local_error = e;
            }
        }
        self.local_selected.retain(|n| self.local_entries.iter().any(|e| &e.name == n));
        self.clamp();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(name: &str, dir: bool) -> Entry {
        Entry { name: name.into(), is_dir: dir, is_link: false, size: 1, perms: "-rw-r--r--".into(), owner: "o".into(), group: "g".into(), mtime: "Jan 1 00:00".into() }
    }

    fn browser() -> Browser {
        let mut b = Browser::new(Host::new("h"), Connection::new("h", Some(std::env::temp_dir().join("sshfm-b"))), std::env::temp_dir());
        b.cwd = "/srv".into();
        b.entries = vec![entry("app", true), entry(".env", false), entry("index.php", false)];
        b
    }

    #[test]
    fn visible_adds_parent_and_applies_hidden_and_filter() {
        let mut b = browser();
        assert_eq!(b.visible().iter().map(|e| e.name.as_str()).collect::<Vec<_>>(), ["..", "app", ".env", "index.php"]);
        b.show_hidden = false;
        assert_eq!(b.visible().len(), 3);
        b.filter = "IND".into();
        assert_eq!(b.visible().iter().map(|e| e.name.as_str()).collect::<Vec<_>>(), ["..", "index.php"]);
        b.cwd = "/".into();
        assert_eq!(b.visible().len(), 1);
    }

    #[test]
    fn targets_prefer_marked_then_cursor_never_parent() {
        let mut b = browser();
        b.cursor = 0;
        assert!(b.targets().is_empty(), ".. is never a target");
        b.cursor = 3;
        assert_eq!(b.targets(), ["index.php"]);
        b.selected.insert("app".into());
        b.selected.insert("index.php".into());
        assert_eq!(b.targets(), ["app", "index.php"]);
    }

    #[test]
    fn local_listing_sorts_dirs_first() {
        let dir = std::env::temp_dir().join(format!("sshfm-ll-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("Zdir")).unwrap();
        std::fs::write(dir.join("a.txt"), "x").unwrap();
        std::fs::write(dir.join(".hid"), "x").unwrap();
        let all = list_local(&dir, true).unwrap();
        assert_eq!(all.iter().map(|e| e.name.as_str()).collect::<Vec<_>>(), ["Zdir", ".hid", "a.txt"]);
        assert_eq!(list_local(&dir, false).unwrap().len(), 2);
        assert!(list_local(&dir.join("nope"), true).is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
