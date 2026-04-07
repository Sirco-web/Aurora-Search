# Aurora Search: Ranking Algorithms Implementation

This document explains the Panda and Penguin algorithms implemented in Aurora Search, how they work together, and how to use them.

## 📊 Overview

Aurora Search uses a unified ranking system that combines three major signals:

1. **PageRank** (40% weight) - Link popularity and authority
2. **Panda** (35% weight) - Content quality
3. **Penguin** (15% weight) - Link trustworthiness  
4. **Query Relevance** (10% weight) - How well content matches the query

```
Final Rank Score = (PageRank × 0.4) + (Panda × 0.35) + (Penguin × 0.15) + (Relevance × 0.1)
```

---

## 🐼 Panda Algorithm: Content Quality Scoring

### What Panda Does

Panda evaluates content quality across multiple dimensions. It ranks helpful, original, high-quality pages higher and pushes down low-quality, thin, or spammy content.

### Panda Scoring Factors

#### 1. **Content Length (25%)**
- **Thin Content Penalty**: Pages < 100 words get heavily penalized
- **Sweet Spot**: 1000-3000 words earns highest score
- **Diminishing Returns**: Content > 5000 words starts to lose value
- **Formula**: Logarithmic scale to prefer depth without penalizing conciseness

| Word Count | Score |
|-----------|-------|
| < 100 | 0.0-0.3 |
| 300 | ~0.3 |
| 1000 | ~0.6 |
| 2000 | ~0.85 |
| 5000+ | ~0.95 |

#### 2. **HTML Structure (15%)**
- Presence of proper heading hierarchy (H1, H2, H3)
- Paragraph elements for readability
- Lists for organized information
- Blockquotes for emphasis
- Well-structured pages score higher

#### 3. **Readability (15%)**
- Optimal sentence length (ideal: 15-20 words)
- Optimal word length (ideal: 4-6 characters)
- Pages with natural word/sentence ratios score better
- Readability is scored on 0.0-1.0 scale

#### 4. **Keyword Stuffing Detection (15%)**
- Detects unnatural keyword repetition
- Uses moving window analysis to find concentrated keyword usage
- If local keyword density >> global density = stuffing penalty
- Natural keyword integration = higher score

#### 5. **Originality/Duplicate Detection (25%)**
- SHA1 fingerprint comparison against known content
- Exact duplicates get 0.2 score (major penalty)
- Original content gets 1.0 score
- Prevents duplicate content farms from ranking

#### 6. **Content Freshness (5%)**
- Older content gets slight penalty
- 365+ days old = ~0.7 freshness score
- Incentivizes regular updates but doesn't dominate ranking

### Panda Implementation (`scripts/panda.py`)

```python
from scripts.panda import score_content_quality

score = score_content_quality(
    content_text="Your page text...",
    html_text="<html>...</html>",
    title="Page Title",
    word_count=1500,
    keywords=["keyword1", "keyword2"],
    duplicate_fingerprints={existing_fingerprints},
    content_fingerprint="abc123...",
    days_old=30
)

# Returns:
# {
#     "overall_score": 0.75,  # 0.0-1.0
#     "length_score": 0.85,
#     "structure_score": 0.70,
#     "readability_score": 0.80,
#     "keyword_score": 0.95,
#     "duplicate_score": 1.00,
#     "freshness_score": 0.98,
#     "details": {...}
# }
```

---

## 🐧 Penguin Algorithm: Link Quality & Trust Scoring

### What Penguin Does

Penguin evaluates link profiles to reward natural, trustworthy links and penalize spammy or artificial link-building patterns.

### Penguin Scoring Factors

#### 1. **Backlink Count (25%)**
- Uses logarithmic scale (1 link = 0.2, 10 links = 0.5, 100 links = 0.9)
- Count matters but not dominantly (many spam links = bad)
- Prevents quantity-over-quality schemes

#### 2. **Domain Authority (35%)**
- **High Authority Sources** (0.9 score):
  - Wikipedia, GitHub, StackOverflow
  - Major news sites (BBC, CNN, Reuters)
  - Academic institutions (.edu, .gov)
- **Medium Authority** (0.6-0.7):
  - .com sites with history
  - Medium blogs and publications
- **Low Authority** (0.2-0.4):
  - New domains, low-trust TLDs
  - Private domains

Authority is weighted by number of links from each domain.

#### 3. **Anchor Text Naturalness (20%)**
- Analyzes if anchor text looks natural or artificial
- **Bad anchors** (0.4 score): "click here", "link", "page"
- **Good anchors** (0.7-0.8): Descriptive phrases
- Detects keyword stuffing in anchors (e.g., "BEST CHEAP LAPTOP BUY NOW!!!")
- Excessive caps/punctuation = spam signal

