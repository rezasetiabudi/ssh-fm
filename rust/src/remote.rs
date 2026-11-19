//! All access to remote hosts (ssh / rsync). UI-free so it can be tested.

use std::collections::HashMap;
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use regex::Regex;

pub const MAX_VIEW_BYTES: u64 = 10_000;

#[derive(Clone, Debug, PartialEq)]
pub struct Entry {
    pub name: String,
    pub is_dir: bool,
    pub is_link: bool,
    pub size: u64,
    pub perms: String,
    pub owner: String,
    pub group: String,
    pub mtime: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Progress {
    pub percent: u8,
    pub speed: String,
    pub eta: String,
}

pub fn parse_ls(output: &str) -> Vec<Entry> {
    let (mut dirs, mut files) = (vec![], vec![]);
    for line in output.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 9 || line.starts_with("total") {
            continue;
        }
        // The name is everything after the 8th field, spaces preserved.
        let mut rest = line.trim_start();
        for _ in 0..8 {
            rest = rest.trim_start_matches(|c: char| !c.is_whitespace()).trim_start();
        }
        let mut name = rest.to_string();
        let perms = parts[0];
        let is_link = perms.starts_with('l');
        if is_link {
            if let Some((n, _)) = name.split_once(" -> ") {
                name = n.to_string();
            }
        }
        if name == "." || name == ".." {
            continue;
        }
        let entry = Entry {
            name,
            is_dir: perms.starts_with('d'),
            is_link,
            size: parts[4].parse().unwrap_or(0),
            perms: perms.into(),
            owner: parts[2].into(),
            group: parts[3].into(),
            mtime: format!("{} {} {}", parts[5], parts[6], parts[7]),
        };
        if entry.is_dir { dirs.push(entry) } else { files.push(entry) }
    }
    let key = |e: &Entry| e.name.to_lowercase();
    dirs.sort_by_key(key);
    files.sort_by_key(key);
    dirs.extend(files);
    dirs
}

pub fn join_path(base: &str, name: &str) -> String {
    if name == ".." {
        if base == "~" || base.ends_with("/..") {
            return format!("{}/..", base.trim_end_matches('/'));
        }
        if base.starts_with("~/") && base.matches('/').count() == 1 {
            return "~".into();
        }
        let trimmed = base.trim_end_matches('/');
        return match trimmed.rfind('/') {
            Some(0) | None => "/".into(),
            Some(i) => trimmed[..i].to_string(),
        };
    }
    format!("{}/{}", base.trim_end_matches('/'), name)
}

pub fn parse_progress(line: &str) -> Option<Progress> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"(\d+)%\s+(\S+/s)\s+(\d+:\d+:\d+)").unwrap());
    let c = re.captures_iter(line).last()?;
    Some(Progress { percent: c[1].parse().ok()?, speed: c[2].into(), eta: c[3].into() })
}

/// Shell-quote like Python's shlex.quote.
pub fn shquote(s: &str) -> String {
    if !s.is_empty() && s.chars().all(|c| c.is_ascii_alphanumeric() || "@%+=:,./-_".contains(c)) {
        return s.to_string();
    }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

/// Quote for a remote shell while keeping a leading ~ expandable.
pub fn quote_path(path: &str) -> String {
    if path == "~" {
        "~".into()
    } else if let Some(rest) = path.strip_prefix("~/") {
        format!("~/{}", shquote(rest))
    } else {
        shquote(path)
    }
}

pub fn perms_to_octal(perms: &str) -> String {
    let bits: Vec<char> = perms.chars().collect();
    if bits.len() < 9 {
        return String::new();
    }
    let bits = &bits[bits.len() - 9..];
    bits.chunks(3)
        .map(|c| {
            let v = (c[0] == 'r') as u8 * 4 + (c[1] == 'w') as u8 * 2 + "xst".contains(c[2]) as u8;
            char::from(b'0' + v)
        })
        .collect()
}

pub fn valid_mode(mode: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"^([0-7]{3,4}|[ugoa]*[-+=][rwxXst]+(,[ugoa]*[-+=][rwxXst]+)*)$").unwrap()
    })
    .is_match(mode)
}

