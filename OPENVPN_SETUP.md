# 🔐 OPENVPN SETUP GUIDE FOR AURORA SEARCH

Aurora Search can now use **free OpenVPN configs** from multiple GitHub repositories to create a distributed VPN proxy network for crawling!

## 🚀 QUICK START (3 STEPS)

### Step 1: Install OpenVPN Client
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install openvpn

# macOS
brew install openvpn

# CentOS/RHEL
sudo yum install openvpn

# Windows
Download from: https://openvpn.net/community-downloads/
```

### Step 2: Download VPN Configs
```bash
python3 download-vpn-configs.py
```
Choose "1" to download from all sources:
- ✅ Zoult USA OpenVPN configs
- ✅ DesertSun35 Free OpenVPN configs  
- ✅ VPNBook (US, Canada, UK, Germany, France servers)

Creates: `/data/vpn_configs/` with 15-30+ VPN configs

### Step 3: Start VPN Manager
```bash
python3 vpn-manager.py
```
This will:
- Launch all VPN connections in **parallel**
- Show which VPNs are active
- Create SOCKS5 proxies on localhost:1090+

### Step 4: Configure Aurora
```bash
python3 setup-proxies.py
# Choose option 6 (OpenVPN)
# Or let it auto-detect active VPNs
```

### Step 5: Crawl!
```bash
python3 app.py
```

Now your crawler rotates through all active VPN connections automatically! 🎉

---

## 📊 HOW IT WORKS

```
┌─────────────────────────────────────────────────────┐
│ Aurora Search Crawler                               │
├─────────────────────────────────────────────────────┤
│ config.txt:                                         │
│   use_proxy = true                                  │
│   proxy_list = socks5://127.0.0.1:1090|            │
│                socks5://127.0.0.1:1091|            │
│                socks5://127.0.0.1:1092             │
└────────────────┬────────────────────────────────────┘
                 │
         ┌───────┴───────┐
         │               │
    ┌────▼────┐    ┌─────▼─────┐
    │ VPN #1  │    │ VPN #2    │
    │ Port    │    │ Port      │
    │ 1090    │    │ 1091      │
    └────┬────┘    └─────┬─────┘
         │               │
    ┌────▼────┐    ┌─────▼─────┐
    │ USA     │    │ Canada    │
    │ Server  │    │ Server    │
    │ IP1     │    │ IP2       │
    └────┬────┘    └─────┬─────┘
         │               │
    ┌────▼──────────────▼─────┐
    │ Crawling target URLs    │
    │ (Rotates through VPNs)  │
    └─────────────────────────┘
```

Each crawler request:
1. Picks next VPN from rotation list
2. Routes request through that VPN's tunnel
3. Target server sees VPN's IP, not yours
4. Next request uses different VPN
5. Distributes crawl across multiple IPs

---

## 📁 FILE STRUCTURE

```
/workspaces/Aurora-Search/
├── download-vpn-configs.py    # Download free VPN configs
├── vpn-manager.py             # Manage VPN connections
├── setup-proxies.py           # Configure proxies (updated with VPN option)
├── OPENVPN_SETUP.md           # This file
└── data/
    └── vpn_configs/           # Downloaded .ovpn files
        ├── us-config1.ovpn
        ├── .auth_us-config1.ovpn.txt     # 🔐 Auto-generated credentials
        ├── us-config2.ovpn
        ├── .auth_us-config2.ovpn.txt
        ├── ca-config1.ovpn
        ├── vpnbook_us16_tcp_443.ovpn
        └── ... (15-30+ configs + auth files)
