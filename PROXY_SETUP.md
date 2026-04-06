# 🌐 PROXY SETUP GUIDE FOR AURORA SEARCH

Aurora Search supports multiple proxy types to help avoid IP bans and distribute requests better.

## 🚀 QUICK START

### Option 1: Automatic Setup (Recommended)
```bash
python3 setup-proxies.py
```
This will walk you through setting up proxies step-by-step.

### Option 2: Manual Setup
Edit `config.txt` and set:
```ini
[Proxy]
use_proxy = true
proxy_list = https://YOUR-PROXY-URL
rotate_proxy = true
```

---

## 🔵 CLOUDFLARE WORKER PROXY (Recommended - Free & Fast)

### Why Cloudflare Workers?
✅ Free account available
✅ Fast globally distributed network
✅ No rate limiting on proxied requests
✅ Easy to deploy
✅ Reliable uptime

### Setup Instructions

1. **Go to Cloudflare Workers**
   - Visit https://workers.cloudflare.com
   - Sign up for free (or log in)

2. **Create a New Worker**
   - Click "Overview" → "Create a Service"
   - Name: `aurora-search-proxy` (or any name)
   - Runtime: JavaScript (default)
   - Click "Create Service"

3. **Add the Code**
   - Delete the default code
   - Copy the entire contents of `cloudflare-worker.js`
   - Paste into the editor
   - Click "Save and Deploy"

4. **Get Your Worker URL**
   - After deployment, you'll see: `https://aurora-search-proxy.YOUR-USERNAME.workers.dev`
   - Copy this full URL

5. **Add to Aurora Search**
   ```bash
   python3 setup-proxies.py
   # Choose option 1 (Cloudflare)
   # Paste your Worker URL
   ```

6. **Verify**
   Test your proxy:
   ```bash
   curl "https://aurora-search-proxy.YOUR-USERNAME.workers.dev?url=https://example.com"
   ```

### Example Configuration
```ini
[Proxy]
use_proxy = true
proxy_list = https://aurora-search-proxy.alice.workers.dev
rotate_proxy = true
```

### Multiple Cloudflare Workers
You can deploy multiple Workers and use them together:
```ini
proxy_list = https://worker1.alice.workers.dev|https://worker2.alice.workers.dev|https://worker3.alice.workers.dev
```

---

## 📡 HTTP/HTTPS PROXIES

### Supported Formats
```
http://proxy.example.com:8080
https://proxy.example.com:8443
http://user:password@proxy.example.com:8080
```

### Popular Services
- **Bright Data** (most reliable): https://brightdata.com
- **SmartProxy**: https://smartproxy.com
- **Oxylabs**: https://oxylabs.io
- **Scaleway**: https://www.scaleway.com/en/proxy/

### Configuration
```ini
[Proxy]
use_proxy = true
proxy_list = http://user:pass@proxy.example.com:8080
rotate_proxy = true
```

### Multiple HTTP Proxies
```ini
proxy_list = http://proxy1.com:8080|http://proxy2.com:8080|http://proxy3.com:8080
```

---

## 🔐 SOCKS5 PROXIES

### Installation
First, install pysocks:
```bash
pip install pysocks --break-system-packages
```

### Supported Formats
```
socks5://proxy.example.com:1080
socks5://user:password@proxy.example.com:1080
socks5h://proxy.example.com:1080  (DNS through proxy)
```

### Configuration
```ini
[Proxy]
use_proxy = true
proxy_list = socks5://proxy.example.com:1080
rotate_proxy = true
```

### VPN Services with SOCKS5
- **ExpressVPN**: Offers SOCKS5 at 127.0.0.1:1080 (when app running)
- **ProtonVPN**: Offers SOCKS5 to Pro users
- **Private Internet Access**: Offers SOCKS5
- **Mullvad**: SOCKS5 support

---

## 🆓 FREE PROXIES

### Free Proxy Sources
- **free-proxy-list.net** - Good selection
- **proxy-list.download** - Updated frequently
- **freeproxylists.net** - Various protocols
- **proxy-server-list.org** - Verified list

⚠️ **Warning**: Free proxies may be:
- Slow
- Unreliable
- Blocked by some websites
- Less anonymous

### Best Practice
Combine multiple free proxies with rotation:
```ini
proxy_list = http://IP1:PORT1|http://IP2:PORT2|http://IP3:PORT3|http://IP4:PORT4|http://IP5:PORT5
```

### Example
```bash
python3 setup-proxies.py
# Choose option 4 (Free proxies)
# Paste: http://123.45.67.89:8080 http://98.76.54.32:3128 http://11.22.33.44:80
```

---

## 🔀 MULTIPLE PROXY TYPES

You can mix different proxy types! The crawler will rotate through them all:

```ini
[Proxy]
use_proxy = true
proxy_list = https://worker.alice.workers.dev|http://user:pass@proxy1.com:8080|socks5://proxy2.com:1080|http://123.45.67.89:8080
rotate_proxy = true
```

**Aurora Search will:**
1. Use Cloudflare Worker on request 1
2. Use HTTP proxy on request 2
3. Use SOCKS5 on request 3
4. Use free proxy on request 4
5. Circle back to Cloudflare on request 5
... and so on