pub fn human(n: u64) -> String {
    let mut v = n as f64;
    for unit in ["B", "K", "M", "G"] {
        if v < 1024.0 {
            return if unit == "B" { format!("{v:.0}B") } else { format!("{v:.1}{unit}") };
        }
        v /= 1024.0;
    }
    format!("{v:.1}T")
}

const INFO_SCRIPT: &str = concat!(
    r#"echo "ssh_conn=$SSH_CONNECTION"; echo "hostname=$(hostname)"; "#,
    r#"echo "os=$( . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -s)"; "#,
    r#"echo "kernel=$(uname -r)"; echo "arch=$(uname -m)"; echo "user=$(id -un)"; "#,
    r#"echo "uptime=$(uptime -p 2>/dev/null || uptime)"; echo "load=$(cut -d" " -f1-3 /proc/loadavg 2>/dev/null)"; "#,
    r#"echo "cpus=$(nproc 2>/dev/null)"; "#,
    r#"echo "memory=$(free -h 2>/dev/null | awk '/^Mem:/{print $3 " / " $2}')"; "#,
    r#"echo "disk=$(df -h ~ 2>/dev/null | awk 'NR==2{print $3 " / " $2 " (" $5 ")"}')""#,
);

#[derive(Clone)]
pub struct Connection {
    pub host: String,
    pub control_dir: PathBuf,
}

/// Run a command, capturing output, killing it after `timeout`.
fn run_capture(mut cmd: Command, timeout: Duration) -> Result<(i32, String, String), String> {
    cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = cmd.spawn().map_err(|e| format!("{:?}: {e}", cmd.get_program()))?;
    let drain = |mut r: Box<dyn Read + Send>| {
        std::thread::spawn(move || {
            let mut buf = Vec::new();
            let _ = r.read_to_end(&mut buf);
            String::from_utf8_lossy(&buf).into_owned()
        })
    };
    let out = drain(Box::new(child.stdout.take().unwrap()));
    let err = drain(Box::new(child.stderr.take().unwrap()));
    let start = Instant::now();
    let status = loop {
        match child.try_wait().map_err(|e| e.to_string())? {
            Some(s) => break s,
            None if start.elapsed() > timeout => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Timed out".into());
            }
            None => std::thread::sleep(Duration::from_millis(15)),
        }
    };
    Ok((status.code().unwrap_or(-1), out.join().unwrap_or_default(), err.join().unwrap_or_default()))
}

