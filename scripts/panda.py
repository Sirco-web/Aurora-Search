"""
Panda Algorithm: Content Quality Scoring

Evaluates pages based on:
- Content length and depth
- Keyword stuffing detection
- Content originality (via fingerprint comparison)
- Readability
- Trust signals (structure, headings, links)
"""

import re
import math
from collections import Counter


def calculate_keyword_density(text, keywords, window_size=100):
    """
    Calculate keyword density with moving window to detect stuffing.
    
    Args:
        text: Full text content
        keywords: List of keywords to check
        window_size: Words per window for local density check
        
    Returns:
        Tuple: (global_density, max_local_density, stuffing_score)
    """
    if not text or not keywords:
        return 0.0, 0.0, 0.0
    
    words = text.lower().split()
    if not words:
        return 0.0, 0.0, 0.0
    
    # Global keyword density
    keyword_set = set(kw.lower() for kw in keywords)
    keyword_count = sum(1 for word in words if word in keyword_set)
    global_density = keyword_count / len(words) if words else 0.0
    
    # Local density (sliding window)
    max_local_density = 0.0
    for i in range(0, len(words), window_size // 2):
        window = words[i:i + window_size]
        if window:
            local_count = sum(1 for word in window if word in keyword_set)
            local_density = local_count / len(window)
            max_local_density = max(max_local_density, local_density)
    
    # Stuffing detection: if local density >> global density, it's probable stuffing
    stuffing_ratio = max_local_density / (global_density + 0.001) if global_density > 0 else 0
    stuffing_score = min(1.0, stuffing_ratio / 5.0)  # Above 5x ratio = high stuffing
    
    return global_density, max_local_density, stuffing_score


def detect_content_structure(html_text):
    """
    Detect well-structured content (headings, paragraphs, lists).
    
    Returns quality indicators.
    """
    h1_count = len(re.findall(r'<h1[^>]*>', html_text, re.IGNORECASE))
    h2_count = len(re.findall(r'<h2[^>]*>', html_text, re.IGNORECASE))
    h3_count = len(re.findall(r'<h[3-6][^>]*>', html_text, re.IGNORECASE))
    p_count = len(re.findall(r'<p[^>]*>', html_text, re.IGNORECASE))
    list_count = len(re.findall(r'<[ul|ol][^>]*>', html_text, re.IGNORECASE))
    blockquote_count = len(re.findall(r'<blockquote[^>]*>', html_text, re.IGNORECASE))
    
    structure_score = (
        h1_count * 0.2 +
        h2_count * 0.15 +
        h3_count * 0.1 +
        min(p_count / 5, 1.0) * 0.25 +
        min(list_count / 3, 1.0) * 0.15 +
        min(blockquote_count / 2, 1.0) * 0.15
    )
    
    return min(structure_score, 1.0), {
        "h1": h1_count,
        "h2": h2_count,
        "h3": h3_count,
        "paragraphs": p_count,
        "lists": list_count,
        "blockquotes": blockquote_count,
    }


def calculate_readability_score(text):
    """
    Simple readability metric based on sentence/word length.
    
    Returns:
        score: 0.0 to 1.0 (higher = more readable)
    """
    if not text or len(text) < 50:
        return 0.0
    
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return 0.0
    
    words = text.split()
    avg_sentence_length = len(words) / len(sentences) if sentences else 0
    avg_word_length = sum(len(w) for w in words) / len(words) if words else 0
    
    # Ideal: 15-20 words per sentence, 4-6 chars per word
    sentence_readability = 1.0 - abs(avg_sentence_length - 17.5) / 30.0
    word_readability = 1.0 - abs(avg_word_length - 5.0) / 10.0
    
    readability = (sentence_readability * 0.6 + word_readability * 0.4)
    return max(0.0, min(1.0, readability))


def calculate_content_freshness_penalty(days_old):
    """
    Older content gets a slight penalty.
    
    Args:
        days_old: Number of days since last update
        
    Returns:
        Freshness score (0.7 to 1.0)
    """
    if days_old is None or days_old < 0:
        return 1.0
    
    # After 365 days, penalty reaches ~0.7
    penalty = 1.0 - (min(days_old, 365) / 365.0) * 0.3
    return max(0.7, penalty)


def score_content_quality(
    content_text,
    html_text,
    title,
    word_count=None,
    keywords=None,
    duplicate_fingerprints=None,
    content_fingerprint=None,
    days_old=None,
):
    """
    Calculate content quality score (Panda-like).
    
    Args:
        content_text: Extracted plain text of page
        html_text: Original HTML
        title: Page title
        word_count: Number of words (optional)
        keywords: Query keywords (optional, for keyword stuffing)
        duplicate_fingerprints: Set of fingerprints of known content (for duplicate detection)
        content_fingerprint: SHA1 fingerprint of this content
        days_old: Age of content in days (optional)
        
    Returns:
        Dict with:
        - overall_score (0.0 to 1.0)
        - length_score
        - structure_score
        - readability_score
        - keyword_score
        - duplicate_score
        - freshness_score
        - details dict
    """
    
    if not content_text:
        return {
            "overall_score": 0.0,
            "length_score": 0.0,
            "structure_score": 0.0,
            "readability_score": 0.0,
            "keyword_score": 1.0,
            "duplicate_score": 1.0,
            "freshness_score": 1.0,
            "details": {"issue": "No content"},
        }
    
    # 1. LENGTH SCORING
    if not word_count:
        word_count = len(content_text.split())
    
    # OPTIMIZED: More generous with thin content, better rewards for substantial content
    # Thin penalty: < 150 words = very low
    # Good: 300-500 words = 0.6
    # Excellent: 1000-2000 words = 0.85
    # Outstanding: 3000+ words = 0.95+
    if word_count < 100:
        length_score = max(0.0, word_count / 150.0) * 0.2
    elif word_count < 300:
        length_score = 0.2 + (word_count - 100) / 200.0 * 0.35
    elif word_count < 800:
        length_score = 0.55 + (word_count - 300) / 500.0 * 0.25
    elif word_count < 2000:
        length_score = 0.80 + (word_count - 800) / 1200.0 * 0.15
    else:
        # After 2000 words, still reward (minimal diminishing return)
        excess = min(word_count - 2000, 3000)
        length_score = 0.95 + (excess / 3000.0) * 0.05
    
    length_score = min(1.0, max(0.0, length_score))
    
    # 2. STRUCTURE SCORING
    structure_score, structure_details = detect_content_structure(html_text or "")
    
    # 3. READABILITY SCORING
    readability_score = calculate_readability_score(content_text)
    
    # 4. KEYWORD STUFFING SCORING
    if keywords:
        global_density, max_local_density, stuffing_penalty = calculate_keyword_density(
            content_text, keywords
        )
        keyword_score = 1.0 - stuffing_penalty
    else:
        keyword_score = 1.0
    
    # 5. DUPLICATE DETECTION
    duplicate_score = 1.0
    if content_fingerprint and duplicate_fingerprints:
        if content_fingerprint in duplicate_fingerprints:
            duplicate_score = 0.2  # Duplicate content = major penalty
        else:
            duplicate_score = 1.0
    
    # 6. FRESHNESS PENALTY
    freshness_score = calculate_content_freshness_penalty(days_old)
    
    # COMBINED SCORE
    # OPTIMIZED: Panda heavily rewards substantial, well-structured content
    overall_score = (
        length_score * 0.30 +           # Content length (MORE IMPORTANT - reward depth)
        structure_score * 0.20 +        # Good HTML structure (IMPROVED)
        readability_score * 0.15 +      # Readability
        keyword_score * 0.15 +          # No keyword stuffing
        duplicate_score * 0.15 +        # Originality
        freshness_score * 0.05          # Recency
    )
    
    return {
        "overall_score": round(overall_score, 4),
        "length_score": round(length_score, 4),
        "structure_score": round(structure_score, 4),
        "readability_score": round(readability_score, 4),
        "keyword_score": round(keyword_score, 4),
        "duplicate_score": round(duplicate_score, 4),
        "freshness_score": round(freshness_score, 4),
        "details": {
            "word_count": word_count,
            "structure": structure_details,
            "has_title": bool(title),
            "title_length": len(title) if title else 0,
        },
    }


def batch_score_content(documents, duplicate_fingerprints=None):
    """
    Score multiple documents efficiently.
    
    Args:
        documents: List of dicts with content_text, title, html_text keys
        duplicate_fingerprints: Optional set of known fingerprints
        
    Returns:
        List of docs with added 'panda_score' key
    """
    scored_docs = []
    
    for doc in documents:
        score = score_content_quality(
            content_text=doc.get("content_text", ""),
            html_text=doc.get("html_text", ""),
            title=doc.get("title", ""),
            word_count=doc.get("word_count"),
            keywords=doc.get("keywords"),
            duplicate_fingerprints=duplicate_fingerprints,
            content_fingerprint=doc.get("content_fingerprint"),
            days_old=doc.get("days_old"),
        )
        doc["panda_score"] = score["overall_score"]
        doc["panda_details"] = score
        scored_docs.append(doc)
    
    return scored_docs
