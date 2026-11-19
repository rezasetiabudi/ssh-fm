//! Hosts stored in ~/.ssh/config, plus a tiny JSON store for UI memory.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Host {
    pub name: String,
    pub hostname: String,
    pub port: String,
    pub user: String,
    pub identity_file: String,
    pub password_auth: bool,
    /// `ProxyJump` (bastion), e.g. `user@bastion:22`.
    pub proxy_jump: String,
    /// `LocalForward` entries, e.g. `8080 localhost:80`.
    pub local_forwards: Vec<String>,
}

impl Host {
    pub fn new(name: &str) -> Self {
        Host { name: name.into(), port: "22".into(), ..Default::default() }
    }

    pub fn target(&self) -> String {
        let user = if self.user.is_empty() { String::new() } else { format!("{}@", self.user) };
        let host = if self.hostname.is_empty() { &self.name } else { &self.hostname };
        format!("{user}{host}:{}", self.port)
    }

    pub fn auth_label(&self) -> String {
        if self.password_auth {
            "password".into()
        } else {
            match self.identity_file.rsplit('/').next() {
                Some(f) if !f.is_empty() => f.into(),
                _ => "default key".into(),
            }
        }
    }
}

const SUPPORTED: [&str; 7] =
    ["hostname", "port", "user", "identityfile", "passwordauthentication", "proxyjump", "localforward"];

pub fn home_dir() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}

fn expand_home(p: &str) -> String {
    match p.strip_prefix("~/") {
        Some(rest) => home_dir().join(rest).to_string_lossy().into_owned(),
        None => p.to_string(),
    }
}

/// `Key value`, `Key=value` or `Key = value` -> (lowercase key, value) without trailing `# comment` and quotes.
fn split_option(line: &str) -> Option<(String, String)> {
    let idx = line.find(|c: char| c.is_whitespace() || c == '=')?;
    let key = &line[..idx];
    if key.is_empty() {
        return None;
    }
    let rest = line[idx..].trim_start();
    let rest = rest.strip_prefix('=').unwrap_or(rest).trim();
    let mut value = rest.to_string();
    if !value.starts_with('"') {
        if let Some(pos) = value.find(" #").or_else(|| value.find("\t#")) {
            value.truncate(pos);
        }
        value = value.trim().to_string();
    }
    Some((key.to_lowercase(), value.trim_matches('"').to_string()))
}

/// Parse ssh_config text -> (hosts in file order, unsupported option names per host).
/// `Host a b` yields both; wildcard patterns and `Match` blocks are skipped.
pub fn parse_ssh_config(text: &str) -> (Vec<Host>, HashMap<String, Vec<String>>) {
    let mut hosts: Vec<Host> = Vec::new();
    let mut ignored: HashMap<String, Vec<String>> = HashMap::new();
    let mut current: Vec<usize> = Vec::new();
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = split_option(line) else { continue };
        if key == "host" {
            current.clear();
            for name in value.split_whitespace() {
                if !name.contains(['*', '?', '!']) && !hosts.iter().any(|h| h.name == name) {
                    hosts.push(Host::new(name));
                    ignored.insert(name.to_string(), vec![]);
                    current.push(hosts.len() - 1);
                }
            }
            continue;
        }
        if key == "match" {
            current.clear();
            continue;
        }
        for &i in &current {
            let h = &mut hosts[i];
            match key.as_str() {
                "hostname" => h.hostname = value.clone(),
                "port" => h.port = value.clone(),
                "user" => h.user = value.clone(),
                "identityfile" => {
                    if h.identity_file.is_empty() {
                        h.identity_file = expand_home(&value); // ssh tries them in order; keep the first
                    }
                }
                "passwordauthentication" => h.password_auth = value.eq_ignore_ascii_case("yes"),
                "proxyjump" => h.proxy_jump = value.clone(),
                "localforward" => h.local_forwards.push(value.clone()),
                k if !SUPPORTED.contains(&k) => {
                    let list = ignored.entry(h.name.clone()).or_default();
                    if !list.iter().any(|x| x == k) {
                        list.push(k.to_string());
                    }
                }
                _ => {}
            }
        }
    }
    (hosts, ignored)
}