impl Connection {
    pub fn new(host: &str, control_dir: Option<PathBuf>) -> Self {
        let dir = control_dir.unwrap_or_else(|| {
            let uid = Command::new("id").arg("-u").output().ok().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string());
            std::env::temp_dir().join(format!("ssh-fm-{}", uid.unwrap_or_else(|| "u".into())))
        });
        let _ = std::fs::create_dir_all(&dir);
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700));
        }
        Connection { host: host.into(), control_dir: dir }
    }

    // --- command builders -------------------------------------------------
    pub fn ssh_opts(&self) -> Vec<String> {
        vec!["-o".into(), format!("ControlPath={}/%C", self.control_dir.display())]
    }

    fn ssh(&self, extra: &[&str]) -> Vec<String> {
        let mut v = vec!["ssh".to_string()];
        v.extend(self.ssh_opts());
        v.extend(extra.iter().map(|s| s.to_string()));
        v
    }

    pub fn master_cmd(&self, batch: bool) -> Vec<String> {
        let mut extra = vec![];
        if batch {
            extra.extend(["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]);
        }
        extra.extend(["-o", "ControlMaster=yes", "-o", "ControlPersist=10m", "-fN", &self.host]);
        self.ssh(&extra)
    }

    pub fn shell_cmd(&self) -> Vec<String> {
        self.ssh(&[&self.host])
    }

    /// Install your public key on the server (ssh-copy-id), going through the same ControlPath.
    pub fn copy_id_cmd(&self, pubkey: Option<&str>) -> Vec<String> {
        let mut v = vec!["ssh-copy-id".to_string()];
        if let Some(k) = pubkey {
            v.extend(["-i".into(), k.into()]);
        }
        v.extend(["-o".into(), format!("ControlPath={}/%C", self.control_dir.display()), self.host.clone()]);
        v
    }

    pub fn sftp_cmd(&self, path: Option<&str>) -> Result<Vec<String>, String> {
        let target = match path {
            Some(p) => format!("{}:{}", self.host, self.expand(p)?),
            None => self.host.clone(),
        };
        let mut v = vec!["sftp".to_string()];
        v.extend(self.ssh_opts());
        v.push(target);
        Ok(v)
    }

    pub fn list_cmd(&self, path: &str) -> String {
        format!("LC_ALL=C ls -la -- {}", quote_path(path))
    }

    pub fn transfer_cmd(&self, up: bool, local: &str, remote: &str) -> Vec<String> {
        let ssh = format!("ssh {}", self.ssh_opts().iter().map(|o| shquote(o)).collect::<Vec<_>>().join(" "));
        let mut v: Vec<String> = ["rsync", "-az", "-s", "--info=progress2", "-e", &ssh].map(String::from).to_vec();
        let remote = format!("{}:{}", self.host, remote);
        if up { v.extend([local.into(), remote]) } else { v.extend([remote, local.into()]) }
        v
    }

    // --- master connection ------------------------------------------------
    /// Silent attempt (no prompts). Returns (exit code, stderr).
    pub fn try_master(&self) -> (i32, String) {
        let args = self.master_cmd(true);
        let mut c = Command::new(&args[0]);
        c.args(&args[1..]);
        match run_capture(c, Duration::from_secs(30)) {
            Ok((rc, _, err)) => (rc, err),
            Err(e) => (-1, e),
        }
    }

    pub fn is_alive(&self) -> bool {
        let args = self.ssh(&["-O", "check", &self.host]);
        let mut c = Command::new(&args[0]);
        c.args(&args[1..]);
        matches!(run_capture(c, Duration::from_secs(10)), Ok((0, _, _)))
    }

    pub fn close(&self) {
        let args = self.ssh(&["-O", "exit", &self.host]);
        let mut c = Command::new(&args[0]);
        c.args(&args[1..]);
        let _ = run_capture(c, Duration::from_secs(5));
    }

    // --- remote commands --------------------------------------------------
    pub fn run(&self, command: &str) -> Result<String, String> {
        let args = self.ssh(&["-o", "BatchMode=yes", &self.host, command]);
        let mut c = Command::new(&args[0]);
        c.args(&args[1..]);
        match run_capture(c, Duration::from_secs(15)) {
            Err(e) if e == "Timed out" => Err(format!("Timed out running: {command}")),
            Err(e) => Err(e),
            Ok((0, out, _)) => Ok(out),
            Ok((rc, _, err)) => {
                let err = err.trim();
                Err(if err.is_empty() { format!("exit status {rc}") } else { err.to_string() })
            }
        }
    }

    pub fn home(&self) -> Result<String, String> {
        Ok(self.run("printf %s \"$HOME\"")?.trim().to_string())
    }

    /// Resolve a leading ~ (rsync -s does not expand it).
    pub fn expand(&self, path: &str) -> Result<String, String> {
        if path == "~" || path.starts_with("~/") {
            Ok(format!("{}{}", self.home()?, &path[1..]))
        } else {
            Ok(path.to_string())
        }
    }

    pub fn list_dir(&self, path: &str) -> Result<Vec<Entry>, String> {
        Ok(parse_ls(&self.run(&self.list_cmd(path))?))
    }

    /// Facts about the remote machine and this SSH session (missing keys are simply absent).
    pub fn server_info(&self) -> Result<HashMap<String, String>, String> {
        let out = self.run(INFO_SCRIPT)?;
        let mut info: HashMap<String, String> = out
            .lines()
            .filter_map(|l| l.split_once('='))
            .map(|(k, v)| (k.to_string(), v.trim().to_string()))
            .filter(|(_, v)| !v.is_empty())
            .collect();
        if let Some(conn) = info.remove("ssh_conn") {
            let p: Vec<&str> = conn.split_whitespace().collect();
            if p.len() == 4 {
                for (k, v) in ["client_ip", "client_port", "server_ip", "server_port"].iter().zip(p) {
                    info.insert((*k).into(), v.into());
                }
            }
        }
        Ok(info)
    }

    /// (size, perms, owner, group, mtime, type) of one path.
    pub fn file_info(&self, path: &str) -> Result<Vec<(String, String)>, String> {
        let q = quote_path(path);
        let out = self
            .run(&format!("stat -c '%s|%A|%U|%G|%y' -- {q} 2>/dev/null || stat -f '%z|%Sp|%Su|%Sg|%Sm' -- {q}"))?;
        let f: Vec<&str> = out.trim().split('|').collect();
        let get = |i: usize| f.get(i).copied().unwrap_or("").to_string();
        let kind = self.run(&format!("file -b -- {q}")).map(|s| s.trim().to_string()).unwrap_or_default();
        Ok(vec![
            ("Size".into(), get(0)),
            ("Perms".into(), get(1)),
            ("Owner".into(), get(2)),
            ("Group".into(), get(3)),
            ("Modified".into(), get(4).split('.').next().unwrap_or("").to_string()),
            ("Type".into(), kind),
        ])
    }

    // --- file operations (one remote command each) --------------------------------
    pub fn remove(&self, path: &str) -> Result<(), String> {
        if matches!(path.trim_end_matches('/'), "" | "~" | "/") {
            return Err(format!("Refusing to delete {path:?}"));
        }
        self.run(&format!("rm -rf -- {}", quote_path(path))).map(|_| ())
    }

    pub fn rename(&self, old: &str, new: &str) -> Result<(), String> {
        self.run(&format!("mv -n -- {} {}", quote_path(old), quote_path(new))).map(|_| ())
    }

    pub fn mkdir(&self, path: &str) -> Result<(), String> {
        self.run(&format!("mkdir -- {}", quote_path(path))).map(|_| ())
    }

    pub fn chmod(&self, path: &str, mode: &str) -> Result<(), String> {
        if !valid_mode(mode) {
            return Err(format!("Invalid mode: {mode}"));
        }
        self.run(&format!("chmod {mode} -- {}", quote_path(path))).map(|_| ())
    }

    pub fn read_head(&self, path: &str) -> Result<String, String> {
        let q = quote_path(path);
        let size = self.run(&format!("stat -c%s -- {q} 2>/dev/null || stat -f%z -- {q}"))?;
        if let Ok(n) = size.trim().parse::<u64>() {
            if n > MAX_VIEW_BYTES {
                return Err(format!("File is too large ({n} bytes). Use download instead."));
            }
        }
        self.run(&format!("head -n 50 -- {q}"))
    }
}

/// Run rsync, streaming progress. Returns the exit code.
pub fn run_transfer(cmd: &[String], mut on_progress: impl FnMut(Progress)) -> i32 {
    let mut child = match Command::new(&cmd[0])
        .args(&cmd[1..])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => return 127,
    };
    let mut out = child.stdout.take().unwrap();
    let (mut buf, mut chunk) = (String::new(), [0u8; 256]);
    while let Ok(n) = out.read(&mut chunk) {
        if n == 0 {
            break;
        }
        buf.push_str(&String::from_utf8_lossy(&chunk[..n]));
        while let Some(i) = buf.find(['\r', '\n']) {
            let part: String = buf.drain(..=i).collect();
            if let Some(p) = parse_progress(&part) {
                on_progress(p);
            }
        }
    }
    child.wait().ok().and_then(|s| s.code()).unwrap_or(-1)
}

