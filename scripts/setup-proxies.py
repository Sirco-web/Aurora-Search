#!/usr/bin/env python3
"""
Aurora Search Proxy Setup Script
Configure various proxy types for the crawler:
- Cloudflare Workers
- Free proxy services
- VPN proxies
- Custom proxies
"""

import sys
import configparser
import os

def load_config():
    """Load config.txt"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.txt')
    if os.path.exists(config_path):
        config.read(config_path)
    return config, config_path

def print_banner():
    print("""
╔════════════════════════════════════════════════════════════════════╗
║           🌐 AURORA SEARCH PROXY SETUP WIZARD 🌐                  ║
╚════════════════════════════════════════════════════════════════════╝
""")

def show_proxy_types():
    print("""
📚 SUPPORTED PROXY TYPES:

1. 🔵 Cloudflare Worker (Recommended)
   - Free, fast, and reliable
   - Deploy cloudflare-worker.js to Cloudflare Workers
   - No rate limiting or blocking
   - Format: https://YOUR-WORKER-NAME.workers.dev

2. 📡 HTTP/HTTPS Proxies
   - Standard HTTP proxies
   - Format: http://IP:PORT or https://IP:PORT
   - Format with auth: http://user:pass@IP:PORT

3. 🔐 VPN Proxies
   - SOCKS5 proxies (via VPN services)
   - Format: socks5://IP:PORT
   - Format with auth: socks5://user:pass@IP:PORT

4. 🆓 Free Proxy Lists
   - Services like: free-proxy-list.net, proxy-list.download
   - Warning: Quality varies, may be slow/unreliable
   - Format: http://IP:PORT

5. 🌍 Residential Proxies
   - From services like: Bright Data, SmartProxy
   - Most reliable for avoiding bans
   - Format: http://user:pass@proxy-service.com:PORT

6. 🔐 OpenVPN Connections (NEW!)
   - Use local OpenVPN configs to start a tunnel before crawling
   - Managed by the server startup prompts or vpn-manager.py
   - This is a system route, not a proxy_list entry
""")

def setup_cloudflare():
    print("""
🔵 CLOUDFLARE WORKER SETUP:

1. Go to https://workers.cloudflare.com
2. Sign up (free account)
3. Click "Create a Service"
4. Name it something like "aurora-search-proxy"
5. Copy contents from cloudflare-worker.js into the editor
6. Save and Deploy
7. Your Worker URL will be: https://aurora-search-proxy.YOUR-USERNAME.workers.dev

Example URL: https://my-proxy.alice.workers.dev

Copy the full URL and enter it here:
""")
    
    worker_url = input("🔗 Cloudflare Worker URL: ").strip()
    if not worker_url:
        print("❌ No URL provided. Skipping Cloudflare setup.")
        return None
    
    if not worker_url.startswith('http'):
        worker_url = 'https://' + worker_url
    
    print(f"✅ Cloudflare Worker added: {worker_url}")
    return worker_url

def setup_http_proxy():
    print("""
📡 HTTP/HTTPS PROXY SETUP:

Examples:
  - http://proxy.example.com:8080
  - http://user:password@proxy.example.com:8080
  - https://proxy.example.com:8443
""")
    
    proxy = input("🔗 HTTP Proxy URL (or skip): ").strip()
    if not proxy:
        print("⏭️  Skipped HTTP proxy setup.")
        return None
    
    print(f"✅ HTTP Proxy added: {proxy}")
    return proxy

def setup_socks5():
    print("""
🔐 SOCKS5 PROXY SETUP:

Examples:
  - socks5://proxy.example.com:1080
  - socks5://user:password@proxy.example.com:1080
  - socks5h://proxy.example.com:1080 (DNS through proxy)
""")
    
    proxy = input("🔗 SOCKS5 Proxy URL (or skip): ").strip()
    if not proxy:
        print("⏭️  Skipped SOCKS5 proxy setup.")
        return None
    
    print(f"✅ SOCKS5 Proxy added: {proxy}")
    return proxy

def setup_free_proxies():
    print("""
🆓 FREE PROXY SETUP:

Free proxy sources:
  - free-proxy-list.net
  - proxy-list.download
  - freeproxylists.net
  - proxy-server-list.org

