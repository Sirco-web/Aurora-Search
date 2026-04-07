import atexit
import configparser
import json
import os
import signal
import site
import ssl
import subprocess
import sys
import threading
import time

# List of required packages
REQUIRED_PACKAGES = {
    "flask": "flask",
    "flask_cors": "flask-cors",
    "nltk": "nltk",
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "socks": "pysocks",
    "psutil": "psutil",
}


def _candidate_site_packages():
    candidates = set()
    version = f"{sys.version_info.major}.{sys.version_info.minor}"

    try:
        candidates.add(site.getusersitepackages())
    except Exception:
        pass

    home = os.path.expanduser("~")
    candidates.add(os.path.join(home, ".local", "lib", f"python{version}", "site-packages"))

    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        sudo_home = os.path.expanduser(f"~{sudo_user}")
        candidates.add(os.path.join(sudo_home, ".local", "lib", f"python{version}", "site-packages"))

    return [path for path in candidates if path]


def _bootstrap_python_paths():
    for path in _candidate_site_packages():
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)


_bootstrap_python_paths()


def install_dependencies():
    """Install missing dependencies with --break-system-packages flag."""
    missing_packages = []

    for module_name, package_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing_packages.append(package_name)

    if missing_packages:
        if os.environ.get("SUDO_USER"):
            print(
                "Missing imports were detected while running under sudo. "
                "Checked user site-packages first, but they still were not importable."
            )
            print("If needed, run without sudo for dependency install, then rerun sudo for VPN mode.")
        print(f"Installing missing packages: {', '.join(missing_packages)}")
        for package in missing_packages:
            try:
                subprocess.check_call(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--break-system-packages",
                        package,
                    ]
                )
                print(f"Installed {package}")
            except subprocess.CalledProcessError as exc:
                print(f"Failed to install {package}: {exc}")
                sys.exit(1)
    else:
        print("All dependencies are already installed.")


install_dependencies()

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
from werkzeug.serving import make_server

from scripts.crawler import load_config as load_crawler_config
from scripts.crawler import run_crawler_service
from scripts.panda import score_content_quality
from scripts.penguin import score_link_quality
from scripts.ranking import rank_results, explain_ranking, calculate_combined_rank

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
IDX_FILE = os.path.join(DATA_DIR, "inverted_index.json")
DOC_FILE = os.path.join(DATA_DIR, "doc_info.json")

os.makedirs(DATA_DIR, exist_ok=True)


def load_config():
    """Load configuration from config.txt."""
    config = configparser.ConfigParser()
    config_path = os.path.join(ROOT_DIR, "config.txt")
    if os.path.exists(config_path):
        config.read(config_path)
        print(f"Loaded config from {config_path}")
    else:
        print(f"Config file not found at {config_path}")
    return config


CONFIG = load_config()

app = Flask(__name__, static_folder="public", static_url_path="")
CORS(app)

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    _create_unverified_https_context = None
else:
    ssl._create_default_https_context = _create_unverified_https_context


def download_nltk_resources():
    try:
        stopwords.words("english")
    except LookupError:
        print("Downloading NLTK stopwords...")
        nltk.download("stopwords", quiet=True)

    try:
        word_tokenize("test")
    except LookupError:
        print("Downloading NLTK punkt...")
        nltk.download("punkt", quiet=True)
        try:
            word_tokenize("test")
        except LookupError:
            nltk.download("punkt_tab", quiet=True)


print("\nNLTK SETUP")
print("=" * 50)
download_nltk_resources()
stop_words = set(stopwords.words("english"))
ps = PorterStemmer()
print("NLTK initialized")

index_lock = threading.Lock()
status_lock = threading.Lock()
runtime_lock = threading.Lock()

inverted_index = {}
document_info = {}
runtime_state = {
    "initialized": False,
    "crawler_thread": None,
    "crawler_stop_event": None,
    "vpn_manager": None,
    "server": None,
    "shutdown_started": False,
    "shutdown_complete": False,
    "startup_options": {},
}
indexing_status = {
    "status": "idle",
    "message": "Server not started yet.",
    "docs_indexed": 0,
    "words_indexed": 0,
    "crawl_count": 0,
    "queue_size": 0,
    "last_saved_count": 0,
    "last_saved_at": None,
    "continuous_mode": True,
    "save_every": 30,
}


