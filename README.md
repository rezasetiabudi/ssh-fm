# 🔑 ssh-fm - SSH File Manager CLI

> A lightweight, user-friendly terminal tool for managing SSH connections and file transfers with an interactive browser interface.

## 🚀 Why ssh-fm?

Working with multiple servers and transferring files via terminal can be tedious. Most existing tools either focus on just SSH connections OR just file transfers, but rarely both with a great user experience.

**ssh-fm** combines everything you need in one simple, interactive CLI tool.

---

## ✨ Features

### 🔥 **All-in-One Solution**
- ✅ SSH connection management with saved profiles
- ✅ Interactive SFTP file browser (like a terminal file explorer)
- ✅ Multiple file upload/download operations
- ✅ Smart file path input (drag files from Finder to paste paths)
- ✅ Smart file selection with ranges (1,3-7,9)
- ✅ Directory synchronization with rsync
- ✅ Smart destination presets (Desktop, Downloads, etc.)

### 🎯 **User Experience Focus**
- **Visual file browser** with emojis and colors
- **Intuitive navigation** - just type numbers to navigate
- **Smart file operations** - no need to remember complex paths
- **Progress tracking** for batch operations
- **Error handling** with clear success/failure indicators

### 🚫 **No Dependencies**
- **Pure Python** (built-in on macOS/Linux)
- **No npm/pip installations** required
- **Self-contained script** - just download and run
- **Works with existing SSH config**

---

## 📸 Interface Preview

```
============================================================
🔑 SSH CONNECTION MANAGER
============================================================

📁 Remote File Browser - server:/home/user

Contents:
 1. 📁 projects
 2. 📁 documents  
 3. 📄 config.json
 4. 📄 deploy.sh
 5. 📄 README.md

Options:
[1-5] Navigate to item    dm  Download multiple files
d     Download file       um  Upload multiple files  
u     Upload file         p   Change path manually
q     Back to menu
```

---

## 🛠️ Installation & Setup

### 1. Download the Script
```bash
# Copy the ssh-fm.py script to your system
chmod +x ssh-fm.py

# Make it globally available
mkdir -p ~/bin
cp ssh-fm.py ~/bin/ssh-fm
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 2. Run ssh-fm
```bash
ssh-fm
```

That's it! The tool will automatically read your existing SSH config and create an interactive menu.

---

## 🎮 How to Use

### **Adding SSH Hosts**
1. Choose "Add new host" from main menu
2. Enter server details (IP, port, username)  
3. Select authentication method (SSH key or password)
4. Host is automatically saved to your SSH config

### **File Browser Operations**
- **Navigate**: Type numbers (1-5) to enter folders or select files
- **Upload single**: Type `u` → select file from list or paste file path
- **Upload multiple**: Type `um` → select ranges like `1,3-7,9`  
- **Download single**: Type `d` → choose file → pick destination
- **Download multiple**: Type `dm` → select ranges → choose destination
- **Quick navigation**: Type `p` to jump to any path directly

### **Multiple File Selection Examples**
```bash
File numbers: 1,3,5        # Select files 1, 3, and 5
File numbers: 1-5          # Select files 1 through 5  
File numbers: 1,3-7,9      # Select files 1, 3-7, and 9
```

---

## 🆚 Comparison with Existing Tools

| Feature | ssh-fm | Termius | storm-ssh | ranger+SFTP | FileZilla CLI |
|---------|-------------|---------|-----------|-------------|---------------|
| SSH Management | ✅ | ✅ | ✅ | ❌ | ❌ |
| Visual SFTP Browser | ✅ | ✅ | ❌ | ✅ | ✅ |
| Multiple File Ops | ✅ | ❌ | ❌ | ✅ | ✅ |
| Smart Path Input | ✅ | ❌ | ❌ | ❌ | ❌ |
| Range Selection | ✅ | ❌ | ❌ | ❌ | ❌ |
| Pure Terminal | ✅ | ❌ | ✅ | ✅ | ❌ |
| No Dependencies | ✅ | ❌ | ❌ | ❌ | ❌ |
| Cost | Free | Paid Pro | Free | Free | Free |

---

## 💡 Use Cases

### **👨‍💻 Developers**
- Deploy code to multiple servers
- Quick file transfers during development  
- Manage development/staging/production environments
- Backup project files from remote servers

### **🔧 System Administrators** 
- Manage multiple server connections
- Bulk file operations across servers
- Quick configuration file transfers
- Server maintenance and file management

### **📊 Data Engineers**
- Transfer data files between servers
- Manage ETL scripts across environments
- Quick access to log files and configs
- Synchronize directories for data pipelines

---

## 🎯 Why This Tool Rocks

### **🚀 Productivity Boost**
No more remembering complex `scp` commands or switching between multiple tools. Everything you need is in one place with an intuitive interface.

### **🧠 Cognitive Load Reduction**  
Visual file browser eliminates the need to remember file paths. Just navigate with numbers like browsing folders in a GUI.

### **⚡ Speed & Efficiency**
- Range selection for multiple files (`1,3-7,9`)
- Smart destinations (Desktop, Downloads)  
- Incremental sync for large directories
- Smart file path handling for quick transfers

### **🛡️ Safety & Reliability**
- Progress tracking for all operations
- Clear success/failure indicators
- Works with your existing SSH keys and config
- No external dependencies to break

---

## 📝 Technical Details

- **Language**: Python 3 (built-in on macOS/Linux)
- **Dependencies**: None (uses standard library + system SSH/SCP)
- **Size**: Single ~50KB script file
- **Compatibility**: macOS, Linux, WSL on Windows
- **SSH Config**: Automatically reads and writes to `~/.ssh/config`

---

## 🤝 Contributing & Feedback

Found this useful? Have suggestions for improvements? 

- **Share with your team** if it helps your workflow
- **Customize** the script for your specific needs
- **Report issues** or suggest features

---

**💪 Built for developers, by developers. Simple tools for complex workflows.**

---

### 🏷️ Tags
`#SSH` `#SFTP` `#CLI` `#DevTools` `#Terminal` `#FileTransfer` `#Productivity` `#Linux` `#macOS` `#DevOps`