#### 4. **Link Farm Detection (20%)**
- Detects patterns of artificial linking:
  - High concentration from few domains (>70% = suspicious)
  - Repeated anchor texts (>30% same = suspicious)
  - Many generic anchors from irrelevant sites
- Suspicious patterns reduce score by up to 50%

### Penguin Implementation (`scripts/penguin.py`)

```python
from scripts.penguin import score_link_quality

score = score_link_quality(
    target_url="https://example.com/page",
    backlinks_data=[
        {
            "domain": "wikipedia.org",
            "anchor_text": "informative article",
            "is_generic_anchor": False
        },
        {
            "domain": "github.com", 
            "anchor_text": "this project",
            "is_generic_anchor": False
        },
    ],
    inbound_link_count=42,
    outbound_link_count=15,
    known_domain_authorities={"wikipedia.org": 0.9, ...}
)

# Returns:
# {
#     "overall_score": 0.72,  # 0.0-1.0
#     "backlink_score": 0.65,
#     "authority_score": 0.85,  # Wikipedia + GitHub boost this
#     "anchor_text_score": 0.80,
#     "farm_penalty_score": 0.95,  # No suspicious patterns
#     "is_suspicious": False,
#     "details": {...}
# }
```

---

## ⚖️ Unified Ranking Algorithm (`scripts/ranking.py`)

### How Scores Combine

```python
from scripts.ranking import rank_results

# Pass search results with all scores
results = [
    {
        "url": "...",
        "title": "...",
        "pagerank": 0.08,
        "panda_score": 0.85,
        "penguin_score": 0.72,
        "relevance_score": 0.95
    },
    # ... more results
]

ranked = rank_results(results, strategy='balanced')
# Results now have 'rank_score' added and are sorted
```

### Quality Thresholds

Hard thresholds apply quality penalties:

- **Panda < 0.3** (likely spam/duplicates): Score × 0.3 reduction
- **Penguin < 0.2** (suspicious links): Score × 0.5 reduction
- **Panda > 0.8 AND Penguin > 0.8** (excellent): Score × 1.2 boost

### Ranking Strategies

Choose different ranking strategies based on your use case:

#### 1. **Balanced** (default)
```
weights = {
    'pagerank': 0.4,
    'panda': 0.35,
    'penguin': 0.15,
    'relevance': 0.1
}
```
Best for general-purpose web search.

#### 2. **Content First**
```
weights = {
    'pagerank': 0.2,
    'panda': 0.60,
    'penguin': 0.1,
    'relevance': 0.1
}
```
Best for finding high-quality articles (blog searches, news).

#### 3. **Relevance First**
```
weights = {
    'pagerank': 0.2,
    'panda': 0.2,
    'penguin': 0.1,
    'relevance': 0.5
}
```
Best for very specific queries where relevance dominates.

#### 4. **Authority First**
```
weights = {
    'pagerank': 0.6,
    'panda': 0.15,
    'penguin': 0.15,
    'relevance': 0.1
}
```
Best for finding authoritative sources (academic search).

---

## 🔍 Using the API

### Basic Search

```bash
curl "http://localhost:5000/search?q=machine+learning&num_results=10&page=1"
```

**Response includes**:
- `rank_score`: Final combined ranking score
- `pagerank`: Link popularity score
- `panda_score`: Content quality (0.0-1.0)
- `penguin_score`: Link trust (0.0-1.0)

### Get Ranking Info

```bash
curl "http://localhost:5000/ranking-info"
```

Returns detailed information about all algorithms and their weights.

### Explain Why A Page Ranked

```bash
curl "http://localhost:5000/explain?url=https://example.com/article"
```

**Response shows**:
- Detailed breakdown of each signal
- Why the page ranked where it did
- Strengths and concerns in the ranking

Example output:
```
Ranking Breakdown for: Understanding Neural Networks
URL: https://example.com/neural-networks

Final Score: 0.782500

Signal Breakdown:
  • PageRank (Link Popularity): 0.0850 x 40.0% = 0.0340
  • Panda (Content Quality): 0.8500 x 35.0% = 0.2975
  • Penguin (Link Trust): 0.7200 x 15.0% = 0.1080
  • Relevance: 10.0%

Quality Assessment:
  ✓ High-quality original content
  ✓ Trusted, natural link profile
  ✓ High link popularity
```

---

## 📊 Data Flow

1. **Crawler** → Fetches web pages
2. **Indexing** → Extracts text, metadata, fingerprints
3. **Panda Scoring** → Evaluates content quality
4. **Penguin Scoring** → Analyzes link profile
5. **PageRank Calculation** → Computes link graph authority
6. **Storage** → Saves scores in `data/doc_info.json`
7. **Search** → Combines all scores for ranking
8. **Results** → Sorted by unified rank score