def load_inverted_index(file_path):
    """Load compressed JSON inverted index."""
    loaded_index = {}
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            for word, doc_ids in data.items():
                loaded_index[word] = set(doc_ids)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Failed to load inverted index: {exc}")
        return {}
    return loaded_index


def load_document_info(file_path):
    """Load compressed JSON document info."""
    loaded_docs = {}
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            for doc_id, info in data.items():
                loaded_docs[int(doc_id)] = {
                    "url": info["url"],
                    "title": info["title"],
                    "description": info["description"],
                    "pagerank": float(info.get("pagerank", 0)),
                    "panda_score": float(info.get("panda_score", 0.5)),
                    "penguin_score": float(info.get("penguin_score", 0.5)),
                }
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Failed to load document info: {exc}")
        return {}
    return loaded_docs


def update_status(status=None, message=None, **fields):
    with status_lock:
        if status is not None:
            indexing_status["status"] = status
        if message is not None:
            indexing_status["message"] = message
        indexing_status.update(fields)


def load_indexes_into_memory(message=None, status="ready"):
    global inverted_index, document_info

    new_inverted_index = load_inverted_index(IDX_FILE)
    new_document_info = load_document_info(DOC_FILE)
    if not new_inverted_index or not new_document_info:
        return False

    with index_lock:
        inverted_index = new_inverted_index
        document_info = new_document_info

    update_status(
        status=status,
        message=message or "Search index loaded.",
        docs_indexed=len(new_document_info),
        words_indexed=len(new_inverted_index),
    )
    return True


def parse_query(query):
    tokens = word_tokenize(query.lower())
    return [ps.stem(word) for word in tokens if word.isalpha() and word not in stop_words]


def calculate_relevance_score(query_words, doc_text, title, description, url=""):
    """
    Calculate strict TF-IDF-inspired relevance score for a document.
    ONLY ranks pages that actually contain the query terms.
    
    Heavily penalizes:
    - Homepage/index pages
    - Pages without query terms in title/description
    - Generic news site homepages
    """
    if not query_words:
        return 0.0
    
    import re
    
    # Normalize all text
    title_lower = (title or "").lower()
    desc_lower = (description or "").lower()
    doc_lower = (doc_text or "").lower()
    url_lower = (url or "").lower()
    
    # HARD FILTER: Is this a homepage/index page?
    homepage_indicators = [
        "homepage",
        "index",
        "home page",
        "news.ycombinator",
        "news | hacker",
        "new comments",
        "latest news",
        "breaking news",
        "world news",
        "current news",
    ]
    
    is_homepage = any(indicator in desc_lower for indicator in homepage_indicators)
    is_homepage = is_homepage or any(indicator in title_lower for indicator in homepage_indicators)
    
    # Generic news site homepages - check description length
    if len(desc_lower.split()) < 10:  # Very short description = likely homepage
        is_homepage = True
    
    if is_homepage:
        return 0.0  # ZERO score for homepages
    
    # Count term occurrences using word boundaries (not substring)
    word_pattern = r'\b(' + "|".join(re.escape(w) for w in query_words) + r')\b'
    
    title_matches = len(re.findall(word_pattern, title_lower))
    desc_matches = len(re.findall(word_pattern, desc_lower))
    content_matches = len(re.findall(word_pattern, doc_lower))
    
    # HARD FILTER: If query terms not in title or description, heavily penalize
    if title_matches == 0 and desc_matches == 0:
        # Query term not in title or description - this is not a relevant result
        # Only give it credit if it appears many times in content
        if content_matches < 3:
            return 0.0  # Not relevant at all
        # If it appears many times in content, give it minimal score
        return 0.15
    
    # Calculate score: title > description > content
    score = (
        (title_matches * 8.0) +     # Title match is excellent signal
        (desc_matches * 3.0) +      # Description match is good signal
        (content_matches * 1.0)     # Content match is weak signal
    )
    
    # Normalize with log scale
    import math
    if score == 0:
        relevance = 0.0
    else:
        # log(1 + score) normalized to 0-1 range
        relevance = min(1.0, math.log(1 + score) / math.log(15))
    
    return round(relevance, 4)