#[cfg(test)]
mod tests {
    use super::*;

    const LS: &str = "total 20
drwxr-xr-x  5 deploy www  4096 Oct 21 10:00 .
drwxr-xr-x  3 root   root 4096 Oct 20 09:00 ..
-rw-r--r--  1 deploy www  4200 Oct 21 10:00 index.php
drwxr-xr-x  2 deploy www  4096 Oct 21 10:00 logs
drwxr-xr-x  2 deploy www  4096 Oct 21 10:00 App
-rw-------  1 deploy www   312 Oct 21 10:00 my file -> not a link.txt
lrwxrwxrwx  1 deploy www    11 Oct 21 10:00 current -> releases/42
";

    #[test]
    fn ls_dirs_first_sorted() {
        let names: Vec<_> = parse_ls(LS).into_iter().map(|e| e.name).collect();
        assert_eq!(names, ["App", "logs", "current", "index.php", "my file -> not a link.txt"]);
        let first = &parse_ls(LS)[0];
        assert!(first.is_dir && first.owner == "deploy" && first.group == "www");
    }

    #[test]
    fn ls_spaces_arrow_symlink_and_noise() {
        let es = parse_ls(LS);
        let e = es.iter().find(|e| e.name.starts_with("my file")).unwrap();
        assert!(!e.is_link && e.size == 312);
        assert!(es.iter().find(|e| e.name == "current").unwrap().is_link);
        assert!(es.iter().all(|e| e.name != "." && e.name != ".."));
        assert!(parse_ls("").is_empty());
    }

