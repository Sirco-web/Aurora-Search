"""
Demo crawler event generator for visualization testing.
Generates realistic crawl events to showcase the visualization.
"""

import json
import random
import threading
import time

# Sample domains from our crawler
DOMAINS = [
    "wikipedia.org",
    "reddit.com",
    "github.com",
    "stackoverflow.com",
    "medium.com",
    "dev.to",
    "news.ycombinator.com",
    "polygon.com",
    "ign.com",
    "bbc.com",
    "cnn.com",
    "arxiv.org",
    "tensorflow.org",
    "pytorch.org",
]

# Fun sample titles
SAMPLE_TITLES = {
    "Machine Learning": "A comprehensive guide to machine learning basics",
    "Python Tutorials": "Learn Python programming with practical examples",
    "Web Development": "Modern web development with React and Node.js",
    "Cloud Computing": "AWS, Azure, and GCP comparison guide",
    "Open Source": "Best open source projects on GitHub",
    "Data Science": "Data science techniques and tools",
    "Security": "Cybersecurity best practices",
    "DevOps": "CI/CD pipelines and deployment strategies",
}

class DemoCrawler:
    """Generates demo crawl events for visualization testing."""
    
    def __init__(self, broadcast_func):
        self.broadcast = broadcast_func
        self.running = False
        self.crawled_urls = set()
        self.pending_urls = set()
        self.failed_urls = set()
        
    def generate_url(self, domain=None, depth=0):
        """Generate a realistic URL."""
        if domain is None:
            domain = random.choice(DOMAINS)
        
        paths = [
            "articles",
            "posts",
            "questions",
            "news",
            "trending",
            "top",
            "best",
            "wiki",
            "learn",
            "docs",
        ]
        
        if depth == 0:
            return f"https://{domain}/"
        
        path = random.choice(paths)
        title = random.choice(list(SAMPLE_TITLES.keys())).lower().replace(" ", "-")
        return f"https://{domain}/{path}/{title}"
    
    def demo_crawl_session(self, num_pages=100):
        """Run a demo crawl session."""
        self.running = True
        self.crawled_urls.clear()
        self.pending_urls.clear()
        self.failed_urls.clear()
        
        # Start with seed URLs
        current_batch = [self.generate_url(d, 0) for d in DOMAINS[:5]]
        self.pending_urls.update(current_batch)
        
        # Broadcast initial queue
        self.broadcast({
            "type": "queue_update",
            "queue": list(current_batch)[:10]
        })
        
        depth = 0
        while self.running and len(self.crawled_urls) < num_pages:
            next_batch = []
            
            for url in list(self.pending_urls)[:10]:
                if not self.running:
                    break
                
                self.pending_urls.discard(url)
                
                # Simulate crawl delay
                time.sleep(random.uniform(0.1, 0.5))
                
                # 90% success rate
                if random.random() < 0.9:
                    title = random.choice(list(SAMPLE_TITLES.values()))
                    links_found = random.randint(5, 20)
                    
                    # Broadcast crawled event
                    self.broadcast({
                        "type": "crawled",
                        "url": url,
                        "depth": depth,
                        "title": title,
                        "links_found": links_found
                    })
                    
                    self.crawled_urls.add(url)
                    
                    # Generate new links
                    for _ in range(links_found):
                        new_url = self.generate_url(depth=depth + 1)
                        if new_url not in self.crawled_urls and new_url not in self.pending_urls:
                            self.pending_urls.add(new_url)
                            next_batch.append(new_url)
                            
                            # Broadcast found event
                            self.broadcast({
                                "type": "found",
                                "from_url": url,
                                "url": new_url,
                                "depth": depth + 1
                            })
                            
                            # Add slight delay between discoveries
                            time.sleep(0.05)
                else:
                    # Failed URL
                    self.broadcast({
                        "type": "failed",
                        "url": url,
                        "reason": random.choice(["timeout", "403 Forbidden", "404 Not Found", "Connection Error"])
                    })
                    self.failed_urls.add(url)
            
            # Update queue
            if self.pending_urls:
                self.broadcast({
                    "type": "queue_update",
                    "queue": list(self.pending_urls)[:20]
                })
            
            depth += 1
            if depth > 3:  # Limit depth
                break
            
            # Small delay between batches
            time.sleep(0.2)
        
        # Final status
        self.broadcast({
            "type": "status",
            "status": "complete",
            "message": f"Crawled {len(self.crawled_urls)} pages with {len(self.failed_urls)} failures"
        })
        
        self.running = False
    
    def stop(self):
        """Stop the demo crawl."""
        self.running = False

# Global demo crawler instance
demo_crawler = None


def init_demo_crawler(broadcast_func):
    """Initialize the demo crawler with a broadcast function."""
    global demo_crawler
    demo_crawler = DemoCrawler(broadcast_func)


def start_demo_crawl(num_pages=100):
    """Start a demo crawl session."""
    if demo_crawler:
        demo_crawler.demo_crawl_session(num_pages)


def stop_demo_crawl():
    """Stop the demo crawl."""
    if demo_crawler:
        demo_crawler.stop()


def run_demo_in_background(broadcast_func, num_pages=100):
    """Run demo crawl in background thread."""
    init_demo_crawler(broadcast_func)
    
    def run():
        start_demo_crawl(num_pages)
    
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