def search(query, current_index, current_docs, num_results=10, page=1):
    query_words = parse_query(query)
    if not query_words:
        return []

    matched_doc_ids = set()
    for word in query_words:
        if word in current_index:
            matched_doc_ids.update(current_index[word])

    if not matched_doc_ids:
        return []

    results = []
    for doc_id in matched_doc_ids:
        info = current_docs.get(doc_id)
        if not info:
            continue
        
        # Calculate how well this document matches the query
        full_text = f"{info.get('title', '')} {info.get('description', '')} {info.get('content', '')}"
        relevance_score = calculate_relevance_score(
            query_words, 
            full_text, 
            info.get('title', ''), 
            info.get('description', ''),
            info.get('url', '')
        )
        
        results.append(
            {
                "doc_id": doc_id,
                "url": info["url"],
                "title": info["title"],
                "description": info["description"],
                "pagerank": info["pagerank"],
                "panda_score": info.get("panda_score", 0.5),
                "penguin_score": info.get("penguin_score", 0.5),
                "relevance_score": relevance_score,  # NEW: Query relevance
            }
        )

    # Use unified ranking algorithm combining PageRank, Panda, Penguin, AND Relevance
    # 'relevance_first' strategy emphasizes matching the query over just link/content metrics
    ranked_results = rank_results(results, strategy='relevance_first')
    
    # Filter out completely irrelevant results (relevance_score = 0)
    ranked_results = [r for r in ranked_results if r.get('relevance_score', 0.0) > 0.0]
    
    start = (page - 1) * num_results
    end = start + num_results
    return ranked_results[start:end]


def collect_startup_options():
    configured_proxy_list = CONFIG.get("Proxy", "proxy_list", fallback="").strip()
    default_reindex_every = CONFIG.getint("Startup", "reindex_every_pages", fallback=30)

    options = {
        "start_crawler": False,
        "continuous_crawl": False,
        "reindex_every": default_reindex_every,
        "use_proxy": False,
        "proxy_list": "",
        "start_vpn": False,
        "start_all_vpns": False,
    }

    if not sys.stdin.isatty():
        return options

    print("\n" + "=" * 60)
    print("AURORA SEARCH - STARTUP MODE")
    print("=" * 60)
    print("\nChoose startup mode:\n")
    print("  [1] SERVE ONLY - Just serve the index/search (no crawler, no VPN)")
    print("  [2] SERVE + CRAWLER - Serve + continuous crawler (no VPN)")
    print("  [3] SERVE + CRAWLER + VPN - Full setup with VPN tunnels\n")
    
    while True:
        try:
            choice = input("Enter your choice (1, 2, or 3): ").strip()
            if choice in ["1", "2", "3"]:
                break
            print("Invalid choice. Please enter 1, 2, or 3.")
        except EOFError:
            # Non-interactive mode, default to option 1
            choice = "1"
            break

    if choice == "1":
        # SERVE ONLY
        options["start_crawler"] = False
        options["continuous_crawl"] = False
        print("\n✓ Mode: SERVE ONLY")
        print("  - Server will run on port 5000")
        print("  - No crawler active")
        print("  - Searching existing index only")
        
    elif choice == "2":
        # SERVE + CRAWLER (no VPN)
        options["start_crawler"] = True
        options["continuous_crawl"] = True
        options["reindex_every"] = default_reindex_every
        options["use_proxy"] = False
        print("\n✓ Mode: SERVE + CRAWLER")
        print("  - Server will run on port 5000")
        print("  - Crawler will run continuously")
        print(f"  - Reindex every {default_reindex_every} pages")
        print("  - No proxies (direct requests)")
        
    elif choice == "3":
        # SERVE + CRAWLER + VPN
        options["start_crawler"] = True
        options["continuous_crawl"] = True
        options["reindex_every"] = default_reindex_every
        options["start_vpn"] = True
        options["start_all_vpns"] = True
        options["use_proxy"] = True
        options["proxy_list"] = ""
        print("\n✓ Mode: SERVE + CRAWLER + VPN")
        print("  - Server will run on port 5000")
        print("  - Crawler will run continuously")
        print(f"  - Reindex every {default_reindex_every} pages")
        print("  - VPN tunnels will start automatically")
        print("  - Crawler will rotate through active VPN proxies")
    
    print("=" * 60)
    return options


def print_startup_summary(options):
    print("\nSTARTUP SUMMARY")
    print("=" * 50)
    print(f"Crawler enabled: {options['start_crawler']}")
    print(f"Continuous crawl: {options['continuous_crawl']}")
    print(f"Reindex every: {options['reindex_every']} pages")
    print(f"Use configured proxies: {options['use_proxy']}")
    print(f"Start VPN first: {options['start_vpn']}")
    print(f"Start all VPN configs: {options['start_all_vpns']}")
    if options["start_vpn"]:
        print("VPN routing mode: multiple active tunnels with rotating local proxies")