---

## 🎯 USAGE

### Start with Proxies Enabled
```bash
python3 app.py
```

The crawler will:
- Automatically rotate proxies
- Log which proxy is being used
- Handle failures gracefully
- Continue crawling if a proxy fails

### Example Output
```
✅ Loaded 3 proxies from config
   1. https://worker.alice.workers.dev
   2. http://proxy1.com:8080
   3. socks5://proxy2.com:1080

🤖 Auroracrawler - Starting crawl in PARALLEL mode
   Crawl Limit: 100000 URLs
   Workers: 50 threads

Time to crawl: https://example.com
   🔗 Via: https://worker.alice.workers.dev
   ✓ Retrieved: 1234 bytes

Time to crawl: https://example.org
   🔗 Via: http://proxy1.com:8080
   ✓ Retrieved: 5678 bytes
```

---

## 🔧 CONFIGURATION OPTIONS

### Use Proxy
```ini
use_proxy = true          # Enable proxy rotation
use_proxy = false         # Disable proxies (direct connection)
```

### Proxy List
```ini
proxy_list = URL1|URL2|URL3    # Pipe-separated list
proxy_list =                    # Empty = no proxies
```

### Rotate Proxy
```ini
rotate_proxy = true       # Switch proxy for each request (recommended)
rotate_proxy = false      # Use same proxy for all requests
```

### Proxy Timeout
```ini
proxy_timeout = 15        # Timeout in seconds for proxy connections
```

---

## 🐛 TROUBLESHOOTING

### "Proxy connection refused"
- Check proxy URL is correct
- Verify proxy is online
- Try without proxy to test: `use_proxy = false`

### "Request timed out"
- Increase `proxy_timeout` in config
- Check internet connection
- Try different proxy service

### "403/429 Still getting blocked"
- Add more proxies to rotate through
- Increase delays: adjust `min_delay` and `max_delay`
- Try residential/datacenter proxy mix
- Check if site requires specific headers

### "Proxy URL incorrect"
Common mistakes:
- ❌ `worker.alice.workers.dev` (missing https://)
- ✅ `https://worker.alice.workers.dev`
- ❌ `socks5:proxy:1080` (missing //)
- ✅ `socks5://proxy:1080`

### "PySocks not installed (for SOCKS5)"
```bash
pip install pysocks --break-system-packages
```

---

## 📊 MONITORING PROXY USAGE

Check your proxy usage in real-time:

1. **Crawler Output**: Shows proxy being used for each request
2. **Status Endpoint**: Check `/status` for crawler progress
3. **Logs**: Monitor app terminal output

Example:
```bash
# Terminal 1: Start crawler
python3 app.py

# Terminal 2: Monitor status
watch -n 2 'curl -s http://localhost:5000/status | python3 -m json.tool'
```

---

## 🚀 RECOMMENDED SETUP

### For Development (Quick Testing)
```ini
[Proxy]
use_proxy = false         # No proxies needed
```

### For Production (Proper Crawling)
```ini
[Proxy]
use_proxy = true
# Deploy 3 Cloudflare Workers + 1 HTTP proxy
proxy_list = https://worker1.alice.workers.dev|https://worker2.alice.workers.dev|https://worker3.alice.workers.dev|http://user:pass@proxy.com:8080
rotate_proxy = true
proxy_timeout = 15
```

### For Large-Scale Crawling
```ini
[Proxy]
use_proxy = true
# Mix everything: Workers + HTTP + Free proxies
proxy_list = https://worker1.alice.workers.dev|https://worker2.alice.workers.dev|http://proxy1.com:8080|http://proxy2.com:8080|http://ip1:port1|http://ip2:port2|http://ip3:port3
rotate_proxy = true
proxy_timeout = 15
```

---

## 💡 BEST PRACTICES

✅ **DO:**
- Start with Cloudflare Workers (free + reliable)
- Mix multiple proxy types
- Use residential proxies for serious crawling
- Respect `robots.txt`
- Add appropriate delays between requests
- Rotate user agents

❌ **DON'T:**
- Don't crawl immediately without delays
- Don't use only free proxies for production
- Don't authenticate with multiple accounts on one IP
- Don't share proxies between many crawlers
- Don't ignore `Disallow:` rules in robots.txt

---

## 🔐 SECURITY NOTES

- Never share your proxy credentials publicly
- Don't commit `config.txt` with passwords to Git
- Use environment variables for sensitive data
- Rotate proxy credentials regularly
- Monitor for suspicious activity

To hide credentials:
```bash
git update-index --assume-unchanged config.txt
```

---

## 📚 RESOURCES

- **Cloudflare Workers Docs**: https://developers.cloudflare.com/workers/
- **Python Requests Docs**: https://docs.python-requests.org/
- **PySocks**: https://github.com/Anorov/PySocks
- **HTTP Proxy Protocol**: https://en.wikipedia.org/wiki/Proxy_server

---

**Need Help?**
Check the logs when running: `python3 app.py`
All proxy usage is logged to console!

