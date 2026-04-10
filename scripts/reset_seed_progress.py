#!/usr/bin/env python3
"""
Reset seed URL crawl progress while preserving all indexed data.

This script:
✓ Removes seeds from visited_urls (allows re-crawling)
✓ Removes seeds from known_urls (queues them again)
✓ Clears the crawl queue (fresh start for seeds)
✓ Resets seed tracking counters
✓ KEEPS all indexed content (inverted_index.json, doc_info.json)
✓ KEEPS all rankings and page data
✓ KEEPS discovered URL history

Usage:
    python3 reset_seed_progress.py
"""
import json
import os
import sys
from urllib.parse import urlparse

# Import the crawler to get DEFAULT_STARTING_URLS
sys.path.insert(0, os.path.dirname(__file__))
from crawler import DEFAULT_STARTING_URLS


def normalize_url(url):
    """Quick URL normalization for comparison."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    normalized_path = parsed.path or "/"
    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path.rstrip("/")
    return f"{scheme}://{netloc}{normalized_path}"


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root_dir, "data")
    state_path = os.path.join(data_dir, "crawl_state.json")

    if not os.path.exists(state_path):
        print("❌ No crawl_state.json found. Nothing to reset.")
        return False

    # Load current state
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    print("🔄 Resetting seed URL progress...")
    print(f"📋 Seeds to reset: {len(DEFAULT_STARTING_URLS)}")

    # Normalize seed URLs for comparison
    seed_urls_normalized = set()
    for url in DEFAULT_STARTING_URLS:
        normalized = normalize_url(url)
        if normalized:
            seed_urls_normalized.add(normalized)

    print(f"✓ Normalized to {len(seed_urls_normalized)} unique seeds")

    # Load current data
    visited_urls = set(state.get("visited_urls", []))
    known_urls = set(state.get("known_urls", []))
    url_depth_map = dict(state.get("url_depth_map", {}))
    url_seed_map = dict(state.get("url_seed_map", {}))
    seed_urls_in_visited = visited_urls & seed_urls_normalized
    seed_urls_in_known = known_urls & seed_urls_normalized

    print(f"📊 Before reset:")
    print(f"   - Seed URLs in visited: {len(seed_urls_in_visited)}")
    print(f"   - Seed URLs in known: {len(seed_urls_in_known)}")

    # RESET STEP 1: Remove seed URLs from visited
    visited_urls -= seed_urls_normalized
    print(f"✓ Removed seeds from visited_urls")

    # RESET STEP 2: Remove seed URLs from known
    known_urls -= seed_urls_normalized
    print(f"✓ Removed seeds from known_urls")

    # RESET STEP 3: Clear the queue
    old_queue_len = len(state.get("queue", []))
    state["queue"] = []
    print(f"✓ Cleared queue (removed {old_queue_len} pending URLs)")

    # RESET STEP 4: Reset depth/seed maps for seeds
    seeds_removed_from_depth = sum(1 for url in url_depth_map.keys() if url in seed_urls_normalized)
    seeds_removed_from_seed_map = sum(1 for url in url_seed_map.keys() if url in seed_urls_normalized)
    
    url_depth_map = {url: depth for url, depth in url_depth_map.items() if url not in seed_urls_normalized}
    url_seed_map = {url: is_seed for url, is_seed in url_seed_map.items() if url not in seed_urls_normalized}
    print(f"✓ Cleared seed mappings ({seeds_removed_from_depth} from depth, {seeds_removed_from_seed_map} from seed_map)")

    # RESET STEP 5: Reset seed tracking counters
    state["seed_urls_crawled"] = 0
    print(f"✓ Reset seed_urls_crawled counter to 0")
    
    # RESET STEP 6: Clear PREVIOUS seed list so all current seeds are detected as NEW
    # This forces seeds to be re-detected and re-enqueued on next run
    state["seed_urls"] = []
    print(f"✓ Cleared previous seed_urls list (forces re-detection)")

    # KEEP: All index data, rankings, page info, discovered URLs
    print(f"\n✅ Preserving:")
    print(f"   - inverted_index.json ({len(state.get('doc_words', {}))} documents)")
    print(f"   - doc_info.json ({len(state.get('url_to_doc_id', {}))} pages indexed)")
    print(f"   - pagerank_graph ({len(state.get('pagerank_graph', {}))} links)")
    print(f"   - All discovered URLs and their history")

    # Save modified state
    state["visited_urls"] = sorted(visited_urls)
    state["known_urls"] = sorted(known_urls)
    state["url_depth_map"] = url_depth_map
    state["url_seed_map"] = url_seed_map

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print(f"\n✅ Progress reset successfully!")
    print(f"\n📝 Next steps:")
    print(f"   1. Run: sudo python3 app.py")
    print(f"   2. Select mode 2 (SERVE + CRAWLER)")
    print(f"   3. Seeds will be re-crawled and indexed")
    print(f"   4. All previously indexed content is preserved")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