---

## ⚙️ Configuration

### Adjusting Weights

Edit `scripts/ranking.py`:

```python
weights = {
    'pagerank': 0.4,   # Change these values
    'panda': 0.35,
    'penguin': 0.15,
    'relevance': 0.1
}
# Must sum to 1.0
```

### Tuning Panda Thresholds

In `scripts/panda.py`, adjust these parameters:

```python
length_score:
  - Thin content threshold: < 100 words
  - Optimal range: 1000-3000 words
  - Diminishing returns: > 5000 words

keyword_density:
  - Stuffing ratio threshold: 5.0x
  - Window size: 100 words

readability_score:
  - Ideal sentence: 15-20 words
  - Ideal word: 4-6 characters
```

### Tuning Penguin Thresholds

In `scripts/penguin.py`:

```python
domain_concentration:
  - Suspicious threshold: > 70% from few domains

anchor_repetition:
  - Suspicious threshold: > 30% same anchor

backlink_scoring:
  - Logarithmic scale base: log(count + 1) / 6.0
```

---

## 🧪 Testing Individual Algorithms

### Test Panda Scoring

```python
from scripts.panda import score_content_quality

# High-quality content
good_doc = score_content_quality(
    content_text="A comprehensive guide about...",  # 2000+ words
    html_text="<h1>Title</h1><p>...</p><h2>Section</h2>...",
    title="Comprehensive Guide to X",
    word_count=2500,
)
print(good_doc["overall_score"])  # Should be ~0.85+

# Low-quality content  
bad_doc = score_content_quality(
    content_text="Click here for more",
    html_text="",
    title="Title",
    word_count=15,
)
print(bad_doc["overall_score"])  # Should be ~0.1-0.3
```

### Test Penguin Scoring

```python
from scripts.penguin import score_link_quality

# Natural links from authoritative sites
good_links = score_link_quality(
    target_url="https://example.com/page",
    backlinks_data=[
        {"domain": "wikipedia.org", "anchor_text": "excellent resource"},
        {"domain": "github.com", "anchor_text": "original implementation"},
    ],
    inbound_link_count=50,
)
print(good_links["overall_score"])  # Should be ~0.75+

# Suspicious link farm pattern
bad_links = score_link_quality(
    target_url="https://example.com/page",
    backlinks_data=[
        {"domain": "spam1.xyz", "anchor_text": "CLICK HERE!!!"},
        {"domain": "spam2.xyz", "anchor_text": "CLICK HERE!!!"},
        {"domain": "spam3.xyz", "anchor_text": "CLICK HERE!!!"},
    ] * 10,  # 30 identical generic anchors
    inbound_link_count=100,
)
print(bad_links["overall_score"])  # Should be ~0.2-0.3
```

---

## 📈 Performance Metrics

The system is designed to:

- **Process thousands of pages** without memory bloat
- **Scale link analysis** using logarithmic scales
- **Detect duplicates efficiently** using content fingerprinting
- **Combine signals robustly** with quality thresholds
- **Support strategy switching** for different search contexts

---

## 🚀 Example: Full Ranking Flow

```python
# 1. User searches
query = "machine learning"

# 2. Find matching documents
matched_docs = [document_info[doc_id] for doc_id in matched_doc_ids]

# 3. Add relevance scores
for doc in matched_docs:
    # Calculate TF-IDF or BM25 relevance
    doc["relevance_score"] = calculate_relevance(query, doc)

# 4. Rank with unified algorithm
ranked_docs = rank_results(matched_docs, strategy='balanced')

# 5. Return top 10
for doc in ranked_docs[:10]:
    print(f"{doc['title']} ({doc['rank_score']:.4f})")
    # Output:
    # Understanding Neural Networks (0.8234)
    # Deep Learning Fundamentals (0.7821)
    # Machine Learning 101 (0.7456)
    # ...
```

---

## 🔗 Related Files

- `scripts/panda.py` - Content quality scoring
- `scripts/penguin.py` - Link quality analysis
- `scripts/ranking.py` - Unified ranking algorithm
- `scripts/pagerank.py` - PageRank computation
- `scripts/crawler.py` - Web crawler with scoring integration
- `scripts/indexing.py` - Page indexing

---

## References

This implementation is inspired by:

- **Google Panda** - Content quality algorithm (2011)
- **Google Penguin** - Link spam algorithm (2012)
- **PageRank** - Link popularity algorithm (Brin & Page, 1998)
- **Modern Search Ranking** - Combining multiple signals

The algorithms are adapted and simplified for a local search engine context while maintaining their core principles.
