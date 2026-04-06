#!/usr/bin/env python3
"""
Aurora Search VPN Manager
Manages multiple OpenVPN connections in parallel
Routes crawler requests through active VPN tunnels
"""

import os
import sys
import subprocess
import time
import signal
import threading
from pathlib import Path
import psutil

class VPNManager:
    def __init__(self):
        self.vpn_processes = {}
        self.active_vpns = []
        self.port_base = 1090
        self.root_dir = os.path.dirname(os.path.abspath(__file__))
        self.vpn_configs_dir = os.path.join(self.root_dir, 'data', 'vpn_configs')
        
    def find_vpn_configs(self):
        """Find all .ovpn config files"""
        if not os.path.exists(self.vpn_configs_dir):
            print(f"❌ VPN configs directory not found: {self.vpn_configs_dir}")
            return []
        
        configs = [f for f in os.listdir(self.vpn_configs_dir) if f.endswith('.ovpn')]
        return sorted(configs)
    
    def check_openvpn_installed(self):
        """Check if OpenVPN is installed"""
        try:
            subprocess.run(['openvpn', '--version'], 
                         capture_output=True, check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def start_vpn(self, config_file, port):
        """Start OpenVPN with specific config"""
        config_path = os.path.join(self.vpn_configs_dir, config_file)
        
        if not os.path.exists(config_path):
            print(f"❌ Config not found: {config_file}")
            return False
        
        try:
            # Create log file for this VPN
            log_file = os.path.join(self.root_dir, 'data', f'vpn_{config_file}.log')
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            # OpenVPN command
            cmd = [
                'openvpn',
                '--config', config_path,
                '--log', log_file,
                '--daemon',  # Run as daemon
                '--writepid', os.path.join(self.root_dir, f'vpn_{port}.pid'),
            ]
            
            # Check for auth file (password-protected VPN)
            # Auth files are named: .auth_<config_name>.txt
            auth_file = os.path.join(self.vpn_configs_dir, f'.auth_{config_file}.txt')
            if os.path.exists(auth_file):
                cmd.extend(['--auth-user-pass', auth_file])
                print(f"   🔐 Using credentials from: .auth_{config_file}.txt")
            
            print(f"   🚀 Starting: {config_file} (port {port})")
            
            # Start process
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.vpn_processes[config_file] = {
                    'port': port,
                    'config': config_file,
                    'status': 'starting',
                    'has_auth': os.path.exists(auth_file)
                }
                print(f"   ✅ Started: {config_file}")
                return True
            else:
                print(f"   ❌ Failed to start {config_file}: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"   ❌ Error starting {config_file}: {e}")
            return False
    
    def check_vpn_status(self):
        """Check status of active VPN connections"""
        active = []
        
        for config, info in self.vpn_processes.items():
            pid_file = os.path.join(self.root_dir, f"vpn_{info['port']}.pid")
            
            if os.path.exists(pid_file):
                try:
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())
                    
                    # Check if process still running
                    if psutil.pid_exists(pid):
                        info['status'] = 'active'
                        active.append(config)
                    else:
                        info['status'] = 'dead'
                except:
                    info['status'] = 'unknown'
        
        return active
    
    def list_vpn_connections(self):
        """List all VPN connections"""
        print(f"\n{'Config':<35} {'Port':<8} {'Auth':<8} {'Status':<12}")
        print("="*65)
        
        for config, info in self.vpn_processes.items():
            status = info['status']
            port = info['port']
            has_auth = '🔐' if info.get('has_auth', False) else '•'
            status_icon = '✅' if status == 'active' else '🔴' if status == 'dead' else '⏳'
            print(f"{config:<35} {port:<8} {has_auth:<8} {status_icon} {status:<10}")
    
    def generate_proxy_list(self):
        """Generate proxy list from active VPNs"""
        active = self.check_vpn_status()
        self.active_vpns = active
        
        proxies = []
        for config in active:
            port = self.vpn_processes[config]['port']
            # Each VPN acts as a SOCKS5 proxy on localhost
            proxies.append(f'socks5://127.0.0.1:{port}')
        
        return '|'.join(proxies) if proxies else ''
    
    def main(self):
        """Main VPN manager loop"""
        print("""
╔════════════════════════════════════════════════════════════════════╗
║             🔐 AURORA SEARCH VPN MANAGER 🔐                       ║
╚════════════════════════════════════════════════════════════════════╝
""")
        
        # Check OpenVPN installed
        if not self.check_openvpn_installed():
            print("""
❌ OpenVPN is not installed!

Install OpenVPN:

Ubuntu/Debian:
  sudo apt update
  sudo apt install openvpn

macOS:
  brew install openvpn

Windows:
  Download from: https://openvpn.net/community-downloads/

CentOS/RHEL:
  sudo yum install openvpn
""")
            return False
        
        print("✅ OpenVPN detected\n")
        
        # Find configs
        configs = self.find_vpn_configs()
        if not configs:
            print(f"❌ No VPN configs found in: {self.vpn_configs_dir}")
            print("\nRun: python3 download-vpn-configs.py")
            return False
        
        print(f"📁 Found {len(configs)} VPN configs:\n")
        for i, config in enumerate(configs, 1):
            print(f"   {i:2}. {config}")
        
        # Ask which to start
        print(f"\n🎯 Start VPN connections:")
        choice = input("Start all VPNs? (y/n): ").strip().lower()
        
        if choice != 'y':
            print("⏭️  Skipped VPN startup")
            return False
        
        print("\n🚀 STARTING VPN CONNECTIONS:\n")
        
        # Start all configs
        started = 0
        for i, config in enumerate(configs):
            port = self.port_base + i
            if self.start_vpn(config, port):
                started += 1
            time.sleep(0.5)  # Stagger starts
        
        # Wait for VPNs to connect
        print("\n⏳ Waiting for VPN connections to establish...")
        time.sleep(10)
        
        # Check status
        print("\n📊 VPN CONNECTION STATUS:\n")
        self.list_vpn_connections()
        
        active = self.check_vpn_status()
        print(f"\n✅ Active VPNs: {len(active)}/{started}")
        
        if not active:
            print("⚠️  No active VPN connections!")
            return False
        
        # Generate proxy list
        proxy_list = self.generate_proxy_list()
        print(f"\n🔗 Available as proxies:")
        for proxy in proxy_list.split('|'):
            print(f"   {proxy}")
        
        # Option to update config
        update = input("\nUpdate Aurora config with these VPNs? (y/n): ").strip().lower()
        if update == 'y':
            self.update_aurora_config(proxy_list)
        
        # Keep running
        print(f"""
╔════════════════════════════════════════════════════════════════════╗
║                  🔐 VPN Manager Running 🔐                        ║
╚════════════════════════════════════════════════════════════════════╝

Proxy URLs available:
{chr(10).join(f'   socks5://127.0.0.1:{self.vpn_processes[c]["port"]}' for c in active)}

Use in Aurora Search:
  python3 setup-proxies.py
  Choose option 6 (Use Active VPNs)

Or manually:
  Edit config.txt [Proxy] section:
  use_proxy = true
  proxy_list = {proxy_list}

Press Ctrl+C to stop VPN manager...
""")
        
        try:
            while True:
                time.sleep(5)
                # Check for dead VPNs and log status
                active = self.check_vpn_status()
                if len(active) != len(self.active_vpns):
                    print(f"⚠️  VPN status changed. Active: {len(active)}")
                    self.list_vpn_connections()
        except KeyboardInterrupt:
            print("\n\n⏹️  Stopping VPN manager...")
            self.stop_all_vpns()
    
    def stop_all_vpns(self):
        """Stop all VPN connections"""
        print("Stopping VPN connections...")
        for config, info in self.vpn_processes.items():
            port = info['port']
            pid_file = os.path.join(self.root_dir, f"vpn_{port}.pid")
            
            if os.path.exists(pid_file):
                try:
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())
                    
                    os.kill(pid, signal.SIGTERM)
                    print(f"   ✅ Stopped: {config}")
                except:
                    pass
    
    def update_aurora_config(self, proxy_list):
        """Update Aurora config.txt with VPN proxies"""
        config_path = os.path.join(self.root_dir, 'config.txt')
        
        try:
            with open(config_path, 'r') as f:
                lines = f.readlines()
            
            # Find and update proxy section
            in_proxy_section = False
            new_lines = []
            
            for line in lines:
                if line.strip().startswith('[Proxy]'):
                    in_proxy_section = True
                    new_lines.append(line)
                elif in_proxy_section and line.strip().startswith('proxy_list'):
                    new_lines.append(f'proxy_list = {proxy_list}\n')
                    in_proxy_section = False
                elif in_proxy_section and line.strip().startswith('['):
                    in_proxy_section = False
                    new_lines.append(line)
                elif in_proxy_section and line.strip().startswith('use_proxy'):
                    new_lines.append('use_proxy = true\n')
                else:
                    new_lines.append(line)
            
            with open(config_path, 'w') as f:
                f.writelines(new_lines)
            
            print(f"✅ Updated config.txt with VPN proxies")
        except Exception as e:
            print(f"❌ Error updating config: {e}")

if __name__ == '__main__':
    manager = VPNManager()
    manager.main()
