//! System clipboard with an OSC 52 fallback (works over ssh / in terminals without a clipboard daemon).

use std::io::Write;

pub struct Clipboard {
    inner: Option<arboard::Clipboard>,
}

fn base64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for c in data.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if c.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if c.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    out
}

impl Clipboard {
    pub fn new() -> Self {
        Clipboard { inner: arboard::Clipboard::new().ok() }
    }

    /// Copy `text`. Always also emits OSC 52 so it works when no native clipboard is reachable.
    pub fn set(&mut self, text: &str) -> bool {
        let native = self.inner.as_mut().is_some_and(|c| c.set_text(text.to_string()).is_ok());
        let mut out = std::io::stdout();
        let _ = write!(out, "\x1b]52;c;{}\x07", base64(text.as_bytes()));
        let _ = out.flush();
        native
    }

    #[allow(dead_code)]
    pub fn inner_available(&self) -> bool {
        self.inner.is_some()
    }

    pub fn get(&mut self) -> Option<String> {
        self.inner.as_mut()?.get_text().ok().filter(|t| !t.is_empty())
    }
}

#[cfg(test)]
mod tests {
    use super::base64;

    #[test]
    fn base64_matches_reference() {
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(b"hello world"), "aGVsbG8gd29ybGQ=");
    }
}
