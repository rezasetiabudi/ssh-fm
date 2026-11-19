//! Type-ahead: plain letters jump to the first name starting with what you typed.

use std::time::{Duration, Instant};

const TIMEOUT: Duration = Duration::from_secs(1);

#[derive(Default)]
pub struct QuickSelect {
    buf: String,
    at: Option<Instant>,
}

impl QuickSelect {
    /// Index in `names` to move to. Typing the same letter again cycles through matches.
    pub fn feed(&mut self, ch: char, names: &[String], current: usize) -> Option<usize> {
        let now = Instant::now();
        if self.at.map_or(true, |t| now.duration_since(t) > TIMEOUT) {
            self.buf.clear();
        }
        self.at = Some(now);
        self.buf.extend(ch.to_lowercase());
        let n = names.len();
        if n == 0 {
            return None;
        }
        let low: Vec<String> = names.iter().map(|s| s.to_lowercase()).collect();
        let first = self.buf.chars().next().unwrap();
        if self.buf.chars().count() > 1 && self.buf.chars().all(|c| c == first) {
            return (0..n).map(|i| (current + 1 + i) % n).find(|&i| low[i].starts_with(first));
        }
        low.iter().position(|s| s.starts_with(&self.buf))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names() -> Vec<String> {
        ["alpha", "beta", "fig", "file", "gamma"].map(String::from).to_vec()
    }

    #[test]
    fn prefix_and_cycle() {
        let mut q = QuickSelect::default();
        assert_eq!(q.feed('f', &names(), 0), Some(2));
        assert_eq!(q.feed('f', &names(), 2), Some(3)); // "ff" -> next f* after current
        let mut q = QuickSelect::default();
        q.feed('f', &names(), 0);
        assert_eq!(q.feed('i', &names(), 2), Some(2));
        assert_eq!(q.feed('l', &names(), 2), Some(3));
        assert_eq!(QuickSelect::default().feed('z', &names(), 0), None);
    }
}
