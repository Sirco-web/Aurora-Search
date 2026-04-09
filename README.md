# 🌐 Aurora Search - A Full-Featured Search Engine

Aurora Search is a complete, production-ready web search engine that replicates Google's core functionality: **web crawling, intelligent indexing, and advanced ranking**. It combines three sophisticated ranking algorithms to deliver highly relevant search results from across the web.

---

## ✨ Features

### 🚀 **Advanced Web Crawling**
- **Distributed crawling** with 80+ concurrent worker threads
- **Smart domain management**: Max 200 pages per domain to ensure diversity
- **Crawl resumption**: Automatically resume from last checkpoint and detect new seed URLs
- **Robots.txt compliance**: Respects website crawling rules
- **Intelligent deduplication**: Detects duplicate content via fingerprinting
- **Circuit breaker pattern**: Temporarily blocks consistently failing domains
- **Configurable crawl depth**: 1-5 levels of link following

### 🔍 **Intelligent Indexing**
- **Full-text search** using inverted index structure
- **NLP processing**: Tokenization, stemming, stopword removal (NLTK)
- **Rich metadata extraction**: Title, description, word count, publish date
- **Content fingerprinting**: Duplicate detection via SHA1 hashing
- **Automatic resume**: Continues from previous crawl state

### 📊 **Live Crawl Visualization**
- **Real-time graph visualization** of crawler activity
- **Interactive web interface** at `/web` - zoom, pan, click for details
- **WebSocket streaming** of crawler events
- **Stats dashboard** showing crawled/pending/failed counts
- **Domain clustering** to see which sites are being crawled
- **Demo mode** to preview visualization without real crawler
- **Physics-based layout** with 1000+ node capacity

### 🏆 **Three-Tier Ranking Algorithm**

Aurora Search combines **three sophisticated signals** for ranking:

#### 1. **PageRank (40% weight)** 🔗
- Link-based page authority scoring
- Iterative algorithm based on Google's PageRank
- Identifies important pages through link topology
- Handles dangling nodes (pages with no outlinks)

#### 2. **Panda (35% weight)** 🐼
**Content Quality Scoring** - Evaluates page quality across multiple dimensions:
- **Content Length** (25%): Prefers depth (1000-3000 words ideal)
- **HTML Structure** (15%): Proper headings, paragraphs, lists
- **Readability** (15%): Optimal sentence and word length
- **Keyword Naturalness** (15%): Detects and penalizes keyword stuffing
- **Originality** (25%): SHA1 fingerprint comparison prevents duplicates
- **Freshness** (5%): Prefers recently updated content

#### 3. **Penguin (15% weight)** 🐧
**Link Quality Scoring** - Evaluates trustworthiness and link integrity:
- **Backlink Quality**: Scores based on source domain authority
- **Anchor Text Analysis**: Detects natural vs. artificial linking patterns
- **Domain Authority**: Wikipedia, GitHub, StackOverflow score ~0.9
- **Link Relevance**: Ensures links relate to page content
- **Spam Prevention**: Detects and penalizes link farms

#### 4. **Query Relevance (10% weight)** 📊
- TF-IDF scoring for query term matching
- Boosts pages with keywords in title/description
- Penalizes generic homepage results

**Final Formula:**
```
Score = (PageRank × 0.4) + (Panda × 0.35) + (Penguin × 0.15) + (Relevance × 0.1)
```

---

## 🏗️ Architecture

### **Directory Structure**
```
aurora-search/
├── app.py                          # Flask web server & search API
├── config.txt                      # Crawler configuration
├── requirements.txt                # Python dependencies
│
├── scripts/                        # Core modules
│   ├── crawler.py                  # Web crawler engine
│   ├── indexing.py                 # Text processing & index building
│   ├── ranking.py                  # Unified ranking algorithm
│   ├── pagerank.py                 # PageRank computation
│   ├── panda.py                    # Content quality scoring
│   ├── penguin.py                  # Link quality scoring
│   ├── vpn_manager.py              # OpenVPN management
│   ├── local_vpn_proxy.py          # SOCKS5 proxy creation
│   └── setup-proxies.py            # Proxy configuration wizard
│
├── public/                         # Frontend UI
│   ├── index.html                  # Home page (search box)
│   ├── search.html                 # Results page with pagination
│   ├── status.html                 # Crawler status dashboard
│   ├── styles.css                  # Dark theme styling
│   └── images/                     # Favicons & icons
│
└── data/                           # Search index storage
    ├── inverted_index.json         # word → [doc_ids]
    ├── doc_info.json               # doc_id → metadata
    └── vpn_health.json             # VPN status tracking
```

### **Data Flow**
```
Seed URLs → Web Crawler → HTML Parser → Indexing Pipeline → Document Storage
                ↓                              ↓
           Link Graph         Inverted Index + Metadata
                ↓                              ↓
           PageRank Algorithm          Content Quality (Panda)
                                             ↓
                                      Link Quality (Penguin)
                                             ↓
                                    User Search Query
                                             ↓
                                    Ranked Results
```

