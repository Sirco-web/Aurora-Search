"""
Penguin Algorithm: Link Quality Scoring

Evaluates pages based on:
- Backlink count and quality
- Anchor text naturalness
- Link source domain authority
- Link relevance to content
- Prevents link spam (link farms, artificial links)
"""

import re
from urllib.parse import urlparse
import math


def calculate_domain_authority(domain, known_authorities=None):
    """
    Estimate domain authority (0.0 to 1.0).
    
    In a real system, this would be from a database.
    For now, we'll use heuristics and top-level domain quality.
    
    Args:
        domain: Domain name (e.g., "wikipedia.org")
        known_authorities: Optional dict of domain -> authority_score
        
    Returns:
        Estimated authority score (0.0 to 1.0)
    """
    if not domain:
        return 0.2
    
    domain = domain.lower()
    
    # Check known authority database
    if known_authorities and domain in known_authorities:
        return min(1.0, max(0.0, known_authorities[domain]))
    
    # High-authority sites - EXPANDED for better coverage
    high_authority = {
        'wikipedia.org', 'github.com', 'stackoverflow.com', 'reddit.com',
        'medium.com', 'dev.to', 'bbc.com', 'cnn.com', 'nytimes.com',
        'guardian.com', 'reuters.com', 'apnews.com', 'aljazeera.com',
        'npr.org', 'themaven.net', 'blogspot.com', 'substack.com',
        'npmjs.com', 'pypi.org', 'docker.com', 'aws.amazon.com',
        'google.com', 'microsoft.com', 'apple.com', 'mozilla.org',
        'linkedin.com', 'youtube.com', 'twitter.com', 'facebook.com',
        'britannica.com', 'coursera.org', 'udemy.com', 'edx.org',
        'allrecipes.com', 'foodnetwork.com', 'bonappetitmag.com',
        'quora.com', 'discourse.com', 'hashnode.com', 'dev.community',
    }
    
    # Remove www if present
    domain_check = domain.replace('www.', '')
    
    if domain_check in high_authority:
        return 0.9
    
    # Check TLD
    if domain_check.endswith('.edu'):
        return 0.85
    elif domain_check.endswith('.gov'):
        return 0.85
    elif domain_check.endswith('.org'):
        return 0.7
    elif domain_check.endswith('.com'):
        return 0.6
    else:
        return 0.4


def analyze_anchor_text(anchor_text, target_content_keywords=None):
    """
    Analyze anchor text for naturalness and keyword stuffing.
    
    Returns:
        Dict with:
        - text_length
        - is_generic (e.g., "click here", "link")
        - has_keyword_stuffing
        - naturalness_score (0.0 to 1.0)
    """
    if not anchor_text:
        return {
            "text_length": 0,
            "is_generic": True,
            "has_keyword_stuffing": False,
            "naturalness_score": 0.3,
        }
    
    anchor_clean = anchor_text.strip().lower()
    text_length = len(anchor_clean.split())
    
    # Generic anchors (bad for SEO)
    generic_phrases = {
        'click here', 'link', 'here', 'more', 'read more',
        'more info', 'continue', 'go', 'visit', 'page',
        'site', 'click', 'a', 'the', 'and',
    }
    is_generic = anchor_clean in generic_phrases
    
    # Keyword stuffing in anchors (BAD - Penguin penalizes this)
    # Excessive punctuation or too many repeated keywords
    has_excessive_caps = len([c for c in anchor_text if c.isupper()]) > text_length * 0.5
    has_excessive_punctuation = anchor_text.count('!') + anchor_text.count('*') > 2
    has_keyword_stuffing = has_excessive_caps or has_excessive_punctuation
    
    # Score naturalness
    if is_generic:
        naturalness_score = 0.4
    elif has_keyword_stuffing:
        naturalness_score = 0.2
    elif text_length > 10:
        naturalness_score = 0.8  # Natural, long anchors
    elif text_length > 3:
        naturalness_score = 0.7  # Good anchor length
    else:
        naturalness_score = 0.6
    
    return {
        "text_length": text_length,
        "is_generic": is_generic,
        "has_keyword_stuffing": has_keyword_stuffing,
        "naturalness_score": round(naturalness_score, 3),
    }


