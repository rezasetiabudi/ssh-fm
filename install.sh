#!/bin/bash

# ssh-fm - SSH File Manager CLI - Installation Script
echo "🔑 Installing ssh-fm (SSH File Manager CLI)..."

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed. Please install Python 3 first."
    exit 1
fi

# Create bin directory if it doesn't exist
mkdir -p ~/bin

# Copy the script to bin directory
cp ssh-fm.py ~/bin/ssh-fm
chmod +x ~/bin/ssh-fm

# Add ~/bin to PATH if not already present
if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
    echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
    echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
    echo "✅ Added ~/bin to PATH in shell configuration"
fi

echo ""
echo "🎉 ssh-fm installed successfully!"
echo ""
echo "📋 Next steps:"
echo "1. Restart your terminal or run: source ~/.zshrc"
echo "2. Run: ssh-fm"
echo ""
echo "💡 Need help? Check the README.md file"