```

---

## 🔐 AUTOMATIC PASSWORD HANDLING

### How It Works

When you download VPN configs, Aurora Search **automatically**:

1. **Finds password files** in the GitHub repos (e.g., `FOV password.url`, `VBK password.url`)
2. **Extracts credentials** from password.url files (username + randomly-generated password)
3. **Creates auth files** named `.auth_configname.ovpn.txt` for OpenVPN
4. **Applies credentials** when starting each VPN connection

### Workflow

```
Step 1: Download VPN Configs
  python3 download-vpn-configs.py
  
  ✓ Found credentials in: FOV password.url
  ✓ Found credentials in: VBK password.url
  ✓ Downloaded: us-config1.ovpn
  ✓ Created auth file: .auth_us-config1.ovpn.txt

Step 2: Start VPN Manager
  python3 vpn-manager.py
  
  🔐 Using credentials from: .auth_us-config1.ovpn.txt
  🚀 Starting: us-config1.ovpn (port 1090)
  ✅ Started: us-config1.ovpn

Step 3: VPN connects using auto-detected credentials
  ✅ Tunnel established with authentication
```

### Important Notes

- ⚠️ **Passwords are randomly generated** - Each download gets new credentials  
- ✅ **Auto-applied** - No manual credential entry needed
- 🔒 **Stored locally** - Auth files only on your machine
- 📋 **One auth file per config** - Named `.auth_configname.ovpn.txt`

### Example Auth File Structure

If a repo has configs with passwords like:

```
https://github.com/Zoult/.ovpn/tree/main/USA/
├── FOV.ovpn
├── FOV password.url        ← Contains: user=vpnuser, pass=abc123xyz
├── VBK.ovpn  
└── VBK password.url        ← Contains: user=vpnuser, pass=xyz789abc
```

Aurora automatically creates:
```
data/vpn_configs/
├── FOV.ovpn
├── .auth_FOV.ovpn.txt      (Contains: vpnuser\nabc123xyz)
├── VBK.ovpn
└── .auth_VBK.ovpn.txt      (Contains: vpnuser\nxyz789abc)
```

---

## 🔐 VPN CONFIG SOURCES

### 1. **Zoult USA OpenVPN** (Recommended)
- **URL**: https://github.com/Zoult/.ovpn/tree/main/USA
- **Servers**: USA-based
- **Auth**: Most are username/password protected
- **Quality**: ⭐⭐⭐⭐ (Very reliable)
- **Speed**: Fast, optimized for speed
- **Count**: 5-10 configs

### 2. **DesertSun35 Free OpenVPN**
- **URL**: https://github.com/DesertSun35/Free-Openvpn-Configs  
- **Servers**: Various (worldwide)
- **Auth**: Most are pre-configured
- **Quality**: ⭐⭐⭐ (Good)
- **Speed**: Variable
- **Count**: 10-20 configs

### 3. **VPNBook** (Free Tier)
- **Services**: vpnbook.com
- **Servers**: US, Canada, UK, Germany, France
- **Auth**: vpnbook / 939pxfv (free tier credentials)
- **Quality**: ⭐⭐⭐⭐ (Professional)
- **Speed**: ⚡⚡⚡ (Fast, reliable)
- **Count**: Auto-generates 12+ from 6 servers × 2 protocols

---

## 🎯 USAGE EXAMPLES

### Example 1: Auto-Detect VPNs (Easiest)
```bash
# Terminal 1: Start VPN manager
python3 vpn-manager.py

# Terminal 2: Configure Aurora
python3 setup-proxies.py
# Choose 6 (OpenVPN), then auto-detect

# Terminal 3: Crawl
python3 app.py
```

### Example 2: Manual Setup
```bash
# Edit config.txt
[Proxy]
use_proxy = true
proxy_list = socks5://127.0.0.1:1090|socks5://127.0.0.1:1091|socks5://127.0.0.1:1092
rotate_proxy = true

