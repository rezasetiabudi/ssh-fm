#!/usr/bin/env python3
"""ssh-fm - SSH File Manager (Textual TUI)"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from ssh_fm.app import main  # noqa: E402

if __name__ == "__main__":
    main()