def detect_link_farm_pattern(backlinks_data):
    """
    Detect suspicious link patterns (link farms, private blog networks).
    
    Heuristics:
    - Many links from same domain
    - Similar anchor text patterns
    - Linking to many irrelevant sites
    
    Args:
        backlinks_data: List of dicts with domain, anchor_text
        
    Returns:
        Tuple: (is_suspicious, farm_score, details)
    """
    if not backlinks_data or len(backlinks_data) < 3:
        return False, 0.0, {}
    
    # Count domains
    domain_counts = {}
    anchor_counts = {}
    
    for link in backlinks_data:
        domain = link.get('domain', 'unknown')
        anchor = link.get('anchor_text', '').lower().strip()
        
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if anchor:
            anchor_counts[anchor] = anchor_counts.get(anchor, 0) + 1
    
    farm_score = 0.0
    details = {}
    
    # Check for concentration in few domains (sign of artificial linking)
    total_links = len(backlinks_data)
    unique_domains = len(domain_counts)
    concentration = 1.0 - (unique_domains / total_links) if total_links > 0 else 0.0
    
    details['domain_concentration'] = round(concentration, 3)
    details['total_links'] = total_links
    details['unique_domains'] = unique_domains
    
    if concentration > 0.7:  # >70% from few domains
        farm_score += 0.4
        details['high_domain_concentration'] = True
    
    # Check for repeated anchor texts (sign of script-generated links)
    anchor_repetition = max(anchor_counts.values()) / total_links if anchor_counts else 0
    details['anchor_repetition'] = round(anchor_repetition, 3)
    
    if anchor_repetition > 0.3:  # >30% same anchor text
        farm_score += 0.4
        details['high_anchor_repetition'] = True
    
    # Many links but generic anchors
    generic_count = sum(1 for link in backlinks_data if link.get('is_generic_anchor'))
    generic_ratio = generic_count / total_links if total_links > 0 else 0
    
    if generic_ratio > 0.5 and total_links > 10:
        farm_score += 0.2
        details['many_generic_anchors'] = True
    
    is_suspicious = farm_score > 0.5
    
    return is_suspicious, min(1.0, farm_score), details


