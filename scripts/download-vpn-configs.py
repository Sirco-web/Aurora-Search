#!/usr/bin/env python3
"""
Aurora Search OpenVPN Config Downloader
Downloads free OpenVPN configs from multiple GitHub repositories
and integrates them with the crawler for proxy rotation
"""

import os
import sys
import subprocess
import requests
import zipfile
import io
from pathlib import Path

def print_banner():
    print("""
╔════════════════════════════════════════════════════════════════════╗
║         📥 OPENVPN CONFIG DOWNLOADER FOR AURORA SEARCH 📥         ║
╚════════════════════════════════════════════════════════════════════╝
""")

def extract_password_from_url_file(content):
    """Extract username and password from .url file content"""
    try:
        # URL files contain lines like:
        # username=vpnbook
        # password=xyz123
        # Or they might be direct URLs with credentials
        credentials = {}
        
        for line in content.decode('utf-8', errors='ignore').split('\n'):
            line = line.strip()
            if 'username' in line.lower() or 'user=' in line.lower():
                if '=' in line:
                    credentials['username'] = line.split('=', 1)[1].strip()
            elif 'password' in line.lower() or 'pass=' in line.lower():
                if '=' in line:
                    credentials['password'] = line.split('=', 1)[1].strip()
        
        return credentials if 'username' in credentials and 'password' in credentials else None
    except Exception as e:
        print(f"      ⚠️  Could not parse password file: {e}")
        return None

def create_auth_file(auth_path, username, password):
    """Create auth.txt file for OpenVPN authentication"""
    try:
        os.makedirs(os.path.dirname(auth_path), exist_ok=True)
        with open(auth_path, 'w') as f:
            f.write(f"{username}\n{password}\n")
        return True
    except Exception as e:
        print(f"      ❌ Error creating auth file: {e}")
        return False

def download_from_github(repo_url, local_path):
    """Download configs from GitHub repository"""
    print(f"\n📥 Downloading from: {repo_url}")
    
    try:
        # Convert GitHub URL to raw ZIP download
        # https://github.com/user/repo/tree/main/folder → https://github.com/user/repo/archive/refs/heads/main.zip
        parts = repo_url.strip('/').split('/')
        user = parts[3]
        repo = parts[4]
        branch = parts[6] if len(parts) > 6 else 'main'
        folder = '/'.join(parts[7:]) if len(parts) > 7 else ''
        
        zip_url = f"https://github.com/{user}/{repo}/archive/refs/heads/{branch}.zip"
        
        print(f"📦 Fetching: {zip_url}")
        response = requests.get(zip_url, timeout=30)
        response.raise_for_status()
        
        # Extract ZIP
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
            # Find the extracted folder name (usually repo-branch)
            names = zip_ref.namelist()
            base_folder = names[0].split('/')[0]
            
            # Track password files for matching with configs
            password_files = {}
            downloaded_configs = {}
            
            # First pass: identify all password.url files
            for file_info in zip_ref.filelist:
                if 'password.url' in file_info.filename.lower():
                    if folder and folder not in file_info.filename:
                        continue
                    
                    # Extract password files for reference
                    try:
                        content = zip_ref.read(file_info)
                        creds = extract_password_from_url_file(content)
                        if creds:
                            # Store for matching with configs
                            base_name = os.path.dirname(file_info.filename)
                            password_files[base_name] = creds
                            print(f"   📋 Found credentials in: {os.path.basename(file_info.filename)}")
                    except:
                        pass
            
            # Second pass: extract .ovpn files and match with passwords
            for file_info in zip_ref.filelist:
                if file_info.filename.endswith('.ovpn'):
                    # Extract only .ovpn files
                    extract_path = file_info.filename
                    if folder:
                        if folder not in extract_path:
                            continue
                    
                    content = zip_ref.read(file_info)
                    filename = os.path.basename(extract_path)
                    filepath = os.path.join(local_path, filename)
                    os.makedirs(local_path, exist_ok=True)
                    
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    
                    downloaded_configs[filepath] = filename
                    print(f"   ✓ Downloaded: {filename}")
                    
                    # Check if we have credentials for this config
                    config_dir = os.path.dirname(extract_path)
                    if config_dir in password_files:
                        creds = password_files[config_dir]
                        auth_file = os.path.join(local_path, f".auth_{filename}.txt")
                        if create_auth_file(auth_file, creds['username'], creds['password']):
                            print(f"      🔐 Created auth file: .auth_{filename}.txt")
        
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def create_vpnbook_config(server, protocol, username, password, local_path):
    """Create OpenVPN config for VPNBook server"""
    
    # Protocol to port mapping
    protocol_ports = {
        'tcp_443': ('tcp', 443),
        'tcp_80': ('tcp', 80),
        'udp_53': ('udp', 53),
        'udp_25000': ('udp', 25000)
    }
    
    if protocol not in protocol_ports:
        return False
    
    proto, port = protocol_ports[protocol]
    
    config_content = f"""
client
dev tun
proto {proto}
remote {server} {port}
resolv-retry infinite
nobind
persist-key
persist-tun
ca ca.crt
tlsauth ta.key 1
comp-lzo
verb 3
auth-user-pass auth.txt
"""
    
    # Save config
    os.makedirs(local_path, exist_ok=True)
    config_file = os.path.join(local_path, f"vpnbook_{server}_{protocol}.ovpn")
    
    with open(config_file, 'w') as f:
        f.write(config_content)
    
    # Save credentials
    auth_file = os.path.join(local_path, 'auth.txt')
    with open(auth_file, 'w') as f:
        f.write(f"{username}\n{password}\n")
    
    print(f"   ✓ Created: vpnbook_{server}_{protocol}.ovpn")
    return True