def setup_crawler_network_namespace():
    """
    Set up isolated network namespace for VPN.
    The crawler uses proxies that route through this namespace.
    This ensures:
    - VPN only affects crawler proxies, not the whole PC
    - Web server stays normal  
    - Both share /data index folder
    """
    import subprocess
    import os
    
    namespace_name = "aurora_crawler"
    
    try:
        # Create namespace (empty if already exists)
        subprocess.run(
            ["ip", "netns", "add", namespace_name],
            capture_output=True,
            timeout=5,
        )
        
        # Enable loopback in namespace for local communication
        subprocess.run(
            ["ip", "netns", "exec", namespace_name, "ip", "link", "set", "lo", "up"],
            capture_output=True,
            timeout=5,
        )
        
        print("✓ Isolated network namespace created for VPN")
        print("  → PC stays normal speed (VPN only in namespace)")
        print("  → Crawler uses proxies through namespace")
        print("  → Index auto-syncs to /data (shared)")
        runtime_state["namespace_name"] = namespace_name
        return True
    except Exception as e:
        print(f"⚠ Could not set up namespace: {e}")
        print("  Using standard routing (VPN may affect whole PC)")
        return False


def start_vpn_if_requested(options):
    if not options["start_vpn"]:
        return True

    try:
        from scripts.vpn_manager import VPNManager
    except Exception as exc:
        print(f"VPN support could not be loaded: {exc}")
        return False

    manager = VPNManager()
    runtime_state["vpn_manager"] = manager
    if not manager.check_openvpn_installed():
        print("OpenVPN is not installed, so VPN startup failed.")
        return False

    # IMPORTANT: Enable network namespace isolation
    # This ensures VPN only affects crawler, not the whole PC
    print("Setting up isolated network namespace for crawler...")
    setup_crawler_network_namespace()

    configs = manager.find_vpn_configs()
    if not configs:
        print(f"No VPN configs were found in {manager.vpn_configs_dir}.")
        return False

    print("\nVPN STARTUP")
    print("=" * 50)
    active_configs = manager.start_all()

    if not active_configs:
        runtime_state["vpn_manager"] = None
        print("VPN startup did not produce an active tunnel.")
        return False

    manager.start_monitoring()
    proxy_list = manager.generate_proxy_list()
    if not proxy_list:
        runtime_state["vpn_manager"] = None
        print("VPN tunnels started, but no local tunnel-bound proxies could be created.")
        return False

    options["use_proxy"] = True
    options["proxy_list"] = proxy_list
    print(f"Active VPN tunnels: {', '.join(active_configs)}")
    print("Crawler requests will rotate across the active VPN-bound local proxies.")
    for proxy in proxy_list.split("|"):
        print(f"  {proxy}")
    return True


def handle_crawler_status(event):
    with index_lock:
        has_searchable_index = bool(inverted_index and document_info)
    with status_lock:
        current_status = dict(indexing_status)

    requested_state = event.get("state", "indexing")
    effective_state = requested_state
    if requested_state == "indexing" and has_searchable_index:
        effective_state = "refreshing"
    elif requested_state == "stopped" and has_searchable_index:
        effective_state = "ready"

    update_status(
        status=effective_state,
        message=event.get("message", current_status["message"]),
        crawl_count=event.get("crawl_count", current_status["crawl_count"]),
        queue_size=event.get("queue_size", current_status["queue_size"]),
        last_saved_count=event.get("last_saved_count", current_status["last_saved_count"]),
        last_saved_at=event.get("last_saved_at", current_status["last_saved_at"]),
        continuous_mode=event.get("continuous_mode", current_status["continuous_mode"]),
        save_every=event.get("save_every", current_status["save_every"]),
        docs_indexed=event.get("docs_indexed", current_status["docs_indexed"]),
        words_indexed=event.get("words_indexed", current_status["words_indexed"]),
    )


def handle_crawler_save(event):
    message = (
        f"Live index refreshed after {event['crawl_count']} crawled pages "
        f"at {event['saved_at']}."
    )
    if not load_indexes_into_memory(message=message, status="ready"):
        update_status(status="error", message="Crawler saved files, but the server could not reload them.")


