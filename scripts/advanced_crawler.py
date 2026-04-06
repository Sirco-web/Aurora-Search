from bs4 import BeautifulSoup
import requests
import time
import random
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
import threading
from urllib.parse import urlparse
import csv
from advanced_indexing import advanced_index_page
import gzip
import json
import sys
import os
import configparser

# Import pagerank computation
from pagerank import compute_pagerank

# Load config from parent directory
def load_config():
    """Load configuration from config.txt"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.txt')
    if os.path.exists(config_path):
        config.read(config_path)
    return config

CONFIG = load_config()

# Load proxies from config
def load_proxies():
    """Load proxy list from config"""
    use_proxy = CONFIG.getboolean('Proxy', 'use_proxy', fallback=False)
    if not use_proxy:
        return []
    
    proxy_list = CONFIG.get('Proxy', 'proxy_list', fallback='')
    if not proxy_list:
        return []
    
    proxies = [p.strip() for p in proxy_list.split('|') if p.strip()]
    if proxies:
        print(f"✅ Loaded {len(proxies)} proxies from config")
        for i, p in enumerate(proxies, 1):
            # Hide auth info for security
            if '@' in p:
                p = p.split('@')[1]
            print(f"   {i}. {p}")
    return proxies

PROXIES = load_proxies()
proxy_index = 0

def get_next_proxy():
    """Get next proxy from rotation list"""
    global proxy_index
    if not PROXIES:
        return None
    
    proxy_url = PROXIES[proxy_index % len(PROXIES)]
    proxy_index += 1
    return {'http': proxy_url, 'https': proxy_url}

# Function to check robots.txt for permission to crawl
# If we don't do this, we could get blocked/banned
# since we don't have permission to crawl.
def can_crawl(url):
    parsed_url = urlparse(url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
    print(f"Checking robots.txt for: {robots_url}")
    min_delay = CONFIG.getfloat('Crawler', 'min_delay', fallback=2)
    max_delay = CONFIG.getfloat('Crawler', 'max_delay', fallback=5)
    timeout = CONFIG.getint('Crawler', 'request_timeout', fallback=10)
    time.sleep(random.uniform(min_delay, max_delay))
    try:
        proxies = get_next_proxy()
        response = requests.get(robots_url, timeout=timeout, proxies=proxies)
        response.raise_for_status()
        disallowed_paths = []
        for line in response.text.splitlines():
            if line.startswith("Disallow"):
                parts = line.split()
                if len(parts) > 1:
                    disallowed_paths.append(parts[1])
        for path in disallowed_paths:
            if urlparse(url).path.startswith(path):
                print(f"Disallowed by robots.txt: {url}")
                return False
        return True
    except requests.RequestException:
        print(f"Failed to access robots.txt: {robots_url}")
        return False  # If we can't access robots.txt, assume we can't crawl (we're being nice here)

# Function to fetch and parse URL
def crawl(args):
    queue = args['queue']
    visited_urls = args['visited_urls']
    crawl_count = args['crawl_count']
    CRAWL_LIMIT = args['CRAWL_LIMIT']
    lock = args['lock']
    index = args['index']
    webpage_info = args['webpage_info']
    webpage_id_counter = args['webpage_id_counter']
    pagerank_graph = args['pagerank_graph']
    stop_crawl = args['stop_crawl']
    min_delay = args.get('min_delay', 2)
    max_delay = args.get('max_delay', 5)
    request_timeout = args.get('request_timeout', 10)

    while not stop_crawl.is_set():
        try:
            current_url = queue.get(timeout=5)
            print("Time to crawl: " + current_url)
        except Exception:
            break  # Exit if no more URLs are available to crawl

        with lock:
            if crawl_count[0] >= CRAWL_LIMIT:
                queue.queue.clear()  # Clear remaining URLs to stop processing
                print("Crawl limit reached. Exiting...")
                stop_crawl.set()
                break
            if current_url in visited_urls:
                queue.task_done()
                continue
            visited_urls.add(current_url)

        """ Checks for noindex directive in the page
            Comment this out if you don't care about noindex 
            WARNING: websites could block/ban you if you don't have permission
        """
        # if not can_crawl(current_url):
        #     queue.task_done()
        #     continue

        time.sleep(random.uniform(min_delay, max_delay))
        try:
            # Get proxy for this request (rotates through available proxies)
            proxies = get_next_proxy()
            
            # Log proxy usage
            if proxies:
                proxy_host = proxies.get('https', '').split('/')[-1].split('@')[-1] if proxies.get('https') else 'direct'
                print(f"   🔗 Via: {proxy_host}")
            
            # Fetch with proxy if configured
            response = requests.get(current_url, timeout=request_timeout, proxies=proxies)
            response.raise_for_status()  # Check for request errors
            content = response.content

            """ Checks for noindex directive in the page
            Comment this out if you don't care about noindex 
            WARNING: websites could block/ban you if you don't have permission
            """
            # if 'noindex' in content.decode('utf-8').lower():
            #     print(f"Noindex found, skipping: {current_url}")
            #     queue.task_done()
            #     continue
            

            # Parse the fetched content to find new URLs
            webpage = BeautifulSoup(content, "html.parser")

            # Index the webpage
            indexed_page = advanced_index_page(webpage, current_url)
            with lock:
                for word in indexed_page["words"]:
                    if word not in index:
                        index[word] = set()
                    index[word].add(webpage_id_counter[0])
                webpage_info[webpage_id_counter[0]] = indexed_page
                webpage_id_counter[0] += 1

            hyperlinks = webpage.select("a[href]")
            new_urls, hyperlink_connections = parse_links(hyperlinks, current_url)
            
            # Track hyperlinks for pagerank
            pagerank_graph[current_url] = hyperlink_connections

            with lock:
                for new_url in new_urls:
                    if new_url not in visited_urls:
                        queue.put(new_url)
                crawl_count[0] += 1

        except requests.RequestException as e:
            print(f"Failed to fetch {current_url}: {e}")
        finally:
            queue.task_done()

# Function to parse links from HTML content
def parse_links(hyperlinks, current_url):
    urls = []
    hyperlink_connections = set()
    for hyperlink in hyperlinks:
        url = hyperlink["href"]

        # Format the URL into a proper URL
        if url.startswith("#"):
            continue  # Skip same-page anchors
        if url.startswith("//"):
            url = "https:" + url  # Add scheme to protocol-relative URLs
        elif url.startswith("/"):
            # Construct full URL for relative links
            base_url = "{0.scheme}://{0.netloc}".format(requests.utils.urlparse(current_url))
            url = base_url + url
        elif not url.startswith("http"):
            continue  # Skip non-HTTP links
        url = url.split("#")[0]  # Remove anchor
        urls.append(url)
        hyperlink_connections.add(url)
    return urls, hyperlink_connections

# Main crawling function
def sloth_bot():
    # Get crawler name and limits from config
    crawler_name = CONFIG.get('Crawler', 'crawler_name', fallback='SlothBot')
    crawl_limit = CONFIG.getint('Crawler', 'crawl_limit', fallback=50)
    num_workers = CONFIG.getint('Crawler', 'num_workers', fallback=20)
    min_delay = CONFIG.getfloat('Crawler', 'min_delay', fallback=2)
    max_delay = CONFIG.getfloat('Crawler', 'max_delay', fallback=5)
    
    print(f"\n🤖 {crawler_name} - Starting crawl in PARALLEL mode")
    print(f"   Crawl Limit: {crawl_limit} URLs")
    print(f"   Workers: {num_workers} threads")
    print(f"   Delay: {min_delay}-{max_delay}s\n")
    
    # Start with the initial pages to crawl
    starting_urls = [
        "https://www.wikipedia.org/wiki/Google",
        "https://www.bbc.com/news/world",
        "https://news.ycombinator.com/",
    ]

    urls_to_crawl = Queue()
    for seed_url in starting_urls:
        urls_to_crawl.put(seed_url)

    visited_urls = set()  # URL tracking
    CRAWL_LIMIT = crawl_limit  # Use config value
    crawl_count = [0]  # Shared counter
    lock = threading.Lock()  # Thread safety lock
    index = {}
    webpage_info = {}
    pagerank_graph = {}  # For tracking hyperlinks for pagerank
    webpage_id_counter = [0]
    stop_crawl = threading.Event()

    # Start concurrent crawling with ThreadPoolExecutor
    #Concurrency = speed
    #Threads go BRRRRR
    #Increase this if you want more threads, but be careful with these.
    NUM_WORKERS = num_workers  # Use config value
    #Setting up arguments for the crawl function
    args = {
        'queue': urls_to_crawl,
        'visited_urls': visited_urls,
        'crawl_count': crawl_count,
        'CRAWL_LIMIT': CRAWL_LIMIT,
        'lock': lock,
        'index': index,
        'webpage_info': webpage_info,
        'webpage_id_counter': webpage_id_counter,
        'pagerank_graph': pagerank_graph,
        'stop_crawl': stop_crawl,
        'min_delay': min_delay,
        'max_delay': max_delay,
        'request_timeout': CONFIG.getint('Crawler', 'request_timeout', fallback=10)
    }

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        for _ in range(NUM_WORKERS):
            executor.submit(crawl, args)

        print("All URLs have been crawled")
    
    # Compute pagerank
    print("\n📊 Computing PageRank scores...")
    pagerank_scores = compute_pagerank(pagerank_graph)
    print(f"✓ PageRank computed")
    
    """ Save data as compressed JSON files with minimal data
        Only save: word->doc_ids and doc_id->url,title,description,pagerank
    """
    import os
    # Get the root directory and data directory
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    
    print("\n💾 SAVING INDEX FILES")
    print("=" * 50)
    print(f"Data directory: {data_dir}")
    
    # Save compressed inverted index
    index_data = {word: list(doc_ids) for word, doc_ids in index.items()}
    idx_path = os.path.join(data_dir, 'advanced_inverted_index.json.gz')
    with gzip.open(idx_path, 'wt', encoding='utf-8') as f:
        json.dump(index_data, f)
    file_size = os.path.getsize(idx_path) / 1024 / 1024  # MB
    print(f"✓ Inverted index: {len(index_data)} words, {file_size:.2f} MB")
    
    # Save compressed document info (minimal data)
    doc_data = {}
    for doc_id, info in webpage_info.items():
        # Minimize description to 150 chars
        desc = info['description'][:150] if len(info['description']) > 150 else info['description']
        doc_data[str(doc_id)] = {
            'url': info['url'],
            'title': info['title'],
            'description': desc,
            'pagerank': pagerank_scores.get(info['url'], 0)
        }
    
    doc_path = os.path.join(data_dir, 'advanced_doc_info.json.gz')
    with gzip.open(doc_path, 'wt', encoding='utf-8') as f:
        json.dump(doc_data, f)
    file_size = os.path.getsize(doc_path) / 1024 / 1024  # MB
    print(f"✓ Document info: {len(doc_data)} documents, {file_size:.2f} MB")
    
    print("\n✅ Crawler completed successfully!")

def main():
    # Start the crawling process
    sloth_bot()

if __name__ == "__main__":
    main()