Paste proxies (comma-separated or line-by-line):
Examples:
  - IP1:PORT1,IP2:PORT2,IP3:PORT3
  - http://IP1:PORT1 http://IP2:PORT2

⚠️  Warning: Free proxies may be slow/unreliable
""")
    
    proxies_input = input("🔗 Free Proxies (or skip): ").strip()
    if not proxies_input:
        print("⏭️  Skipped free proxy setup.")
        return None
    
    # Parse and format proxies
    proxies = []
    for proxy in proxies_input.replace(',', ' ').split():
        proxy = proxy.strip()
        if proxy:
            if not proxy.startswith('http'):
                proxy = 'http://' + proxy
            proxies.append(proxy)
    
    if proxies:
        print(f"✅ Added {len(proxies)} free proxies")
        return '|'.join(proxies)
    return None

def setup_openvpn():
    print("""
🔐 OPENVPN SETUP:

OpenVPN is now started directly by the server startup flow.

Recommended steps:
  1. python3 scripts/download-vpn-configs.py
  2. python3 app.py
  3. Answer "yes" when the server asks whether it should start a VPN tunnel

OpenVPN tunnels are not added to proxy_list, so there is nothing to save here.
""")
    return None

def save_config(config, config_path, proxies_list, use_proxy):
    """Save proxy configuration to config.txt"""
    if 'Proxy' not in config:
        config.add_section('Proxy')
    
    config.set('Proxy', 'use_proxy', str(use_proxy).lower())
    config.set('Proxy', 'proxy_list', proxies_list or '')
    config.set('Proxy', 'rotate_proxy', 'true')
    config.set('Proxy', 'proxy_timeout', '15')
    
    with open(config_path, 'w') as f:
        config.write(f)
    
    print(f"\n✅ Config saved to {config_path}")

def main():
    print_banner()
    
    config, config_path = load_config()
    show_proxy_types()
    
    choice = input("\n🎯 Setup which proxy type?\n(1=Cloudflare, 2=HTTP, 3=SOCKS5, 4=Free, 5=Multiple, 6=OpenVPN, 0=Skip): ").strip()
    
    proxies = []
    
    if choice == '1':
        proxy = setup_cloudflare()
        if proxy:
            proxies.append(proxy)
    
    elif choice == '2':
        proxy = setup_http_proxy()
        if proxy:
            proxies.append(proxy)
    
    elif choice == '3':
        proxy = setup_socks5()
        if proxy:
            proxies.append(proxy)
    
    elif choice == '4':
        proxy = setup_free_proxies()
        if proxy:
            proxies.append(proxy)
    
    elif choice == '5':
        print("\n🔀 MULTIPLE PROXY SETUP")
        proxy = setup_cloudflare()
        if proxy:
            proxies.append(proxy)
        
        proxy = setup_http_proxy()
        if proxy:
            proxies.append(proxy)
        
        proxy = setup_socks5()
        if proxy:
            proxies.append(proxy)
    
    elif choice == '6':
        print("\n🔐 OPENVPN SETUP")
        setup_openvpn()
        return
    
    else:
        print("❌ Skipped proxy setup")
        return
    
    if not proxies:
        print("❌ No proxies configured. Exiting.")
        return
    
    proxies_list = '|'.join(proxies)
    
    print(f"""
╔════════════════════════════════════════════════════════════════════╗
║                    📋 CONFIGURATION SUMMARY                        ║
╚════════════════════════════════════════════════════════════════════╝

Proxies to use: {len(proxies)}
  - {chr(10).join(proxies)}

✅ Ready to save to config.txt
""")
    
    confirm = input("Save configuration? (y/n): ").strip().lower()
    if confirm == 'y':
        save_config(config, config_path, proxies_list, True)
        
        print("""
✅ PROXY SETUP COMPLETE!

Next steps:
1. Run: python3 app.py
2. Crawler will automatically rotate through your proxies
3. Check /status endpoint to see proxy usage

Your crawler will now:
  ✓ Rotate proxies on each request
  ✓ Avoid IP bans
  ✓ Respect rate limits better
  ✓ Appear as different IPs

Tips:
  - Start with Cloudflare Worker (most reliable)
  - Add multiple proxies for better distribution
  - Cloudflare Worker is free and recommended
  - Rotate proxies automatically every request
""")
    else:
        print("⏭️  Configuration not saved.")

if __name__ == '__main__':
    main()