/// A key path copied from someone else's config rarely exists here: use ~/.ssh/<same filename>, else clear it.
pub fn localize_identity(mut host: Host) -> (Host, String) {
    if host.identity_file.is_empty() || Path::new(&host.identity_file).exists() {
        return (host, String::new());
    }
    let file = Path::new(&host.identity_file).file_name().map(|f| f.to_owned()).unwrap_or_default();
    let local = home_dir().join(".ssh").join(file);
    if local.exists() {
        let note = format!("key -> {}", local.display());
        host.identity_file = local.to_string_lossy().into_owned();
        (host, note)
    } else {
        let note = format!("key {} not found here - set one with Edit", host.identity_file);
        host.identity_file.clear();
        (host, note)
    }
}

pub struct State {
    path: PathBuf,
    data: serde_json::Map<String, serde_json::Value>,
}

impl State {
    pub fn new(path: Option<PathBuf>) -> Self {
        let path = path.unwrap_or_else(|| {
            let base = std::env::var_os("XDG_STATE_HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|| home_dir().join(".local/state"));
            base.join("ssh-fm/state.json")
        });
        let data = fs::read_to_string(&path)
            .ok()
            .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default();
        State { path, data }
    }

    pub fn get(&self, key: &str) -> Option<String> {
        self.data.get(key).and_then(|v| v.as_str()).map(String::from)
    }

    pub fn set(&mut self, key: &str, value: &str) {
        if self.get(key).as_deref() == Some(value) {
            return;
        }
        self.data.insert(key.into(), value.into());
        if let Some(dir) = self.path.parent() {
            let _ = fs::create_dir_all(dir);
        }
        let _ = fs::write(&self.path, serde_json::to_string_pretty(&self.data).unwrap_or_default());
    }
}

pub struct SshConfig {
    pub path: PathBuf,
    pub hosts: Vec<Host>,
}

impl SshConfig {
    pub fn new(path: Option<PathBuf>) -> Self {
        let path = path.unwrap_or_else(|| home_dir().join(".ssh/config"));
        let mut c = SshConfig { path, hosts: vec![] };
        c.load();
        c
    }

    pub fn load(&mut self) {
        self.hosts = fs::read_to_string(&self.path).map(|t| parse_ssh_config(&t).0).unwrap_or_default();
    }

    pub fn get(&self, name: &str) -> Option<&Host> {
        self.hosts.iter().find(|h| h.name == name)
    }

    pub fn render(&self) -> String {
        let home = home_dir().to_string_lossy().into_owned();
        let mut lines: Vec<String> = vec!["IgnoreUnknown UseKeychain".into()];
        for h in &self.hosts {
            lines.push(format!("Host {}", h.name));
            if !h.hostname.is_empty() {
                lines.push(format!("  HostName {}", h.hostname));
            }
            if h.port != "22" && !h.port.is_empty() {
                lines.push(format!("  Port {}", h.port));
            }
            if !h.user.is_empty() {
                lines.push(format!("  User {}", h.user));
            }
            if !h.identity_file.is_empty() {
                let mut ident = h.identity_file.replace(&home, "~");
                if ident.contains(' ') {
                    ident = format!("\"{ident}\"");
                }
                lines.push(format!("  IdentityFile {ident}"));
            }
            lines.push("  IdentitiesOnly yes".into());
            if h.password_auth {
                lines.push("  PasswordAuthentication yes".into());
            }
            if !h.proxy_jump.is_empty() {
                lines.push(format!("  ProxyJump {}", h.proxy_jump));
            }
            for f in &h.local_forwards {
                lines.push(format!("  LocalForward {f}"));
            }
            lines.push(String::new());
        }
        lines.extend(["Host *", "  AddKeysToAgent yes", "  ServerAliveInterval 60", "  ServerAliveCountMax 3"].map(String::from));
        if cfg!(target_os = "macos") {
            lines.push("  UseKeychain yes".into());
        }
        lines.join("\n")
    }