def count_configs(local_path):
    """Count downloaded .ovpn files"""
    if not os.path.exists(local_path):
        return 0
    return len([f for f in os.listdir(local_path) if f.endswith('.ovpn')])

def main():
    print_banner()
    
    # Create VPN configs directory
    root_dir = os.path.dirname(os.path.abspath(__file__))
    vpn_dir = os.path.join(root_dir, 'data', 'vpn_configs')
    
    print(f"""
🔐 OPENVPN CONFIG SOURCES:

1. 🟦 Zoult Free OpenVPN (USA configs)
   https://github.com/Zoult/.ovpn/tree/main/USA

2. 🟦 DesertSun35 Free OpenVPN Configs
   https://github.com/DesertSun35/Free-Openvpn-Configs

3. 📕 VPNBook (Commercial but free tier)
   Multiple servers: US, CA, UK, DE, FR
   Protocol options: TCP/UDP, various ports

📁 Configs will be saved to: {vpn_dir}
""")
    
    choice = input("🎯 Download VPN configs? (1=All, 2=Repos only, 3=VPNBook only, 0=Skip): ").strip()
    
    total_configs = 0
    
    if choice in ['1', '2']:
        print("\n📥 DOWNLOADING FROM GITHUB REPOSITORIES:\n")
        
        # Zoult configs
        if download_from_github('https://github.com/Zoult/.ovpn/tree/main/USA', vpn_dir):
            count = count_configs(vpn_dir)
            total_configs += count
        
        # DesertSun35 configs
        if download_from_github('https://github.com/DesertSun35/Free-Openvpn-Configs', vpn_dir):
            count = count_configs(vpn_dir)
            total_configs += count
    
    if choice in ['1', '3']:
        print("\n📕 CREATING VPNBOOK CONFIGS:\n")
        
        vpnbook_servers = [
            ('us16.vpnbook.com', 'US Server 1'),
            ('us178.vpnbook.com', 'US Server 2'),
            ('ca149.vpnbook.com', 'Canada Server 1'),
            ('uk205.vpnbook.com', 'UK Server 1'),
            ('de20.vpnbook.com', 'Germany Server 1'),
            ('fr200.vpnbook.com', 'France Server 1'),
        ]
        
        username = input("VPNBook Username (default: vpnbook): ").strip() or 'vpnbook'
        password = input("VPNBook Password (default: 939pxfv): ").strip() or '939pxfv'
        
        protocols = ['tcp_443', 'tcp_80', 'udp_53']
        
        for server, server_name in vpnbook_servers:
            print(f"Creating configs for {server_name}...")
            for protocol in protocols:
                if create_vpnbook_config(server, protocol, username, password, vpn_dir):
                    total_configs += 1
    
    if choice == '0':
        print("⏭️  Skipped VPN config download")
        return
    
    # Summary
    final_count = count_configs(vpn_dir)
    print(f"""
╔════════════════════════════════════════════════════════════════════╗
║                      ✅ DOWNLOAD COMPLETE ✅                       ║
╚════════════════════════════════════════════════════════════════════╝

📊 STATISTICS:
   ✓ Total VPN configs: {final_count}
   ✓ Saved to: {vpn_dir}

🔐 NEXT STEPS:

1. Install OpenVPN client:
   Ubuntu/Debian: sudo apt install openvpn
   macOS: brew install openvpn
   Windows: Download from openvpn.net

2. Start VPN manager:
   python3 vpn-manager.py

3. Configure in Aurora Search:
   python3 setup-proxies.py
   Choose option 6 (OpenVPN)

4. Run crawler with VPN proxies:
   python3 app.py

Each VPN connection will be available as:
   socks5://127.0.0.1:PORT

The crawler will rotate through all active VPN connections!

═════════════════════════════════════════════════════════════════════
""")

if __name__ == '__main__':
    main()