---

## 🚀 Getting Started

### **1. Installation**

```bash
# Clone repository
git clone https://github.com/Sirco-web/Aurora-Search.git
cd Aurora-Search

# Install dependencies
pip install -r requirements.txt
```

**Requirements:**
- Python 3.8+
- BeautifulSoup4 (HTML parsing)
- NLTK (Natural Language Processing)
- Flask (Web server)
- requests (HTTP client)
- psutil (System monitoring)

### **2. Configure the Crawler**

Edit `config.txt` to customize:

```ini
[Crawler]
crawler_name = SircoAuroraBot           # Crawler user-agent name
crawl_limit = 100000                    # Max pages to crawl
num_workers = 80                        # Concurrent threads
request_timeout = 8                     # Seconds per request
max_pages_per_domain = 200              # Per-domain limit
max_crawl_depth = 3                     # Link following depth
min_delay = 1                           # Min delay between requests
max_delay = 2                           # Max delay (random between)
```

### **3. Start the Search Engine**

```bash
# Run crawler + search API + web server
python3 app.py
```

The server will:
1. Start the web crawler in background
2. Build inverted index from crawled pages
3. Launch Flask API on `http://localhost:5000`
4. Serve search interface and status dashboard

**Access the interface:**
- **Search**: http://localhost:5000/index.html
- **Results**: http://localhost:5000/search.html?search=your+query
- **Crawler Status**: http://localhost:5000/status.html
- **🌟 Live Crawl Map**: http://localhost:5000/web

---

## 🌐 Live Crawl Visualization

Aurora Search includes an **interactive real-time crawler visualization** that shows what's being crawled in real-time!

### Quick Start

Visit **http://localhost:5000/web** while Aurora Search is running to see:
- 🟢 Green nodes = Successfully crawled pages
- 🟡 Yellow nodes = Pages waiting to crawl
- 🔴 Red nodes = Failed crawls
- Edges = Links discovered between pages

### Try the Demo

No crawler running? No problem! Click **▶ Start Demo** to see a simulated crawl:
- Watch nodes appear as pages are "crawled"
- See the graph layout itself in real-time
- Click nodes for page details
- Monitor live statistics on the sidebar

**For complete documentation, see [VISUALIZATION_QUICKSTART.md](VISUALIZATION_QUICKSTART.md) and [web/README.md](web/README.md)**

---

## ⚙️ Configuration Guide

### **Crawler Settings**

| Setting | Default | Purpose |
|---------|---------|---------|
| `crawl_limit` | 100000 | Maximum pages to crawl (0 = unlimited) |
| `num_workers` | 80 | Concurrent crawler threads |
| `request_timeout` | 8 | Request timeout in seconds |
| `max_pages_per_domain` | 200 | Pages per domain (prevents bias) |
| `max_crawl_depth` | 3 | Maximum link-following depth |
| `min_delay` / `max_delay` | 1 / 2 | Delay between requests (respectful crawling) |
| `query_string_dedup` | true | Treat URLs with different params as duplicates |

### **Seed URLs**

The crawler starts from these high-quality sources (from `scripts/crawler.py`):

**Knowledge & Encyclopedia:**
- Wikipedia (60+ portals & categories)
- Britannica, Khan Academy, Coursera, edX

**Discussion & Community:**
- Reddit (20+ subreddits)
- Stack Overflow, Quora, Discourse

**News & Current Events:**
- BBC, CNN, Reuters, AP News, NPR, Al Jazeera, Guardian, Washington Post

**Gaming & Entertainment:**
- Polygon, IGN, GameSpot, Metacritic, IMDB, RottenTomatoes

**Technology & Development:**
- GitHub (trending), Dev.to, Medium, CSS-Tricks, Smashing Magazine, Hacker News

**Academic & Research:**
- arXiv, Google Scholar, PubMed, ScienceDirect, Nature, JSTOR

**And 50+ more sites** covering business, travel, sports, shopping, arts, and more.

---

## 🔧 Advanced Features

### **Proxy Support**

Aurora Search supports multiple proxy types for distributed crawling:

#### **Option 1: Cloudflare Workers** (Recommended)
```bash
python3 setup-proxies.py
# Choose option 1 for Cloudflare setup
```

#### **Option 2: OpenVPN**
```bash
# Download free VPN configs
python3 download-vpn-configs.py

# Launch VPN network
python3 vpn-manager.py

# Configure proxies
python3 setup-proxies.py
```

#### **Option 3: Manual SOCKS5**
Edit `config.txt`:
```ini
[Proxy]
use_proxy = true
proxy_list = socks5://127.0.0.1:1090|socks5://127.0.0.1:1091
rotate_proxy = true
```

### **Resume Crawling**

