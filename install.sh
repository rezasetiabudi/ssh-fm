#!/bin/bash

# ssh-fm - SSH File Manager CLI - Installation Script
echo "🔑 Installing ssh-fm (SSH File Manager CLI)..."

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed. Please install Python 3 first."
    exit 1
fi

# Install the 'textual' dependency (required by ssh-fm)
if ! python3 -c "import textual" &> /dev/null; then
    echo "🔧 Installing 'textual' dependency..."
    if python3 -m pip install textual &> /dev/null; then
        echo "✅ textual installed"
    else
        echo "⚠️  Standard pip install failed (PEP 668?). Retrying with --break-system-packages..."
        python3 -m pip install --user --break-system-packages textual || {
            echo "❌ Failed to install 'textual'. Install it manually: python3 -m pip install textual"
            exit 1
        }
        echo "✅ textual installed"
    fi
else
    echo "✅ textual already installed"
fi

# Create bin directory if it doesn't exist
mkdir -p "$HOME/bin"

# Copy the script to bin directory
cp ssh-fm.py "$HOME/bin/ssh-fm"
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