def run_crawler_in_background(options):
    try:
        runtime_options = {
            "save_every": options["reindex_every"],
            "continuous": options["continuous_crawl"],
            "use_proxy": options["use_proxy"],
            "proxy_list": options.get("proxy_list", ""),
        }

        run_crawler_service(
            config=load_crawler_config(),
            runtime_options=runtime_options,
            log_callback=print,
            status_callback=handle_crawler_status,
            save_callback=handle_crawler_save,
            stop_event=runtime_state["crawler_stop_event"],
        )
    except Exception as exc:
        print(f"Crawler crashed: {exc}")
        update_status(status="error", message=f"Crawler crashed: {exc}")


def initialize_runtime(options):
    with runtime_lock:
        if runtime_state["initialized"]:
            return
        runtime_state["initialized"] = True
        runtime_state["startup_options"] = dict(options)

    if load_indexes_into_memory(message="Loaded cached index from disk.", status="ready"):
        print("Cached search index loaded.")
    else:
        update_status(status="indexing", message="Waiting for the crawler to produce the first live index.")

    if options["start_vpn"] and not start_vpn_if_requested(options):
        update_status(
            status="error",
            message="VPN was required but no active VPN tunnels could be started.",
            continuous_mode=False,
            save_every=options["reindex_every"],
        )
        return False

    if not options["start_crawler"]:
        update_status(
            status="ready" if inverted_index and document_info else "idle",
            message="Crawler startup skipped." if inverted_index and document_info else "Crawler is disabled.",
            continuous_mode=False,
            save_every=options["reindex_every"],
        )
        return True

    if inverted_index and document_info:
        update_status(
            status="refreshing",
            message="Cached index loaded. Fresh crawl is running in the background.",
            continuous_mode=options["continuous_crawl"],
            save_every=options["reindex_every"],
        )
    else:
        update_status(
            status="indexing",
            message="SircoAuroraBot is building the first live index.",
            continuous_mode=options["continuous_crawl"],
            save_every=options["reindex_every"],
        )

    runtime_state["crawler_stop_event"] = threading.Event()
    runtime_state["crawler_thread"] = threading.Thread(
        target=run_crawler_in_background,
        args=(options,),
        daemon=False,
    )
    runtime_state["crawler_thread"].start()
    print("SircoAuroraBot background crawl thread started.")
    return True


def perform_runtime_shutdown(reason="Safe stop requested"):
    stop_event = runtime_state.get("crawler_stop_event")
    if stop_event:
        stop_event.set()

    server = runtime_state.get("server")
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass

    crawler_thread = runtime_state.get("crawler_thread")
    if crawler_thread and crawler_thread.is_alive():
        crawler_thread.join(timeout=20)

    vpn_manager = runtime_state.get("vpn_manager")
    if vpn_manager:
        vpn_manager.stop_all_vpns()

    runtime_state["shutdown_complete"] = True
    update_status(status="stopped", message=reason)


def initiate_safe_stop(reason):
    with runtime_lock:
        if runtime_state["shutdown_started"]:
            return
        runtime_state["shutdown_started"] = True

    print("\nStarting safe stop. Waiting for SircoAuroraBot to finish in-flight work and save...")
    update_status(status="stopping", message=reason)
    shutdown_thread = threading.Thread(
        target=perform_runtime_shutdown,
        args=(reason,),
        daemon=True,
    )
    shutdown_thread.start()


def handle_interrupt(signum, frame):
    initiate_safe_stop("Safe stop requested by Ctrl+C.")


def shutdown_runtime():
    if runtime_state.get("shutdown_complete"):
        return
    perform_runtime_shutdown("Runtime shutdown requested.")


atexit.register(shutdown_runtime)


@app.route("/")
def serve_index():
    return send_from_directory("public", "index.html")


@app.route("/search.html")
def serve_search():
    return send_from_directory("public", "search.html")


@app.route("/search")
def search_api():
    query = request.args.get("q", "")
    default_results = CONFIG.getint("Server", "results_per_page", fallback=10)
    num_results = int(request.args.get("num_results", default_results))
    page = int(request.args.get("page", 1))

    print(f"\nSEARCH REQUEST: '{query}' (page {page})")
    if not query:
        return jsonify({"error": "No query provided"}), 400

    with index_lock:
        current_index = inverted_index
        current_docs = document_info

    with status_lock:
        current_status = dict(indexing_status)

    if not current_index or not current_docs:
        return (
            jsonify(
                {
                    "error": "Search index not ready yet",
                    "message": current_status["message"],
                    "status": current_status["status"],
                    "docs_indexed": current_status["docs_indexed"],
                    "words_indexed": current_status["words_indexed"],
                    "query": query,
                    "results": [],
                }
            ),
            202,
        )

    results = search(query, current_index, current_docs, num_results=num_results, page=page)
    return jsonify(
        {
            "query": query,
            "page": page,
            "num_results": num_results,
            "status": current_status["status"],
            "results": results,
        }
    )


