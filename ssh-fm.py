#!/usr/bin/env python3
"""
SSH Manager CLI Tool
Manage SSH connections with an interactive menu
"""

import os
import sys
import re
import subprocess
import json
from pathlib import Path

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

class SSHManager:
    def __init__(self):
        self.ssh_config_path = Path.home() / '.ssh' / 'config'
        self.hosts = {}
        self.load_config()
    
    def load_config(self):
        """Parse SSH config file and load hosts"""
        if not self.ssh_config_path.exists():
            return
        
        with open(self.ssh_config_path, 'r') as f:
            content = f.read()
        
        # Parse SSH config
        current_host = None
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            if line.lower().startswith('host '):
                # Extract host name
                host_name = line.split()[1]
                if host_name != '*':  # Skip wildcard hosts
                    current_host = host_name
                    self.hosts[current_host] = {
                        'hostname': '',
                        'port': '22',
                        'user': '',
                        'identity_file': '',
                        'password_auth': False
                    }
            elif current_host and line:
                # Parse host properties
                parts = line.split(None, 1)
                if len(parts) == 2:
                    key, value = parts
                    key_lower = key.lower()
                    
                    if key_lower == 'hostname':
                        self.hosts[current_host]['hostname'] = value
                    elif key_lower == 'port':
                        self.hosts[current_host]['port'] = value
                    elif key_lower == 'user':
                        self.hosts[current_host]['user'] = value
                    elif key_lower == 'identityfile':
                        self.hosts[current_host]['identity_file'] = value.replace('~', str(Path.home()))
                    elif key_lower == 'passwordauthentication':
                        self.hosts[current_host]['password_auth'] = value.lower() == 'yes'
    
    def save_config(self):
        """Save hosts back to SSH config file"""
        config_lines = []
        
        for host_name, config in self.hosts.items():
            config_lines.append(f"Host {host_name}")
            if config['hostname']:
                config_lines.append(f"  HostName {config['hostname']}")
            if config['port'] != '22':
                config_lines.append(f"  Port {config['port']}")
            if config['user']:
                config_lines.append(f"  User {config['user']}")
            if config['identity_file']:
                identity_file = config['identity_file'].replace(str(Path.home()), '~')
                config_lines.append(f"  IdentityFile {identity_file}")
            config_lines.append("  IdentitiesOnly yes")
            if config['password_auth']:
                config_lines.append("  PasswordAuthentication yes")
            config_lines.append("")
        
        # Add default settings
        config_lines.extend([
            "# Default settings for all hosts",
            "Host *",
            "  AddKeysToAgent yes",
            "  UseKeychain yes",
            "  ServerAliveInterval 60",
            "  ServerAliveCountMax 3"
        ])
        
        with open(self.ssh_config_path, 'w') as f:
            f.write('\n'.join(config_lines))
    
    def print_header(self):
        print(f"\n{Colors.HEADER}{'='*60}")
        print(f"🔑 SSH CONNECTION MANAGER")
        print(f"{'='*60}{Colors.ENDC}\n")
    
    def list_hosts(self):
        """List all configured hosts"""
        if not self.hosts:
            print(f"{Colors.WARNING}No SSH hosts configured.{Colors.ENDC}")
            return
        
        print(f"{Colors.CYAN}Configured SSH Hosts:{Colors.ENDC}\n")
        
        for i, (host_name, config) in enumerate(self.hosts.items(), 1):
            hostname = config['hostname'] or 'localhost'
            port = config['port']
            user = config['user'] or 'current user'
            key_file = config['identity_file']
            
            print(f"{Colors.GREEN}{i}. {host_name}{Colors.ENDC}")
            print(f"   📍 {hostname}:{port}")
            print(f"   👤 {user}")
            
            if key_file:
                key_name = os.path.basename(key_file)
                print(f"   🔑 {key_name}")
            elif config['password_auth']:
                print(f"   🔒 Password authentication")
            else:
                print(f"   🔑 Default key")
            print()
    
    def connect_to_host(self):
        """Connect to a selected host"""
        if not self.hosts:
            print(f"{Colors.WARNING}No hosts configured.{Colors.ENDC}")
            return
        
        self.list_hosts()
        try:
            choice = input(f"{Colors.CYAN}Select host number to connect: {Colors.ENDC}")
            if not choice.isdigit():
                return
            
            host_names = list(self.hosts.keys())
            if 1 <= int(choice) <= len(host_names):
                host_name = host_names[int(choice) - 1]
                print(f"{Colors.GREEN}Connecting to {host_name}...{Colors.ENDC}")
                subprocess.run(['ssh', host_name])
            else:
                print(f"{Colors.FAIL}Invalid selection.{Colors.ENDC}")
        except KeyboardInterrupt:
            print()
    
    def add_host(self):
        """Add a new SSH host"""
        print(f"{Colors.CYAN}Add New SSH Host{Colors.ENDC}\n")
        
        host_name = input("Host alias/name: ").strip()
        if not host_name or host_name in self.hosts:
            print(f"{Colors.FAIL}Invalid or duplicate host name.{Colors.ENDC}")
            return
        
        hostname = input("IP/Hostname: ").strip()
        port = input("Port (default 22): ").strip() or "22"
        user = input("Username: ").strip()
        
        print("\nAuthentication method:")
        print("1. SSH Key")
        print("2. Password")
        auth_choice = input("Choose (1/2): ").strip()
        
        identity_file = ""
        password_auth = False
        
        if auth_choice == "1":
            # Show available keys
            ssh_dir = Path.home() / '.ssh'
            key_files = []
            for key_file in ssh_dir.glob('id_*'):
                if not key_file.name.endswith('.pub'):
                    key_files.append(key_file)
            
            if key_files:
                print("\nAvailable SSH keys:")
                for i, key_file in enumerate(key_files, 1):
                    print(f"{i}. {key_file.name}")
                
                key_choice = input("Select key number (or press Enter for default): ").strip()
                if key_choice.isdigit() and 1 <= int(key_choice) <= len(key_files):
                    identity_file = str(key_files[int(key_choice) - 1])
            else:
                identity_file = input("Key file path (optional): ").strip()
        
        elif auth_choice == "2":
            password_auth = True
        
        self.hosts[host_name] = {
            'hostname': hostname,
            'port': port,
            'user': user,
            'identity_file': identity_file,
            'password_auth': password_auth
        }
        
        self.save_config()
        print(f"{Colors.GREEN}Host '{host_name}' added successfully!{Colors.ENDC}")
    
    def edit_host(self):
        """Edit an existing host"""
        if not self.hosts:
            print(f"{Colors.WARNING}No hosts to edit.{Colors.ENDC}")
            return
        
        self.list_hosts()
        try:
            choice = input(f"{Colors.CYAN}Select host number to edit: {Colors.ENDC}")
            if not choice.isdigit():
                return
            
            host_names = list(self.hosts.keys())
            if 1 <= int(choice) <= len(host_names):
                host_name = host_names[int(choice) - 1]
                self.edit_host_details(host_name)
            else:
                print(f"{Colors.FAIL}Invalid selection.{Colors.ENDC}")
        except KeyboardInterrupt:
            print()
    
    def edit_host_details(self, host_name):
        """Edit details of a specific host"""
        config = self.hosts[host_name]
        
        print(f"\n{Colors.CYAN}Editing host: {host_name}{Colors.ENDC}")
        print(f"Current settings:")
        print(f"1. Hostname: {config['hostname']}")
        print(f"2. Port: {config['port']}")
        print(f"3. User: {config['user']}")
        print(f"4. Identity file: {config['identity_file'] or 'None'}")
        print(f"5. Password auth: {'Yes' if config['password_auth'] else 'No'}")
        print("6. Rename host")
        print("7. Back to main menu")
        
        choice = input(f"\n{Colors.CYAN}What to edit (1-7): {Colors.ENDC}").strip()
        
        if choice == "1":
            new_hostname = input(f"New hostname ({config['hostname']}): ").strip()
            if new_hostname:
                config['hostname'] = new_hostname
        elif choice == "2":
            new_port = input(f"New port ({config['port']}): ").strip()
            if new_port:
                config['port'] = new_port
        elif choice == "3":
            new_user = input(f"New username ({config['user']}): ").strip()
            if new_user:
                config['user'] = new_user
        elif choice == "4":
            new_key = input(f"New identity file ({config['identity_file']}): ").strip()
            config['identity_file'] = new_key
        elif choice == "5":
            config['password_auth'] = not config['password_auth']
            print(f"Password auth set to: {'Yes' if config['password_auth'] else 'No'}")
        elif choice == "6":
            new_name = input(f"New host name ({host_name}): ").strip()
            if new_name and new_name != host_name and new_name not in self.hosts:
                self.hosts[new_name] = self.hosts.pop(host_name)
                host_name = new_name
        elif choice == "7":
            return
        
        if choice in ["1", "2", "3", "4", "5", "6"]:
            self.save_config()
            print(f"{Colors.GREEN}Host updated successfully!{Colors.ENDC}")
    
    def delete_host(self):
        """Delete a host"""
        if not self.hosts:
            print(f"{Colors.WARNING}No hosts to delete.{Colors.ENDC}")
            return
        
        self.list_hosts()
        try:
            choice = input(f"{Colors.CYAN}Select host number to delete: {Colors.ENDC}")
            if not choice.isdigit():
                return
            
            host_names = list(self.hosts.keys())
            if 1 <= int(choice) <= len(host_names):
                host_name = host_names[int(choice) - 1]
                confirm = input(f"{Colors.WARNING}Delete '{host_name}'? (y/N): {Colors.ENDC}").strip().lower()
                if confirm == 'y':
                    del self.hosts[host_name]
                    self.save_config()
                    print(f"{Colors.GREEN}Host '{host_name}' deleted.{Colors.ENDC}")
            else:
                print(f"{Colors.FAIL}Invalid selection.{Colors.ENDC}")
        except KeyboardInterrupt:
            print()
    
    def sftp_menu(self):
        """SFTP operations menu"""
        if not self.hosts:
            print(f"{Colors.WARNING}No hosts configured.{Colors.ENDC}")
            return
        
        self.list_hosts()
        try:
            choice = input(f"{Colors.CYAN}Select host for SFTP: {Colors.ENDC}")
            if not choice.isdigit():
                return
            
            host_names = list(self.hosts.keys())
            if 1 <= int(choice) <= len(host_names):
                host_name = host_names[int(choice) - 1]
                self.sftp_operations(host_name)
            else:
                print(f"{Colors.FAIL}Invalid selection.{Colors.ENDC}")
        except KeyboardInterrupt:
            print()
    
    def sftp_operations(self, host_name):
        """SFTP operations for selected host"""
        while True:
            print(f"\n{Colors.HEADER}SFTP Operations - {host_name}{Colors.ENDC}\n")
            print(f"{Colors.BLUE}1.{Colors.ENDC} 📁 File Browser (Interactive)")
            print(f"{Colors.BLUE}2.{Colors.ENDC} 📋 Terminal SFTP Session")
            print(f"{Colors.BLUE}3.{Colors.ENDC} 🔄 Directory Sync (rsync)")
            print(f"{Colors.BLUE}4.{Colors.ENDC} ⬅️  Back to main menu")
            
            try:
                sftp_choice = input(f"\n{Colors.CYAN}Select SFTP operation (1-4): {Colors.ENDC}").strip()
                
                if sftp_choice == "1":
                    self.browse_remote(host_name)
                elif sftp_choice == "2":
                    self.interactive_sftp(host_name)
                elif sftp_choice == "3":
                    self.sync_directory(host_name)
                elif sftp_choice == "4":
                    break
                else:
                    print(f"{Colors.FAIL}Invalid option. Please choose 1-4.{Colors.ENDC}")
                    
            except KeyboardInterrupt:
                break
    
    def browse_remote(self, host_name, current_path="~"):
        """Interactive remote directory browser"""
        while True:
            print(f"\n{Colors.HEADER}📁 Remote File Browser - {host_name}:{current_path}{Colors.ENDC}")
            
            try:
                # Get directory listing with file types
                result = subprocess.run(['ssh', host_name, f'ls -la {current_path}'], 
                                      capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"{Colors.FAIL}Error: {result.stderr}{Colors.ENDC}")
                    break
                
                lines = result.stdout.strip().split('\n')[1:]  # Skip 'total' line
                files = []
                dirs = []
                
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 9:
                            perms = parts[0]
                            name = ' '.join(parts[8:])
                            if perms.startswith('d'):
                                if name not in ['.', '..']:
                                    dirs.append(name)
                            else:
                                files.append(name)
                
                # Display directories first, then files
                all_items = []
                if current_path != '/' and current_path != '~':
                    all_items.append(('..', 'dir'))  # Parent directory
                
                for d in sorted(dirs):
                    all_items.append((d, 'dir'))
                for f in sorted(files):
                    all_items.append((f, 'file'))
                
                if not all_items:
                    print(f"{Colors.WARNING}Directory is empty{Colors.ENDC}")
                else:
                    print(f"\n{Colors.CYAN}Contents:{Colors.ENDC}")
                    for i, (item, item_type) in enumerate(all_items, 1):
                        if item_type == 'dir':
                            print(f"{Colors.BLUE}{i:2d}.{Colors.ENDC} 📁 {item}")
                        else:
                            print(f"{Colors.GREEN}{i:2d}.{Colors.ENDC} 📄 {item}")
                
                print(f"\n{Colors.CYAN}Options:{Colors.ENDC}")
                print(f"{Colors.BLUE}[1-{len(all_items)}]{Colors.ENDC} Navigate to item")
                print(f"{Colors.BLUE}d{Colors.ENDC} Download selected file")
                print(f"{Colors.BLUE}dm{Colors.ENDC} Download multiple files")
                print(f"{Colors.BLUE}u{Colors.ENDC} Upload file to current directory")
                print(f"{Colors.BLUE}um{Colors.ENDC} Upload multiple files")
                print(f"{Colors.BLUE}p{Colors.ENDC} Change path manually")
                print(f"{Colors.BLUE}q{Colors.ENDC} Back to SFTP menu")
                
                choice = input(f"\n{Colors.CYAN}Your choice: {Colors.ENDC}").strip().lower()
                
                if choice == 'q':
                    break
                elif choice == 'p':
                    new_path = input(f"{Colors.CYAN}Enter new path: {Colors.ENDC}").strip()
                    if new_path:
                        current_path = new_path
                elif choice == 'u':
                    self.upload_file_to_path(host_name, current_path)
                elif choice == 'um':
                    self.upload_multiple_files(host_name, current_path)
                elif choice == 'd':
                    if all_items:
                        file_num = input(f"{Colors.CYAN}Enter file number to download: {Colors.ENDC}").strip()
                        if file_num.isdigit() and 1 <= int(file_num) <= len(all_items):
                            item_name, item_type = all_items[int(file_num) - 1]
                            if item_type == 'file':
                                file_path = f"{current_path.rstrip('/')}/{item_name}" if current_path != '~' else item_name
                                self.download_specific_file(host_name, file_path, item_name)
                elif choice == 'dm':
                    if all_items:
                        self.download_multiple_files(host_name, current_path, all_items)
                elif choice.isdigit() and 1 <= int(choice) <= len(all_items):
                    item_name, item_type = all_items[int(choice) - 1]
                    if item_type == 'dir':
                        if item_name == '..':
                            # Go to parent directory
                            if current_path != '~' and current_path != '/':
                                current_path = '/'.join(current_path.rstrip('/').split('/')[:-1]) or '/'
                        else:
                            # Enter directory
                            if current_path == '~':
                                current_path = item_name
                            else:
                                current_path = f"{current_path.rstrip('/')}/{item_name}"
                    else:
                        # Show file options
                        self.file_actions(host_name, current_path, item_name)
                        
            except Exception as e:
                print(f"{Colors.FAIL}Error browsing directory: {e}{Colors.ENDC}")
                input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def upload_file(self, host_name):
        """Upload file to server"""
        print(f"{Colors.CYAN}Upload File to {host_name}{Colors.ENDC}\n")
        
        # Show current local directory
        print(f"Current local directory: {os.getcwd()}")
        result = subprocess.run(['ls', '-la'], capture_output=True, text=True)
        print(result.stdout[:500])  # Show first 500 chars
        
        local_path = input(f"\n{Colors.CYAN}Local file path (drag file here or type path): {Colors.ENDC}").strip()
        if not local_path:
            return
        
        # Clean up path (remove quotes if dragged)
        local_path = local_path.strip('"').strip("'")
        
        if not os.path.exists(local_path):
            print(f"{Colors.FAIL}File not found: {local_path}{Colors.ENDC}")
            return
        
        remote_path = input(f"{Colors.CYAN}Remote destination path: {Colors.ENDC}").strip()
        if not remote_path:
            filename = os.path.basename(local_path)
            remote_path = f"~/{filename}"
        
        print(f"{Colors.GREEN}Uploading {local_path} to {remote_path}...{Colors.ENDC}")
        
        try:
            result = subprocess.run(['scp', local_path, f'{host_name}:{remote_path}'])
            if result.returncode == 0:
                print(f"{Colors.GREEN}✅ Upload successful!{Colors.ENDC}")
            else:
                print(f"{Colors.FAIL}❌ Upload failed!{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}Error uploading file: {e}{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def download_file(self, host_name):
        """Download file from server"""
        print(f"{Colors.CYAN}Download File from {host_name}{Colors.ENDC}\n")
        
        # Browse remote first
        browse = input(f"{Colors.CYAN}Browse remote directory first? (y/N): {Colors.ENDC}").strip().lower()
        if browse == 'y':
            self.browse_remote(host_name)
        
        remote_path = input(f"{Colors.CYAN}Remote file path: {Colors.ENDC}").strip()
        if not remote_path:
            return
        
        local_path = input(f"{Colors.CYAN}Local destination (default: current dir): {Colors.ENDC}").strip()
        if not local_path:
            filename = os.path.basename(remote_path)
            local_path = f"./{filename}"
        
        print(f"{Colors.GREEN}Downloading {remote_path} to {local_path}...{Colors.ENDC}")
        
        try:
            result = subprocess.run(['scp', f'{host_name}:{remote_path}', local_path])
            if result.returncode == 0:
                print(f"{Colors.GREEN}✅ Download successful!{Colors.ENDC}")
                print(f"File saved to: {os.path.abspath(local_path)}")
            else:
                print(f"{Colors.FAIL}❌ Download failed!{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}Error downloading file: {e}{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def interactive_sftp(self, host_name):
        """Open interactive SFTP session"""
        print(f"{Colors.GREEN}Opening SFTP session to {host_name}...{Colors.ENDC}")
        print(f"{Colors.CYAN}Use 'help' for commands, 'exit' or 'quit' to close{Colors.ENDC}")
        
        try:
            subprocess.run(['sftp', host_name])
        except Exception as e:
            print(f"{Colors.FAIL}Error opening SFTP session: {e}{Colors.ENDC}")
    
    def sync_directory(self, host_name):
        """Sync directory with rsync"""
        print(f"{Colors.CYAN}Directory Sync with {host_name}{Colors.ENDC}\n")
        print("1. Upload local directory to remote")
        print("2. Download remote directory to local")
        
        sync_choice = input(f"\n{Colors.CYAN}Choose sync direction (1/2): {Colors.ENDC}").strip()
        
        if sync_choice == "1":
            local_dir = input(f"{Colors.CYAN}Local directory path: {Colors.ENDC}").strip()
            remote_dir = input(f"{Colors.CYAN}Remote directory path: {Colors.ENDC}").strip()
            
            if local_dir and remote_dir:
                print(f"{Colors.GREEN}Syncing {local_dir} to {host_name}:{remote_dir}...{Colors.ENDC}")
                try:
                    result = subprocess.run(['rsync', '-avz', '--progress', local_dir, f'{host_name}:{remote_dir}'])
                    if result.returncode == 0:
                        print(f"{Colors.GREEN}✅ Sync successful!{Colors.ENDC}")
                    else:
                        print(f"{Colors.FAIL}❌ Sync failed!{Colors.ENDC}")
                except Exception as e:
                    print(f"{Colors.FAIL}Error syncing directory: {e}{Colors.ENDC}")
                    
        elif sync_choice == "2":
            remote_dir = input(f"{Colors.CYAN}Remote directory path: {Colors.ENDC}").strip()
            local_dir = input(f"{Colors.CYAN}Local directory path: {Colors.ENDC}").strip()
            
            if local_dir and remote_dir:
                print(f"{Colors.GREEN}Syncing {host_name}:{remote_dir} to {local_dir}...{Colors.ENDC}")
                try:
                    result = subprocess.run(['rsync', '-avz', '--progress', f'{host_name}:{remote_dir}', local_dir])
                    if result.returncode == 0:
                        print(f"{Colors.GREEN}✅ Sync successful!{Colors.ENDC}")
                    else:
                        print(f"{Colors.FAIL}❌ Sync failed!{Colors.ENDC}")
                except Exception as e:
                    print(f"{Colors.FAIL}Error syncing directory: {e}{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def upload_file_to_path(self, host_name, remote_path):
        """Upload file to specific remote path"""
        print(f"\n{Colors.CYAN}📤 Upload to {host_name}:{remote_path}{Colors.ENDC}")
        
        # Show local files for easy selection
        print(f"\n{Colors.CYAN}Local files in current directory:{Colors.ENDC}")
        try:
            result = subprocess.run(['ls', '-la'], capture_output=True, text=True)
            local_files = []
            for line in result.stdout.split('\n')[1:]:
                if line.strip() and not line.startswith('d'):
                    parts = line.split()
                    if len(parts) >= 9 and not parts[0].startswith('d'):
                        filename = ' '.join(parts[8:])
                        if filename not in ['.', '..']:
                            local_files.append(filename)
            
            if local_files:
                for i, file in enumerate(local_files[:10], 1):  # Show max 10 files
                    print(f"{Colors.GREEN}{i:2d}.{Colors.ENDC} {file}")
                if len(local_files) > 10:
                    print(f"{Colors.WARNING}... and {len(local_files)-10} more files{Colors.ENDC}")
        except:
            pass
        
        print(f"\n{Colors.CYAN}Options:{Colors.ENDC}")
        print(f"{Colors.BLUE}1-{len(local_files[:10])}{Colors.ENDC} Select file by number")
        print(f"{Colors.BLUE}f{Colors.ENDC} Enter file path manually")
        print(f"{Colors.BLUE}d{Colors.ENDC} Drag \u0026 drop file (paste path)")
        
        choice = input(f"\n{Colors.CYAN}Your choice: {Colors.ENDC}").strip().lower()
        
        local_file = None
        if choice == 'f' or choice == 'd':
            local_path = input(f"{Colors.CYAN}File path (drag here or type): {Colors.ENDC}").strip()
            local_file = local_path.strip('"').strip("'")
        elif choice.isdigit() and 1 <= int(choice) <= min(len(local_files), 10):
            local_file = local_files[int(choice) - 1]
        
        if local_file and os.path.exists(local_file):
            filename = os.path.basename(local_file)
            full_remote_path = f"{remote_path.rstrip('/')}/{filename}" if remote_path != '~' else filename
            
            print(f"{Colors.GREEN}Uploading {local_file} to {full_remote_path}...{Colors.ENDC}")
            
            try:
                result = subprocess.run(['scp', local_file, f'{host_name}:{full_remote_path}'])
                if result.returncode == 0:
                    print(f"{Colors.GREEN}✅ Upload successful!{Colors.ENDC}")
                else:
                    print(f"{Colors.FAIL}❌ Upload failed!{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}File not found or invalid selection.{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def download_specific_file(self, host_name, remote_file_path, filename):
        """Download specific file with local path options"""
        print(f"\n{Colors.CYAN}📥 Download {filename}{Colors.ENDC}")
        
        # Show download options
        print(f"\n{Colors.CYAN}Download options:{Colors.ENDC}")
        print(f"{Colors.BLUE}1.{Colors.ENDC} Current directory ({os.getcwd()})")
        print(f"{Colors.BLUE}2.{Colors.ENDC} Desktop")
        print(f"{Colors.BLUE}3.{Colors.ENDC} Downloads folder")
        print(f"{Colors.BLUE}4.{Colors.ENDC} Custom path")
        
        choice = input(f"\n{Colors.CYAN}Where to save? (1-4): {Colors.ENDC}").strip()
        
        if choice == '1':
            local_path = f"./{filename}"
        elif choice == '2':
            local_path = f"{Path.home()}/Desktop/{filename}"
        elif choice == '3':
            local_path = f"{Path.home()}/Downloads/{filename}"
        elif choice == '4':
            local_path = input(f"{Colors.CYAN}Enter full path: {Colors.ENDC}").strip()
            if not local_path:
                local_path = f"./{filename}"
        else:
            local_path = f"./{filename}"
        
        print(f"{Colors.GREEN}Downloading {remote_file_path} to {local_path}...{Colors.ENDC}")
        
        try:
            result = subprocess.run(['scp', f'{host_name}:{remote_file_path}', local_path])
            if result.returncode == 0:
                print(f"{Colors.GREEN}✅ Download successful!{Colors.ENDC}")
                print(f"{Colors.CYAN}File saved to: {os.path.abspath(local_path)}{Colors.ENDC}")
            else:
                print(f"{Colors.FAIL}❌ Download failed!{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def file_actions(self, host_name, current_path, filename):
        """Show actions available for a selected file"""
        print(f"\n{Colors.CYAN}📄 File Actions: {filename}{Colors.ENDC}")
        
        file_path = f"{current_path.rstrip('/')}/{filename}" if current_path != '~' else filename
        
        print(f"\n{Colors.BLUE}1.{Colors.ENDC} 📥 Download file")
        print(f"{Colors.BLUE}2.{Colors.ENDC} 👁️  View file info")
        print(f"{Colors.BLUE}3.{Colors.ENDC} 📝 View file content (small files)")
        print(f"{Colors.BLUE}4.{Colors.ENDC} ⬅️  Back to browser")
        
        choice = input(f"\n{Colors.CYAN}Select action (1-4): {Colors.ENDC}").strip()
        
        if choice == '1':
            self.download_specific_file(host_name, file_path, filename)
        elif choice == '2':
            self.show_file_info(host_name, file_path)
        elif choice == '3':
            self.view_file_content(host_name, file_path)
        # elif choice == '4' or default, just return to browser
    
    def show_file_info(self, host_name, file_path):
        """Show detailed file information"""
        print(f"\n{Colors.CYAN}📊 File Info: {os.path.basename(file_path)}{Colors.ENDC}")
        
        try:
            # Get file info
            result = subprocess.run(['ssh', host_name, f'ls -lh \"{file_path}\"'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"\n{result.stdout}")
            
            # Get file type
            result = subprocess.run(['ssh', host_name, f'file \"{file_path}\"'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Type: {result.stdout.strip()}")
                
        except Exception as e:
            print(f"{Colors.FAIL}Error getting file info: {e}{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def view_file_content(self, host_name, file_path):
        """View content of small text files"""
        print(f"\n{Colors.CYAN}📖 File Content: {os.path.basename(file_path)}{Colors.ENDC}")
        
        try:
            # Check file size first
            result = subprocess.run(['ssh', host_name, f'stat -f%z \"{file_path}\" 2>/dev/null || stat -c%s \"{file_path}\"'], 
                                  capture_output=True, text=True)
            
            file_size = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
            
            if file_size > 10000:  # 10KB limit
                print(f"{Colors.WARNING}File is too large ({file_size} bytes). Use download instead.{Colors.ENDC}")
            else:
                result = subprocess.run(['ssh', host_name, f'head -50 \"{file_path}\"'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"\n{Colors.GREEN}Content (first 50 lines):{Colors.ENDC}")
                    print("-" * 50)
                    print(result.stdout)
                    print("-" * 50)
                else:
                    print(f"{Colors.FAIL}Could not read file content.{Colors.ENDC}")
                    
        except Exception as e:
            print(f"{Colors.FAIL}Error viewing file: {e}{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def upload_multiple_files(self, host_name, remote_path):
        """Upload multiple files to remote directory"""
        print(f"\n{Colors.CYAN}📤 Upload Multiple Files to {host_name}:{remote_path}{Colors.ENDC}")
        
        # Show local files
        print(f"\n{Colors.CYAN}Local files in current directory:{Colors.ENDC}")
        try:
            result = subprocess.run(['ls', '-la'], capture_output=True, text=True)
            local_files = []
            for line in result.stdout.split('\n')[1:]:
                if line.strip() and not line.startswith('d'):
                    parts = line.split()
                    if len(parts) >= 9 and not parts[0].startswith('d'):
                        filename = ' '.join(parts[8:])
                        if filename not in ['.', '..']:
                            local_files.append(filename)
            
            if local_files:
                for i, file in enumerate(local_files, 1):
                    print(f"{Colors.GREEN}{i:2d}.{Colors.ENDC} {file}")
        except:
            print(f"{Colors.FAIL}Error reading local directory{Colors.ENDC}")
            return
        
        if not local_files:
            print(f"{Colors.WARNING}No files found in current directory{Colors.ENDC}")
            return
        
        print(f"\n{Colors.CYAN}Select files to upload:{Colors.ENDC}")
        print(f"{Colors.BLUE}Example:{Colors.ENDC} '1,3,5' or '1-5' or '1,3-7,9'")
        
        selection = input(f"{Colors.CYAN}File numbers: {Colors.ENDC}").strip()
        if not selection:
            return
        
        # Parse selection
        selected_files = []
        try:
            for part in selection.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    selected_files.extend(range(start, end + 1))
                else:
                    selected_files.append(int(part))
            
            # Remove duplicates and validate
            selected_files = list(set(selected_files))
            selected_files = [i for i in selected_files if 1 <= i <= len(local_files)]
            
            if not selected_files:
                print(f"{Colors.FAIL}No valid files selected.{Colors.ENDC}")
                return
            
            # Upload files
            upload_files = [local_files[i-1] for i in selected_files]
            print(f"\n{Colors.GREEN}Uploading {len(upload_files)} files...{Colors.ENDC}")
            
            success_count = 0
            for file in upload_files:
                filename = os.path.basename(file)
                full_remote_path = f"{remote_path.rstrip('/')}/{filename}" if remote_path != '~' else filename
                
                print(f"{Colors.CYAN}Uploading {file}...{Colors.ENDC}")
                try:
                    result = subprocess.run(['scp', file, f'{host_name}:{full_remote_path}'], 
                                          capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"{Colors.GREEN}✓ {file} uploaded{Colors.ENDC}")
                        success_count += 1
                    else:
                        print(f"{Colors.FAIL}✗ {file} failed: {result.stderr.strip()}{Colors.ENDC}")
                except Exception as e:
                    print(f"{Colors.FAIL}✗ {file} error: {e}{Colors.ENDC}")
            
            print(f"\n{Colors.GREEN}✅ Upload completed: {success_count}/{len(upload_files)} files successful{Colors.ENDC}")
            
        except ValueError:
            print(f"{Colors.FAIL}Invalid selection format. Use numbers, ranges, or comma-separated.{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def download_multiple_files(self, host_name, current_path, all_items):
        """Download multiple files from remote directory"""
        print(f"\n{Colors.CYAN}📥 Download Multiple Files from {host_name}:{current_path}{Colors.ENDC}")
        
        # Filter only files
        files_only = [(i+1, item_name) for i, (item_name, item_type) in enumerate(all_items) if item_type == 'file']
        
        if not files_only:
            print(f"{Colors.WARNING}No files available for download in current directory{Colors.ENDC}")
            input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
            return
        
        print(f"\n{Colors.CYAN}Available files:{Colors.ENDC}")
        for file_num, filename in files_only:
            print(f"{Colors.GREEN}{file_num:2d}.{Colors.ENDC} {filename}")
        
        print(f"\n{Colors.CYAN}Select files to download:{Colors.ENDC}")
        print(f"{Colors.BLUE}Example:{Colors.ENDC} '1,3,5' or '1-5' or '1,3-7,9'")
        
        selection = input(f"{Colors.CYAN}File numbers: {Colors.ENDC}").strip()
        if not selection:
            return
        
        # Choose download destination
        print(f"\n{Colors.CYAN}Download destination:{Colors.ENDC}")
        print(f"{Colors.BLUE}1.{Colors.ENDC} Current directory ({os.getcwd()})")
        print(f"{Colors.BLUE}2.{Colors.ENDC} Desktop")
        print(f"{Colors.BLUE}3.{Colors.ENDC} Downloads folder")
        print(f"{Colors.BLUE}4.{Colors.ENDC} Custom path")
        
        dest_choice = input(f"\n{Colors.CYAN}Where to save? (1-4): {Colors.ENDC}").strip()
        
        if dest_choice == '2':
            base_path = str(Path.home() / 'Desktop')
        elif dest_choice == '3':
            base_path = str(Path.home() / 'Downloads')
        elif dest_choice == '4':
            base_path = input(f"{Colors.CYAN}Enter directory path: {Colors.ENDC}").strip()
            if not base_path:
                base_path = os.getcwd()
        else:
            base_path = os.getcwd()
        
        # Parse selection
        try:
            selected_nums = []
            for part in selection.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    selected_nums.extend(range(start, end + 1))
                else:
                    selected_nums.append(int(part))
            
            # Remove duplicates and validate
            selected_nums = list(set(selected_nums))
            valid_files = [(num, filename) for num, filename in files_only if num in selected_nums]
            
            if not valid_files:
                print(f"{Colors.FAIL}No valid files selected.{Colors.ENDC}")
                return
            
            # Download files
            print(f"\n{Colors.GREEN}Downloading {len(valid_files)} files to {base_path}...{Colors.ENDC}")
            
            success_count = 0
            for file_num, filename in valid_files:
                remote_file_path = f"{current_path.rstrip('/')}/{filename}" if current_path != '~' else filename
                local_file_path = os.path.join(base_path, filename)
                
                print(f"{Colors.CYAN}Downloading {filename}...{Colors.ENDC}")
                try:
                    result = subprocess.run(['scp', f'{host_name}:{remote_file_path}', local_file_path], 
                                          capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"{Colors.GREEN}✓ {filename} downloaded{Colors.ENDC}")
                        success_count += 1
                    else:
                        print(f"{Colors.FAIL}✗ {filename} failed: {result.stderr.strip()}{Colors.ENDC}")
                except Exception as e:
                    print(f"{Colors.FAIL}✗ {filename} error: {e}{Colors.ENDC}")
            
            print(f"\n{Colors.GREEN}✅ Download completed: {success_count}/{len(valid_files)} files successful{Colors.ENDC}")
            print(f"{Colors.CYAN}Files saved to: {base_path}{Colors.ENDC}")
            
        except ValueError:
            print(f"{Colors.FAIL}Invalid selection format. Use numbers, ranges, or comma-separated.{Colors.ENDC}")
        
        input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
    
    def show_menu(self):
        """Show main menu"""
        while True:
            self.print_header()
            print(f"{Colors.BLUE}1.{Colors.ENDC} 📋 List all hosts")
            print(f"{Colors.BLUE}2.{Colors.ENDC} 🔗 Connect to host (SSH)")
            print(f"{Colors.BLUE}3.{Colors.ENDC} 📁 File transfer (SFTP)")
            print(f"{Colors.BLUE}4.{Colors.ENDC} ➕ Add new host")
            print(f"{Colors.BLUE}5.{Colors.ENDC} ✏️  Edit host")
            print(f"{Colors.BLUE}6.{Colors.ENDC} 🗑️  Delete host")
            print(f"{Colors.BLUE}7.{Colors.ENDC} 🚪 Exit")
            
            try:
                choice = input(f"\n{Colors.CYAN}Select option (1-7): {Colors.ENDC}").strip()
                
                if choice == "1":
                    self.list_hosts()
                    input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.ENDC}")
                elif choice == "2":
                    self.connect_to_host()
                elif choice == "3":
                    self.sftp_menu()
                elif choice == "4":
                    self.add_host()
                elif choice == "5":
                    self.edit_host()
                elif choice == "6":
                    self.delete_host()
                elif choice == "7":
                    print(f"{Colors.GREEN}Goodbye! 👋{Colors.ENDC}")
                    break
                else:
                    print(f"{Colors.FAIL}Invalid option. Please choose 1-7.{Colors.ENDC}")
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.GREEN}Goodbye! 👋{Colors.ENDC}")
                break
            except Exception as e:
                print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")

def main():
    ssh_manager = SSHManager()
    ssh_manager.show_menu()

if __name__ == "__main__":
    main()
