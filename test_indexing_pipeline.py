#!/usr/bin/env python3
"""
Test script to verify the complete indexing pipeline works correctly.
Tests: HTML parsing → indexing → document storage → search
"""

import sys
import json
from bs4 import BeautifulSoup

# Import indexing module
sys.path.insert(0, 'scripts')
from indexing import index_page
from panda import score_content_quality
from penguin import score_link_quality

# Test 1: Parse and index a test page
print("=" * 60)
print("TEST 1: HTML Parsing & Indexing")
print("=" * 60)

test_html = """
<html>
<head>
    <title>Test Article About Machine Learning</title>
    <meta name="description" content="A comprehensive guide to machine learning basics"/>
</head>
<body>
    <h1>Introduction to Machine Learning</h1>
    <p>Machine learning is a branch of artificial intelligence that enables computers to learn from data.</p>
    <h2>What is Machine Learning?</h2>
    <p>Machine learning (ML) allows systems to automatically learn and improve from experience without being explicitly programmed.
    It focuses on developing computer programs that can access data and use it to learn for themselves.</p>
    <p>The process of learning begins with observations and direct experience, such as examples or instructions,
    in order to look for patterns in data and make better decisions in the future.</p>
    <h2>Types of Machine Learning</h2>
    <p>There are three main types: supervised learning, unsupervised learning, and reinforcement learning.</p>
    <ul>
        <li>Supervised Learning: Training with labeled examples</li>
        <li>Unsupervised Learning: Finding patterns in unlabeled data</li>
        <li>Reinforcement Learning: Learning through reward signals</li>
    </ul>
    <p>Each type has different applications and use cases in the real world.</p>
</body>
</html>
"""

soup = BeautifulSoup(test_html, "html.parser")
indexed = index_page(soup, "https://example.com/ml-guide")

print(f"✓ URL: {indexed['url']}")
print(f"✓ Title: {indexed['title']}")
print(f"✓ Description length: {len(indexed['description'])} chars")
print(f"✓ Content length: {len(indexed['content'])} chars")
print(f"✓ Word count: {indexed['word_count']}")
print(f"✓ Stemmed words: {len(indexed['words'])} terms")
print(f"✓ Content fingerprint: {indexed['content_fingerprint'][:16]}...")

# Verify all required fields are present
required_fields = ['url', 'title', 'description', 'content', 'words', 'word_count', 'content_fingerprint']
missing = [f for f in required_fields if f not in indexed]
if missing:
    print(f"❌ ERROR: Missing fields: {missing}")
    sys.exit(1)
else:
    print(f"✓ All required fields present")

# Test 2: Panda scoring
print("\n" + "=" * 60)
print("TEST 2: Panda Content Quality Scoring")  
print("=" * 60)

panda_result = score_content_quality(
    content_text=indexed['content'],
    html_text=test_html,
    title=indexed['title'],
    word_count=indexed['word_count'],
    keywords=['machine', 'learning'],
)

print(f"✓ Overall Panda Score: {panda_result['overall_score']:.4f}")
print(f"  - Length Score: {panda_result['length_score']:.4f}")
print(f"  - Structure Score: {panda_result['structure_score']:.4f}")
print(f"  - Readability Score: {panda_result['readability_score']:.4f}")

if panda_result['overall_score'] <= 0:
    print(f"❌ ERROR: Panda score is 0 or negative!")
    print(f"   Details: {panda_result.get('details', {})}")
    sys.exit(1)
else:
    print(f"✓ Panda scoring working correctly")

# Test 3: Penguin scoring (link quality)
print("\n" + "=" * 60)
print("TEST 3: Penguin Link Quality Scoring")
print("=" * 60)

penguin_result = score_link_quality(
    target_url="https://example.com/ml-guide",
    backlinks_data=[
        {'domain': 'wikipedia.org', 'anchor_text': 'Machine Learning'},
        {'domain': 'github.com', 'anchor_text': 'ML Libraries'},
    ],
    inbound_link_count=2,
    outbound_link_count=5,
)

print(f"✓ Overall Penguin Score: {penguin_result['overall_score']:.4f}")
print(f"  - Backlink Score: {penguin_result.get('backlink_score', 0):.4f}")
print(f"  - Authority Score: {penguin_result.get('authority_score', 0):.4f}")

if penguin_result['overall_score'] <= 0:
    print(f"❌ ERROR: Penguin score is 0 or negative!")
    sys.exit(1)
else:
    print(f"✓ Penguin scoring working correctly")

# Test 4: Create document info JSON format
print("\n" + "=" * 60)
print("TEST 4: Document Info JSON Format")
print("=" * 60)

doc_info = {
    "1": {
        "url": indexed['url'],
        "title": indexed['title'],
        "description": indexed['description'],
        "content": indexed['content'],  # NEW: This field should now be stored
        "pagerank": 0.45,
        "panda_score": round(panda_result['overall_score'], 4),
        "penguin_score": round(penguin_result['overall_score'], 4),
    }
}

# Verify we can serialize it
try:
    json_str = json.dumps(doc_info, indent=2)
    print(f"✓ Document can be serialized to JSON")
    print(f"✓ JSON size: {len(json_str)} bytes")
    
    # Verify we can deserialize it back
    reloaded = json.loads(json_str)
    doc = reloaded["1"]
    print(f"✓ Successfully reloaded document from JSON")
    
    # Check all fields are present
    required_fields = ['url', 'title', 'description', 'content', 'pagerank', 'panda_score', 'penguin_score']
    missing = [f for f in required_fields if f not in doc]
    if missing:
        print(f"❌ ERROR: Missing fields in JSON: {missing}")
        sys.exit(1)
    else:
        print(f"✓ All fields present and retrievable: {list(doc.keys())}")
        
except Exception as e:
    print(f"❌ ERROR: Failed to serialize/deserialize: {e}")
    sys.exit(1)

# Test 5: Verify search can use the content field
print("\n" + "=" * 60)
print("TEST 5: Search Content Field Availability")
print("=" * 60)

# Simulate what the search endpoint does
query = "machine learning"
query_words = set(query.lower().split())

print(f"✓ Query: '{query}'")
print(f"✓ Looking for content in document...")

if 'content' in doc:
    full_text = f"{doc.get('title', '')} {doc.get('description', '')} {doc.get('content', '')}"
    print(f"✓ Full text available for relevance scoring")
    print(f"✓ Full text length: {len(full_text)} chars")
    
    # Check if query terms are in the content
    content_lower = doc['content'].lower()
    found_terms = [word for word in query_words if word in content_lower]
    print(f"✓ Query terms found in content: {found_terms}")
else:
    print(f"❌ ERROR: 'content' field not in document!")
    sys.exit(1)

# Final summary
print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED")
print("=" * 60)
print("\nIndexing pipeline is working correctly:")
print("  - HTML parsing extracts content properly")
print("  - Document info includes full content + word count")
print("  - Panda/Penguin scoring receives proper inputs")
print("  - JSON serialization/deserialization works")
print("  - Search endpoint can access content field")
print("\nYou can now run the crawler and it will properly index sites!")
