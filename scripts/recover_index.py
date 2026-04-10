#!/usr/bin/env python3
"""
Recover index from corrupted state file.
Reads snapshot files and creates a clean state with seeds ready to re-crawl.
"""
import json
import os
import sys
from pathlib import Path

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root_dir, "data")
    state_path = os.path.join(data_dir, "crawl_state.json")
    idx_path = os.path.join(data_dir, "inverted_index.json")
    doc_path = os.path.join(data_dir, "doc_info.json")
    snapshots_dir = os.path.join(data_dir, "snapshots")

    print("🔧 Recovering index from corrupted state...")
    
    # Check if index snapshot exists
    latest_snapshot = None
    if os.path.exists(snapshots_dir):
        snapshots = sorted(Path(snapshots_dir).glob("*.json"))
        if snapshots:
            latest_snapshot = snapshots[-1]
            print(f"✓ Found latest snapshot: {latest_snapshot.name}")
    
    # Try to load index data
    index_data = {}
    doc_info = {}
    
    if latest_snapshot:
        try:
            with open(latest_snapshot, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
                index_data = snapshot.get("index", {})
                doc_info = snapshot.get("webpage_info", {})
                print(f"✓ Loaded {len(doc_info)} documents from snapshot")
        except Exception as e:
            print(f"⚠ Could not read snapshot: {e}")
    
    # If no snapshot, try reading current index files
    if not index_data and os.path.exists(idx_path):
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
                print(f"✓ Loaded index with {len(index_data)} terms")
        except Exception as e:
            print(f"⚠ Index file corrupted: {e}")
    
    if not doc_info and os.path.exists(doc_path):
        try:
            with open(doc_path, "r", encoding="utf-8") as f:
                doc_info = json.load(f)
                print(f"✓ Loaded {len(doc_info)} documents from doc_info.json")
        except Exception as e:
            print(f"⚠ Doc info corrupted: {e}")
    
    # Back up corrupted state
    if os.path.exists(state_path):
        backup_path = state_path + ".corrupted"
        try:
            os.rename(state_path, backup_path)
            print(f"✓ Backed up corrupted state to {os.path.basename(backup_path)}")
        except Exception as e:
            print(f"⚠ Could not backup: {e}")
    
    # Create minimal clean state that resets seeds
    clean_state = {
        "queue": [],
        "visited_urls": [],
        "known_urls": list(doc_info.keys()) if doc_info else [],
        "pagerank_graph": {},
        "domain_sitemap_discovered": [],
        "processed_sitemaps": [],
        "bad_sitemaps": [],
        "doc_words": {},
        "content_fingerprints": {},
        "url_to_doc_id": {
            url: int(doc_id) 
            for url, doc_id in doc_info.items() 
            if isinstance(doc_id, (int, float))
        } if doc_info else {},
        "doc_id_counter": len(doc_info) if doc_info else 0,
        "crawl_count": len(doc_info) if doc_info else 0,
        "last_saved_count": len(doc_info) if doc_info else 0,
        "last_saved_at": None,
        "seed_urls": [],  # EMPTY - forces all seeds to be detected as NEW
        "url_depth_map": {},
        "url_seed_map": {},
        "seed_urls_crawled": 0,
    }
    
    # Write clean state
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(clean_state, f, indent=2)
    
    print(f"\n✅ Recovery complete!")
    print(f"   - Recovered {len(doc_info)} documents")
    print(f"   - Cleared seed list (all 420+ will be re-detected as NEW)")
    print(f"   - Created fresh crawl_state.json")
    print(f"\n📝 Next: Run: sudo python3 app.py")
    print(f"   Select mode 2 (SERVE + CRAWLER)")
    print(f"   Seeds will crawl with HIGH PRIORITY")
    

if __name__ == "__main__":
    main()
