# Changelog - ssh-fm

All notable changes to this project will be documented in this file.

## [1.0.0] - 2025-08-19

### 🎉 Initial Release

#### ✨ Added
- **SSH Connection Management**
  - Add, edit, delete SSH host profiles
  - Automatic SSH config file management
  - Support for SSH key and password authentication
  
- **Interactive SFTP File Browser**
  - Visual file/directory navigation with emojis
  - Number-based navigation (type numbers to navigate)
  - Real-time directory listing with file type indicators
  
- **Multiple File Operations** 
  - Upload multiple files with range selection (`1,3-7,9`)
  - Download multiple files with flexible selection
  - Smart destination presets (Desktop, Downloads, Custom)
  
- **File Transfer Features**
  - Drag & drop support for easy file uploads
  - Progress tracking for batch operations  
  - Error handling with success/failure indicators
  - File info viewer and content preview for small files
  
- **Directory Synchronization**
  - Two-way directory sync with rsync
  - Incremental sync (only transfers changed files)
  - Progress tracking for large directory operations
  
- **User Experience**
  - Colorful terminal interface with emojis
  - Intuitive command structure
  - Clear error messages and user guidance
  - Interactive menus with keyboard shortcuts

#### 🔧 Technical Details
- Pure Python 3 implementation (no external dependencies)
- Cross-platform compatibility (macOS, Linux, WSL)
- Automatic SSH config integration
- Self-contained single script (~50KB)

---

## 📋 Future Roadmap

### Planned Features
- [ ] Bookmarks for frequently accessed remote directories
- [ ] File search functionality across remote servers
- [ ] Compression options for large file transfers
- [ ] Batch operations scripting
- [ ] Configuration backup/restore functionality
- [ ] SSH tunnel management
- [ ] Integration with cloud storage providers

### Potential Enhancements  
- [ ] Plugin system for custom operations
- [ ] Theme customization options
- [ ] Encrypted credential storage
- [ ] Multi-server operations
- [ ] File synchronization scheduling

---

*Format based on [Keep a Changelog](https://keepachangelog.com/)*