Aurora Search automatically:
1. **Saves crawl state** every 30 seconds
2. **Resumes from checkpoint** on restart
3. **Detects new seed URLs** and crawls them
4. **Tracks previously crawled URLs** to avoid duplicates

When you add new URLs to DEFAULT_STARTING_URLS in `scripts/crawler.py`, the next crawl automatically includes them.

### **Live Status Monitoring**

Access the status dashboard at `http://localhost:5000/status.html` to monitor:
- Crawler state (running/paused/complete)
- Documents indexed
- Terms indexed
- Queue size
- Last save time
- Crawled domains

---

## 📊 Search API

### **Query Endpoint**

```bash
GET /api/search?q=query&page=1&num=10
```

**Example:**
```bash
curl "http://localhost:5000/api/search?q=machine%20learning&page=1&num=10"
```

**Response:**
```json
{
  "results": [
    {
      "doc_id": 42,
      "url": "https://en.wikipedia.org/wiki/Machine_learning",
      "title": "Machine Learning - Wikipedia",
      "description": "Comprehensive guide to machine learning...",
      "score": 0.876,
      "pagerank": 0.045,
      "panda_score": 0.92,
      "penguin_score": 0.88
    }
  ],
  "total_results": 1523,
  "query_time_ms": 234
}
```

### **Status Endpoint**

```bash
GET /api/status
```

Returns current crawler status, indexed counts, and statistics.

---

## 🎨 Frontend

### **Home Page** (`index.html`)
- Clean Google-like search interface
- "I'm Feeling Lucky" button (random result)
- Dark modern theme

### **Results Page** (`search.html`)
- Paginated search results (10 per page)
- Result cards with title, description, URL
- Dynamic pagination controls
- Instant search experience

### **Status Dashboard** (`status.html`)
- Real-time crawler statistics
- Live indexing progress
- Domain activity feed
- Queue size monitoring

---

## 📈 How the Ranking Works (Example)

For the query **"machine learning"**:

1. **Find matching documents** via inverted index
   - Documents containing "machine" and "learning"

2. **Calculate Panda score** for each result
   - Wikipedia: 0.95 (authoritative, well-structured, comprehensive)
   - Random blog: 0.45 (thin content, poor structure)

3. **Calculate Penguin score**
   - Wikipedia: 0.99 (linked from high-authority sites)
   - Blog: 0.30 (few inbound links)

4. **Calculate PageRank**
   - Wikipedia: 0.08 (highly linked throughout web)
   - Blog: 0.001 (isolated page)

5. **Calculate relevance** to query
   - Both have "machine learning" in title: 0.9

6. **Combine all signals:**
   ```
   Wikipedia = (0.08 × 0.4) + (0.95 × 0.35) + (0.99 × 0.15) + (0.9 × 0.1)
             = 0.032 + 0.333 + 0.149 + 0.09 = 0.604
   
   Blog = (0.001 × 0.4) + (0.45 × 0.35) + (0.30 × 0.15) + (0.9 × 0.1)
        = 0.0004 + 0.158 + 0.045 + 0.09 = 0.293
   ```

**Result:** Wikipedia appears first (0.604 > 0.293)

---

## 🛡️ Ethics & Compliance

- ✅ **Respects robots.txt** and crawling rules
- ✅ **Rate limiting**: Delays between requests (1-2 seconds)
- ✅ **Circuit breaker**: Backs off from failing domains
- ✅ **User-agent**: Identifies crawler in HTTP headers
- ✅ **No API abuse**: Handles timeouts gracefully
- ✅ **Content respect**: Never modifies or redistributes content

---

## 🐛 Testing

Run the indexing pipeline test:

```bash
python3 test_indexing_pipeline.py
```

This validates:
- HTML parsing
- Text tokenization & stemming
- Content quality scoring
- Link analysis

---

## 📚 Additional Resources

- **[RANKING_ALGORITHMS.md](RANKING_ALGORITHMS.md)** - Detailed algorithm documentation
- **[PROXY_SETUP.md](PROXY_SETUP.md)** - Proxy configuration guide
- **[OPENVPN_SETUP.md](OPENVPN_SETUP.md)** - OpenVPN setup instructions
- **[cloudflare-worker.js](cloudflare-worker.js)** - Cloudflare Worker proxy code

---

## 🤝 Contributing

Contributions are welcome! Areas for improvement:
- Additional ranking signals (freshness boosting, social signals)
- Query parsing improvements (phrase search, boolean operators)
- Spell correction & suggestions
- Advanced filtering (date range, site-specific search)
- Distributed indexing for multiple servers

---

## 📄 License

This project is open-source under the **MIT License**.

---

## 👨‍💻 Author

**Sirco Aurora Bot** - A complete search engine implementation demonstrating crawling, indexing, and advanced ranking algorithms.

**Questions?** Check the documentation files or review the source code comments.

**Happy Searching! 🚀**