    #[test]
    fn join_path_cases() {
        assert_eq!(join_path("~", "a"), "~/a");
        assert_eq!(join_path("/", "a"), "/a");
        assert_eq!(join_path("/var/www", ".."), "/var");
        assert_eq!(join_path("/var", ".."), "/");
        assert_eq!(join_path("~", ".."), "~/..");
        assert_eq!(join_path("~/x", ".."), "~");
        assert_eq!(join_path("/var/www/", "x y"), "/var/www/x y");
    }

    #[test]
    fn progress_variants() {
        let p = parse_progress("  1,234,567  68%   12.40MB/s    0:00:04 (xfr#1, to-chk=0/1)").unwrap();
        assert_eq!(p, Progress { percent: 68, speed: "12.40MB/s".into(), eta: "0:00:04".into() });
        assert_eq!(parse_progress("\r  100%  1.00kB/s  0:00:00\r  200  50%  2.00MB/s  0:00:09").unwrap().percent, 50);
        assert!(parse_progress("sending incremental file list").is_none());
    }

    #[test]
    fn quoting_prevents_injection() {
        let c = Connection::new("web", Some(std::env::temp_dir().join("sshfm-t1")));
        assert_eq!(c.list_cmd("/srv/a; rm -rf ~"), "LC_ALL=C ls -la -- '/srv/a; rm -rf ~'");
        assert_eq!(c.list_cmd("~/my dir"), "LC_ALL=C ls -la -- ~/'my dir'");
        assert_eq!(shquote("it's"), "'it'\"'\"'s'");
    }

    #[test]
    fn transfer_uses_control_path_and_protect_args() {
        let c = Connection::new("web", Some(std::env::temp_dir().join("sshfm-t2")));
        let up = c.transfer_cmd(true, "/l/f", "/r/f");
        assert!(up.contains(&"-s".to_string()));
        assert!(up.iter().any(|a| a.contains("ControlPath=")));
        assert_eq!(&up[up.len() - 2..], ["/l/f", "web:/r/f"]);
        let down = c.transfer_cmd(false, "/l/f", "/r/f");
        assert_eq!(&down[down.len() - 2..], ["web:/r/f", "/l/f"]);
    }

    #[test]
    fn mode_and_perms() {
        assert_eq!(perms_to_octal("-rwxr-xr--"), "754");
        assert_eq!(perms_to_octal("drwxr-xr-x"), "755");
        assert!(valid_mode("755") && valid_mode("u+x") && valid_mode("go-w,u+x"));
        assert!(!valid_mode("755; rm") && !valid_mode("abc"));
    }

    #[test]
    fn refuses_dangerous_delete() {
        let c = Connection::new("web", Some(std::env::temp_dir().join("sshfm-t3")));
        assert!(c.remove("/").is_err() && c.remove("~").is_err() && c.remove("").is_err());
    }

    #[test]
    fn human_sizes() {
        assert_eq!(human(512), "512B");
        assert_eq!(human(2048), "2.0K");
    }
}
