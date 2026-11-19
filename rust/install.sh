#!/bin/sh
# Install the latest ssh-fm release binary (no Rust needed).
#   curl -sSf https://raw.githubusercontent.com/rezasetiabudi/ssh-fm/main/rust/install.sh | sh
# Env: INSTALL_DIR (default ~/.local/bin), SSH_FM_BASE_URL (override download location, for testing)
set -eu

REPO="rezasetiabudi/ssh-fm"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
BASE="${SSH_FM_BASE_URL:-https://github.com/$REPO/releases/latest/download}"

os=$(uname -s)
arch=$(uname -m)
case "$os/$arch" in
  Linux/x86_64)                target=x86_64-unknown-linux-gnu ;;
  Linux/aarch64|Linux/arm64)   target=aarch64-unknown-linux-gnu ;;
  Darwin/x86_64)               target=x86_64-apple-darwin ;;
  Darwin/arm64)                target=aarch64-apple-darwin ;;
  *) echo "No prebuilt binary for $os/$arch. Build from source: cargo install --git https://github.com/$REPO --locked ssh-fm" >&2; exit 1 ;;
esac

for tool in ssh rsync sftp; do
  command -v "$tool" >/dev/null 2>&1 || echo "warning: '$tool' not found - ssh-fm needs it at runtime" >&2
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
name="ssh-fm-$target"

echo "Downloading $name ..."
curl -fsSL "$BASE/$name.tar.gz" -o "$tmp/$name.tar.gz" || {
  echo "Download failed. Is there a release yet? Build from source instead:" >&2
  echo "  cargo install --git https://github.com/$REPO --locked ssh-fm" >&2
  exit 1
}

if curl -fsSL "$BASE/$name.tar.gz.sha256" -o "$tmp/$name.tar.gz.sha256" 2>/dev/null; then
  expected=$(cut -d' ' -f1 "$tmp/$name.tar.gz.sha256")
  if command -v sha256sum >/dev/null 2>&1; then actual=$(sha256sum "$tmp/$name.tar.gz" | cut -d' ' -f1)
  else actual=$(shasum -a 256 "$tmp/$name.tar.gz" | cut -d' ' -f1); fi
  [ "$expected" = "$actual" ] || { echo "Checksum mismatch - aborting." >&2; exit 1; }
fi

tar xzf "$tmp/$name.tar.gz" -C "$tmp"
mkdir -p "$INSTALL_DIR"
install -m 755 "$tmp/$name/ssh-fm" "$INSTALL_DIR/ssh-fm"
echo "Installed $INSTALL_DIR/ssh-fm"
case ":$PATH:" in *":$INSTALL_DIR:"*) ;; *) echo "Add to PATH:  export PATH=\"$INSTALL_DIR:\$PATH\"" ;; esac
