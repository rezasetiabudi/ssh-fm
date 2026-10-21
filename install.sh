#!/bin/bash

# ssh-fm - SSH File Manager - Installation Script
set -e
echo "🔑 Installing ssh-fm (SSH File Manager)..."

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${SSH_FM_HOME:-$HOME/.local/share/ssh-fm}"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed. Please install Python 3 first."
    exit 1
fi

# Copy the app (package + entry point)
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/ssh_fm"
cp -R "$SRC_DIR/ssh_fm" "$APP_DIR/ssh_fm"
find "$APP_DIR/ssh_fm" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$SRC_DIR/ssh-fm.py" "$SRC_DIR/requirements.txt" "$APP_DIR/"

# Private virtualenv so we never touch system Python (works with PEP 668 too)
echo "🔧 Installing dependencies (textual) into $APP_DIR/venv ..."
if command -v uv &> /dev/null; then
    uv venv -q --allow-existing "$APP_DIR/venv"
    uv pip install -q --python "$APP_DIR/venv/bin/python" -r "$APP_DIR/requirements.txt"
else
    [ -x "$APP_DIR/venv/bin/python" ] || python3 -m venv "$APP_DIR/venv"
    "$APP_DIR/venv/bin/python" -m pip install -q -r "$APP_DIR/requirements.txt"
fi
echo "✅ Dependencies installed"

# Launcher in ~/bin
mkdir -p "$HOME/bin"
cat > "$HOME/bin/ssh-fm" <<LAUNCHER
#!/bin/sh
exec "$APP_DIR/venv/bin/python" "$APP_DIR/ssh-fm.py" "\$@"
LAUNCHER
chmod +x "$HOME/bin/ssh-fm"

# Detect the user's shell config file (works on macOS and Linux)
SHELL_RC=""
case "$SHELL" in
    */zsh)
        SHELL_RC="$HOME/.zshrc"
        ;;
    */bash)
        SHELL_RC="$HOME/.bashrc"
        ;;
    */fish)
        SHELL_RC="$HOME/.config/fish/config.fish"
        ;;
    *)
        SHELL_RC="$HOME/.profile"
        ;;
esac

# Fallback: if the detected config file doesn't exist, use ~/.profile
if [ ! -f "$SHELL_RC" ]; then
    SHELL_RC="$HOME/.profile"
fi

# Add ~/bin to PATH if not already present
if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
    mkdir -p "$(dirname "$SHELL_RC")"
    echo 'export PATH="$HOME/bin:$PATH"' >> "$SHELL_RC"
    echo "✅ Added ~/bin to PATH in $SHELL_RC"
fi

echo ""
echo "🎉 ssh-fm installed successfully!"
echo ""
echo "📋 Next steps:"
echo "1. Restart your terminal or run: source $SHELL_RC"
echo "2. Run: ssh-fm"
echo ""
echo "💡 Need help? Check the README.md file"
