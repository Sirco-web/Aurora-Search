"""
Unified Ranking Algorithm

Combines:
- PageRank (link popularity)
- Panda Score (content quality)
- Penguin Score (link quality/trust)

Final ranking formula inspired by modern search engines.
"""

import math


def normalize_score(score, min_val=0.0, max_val=1.0):
    """
    Normalize a score to 0.0-1.0 range.
    
    Args:
        score: Raw score value
        min_val: Expected minimum value in raw data
        max_val: Expected maximum value in raw data
        
    Returns:
        Normalized score 0.0-1.0
    """
    if max_val == min_val:
        return 0.5
    normalized = (score - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, normalized))


def calculate_combined_rank(
    pagerank_score,
    panda_score,
    penguin_score,
    weights=None,
    boost_freshness=False,
    query_relevance=1.0,
):
    """
    Calculate final ranking score combining all algorithms.
    
    Args:
        pagerank_score: PageRank (typically 0.0-1.0 but can exceed)
        panda_score: Panda content quality score (0.0-1.0)
        penguin_score: Penguin link quality score (0.0-1.0)
        weights: Dict with keys 'pagerank', 'panda', 'penguin'. Default is balanced.
        boost_freshness: If True, apply freshness multiplier (not implemented, reserved for future)
        query_relevance: TF-IDF or BM25 relevance score (0.0-1.0)
        
    Returns:
        Final ranking score (typically 0.0-1.0, but can exceed for very relevant pages)
    """
    
    if weights is None:
        weights = {
            'pagerank': 0.4,      # External reputation (40%)
            'panda': 0.35,        # Content quality (35%)
            'penguin': 0.15,      # Link trustworthiness (15%)
            'relevance': 0.1,     # Query relevance (10%)
        }
    
    # Normalize PageRank (it can have various ranges)
    # Most PageRank values cluster around 0-0.1 with occasional spikes
    normalized_pr = normalize_score(pagerank_score, min_val=0.0, max_val=0.1)
    
    # Ensure all scores are in 0.0-1.0 range
    panda_score = max(0.0, min(1.0, panda_score))
    penguin_score = max(0.0, min(1.0, penguin_score))
    query_relevance = max(0.0, min(1.0, query_relevance))
    
    # Combine scores
    combined_score = (
        normalized_pr * weights.get('pagerank', 0.4) +
        panda_score * weights.get('panda', 0.35) +
        penguin_score * weights.get('penguin', 0.15) +
        query_relevance * weights.get('relevance', 0.1)
    )
    
    return round(combined_score, 6)


def apply_quality_thresholds(rank_score, panda_score, penguin_score):
    """
    Apply hard thresholds for spam and low-quality content.
    
    Returns:
        Adjusted score (can set to 0 if content fails thresholds)
    """
    
    # Hard penalty for obvious spam/duplicates (Panda < 0.3)
    if panda_score < 0.3:
        return rank_score * 0.3
    
    # Suspicious link patterns (Penguin < 0.2)
    if penguin_score < 0.2:
        return rank_score * 0.5
    
    # Boost pages with very good quality (Panda > 0.8) and links (Penguin > 0.8)
    if panda_score > 0.8 and penguin_score > 0.8:
        return rank_score * 1.2
    
    return rank_score


def rank_results(
    documents,
    strategy='relevance_first',
):
    """
    Rank a list of result documents using all signals.
    
    Args:
        documents: List of result dicts with pagerank, panda_score, penguin_score, relevance
        strategy: 'balanced' (default), 'content_first', 'relevance_first', 'authority_first'
        
    Returns:
        List of documents sorted by final rank score, with 'rank_score' added
    """
    
    # Choose weights based on strategy
    if strategy == 'content_first':
        weights = {
            'pagerank': 0.15,
            'panda': 0.60,
            'penguin': 0.1,
            'relevance': 0.15,
        }
    elif strategy == 'relevance_first':
        weights = {
            'pagerank': 0.10,
            'panda': 0.25,      # INCREASED: Content quality very important
            'penguin': 0.10,
            'relevance': 0.55,  # Query match still highest
        }
    elif strategy == 'authority_first':
        weights = {
            'pagerank': 0.6,
            'panda': 0.15,
            'penguin': 0.15,
            'relevance': 0.1,
        }
    else:  # balanced (default)
        weights = {
            'pagerank': 0.25,
            'panda': 0.35,      # INCREASED: Content quality rewarded
            'penguin': 0.15,
            'relevance': 0.25,
        }
    
    # Calculate rank scores
    for doc in documents:
        pagerank = doc.get('pagerank', 0.0)
        panda = doc.get('panda_score', 0.5)  # Default to neutral if not available
        penguin = doc.get('penguin_score', 0.5)  # Default to neutral if not available
        relevance = doc.get('relevance_score', 0.0)  # Default to 0 if not specified (not relevant)
        
        rank = calculate_combined_rank(pagerank, panda, penguin, weights, query_relevance=relevance)
        
        # Apply quality thresholds
        rank = apply_quality_thresholds(rank, panda, penguin)
        
        doc['rank_score'] = round(rank, 6)
    
    # Sort by rank score descending
    return sorted(documents, key=lambda d: d.get('rank_score', 0.0), reverse=True)


def explain_ranking(document, weights=None):
    """
    Provide human-readable explanation of why a page ranked here.
    
    Args:
        document: Result document with all scores
        weights: Optional custom weights (default: balanced)
        
    Returns:
        String explanation
    """
    
    if weights is None:
        weights = {
            'pagerank': 0.4,
            'panda': 0.35,
            'penguin': 0.15,
            'relevance': 0.1,
        }
    
    pagerank = document.get('pagerank', 0.0)
    panda = document.get('panda_score', 0.5)
    penguin = document.get('penguin_score', 0.5)
    rank_score = document.get('rank_score', 0.0)
    
    explanation = f"""
Ranking Breakdown for: {document.get('title', 'Unknown')}
URL: {document.get('url', 'Unknown')}
Final Score: {rank_score:.4f}

Signal Breakdown:
  • PageRank (Link Popularity): {pagerank:.4f} x {weights['pagerank']:.1%} = {pagerank * weights['pagerank']:.4f}
  • Panda (Content Quality): {panda:.4f} x {weights['panda']:.1%} = {panda * weights['panda']:.4f}
  • Penguin (Link Trust): {penguin:.4f} x {weights['penguin']:.1%} = {penguin * weights['penguin']:.4f}
  • Relevance: {weights.get('relevance', 0.1):.1%}

Quality Assessment:
"""
    
    if panda > 0.8:
        explanation += "  ✓ High-quality original content\n"
    elif panda > 0.6:
        explanation += "  ✓ Good quality content\n"
    elif panda > 0.4:
        explanation += "  ⚠ Moderate quality content\n"
    else:
        explanation += "  ✗ Low quality or thin content\n"
    
    if penguin > 0.8:
        explanation += "  ✓ Trusted, natural link profile\n"
    elif penguin > 0.5:
        explanation += "  ✓ Good link quality\n"
    elif penguin > 0.3:
        explanation += "  ⚠ Some link quality concerns\n"
    else:
        explanation += "  ✗ Suspicious link patterns detected\n"
    
    if pagerank > 0.08:
        explanation += "  ✓ High link popularity\n"
    elif pagerank > 0.04:
        explanation += "  ✓ Good link popularity\n"
    else:
        explanation += "  • Average link popularity\n"
    
    return explanation.strip()