    pub fn save(&self) -> Result<(), String> {
        if let Some(dir) = self.path.parent() {
            fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        fs::write(&self.path, self.render()).map_err(|e| e.to_string())
    }

    fn check(&self, host: &mut Host, old: Option<&str>) -> Result<(), String> {
        let name = host.name.trim().to_string();
        if name.is_empty() || name.contains(char::is_whitespace) || (Some(name.as_str()) != old && self.get(&name).is_some()) {
            return Err(format!("Invalid or duplicate host name: {:?}", host.name));
        }
        host.name = name;
        if host.port.trim().is_empty() {
            host.port = "22".into();
        }
        Ok(())
    }

    pub fn add(&mut self, mut host: Host) -> Result<(), String> {
        self.check(&mut host, None)?;
        self.hosts.push(host);
        self.save()
    }

    pub fn update(&mut self, old: &str, mut host: Host) -> Result<(), String> {
        self.check(&mut host, Some(old))?;
        match self.hosts.iter_mut().find(|h| h.name == old) {
            Some(slot) => *slot = host, // keeps ordering when renaming
            None => self.hosts.push(host),
        }
        self.save()
    }

    pub fn delete(&mut self, name: &str) -> Result<(), String> {
        self.hosts.retain(|h| h.name != name);
        self.save()
    }
}

/// Private keys in ~/.ssh: `id_*`, `*.pem`, `*.key` (never `.pub`).
pub fn find_keys(dir: Option<&Path>) -> Vec<PathBuf> {
    let dir = dir.map(Path::to_path_buf).unwrap_or_else(|| home_dir().join(".ssh"));
    let mut keys: Vec<PathBuf> = fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            let ext = p.extension().and_then(|e| e.to_str()).unwrap_or("");
            p.is_file() && ext != "pub" && (name.starts_with("id_") || ext == "pem" || ext == "key")
        })
        .collect();
    keys.sort();
    keys
}

/// ssh rejects private keys readable by group/others. Returns true if the mode was changed.
pub fn ensure_key_permissions(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    match fs::metadata(path) {
        Ok(m) if m.permissions().mode() & 0o077 != 0 => {
            fs::set_permissions(path, fs::Permissions::from_mode(0o600)).is_ok()
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"
Host web db
  HostName 10.0.0.5   # primary
  User deploy
  Port=2222
  IdentityFile ~/.ssh/id_ed25519
  IdentityFile ~/.ssh/other
  ForwardAgent yes
  ProxyJump bastion
  LocalForward 8080 localhost:80

Host *
  ServerAliveInterval 60

Host pw
  HostName "example.com"
  PasswordAuthentication yes
Match host foo
  User nobody
"#;

    #[test]
    fn parses_multi_alias_and_skips_wildcards() {
        let (hosts, ignored) = parse_ssh_config(SAMPLE);
        let names: Vec<_> = hosts.iter().map(|h| h.name.as_str()).collect();
        assert_eq!(names, ["web", "db", "pw"]);
        let web = &hosts[0];
        assert_eq!(web.hostname, "10.0.0.5");
        assert_eq!(web.port, "2222");
        assert_eq!(web.user, "deploy");
        assert!(web.identity_file.ends_with(".ssh/id_ed25519"), "{}", web.identity_file);
        assert_eq!(web.proxy_jump, "bastion");
        assert_eq!(web.local_forwards, ["8080 localhost:80"]);
        assert_eq!(ignored["web"], ["forwardagent"]);
        assert_eq!(hosts[2].hostname, "example.com");
        assert!(hosts[2].password_auth);
    }

    #[test]
    fn save_and_load_roundtrip() {
        let dir = std::env::temp_dir().join(format!("sshfm-cfg-{}", std::process::id()));
        let mut c = SshConfig::new(Some(dir.join("config")));
        let mut h = Host::new("a");
        h.hostname = "1.2.3.4".into();
        h.user = "me".into();
        h.proxy_jump = "jump".into();
        h.local_forwards = vec!["9000 localhost:9000".into()];
        c.add(h.clone()).unwrap();
        assert!(c.add(h.clone()).is_err(), "duplicate");
        let c2 = SshConfig::new(Some(dir.join("config")));
        assert_eq!(c2.hosts, vec![h]);
        let mut renamed = c2.hosts[0].clone();
        renamed.name = "b".into();
        let mut c3 = c2;
        c3.update("a", renamed).unwrap();
        assert_eq!(c3.hosts[0].name, "b");
        c3.delete("b").unwrap();
        assert!(SshConfig::new(Some(dir.join("config"))).hosts.is_empty());
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn invalid_names_rejected() {
        let mut c = SshConfig { path: std::env::temp_dir().join("sshfm-unused"), hosts: vec![] };
        assert!(c.add(Host::new("  ")).is_err());
        assert!(c.add(Host::new("has space")).is_err());
    }

    #[test]
    fn key_permissions_fixed() {
        use std::os::unix::fs::PermissionsExt;
        let p = std::env::temp_dir().join(format!("sshfm-key-{}", std::process::id()));
        fs::write(&p, "k").unwrap();
        fs::set_permissions(&p, fs::Permissions::from_mode(0o644)).unwrap();
        assert!(ensure_key_permissions(&p));
        assert!(!ensure_key_permissions(&p));
        let _ = fs::remove_file(p);
    }
}