# Run crawler
python3 app.py
```

### Example 3: Mix VPN + HTTP Proxies
```bash
# config.txt
[Proxy]
use_proxy = true
proxy_list = socks5://127.0.0.1:1090|socks5://127.0.0.1:1091|http://proxy1.com:8080|http://proxy2.com:8080
rotate_proxy = true
```

---

## 📊 MONITORING VPNs

### Check Active Connections
```bash
# While VPN manager is running
ps aux | grep openvpn
```

### View VPN Logs
```bash
# Check connection status and errors
tail -f data/vpn_*.log
```

### Real-time Status
```bash
# In VPN manager output, see:
Config                             Port     Auth   Status
===========================================================
us-config1.ovpn                    1090     🔐     ✅ active
us-config2.ovpn                    1091     🔐     ✅ active
ca-config1.ovpn                    1092     •      ✅ active
vpnbook_us16_tcp_443.ovpn          1093     🔐     ⏳ starting
free-config.ovpn                   1094     •      🔴 dead

Legend:
  🔐 = VPN uses authentication (credentials auto-applied)
  •  = VPN is pre-configured (no auth needed)
  ✅ = Active/Connected
  ⏳ = Starting/Connecting
  🔴 = Dead/Failed
```

### Crawler Output
```
Time to crawl: https://example.com
🔗 Via: socks5://127.0.0.1:1090
✓ Retrieved: 5000 bytes

Time to crawl: https://example.org
🔗 Via: socks5://127.0.0.1:1091
✓ Retrieved: 3000 bytes
```

---

## ⚙️ CONFIGURATION OPTIONS

### In config.txt:

```ini
[Proxy]
# Enable proxy rotation
use_proxy = true

# SOCKS5 proxies from active VPNs
proxy_list = socks5://127.0.0.1:1090|socks5://127.0.0.1:1091|socks5://127.0.0.1:1092

# Rotate proxy on each request
rotate_proxy = true

# Timeout for proxy connections
proxy_timeout = 15
```

### VPN Manager Options:

```bash
# Edit vpn-manager.py to customize:
port_base = 1090          # Starting port for VPNs
vpn_configs_dir = ...     # Path to .ovpn files
```

---

## 🐛 TROUBLESHOOTING

### "OpenVPN not found"
```bash
# Install OpenVPN:
sudo apt install openvpn

# Or macOS:
brew install openvpn
```

### "No active VPN connections"
```bash
# Check if VPN manager is running:
python3 vpn-manager.py

# Check OpenVPN logs:
tail -f data/vpn_*.log

# Common issues:
# - Wrong credentials in config
# - Missing ca.crt or ta.key files
# - VPN server blocked/down
# - Need to accept license or disclaimer
```

### "Connection refused on localhost:1090"
```bash
# VPN manager not running - start it:
python3 vpn-manager.py

# Or VPN failed to start - check logs:
tail -f data/vpn_*.log
```

### "Slow crawling speed"
```bash
# Options:
# 1. Use only fastest VPNs (remove slow ones)
# 2. Increase crawler workers in config.txt
# 3. Use fewer VPN connections
# 4. Use HTTP proxies + VPN mix for speed

[Crawler]
num_workers = 50

[Proxy]
# Mix fast proxies with VPNs
proxy_list = http://proxy1:8080|socks5://127.0.0.1:1090|http://proxy2:8080
```

### "VPN disconnects during crawl"
```bash
# VPN manager monitors and can restart
# Or use residential proxies for reliability

# To manually restart:
python3 vpn-manager.py
# Will reconnect all VPNs
```

### "Auth failed for VPNBook"
```bash
# Check credentials in config
# Default VPNBook free tier:
username: vpnbook
password: 939pxfv

# Some configs may need updating
# Download fresh configs:
python3 download-vpn-configs.py
```

---

## 🔒 SECURITY NOTES

✅ **DO:**
- Keep OpenVPN updated
- Use trusted VPN configs (GitHub repos are good)
- Monitor bandwidth logs
- Rotate VPN configs periodically
- Use rotating VPNs for ethical crawling

❌ **DON'T:**
- Share VPN auth credentials
- Store passwords in code
- Commit config.txt with credentials to Git
- Use for illegal activities
- Overload VPN servers

**Git Safety:**
```bash
# Hide config.txt from Git:
git update-index --assume-unchanged config.txt

