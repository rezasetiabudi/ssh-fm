"""Type-ahead: plain letters jump to the first name starting with what you typed."""

import time


class QuickSelect:
    TIMEOUT = 1.0

    def __init__(self):
        self.buf, self.at = "", 0.0

    def feed(self, char, names, current):
        """Return the index in `names` to move to (or None). Typing the same letter again cycles through matches."""
        now = time.monotonic()
        if now - self.at > self.TIMEOUT:
            self.buf = ""
        self.at = now
        self.buf += char.lower()
        low, n = [x.lower() for x in names], len(names)
        if not n:
            return None
        if len(set(self.buf)) == 1 and len(self.buf) > 1:  # "ff": next name starting with f after the current one
            order = [(current + 1 + i) % n for i in range(n)]
            return next((i for i in order if low[i].startswith(self.buf[0])), None)
        return next((i for i in range(n) if low[i].startswith(self.buf)), None)