def score_link_quality(
    target_url,
    backlinks_data=None,
    inbound_link_count=0,
    outbound_link_count=0,
    known_domain_authorities=None,
):
    """
    Calculate link quality score (Penguin-like).
    
    Args:
        target_url: Target page URL
        backlinks_data: List of dicts with domain, anchor_text (and optionally is_generic_anchor)
        inbound_link_count: Total count of backlinks
        outbound_link_count: Number of outgoing links (for reciprocal check)
        known_domain_authorities: Dict of domain -> authority_score
        
    Returns:
        Dict with:
        - overall_score (0.0 to 1.0)
        - backlink_score
        - authority_score
        - anchor_text_score
        - farm_penalty_score
        - details dict
    """
    
    # 1. BACKLINK COUNT SCORING
    # Logarithmic scale: 1 link = 0.2, 10 links = 0.5, 100 links = 0.9
    if inbound_link_count == 0:
        backlink_score = 0.0
    else:
        backlink_score = min(1.0, 0.1 + math.log(inbound_link_count + 1) / 6.0)
    
    # 2. SOURCE AUTHORITY SCORING
    authority_scores = []
    authority_details = {}
    
    if backlinks_data:
        for link in backlinks_data:
            domain = link.get('domain', 'unknown')
            authority = calculate_domain_authority(domain, known_domain_authorities)
            authority_scores.append(authority)
            
            if domain not in authority_details:
                authority_details[domain] = authority
    
    if authority_scores:
        # Average authority, weighted by domain count
        domain_weights = {}
        if backlinks_data:
            for link in backlinks_data:
                domain = link.get('domain', 'unknown')
                domain_weights[domain] = domain_weights.get(domain, 0) + 1
        
        weighted_authority = sum(
            authority_scores[i] * domain_weights.get(backlinks_data[i].get('domain'), 1)
            for i in range(len(authority_scores))
        ) / len(backlinks_data)
        authority_score = weighted_authority
    else:
        authority_score = 0.0
    
    # 3. ANCHOR TEXT SCORING
    anchor_scores = []
    
    if backlinks_data:
        for link in backlinks_data:
            anchor_analysis = analyze_anchor_text(
                link.get('anchor_text', ''),
                link.get('target_keywords')
            )
            anchor_scores.append(anchor_analysis['naturalness_score'])
    
    if anchor_scores:
        anchor_text_score = sum(anchor_scores) / len(anchor_scores)
    else:
        anchor_text_score = 0.5  # Neutral if no data
    
    # 4. LINK FARM DETECTION (Penguin's main target)
    is_suspicious, farm_penalty, farm_details = detect_link_farm_pattern(backlinks_data or [])
    
    # Strong penalty for suspicious patterns
    farm_penalty_score = 1.0 - farm_penalty if not is_suspicious else 0.5 - farm_penalty
    farm_penalty_score = max(0.0, farm_penalty_score)
    
    # COMBINED SCORE
    # Weights reflect Penguin's focus on link quality over quantity
    overall_score = (
        backlink_score * 0.25 +          # Link count (but not dominant)
        authority_score * 0.35 +         # Who's linking (very important)
        anchor_text_score * 0.20 +       # How they're linking (important)
        farm_penalty_score * 0.20        # Avoid spam patterns (critical)
    )
    
    return {
        "overall_score": round(overall_score, 4),
        "backlink_score": round(backlink_score, 4),
        "authority_score": round(authority_score, 4),
        "anchor_text_score": round(anchor_text_score, 4),
        "farm_penalty_score": round(farm_penalty_score, 4),
        "is_suspicious": is_suspicious,
        "details": {
            "inbound_links": inbound_link_count,
            "outbound_links": outbound_link_count,
            "unique_domains": len(set(link.get('domain') for link in (backlinks_data or []))) if backlinks_data else 0,
            "authority_details": authority_details,
            "farm_details": farm_details,
        },
    }


def batch_score_links(documents, graph=None):
    """
    Score links for multiple documents.
    
    Args:
        documents: List of dicts with URL
        graph: Dict of url -> list of outgoing urls (for link counting)
        
    Returns:
        List of docs with added 'penguin_score' key
    """
    scored_docs = []
    
    # Build reverse graph (inbound links)
    inbound_graph = {}
    if graph:
        for source_url, targets in graph.items():
            for target_url in targets:
                if target_url not in inbound_graph:
                    inbound_graph[target_url] = []
                inbound_graph[target_url].append(source_url)
    
    for doc in documents:
        url = doc.get("url", "")
        
        # Get backlinks
        backlinks = inbound_graph.get(url, [])
        backlinks_data = [
            {
                'domain': urlparse(link).netloc or 'unknown',
                'anchor_text': f"link from {urlparse(link).netloc}",
                'is_generic_anchor': True,  # Without crawling source, assume generic
            }
            for link in backlinks
        ]
        
        # Get outgoing links
        outbound_links = graph.get(url, []) if graph else []
        
        score = score_link_quality(
            target_url=url,
            backlinks_data=backlinks_data,
            inbound_link_count=len(backlinks),
            outbound_link_count=len(outbound_links),
        )
        
        doc["penguin_score"] = score["overall_score"]
        doc["penguin_details"] = score
        scored_docs.append(doc)
    
    return scored_docs