# Or use .gitignore:
echo "config.txt" >> .gitignore
```

---

## 📈 PERFORMANCE TIPS

### 1. **Use Reliable VPNs Only**
```bash
# Remove slow/dead configs:
ls -la data/vpn_configs/
# Delete problematic .ovpn files
```

### 2. **Optimize Crawler for VPN**
```ini
# config.txt
[Proxy]
proxy_timeout = 20          # Increase timeout for VPN
rotate_proxy = true         # Rotate between VPNs

[Crawler]
num_workers = 50            # Parallel requests
min_delay = 1               # Less delay (VPN adds latency)
max_delay = 3
```

### 3. **Monitor Active VPNs**
```bash
# Keep VPN manager running in separate terminal
# Watch active count
python3 vpn-manager.py
```

### 4. **Mix Proxy Types**
```ini
# Fastest: Direct
# Fast: Cloudflare Worker  
# Medium: HTTP Proxy
# Slow: VPN (but best for avoiding bans)

proxy_list = https://worker.alice.workers.dev|http://proxy:8080|socks5://127.0.0.1:1090
```

---

## 💡 ADVANCED SETUP

### Using with Multiple VPN Providers

```bash
# Download configs from multiple repos
mkdir -p data/vpn_configs

# Zoult + DesertSun35 + VPNBook all in one
python3 download-vpn-configs.py
# Choose option 1 (All sources)

# Start all in parallel
python3 vpn-manager.py
```

### Running Multiple Crawlers with Different VPNs

```bash
# Terminal 1: Start VPN manager
python3 vpn-manager.py

# Terminal 2: Crawler 1 with VPN rotation
python3 app.py
# Uses config.txt with all VPNs

# Terminal 3: Crawler 2 (different config)
CRAWLER_ID=2 python3 app.py
# Can use subset of VPNs
```

### Automatic VPN Reconnection

VPN manager automatically:
- Detects dead VPNs
- Logs status changes  
- Maintains active connection list
- Updates crawler's proxy list

```bash
# Runs continuously:
python3 vpn-manager.py

# Logs active VPNs every 5 seconds
```

---

## 🚀 FULL WORKFLOW

```bash
# 1. Install OpenVPN
sudo apt install openvpn

# 2. Download VPN configs from GitHub
python3 download-vpn-configs.py
# Choose all sources

# 3. Start VPN manager (in background)
python3 vpn-manager.py &

# 4. Configure Aurora proxies
python3 setup-proxies.py
# Choose option 6 (OpenVPN)

# 5. Start crawler
python3 app.py

# Now crawling with rotating VPN proxies!
# Each request uses different VPN tunnel
# Server sees different IPs for each request
```

---

## 📚 RESOURCES

- **OpenVPN Docs**: https://openvpn.net/
- **VPNBook**: https://www.vpnbook.com
- **Zoult Configs**: https://github.com/Zoult/.ovpn
- **DesertSun35**: https://github.com/DesertSun35/Free-Openvpn-Configs

---


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

## ❓ FAQ

**Q: Will crawling with VPN be slow?**
A: Yes, slightly. VPNs add latency. Use HTTP proxies for speed, VPNs for avoiding bans.

**Q: Can I use VPN + HTTP proxies together?**
A: Yes! Mix them in proxy_list to optimize speed and reliability.

**Q: How many VPNs can I run?**
A: Depends on system resources. 10-20 is reasonable. Each uses some RAM/CPU.

**Q: What if a VPN drops?**
A: VPN manager detects it. Either restart or use other active VPNs.

**Q: Is free VPN safe?**
A: These configs are community-maintained. Use trusted sources (GitHub). For sensitive work, use paid VPN.

**Q: Can this get me blocked?**
A: Using rotating VPNs is better than using same IP, but excessive crawling can still get you blocked. Respect robots.txt!

---

**Ready to crawl with distributed VPNs? 🚀**

Start with: `python3 download-vpn-configs.py`