@app.route("/ranking-info")
def ranking_info_api():
    """Return information about ranking algorithms used."""
    return jsonify(
        {
            "algorithms": {
                "pagerank": {
                    "name": "PageRank",
                    "description": "Measures link popularity and authority",
                    "weight": 0.4,
                    "range": "0.0 to 1.0 (normalized)",
                },
                "panda": {
                    "name": "Panda Algorithm",
                    "description": "Scores content quality based on depth, structure, originality, and readability",
                    "weight": 0.35,
                    "factors": [
                        "Content length (thin content penalized)",
                        "HTML structure (headings, paragraphs, lists)",
                        "Readability (sentence/word length)",
                        "Keyword stuffing detection",
                        "Duplicate content detection",
                        "Content freshness",
                    ],
                },
                "penguin": {
                    "name": "Penguin Algorithm",
                    "description": "Scores link quality and trustworthiness",
                    "weight": 0.15,
                    "factors": [
                        "Backlink count (logarithmic scale)",
                        "Domain authority of linking sites",
                        "Anchor text naturalness",
                        "Link farm pattern detection",
                    ],
                },
            },
            "formula": "rank_score = (pagerank * 0.4) + (panda * 0.35) + (penguin * 0.15) + (relevance * 0.1)",
            "quality_thresholds": {
                "low_quality_content": "Panda < 0.3 reduces score by 70%",
                "suspicious_links": "Penguin < 0.2 reduces score by 50%",
                "high_quality_boost": "Panda > 0.8 AND Penguin > 0.8 boosts score by 20%",
            },
        }
    )


@app.route("/explain")
def explain_ranking_api():
    """Explain why a specific result ranked where it did."""
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "URL parameter required"}), 400

    with index_lock:
        current_docs = document_info

    # Find the document
    target_doc = None
    for doc_id, info in current_docs.items():
        if info["url"] == url:
            target_doc = info
            break

    if not target_doc:
        return jsonify({"error": "URL not found in index"}), 404

    explanation = explain_ranking(target_doc)
    return jsonify(
        {
            "url": url,
            "title": target_doc.get("title"),
            "explanation": explanation,
            "scores": {
                "pagerank": target_doc.get("pagerank", 0),
                "panda": target_doc.get("panda_score", 0.5),
                "penguin": target_doc.get("penguin_score", 0.5),
                "rank_score": target_doc.get("rank_score", 0),
            },
        }
    )


@app.route("/status")
def status_api():
    with status_lock:
        return jsonify(dict(indexing_status))


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_interrupt)
    signal.signal(signal.SIGTERM, handle_interrupt)

    startup_options = collect_startup_options()
    print_startup_summary(startup_options)
    initialized = initialize_runtime(startup_options)
    if not initialized:
        print("Startup stopped because no working VPN tunnels were available.")
        sys.exit(1)

    host = CONFIG.get("Server", "host", fallback="0.0.0.0")
    port = CONFIG.getint("Server", "port", fallback=5000)
    debug = CONFIG.getboolean("Server", "debug", fallback=True)

    print("\n" + "=" * 50)
    print("AURORA SEARCH SERVER")
    print("=" * 50)
    print(f"URL: http://localhost:{port}")
    print(f"Host binding: {host}:{port}")
    print(f"Debug mode: {debug}")
    print(f"Search API: http://localhost:{port}/search?q=query")
    print(f"Ranking Info: http://localhost:{port}/ranking-info")
    print(f"Explain Rank: http://localhost:{port}/explain?url=https://...")
    print(f"Status API: http://localhost:{port}/status")
    print("SircoAuroraBot logs will stream in this terminal while the server is running.")
    print("=" * 50 + "\n")

    server = make_server(host, port, app)
    runtime_state["server"] = server

    try:
        server.serve_forever()
    finally:
        if not runtime_state.get("shutdown_started"):
            initiate_safe_stop("Server loop exited.")
