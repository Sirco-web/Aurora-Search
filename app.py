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


def check_public_ip():
    """Check public IP without VPN"""
    import requests
    try:
        resp = requests.get('https://api.ipify.org?format=json', timeout=5, verify=False)
        return resp.json().get('ip', 'unknown')
    except:
        return None

def check_docker_available():
    """Check if Docker is installed and running. If not, install/start it automatically."""
    import subprocess
    
    # First, check if docker command exists
    result = subprocess.run(["which", "docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    docker_installed = result.returncode == 0
    
    if not docker_installed:
        print("  [DOCKER] Docker not found. Installing Docker...")
        
        # Update package list
        result = subprocess.run(["sudo", "apt", "update"], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        
        # Install Docker
        result = subprocess.run(["sudo", "apt", "install", "-y", "docker.io"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        
        if result.returncode != 0:
            print("  ✗ Failed to install Docker")
            return False
        
        print("  ✓ Docker installed successfully")
        
        # Add current user to docker group so we can run without sudo
        subprocess.run(["sudo", "usermod", "-aG", "docker", os.environ.get("USER", "root")],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Check if Docker daemon is running
    result = subprocess.run(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    
    if result.returncode != 0:
        print("  [DOCKER] Docker daemon not running. Starting Docker...")
        
        # Try to start Docker daemon
        result = subprocess.run(["sudo", "systemctl", "start", "docker"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        
        if result.returncode != 0:
            print("  ✗ Failed to start Docker daemon")
            return False
        
        print("  ✓ Docker daemon started")
        
        # Wait for Docker to be ready
        time.sleep(2)
        
        # Verify it's running
        result = subprocess.run(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if result.returncode != 0:
            print("  ✗ Docker still not responding")
            return False
    
    print("  ✓ Docker is running and ready")
    return True

def docker_image_exists(image_name="aurora-vpn:latest"):
    """Check if Docker image already exists (skip rebuild)"""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False

def get_vpn_ip_from_docker():
    """Get public IP from inside Docker container"""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "exec", "aurora-vpn", "curl", "-s", "--max-time", "15",
             "https://api.ipify.org?format=json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            return data.get('ip', 'unknown')
    except:
        pass
    return None

def build_vpn_docker_image(force_rebuild=False):
    """Build Docker image for VPN from Dockerfile.vpn - only if needed"""
    
    # Skip if already exists (unless force_rebuild)
    if docker_image_exists() and not force_rebuild:
        print("  ✓ Docker image already built: aurora-vpn:latest")
        return True
    
    print("  [DOCKER] Building VPN container image...")
    
    dockerfile_path = os.path.join(os.path.dirname(__file__), "Dockerfile.vpn")
    
    result = subprocess.run(
        ["docker", "build", "-f", dockerfile_path, "-t", "aurora-vpn:latest", "."],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120
    )
    
    if result.returncode != 0:
        error = result.stderr.decode() if result.stderr else "Unknown error"
        print(f"  ✗ Failed to build Docker image: {error}")
        return False
    
    print(f"  ✓ Docker image built successfully: aurora-vpn:latest")
    return True

def start_vpn_docker_container(config_path):
    """Start VPN inside Docker container with SOCKS5 proxy"""
    print("  [DOCKER] Starting VPN container...")
    
    # Clean up old container if exists
    subprocess.run(
        ["docker", "rm", "-f", "aurora-vpn"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10
    )
    
    time.sleep(1)
    
    # Start new container
    result = subprocess.run(
        ["docker", "run", "-d",
         "--name", "aurora-vpn",
         "--cap-add", "NET_ADMIN",
         "--cap-add", "NET_RAW",
         "-p", "127.0.0.1:1080:1080",  # SOCKS5 proxy (only local)
         "-v", f"{config_path}:/etc/openvpn/config/vpn.ovpn:ro",
         "aurora-vpn:latest"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10
    )
    
    if result.returncode != 0:
        error = result.stderr.decode()
        print(f"  ✗ Failed to start container: {error}")
        return False
    
    container_id = result.stdout.decode().strip()[:12]
    print(f"  ✓ VPN container started (ID: {container_id})")
    
    # Wait for container to be ready
    time.sleep(2)
    
    return True

def test_vpn_docker_tunnel():
    """Test if VPN tunnel inside Docker is working - returns VPN IP or None"""
    print(f"  [TEST] Testing VPN tunnel inside Docker container...")
    
    try:
        result = subprocess.run(
            ["docker", "exec", "aurora-vpn", "curl", "-s", "--max-time", "15",
             "https://api.ipify.org?format=json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20
        )
        
        if result.returncode == 0:
            try:
                import json
                data = json.loads(result.stdout)
                vpn_ip = data.get('ip', None)
                if vpn_ip:
                    print(f"  ✓ Got VPN IP from container: {vpn_ip}")
                    return vpn_ip
            except:
                pass
    except:
        pass
    
    print(f"  ✗ VPN tunnel test failed")
    return None

def setup_vpn_namespace():
    """Create isolated network namespace for VPN - returns namespace name or None"""
    import subprocess
    import os
    
    ns_name = "vpn-ns"
    
    print("  [NS] Creating isolated network namespace...")
    
    # Check if namespace exists
    result = subprocess.run(["ip", "netns", "list"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ns_name.encode() in result.stdout:
        print(f"  [NS] Namespace {ns_name} already exists, cleaning up...")
        subprocess.run(["ip", "netns", "delete", ns_name], stderr=subprocess.DEVNULL)
        time.sleep(0.5)
    
    # Create namespace
    result = subprocess.run(["ip", "netns", "add", ns_name], stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"  ✗ Failed to create namespace: {result.stderr.decode()}")
        return None
    
    print(f"  ✓ Namespace {ns_name} created")
    
    # Bring up loopback in namespace
    subprocess.run(["ip", "netns", "exec", ns_name, "ip", "link", "set", "lo", "up"], 
                   stderr=subprocess.DEVNULL)
    
    # Create veth pair for host->namespace communication
    print("  [NS] Setting up virtual ethernet pair...")
    veth_host = "veth-host"
    veth_ns = "veth-ns"
    
    subprocess.run(["ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_ns],
                   stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", veth_ns, "netns", ns_name], stderr=subprocess.DEVNULL)
    
    # Configure veth interfaces
    subprocess.run(["ip", "addr", "add", "192.168.100.1/24", "dev", veth_host], 
                   stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", veth_host, "up"], stderr=subprocess.DEVNULL)
    
    subprocess.run(["ip", "netns", "exec", ns_name, "ip", "addr", "add", "192.168.100.2/24", 
                    "dev", veth_ns], stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "netns", "exec", ns_name, "ip", "link", "set", veth_ns, "up"],
                   stderr=subprocess.DEVNULL)
    
    print(f"  ✓ Veth pair configured (host: 192.168.100.1, ns: 192.168.100.2)")
    
    # Enable namespace to reach outside world
    print("  [NS] Enabling internet access from namespace...")
    
    # Enable IP forwarding on host
    subprocess.run(["sysctl", "-w", "net.ipv4.ip_forward=1"], 
                   stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    
    # Add default route in namespace to reach host
    subprocess.run(["ip", "netns", "exec", ns_name, "ip", "route", "add", "default", "via", "192.168.100.1"],
                   stderr=subprocess.DEVNULL)
    
    # Get default network interface on host
    result = subprocess.run(["ip", "route", "show", "default"], 
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    default_iface = None
    if result.returncode == 0:
        # Parse something like: default via 172.17.0.1 dev eth0
        parts = result.stdout.strip().split()
        if "dev" in parts:
            default_iface = parts[parts.index("dev") + 1]
    
    if default_iface:
        # Enable NAT on host's default interface
        subprocess.run(["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", default_iface, "-j", "MASQUERADE"],
                       stderr=subprocess.DEVNULL)
        
        # Enable forward rules
        subprocess.run(["iptables", "-A", "FORWARD", "-i", "veth-host", "-j", "ACCEPT"],
                       stderr=subprocess.DEVNULL)
        subprocess.run(["iptables", "-A", "FORWARD", "-o", "veth-host", "-j", "ACCEPT"],
                       stderr=subprocess.DEVNULL)
        
        print(f"  ✓ IP forwarding enabled (NAT on {default_iface})")
    else:
        print(f"  ⚠ Could not detect interface for NAT (namespace may have limited access)")
    
    return ns_name

def test_vpn_config_manually(config_path, timeout=30):
    """Test if a VPN config works (manual test before namespace) - returns True if works"""
    print(f"  [PREFLIGHT] Testing config: {os.path.basename(config_path)}...", end=' ')
    
    result = subprocess.run(
        ["timeout", str(timeout), "openvpn", "--config", config_path, 
         "--data-ciphers", "AES-128-CBC",
         "--data-ciphers-fallback", "AES-128-CBC",
         "--daemon", "--log", "/tmp/openvpn-test.log"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        timeout=timeout + 5
    )
    
    # Check if it started
    time.sleep(2)
    result = subprocess.run(
        ["curl", "-s", "--max-time", "10", "https://api.ipify.org?format=json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=15
    )
    
    if result.returncode == 0:
        try:
            import json
            data = json.loads(result.stdout)
            if "ip" in data:
                print(f"✓ WORKS (IP: {data['ip']})")
                # Kill test VPN
                subprocess.run(["pkill", "-f", f"openvpn.*{os.path.basename(config_path)}"],
                              stderr=subprocess.DEVNULL)
                time.sleep(1)
                return True
        except:
            pass
    
    print("✗ FAILED (no connection)")
    subprocess.run(["pkill", "-f", "openvpn"], stderr=subprocess.DEVNULL)
    return False

def find_working_vpn_config(vpn_dir):
    """Find first working VPN config - skip broken ones"""
    configs = [f for f in os.listdir(vpn_dir) if f.endswith('.ovpn')]
    
    if not configs:
        print(f"✗ No .ovpn files found in {vpn_dir}")
        return None
    
    print(f"\n📋 Found {len(configs)} VPN config(s). Testing for working tunnel...")
    print("=" * 50)
    
    for config_file in configs:
        config_path = os.path.join(vpn_dir, config_file)
        
        # Test this config
        if test_vpn_config_manually(config_path, timeout=30):
            print(f"✓ Using config: {config_file}")
            return config_path
        
        time.sleep(1)
    
    print("\n✗ No working VPN configs found. All tested configs failed.")
    print("  Possible issues:")
    print("  • Cipher mismatch (check cipher in .ovpn file)")
    print("  • VPN server unavailable")
    print("  • Network connectivity issue")
    print("  • Invalid credentials in .ovpn")
    return None

def start_vpn_in_namespace(ns_name, config_path):
    """Start OpenVPN inside the network namespace"""
    import subprocess
    
    print(f"  [VPN] Starting OpenVPN in namespace {ns_name}...")
    
    # Start VPN in namespace with proper logging
    cmd = [
        "ip", "netns", "exec", ns_name,
        "openvpn",
        "--config", config_path,
        "--data-ciphers", "AES-128-CBC",
        "--data-ciphers-fallback", "AES-128-CBC",
        "--daemon",
        "--dev", "tun0",
        "--writepid", f"/tmp/vpn-{ns_name}.pid",
        "--log", f"/tmp/vpn-{ns_name}.log",
        "--script-security", "2",
        "--redirect-gateway", "def1",  # SAFE inside namespace
    ]
    
    result = subprocess.run(cmd, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"  ✗ Failed to start VPN: {result.stderr.decode()}")
        return False
    
    time.sleep(3)
    
    # Verify VPN started
    pid_file = f"/tmp/vpn-{ns_name}.pid"
    if not os.path.exists(pid_file):
        print(f"  ✗ VPN failed to start (no PID file)")
        return False
    
    with open(pid_file) as f:
        vpn_pid = f.read().strip()
    print(f"  ✓ OpenVPN running in namespace (PID: {vpn_pid})")
    return True

def test_vpn_tunnel(ns_name):
    """Test if VPN tunnel in namespace is working"""
    import subprocess
    
    print(f"  [TEST] Verifying tunnel in {ns_name}...")
    
    # Try to get IP from within namespace
    result = subprocess.run(
        ["ip", "netns", "exec", ns_name, "curl", "-s", 
         "https://api.ipify.org?format=json"],
        timeout=10,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.PIPE
    )
    
    if result.returncode == 0:
        try:
            import json
            data = json.loads(result.stdout.decode())
            vpn_ip = data.get('ip', 'unknown')
            print(f"  ✓ VPN tunnel working! IP in namespace: {vpn_ip}")
            return True
        except:
            pass
    
    print(f"  ✗ VPN tunnel test failed or took too long")
    return False

def start_proxy_in_namespace(ns_name, proxy_port=1080):
    """Start a SOCKS5 proxy inside namespace - supports both HTTP and HTTPS"""
    import subprocess
    
    # Create simple SOCKS5 proxy script
    proxy_script = f"""
import socket
import struct
import sys

def handle_socks5(client_socket):
    # SOCKS5 greeting
    data = client_socket.recv(2)
    if data[0] != 5:
        return
    
    nmethods = data[1]
    methods = client_socket.recv(nmethods)
    client_socket.send(b'\\x05\\x00')  # No auth required
    
    # Request
    data = client_socket.recv(4)
    ver, cmd, _, atyp = data[0], data[1], data[2], data[3]
    
    if cmd != 1:  # Only CONNECT
        return
    
    # Parse address
    if atyp == 1:  # IPv4
        addr = socket.inet_ntoa(client_socket.recv(4))
        port = struct.unpack('>H', client_socket.recv(2))[0]
    elif atyp == 3:  # Domain
        domain_len = client_socket.recv(1)[0]
        addr = client_socket.recv(domain_len).decode()
        port = struct.unpack('>H', client_socket.recv(2))[0]
    elif atyp == 4:  # IPv6
        addr = socket.inet_ntop(socket.AF_INET6, client_socket.recv(16))
        port = struct.unpack('>H', client_socket.recv(2))[0]
    else:
        return
    
    # Connect to remote
    try:
        remote = socket.socket(socket.AF_INET if atyp != 4 else socket.AF_INET6, socket.SOCK_STREAM)
        remote.connect((addr, port))
        
        # Send success response
        resp = b'\\x05\\x00\\x00\\x01'
        resp += socket.inet_aton(remote.getsockname()[0])
        resp += struct.pack('>H', remote.getsockname()[1])
        client_socket.send(resp)
        
        # Relay traffic
        import select
        while True:
            ready = select.select([client_socket, remote], [], [], 1)
            if client_socket in ready[0]:
                data = client_socket.recv(4096)
                if not data:
                    break
                remote.send(data)
            if remote in ready[0]:
                data = remote.recv(4096)
                if not data:
                    break
                client_socket.send(data)
    except:
        pass
    finally:
        client_socket.close()
        remote.close()

if __name__ == '__main__':
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', {proxy_port}))
    server.listen(100)
    print(f"SOCKS5 server listening on port {proxy_port}", file=sys.stderr, flush=True)
    
    try:
        while True:
            client, addr = server.accept()
            try:
                handle_socks5(client)
            except:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
"""
    
    proxy_file = f"/tmp/socks5-{ns_name}.py"
    with open(proxy_file, 'w') as f:
        f.write(proxy_script)
    
    print(f"  [SOCKS5] Starting SOCKS5 proxy on port {proxy_port} in namespace...")
    
    cmd = ["ip", "netns", "exec", ns_name, "python3", proxy_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    time.sleep(1)
    
    # Verify proxy started
    if proc.poll() is None:
        print(f"  ✓ SOCKS5 proxy running (PID: {proc.pid})")
        runtime_state["proxy_process"] = proc
        runtime_state["proxy_port"] = proxy_port
        return True
    else:
        print(f"  ✗ SOCKS5 proxy failed to start")
        return False

def find_working_vpn_config_docker(vpn_dir, ip_before):
    """Try to find working VPN config using Docker - tests each config"""
    configs = [f for f in os.listdir(vpn_dir) if f.endswith('.ovpn')]
    
    if not configs:
        print(f"✗ No .ovpn files found in {vpn_dir}")
        return None
    
    print(f"\n📋 Found {len(configs)} VPN config(s). Testing in Docker...")
    print("=" * 50)
    
    for idx, config_file in enumerate(configs, 1):
        config_path = os.path.join(vpn_dir, config_file)
        print(f"\n[{idx}/{len(configs)}] Testing: {config_file}...")
        
        # Try this config in Docker (timeout=30 for quick testing per config)
        vpn_ip = start_vpn_with_docker(config_path, ip_before, timeout=30)
        
        if vpn_ip:  # Returns VPN IP if successful
            print(f"✓ SUCCESS! Using config: {config_file}")
            return vpn_ip
        
        print(f"✗ Config failed, trying next...")
        time.sleep(1)
    
    print("\n✗ No working VPN configs found in Docker.")
    return None

def start_vpn_with_docker(config_path, ip_before, timeout=60):
    """Start VPN using Docker container - reuses container/image, no waste"""
    print("\n🐳 VPN SETUP WITH DOCKER CONTAINER")
    print("=" * 50)
    
    # STEP 1: Build Docker image (skip if already exists)
    print("\nSTEP 1: Checking Docker image...")
    if not build_vpn_docker_image(force_rebuild=False):
        print("✗ Failed to build/check Docker image")
        return None
    
    # STEP 2: Start Docker container (reuses name, replaces old one)
    print("\nSTEP 2: Starting Docker container with VPN...")
    if not start_vpn_docker_container(config_path):
        print("✗ Failed to start Docker container")
        return None
    
    # STEP 3: Test VPN tunnel - MUST GET DIFFERENT IP (VPN working = different IP)
    print(f"\nSTEP 3: Testing VPN tunnel (waiting up to {timeout} seconds for tunnel...)...")
    vpn_ip = None
    max_attempts = timeout // 5
    for attempt in range(max_attempts):
        if timeout <= 40:  # Shorter testing for config loop
            print(f"  Attempt {attempt + 1}/{max_attempts}...", end='\r')
        else:
            print(f"  Attempt {attempt + 1}/{max_attempts}...")
        vpn_ip = test_vpn_docker_tunnel()
        if vpn_ip:
            print(f"  ✓ Got VPN IP: {vpn_ip}    ")
            break
        time.sleep(5)
    
    if not vpn_ip:
        print("✗ VPN tunnel FAILED in this container")
        subprocess.run(["docker", "rm", "-f", "aurora-vpn"], stderr=subprocess.DEVNULL)
        return None
    
    # STEP 4: Verify your PC is PROTECTED (IP unchanged)
    print("\nSTEP 4: Verifying YOUR PC is PROTECTED...")
    ip_after = check_public_ip()
    if ip_after:
        print(f"✓ Your public IP: {ip_after}")
    else:
        print("⚠ Could not check")
        ip_after = "unknown"
    
    # STEP 5: Final comparison
    print("\nSTEP 5: FINAL VERIFICATION:")
    print(f"  Your PC before: {ip_before}")
    print(f"  Your PC after:  {ip_after}")
    print(f"  VPN in container: {vpn_ip}")
    
    # Check 1: PC must stay same
    if ip_before != "unknown" and ip_after != "unknown":
        if ip_before != ip_after:
            print("\n✗ CRITICAL: Your PC's IP CHANGED!")
            print("  Docker is NOT providing proper isolation")
            subprocess.run(["docker", "rm", "-f", "aurora-vpn"], stderr=subprocess.DEVNULL)
            return None
        print("  ✓ Your PC IP unchanged (PC protected)")
    
    # Check 2: VPN must be DIFFERENT (VPN working)
    if ip_before != "unknown" and vpn_ip != "unknown":
        if ip_before == vpn_ip:
            print("\n✗ CRITICAL: VPN IP = Your IP!")
            print("  VPN is NOT WORKING - same IP means no tunnel")
            subprocess.run(["docker", "rm", "-f", "aurora-vpn"], stderr=subprocess.DEVNULL)
            return None
        print("  ✓ ✓ ✓ VPN IP DIFFERENT - VPN IS WORKING!")
    
    # Return VPN IP on success (caller handles final setup messages)
    return vpn_ip

def start_vpn_if_requested(options):
    """Start VPN - ask user to choose Docker or Namespace"""
    if not options["start_vpn"]:
        return True

    vpn_dir = os.path.join(os.path.dirname(__file__), "ovpn")
    if not os.path.exists(vpn_dir):
        print("No VPN configs directory found.")
        return False
    
    configs = [f for f in os.listdir(vpn_dir) if f.endswith('.ovpn')]
    if not configs:
        print(f"No .ovpn files found in {vpn_dir}")
        return False
    
    config_file = configs[0]
    config_path = os.path.join(vpn_dir, config_file)
    
    # Get IP before VPN
    print("\n🔍 Checking your PUBLIC IP (before VPN)...")
    ip_before = check_public_ip()
    if ip_before:
        print(f"✓ Your public IP: {ip_before}")
    else:
        print("⚠ Could not check public IP")
        ip_before = "unknown"
    
    # Ask user to choose isolation method
    print("\n" + "=" * 50)
    print("VPN ISOLATION METHOD")
    print("=" * 50)
    print("\nChoose how to isolate the VPN:\n")
    print("1) DOCKER (recommended)")
    print("   • Simple, fast, reuses container/image")
    print("   • No data waste (same container each run)")
    print("   • Most reliable\n")
    print("2) NAMESPACE (advanced)")
    print("   • Network namespace isolation")
    print("   • More manual control")
    print("   • Uses veth pairs and routing\n")
    
    # Get user input with timeout
    choice = None
    try:
        choice = input("Choose method (1 or 2) [default: 1]: ").strip()
        if not choice:
            choice = "1"
    except:
        choice = "1"
    
    if choice not in ["1", "2"]:
        print("Invalid choice. Using Docker by default.")
        choice = "1"
    
    # Call appropriate setup
    if choice == "1":
        # Docker approach - try each config until one works
        print("\n🐳 Checking Docker installation and starting if needed...")
        if not check_docker_available():
            print("\n✗ Failed to install or start Docker.\n"
                  "Please check that:\n"
                  "  • You have sudo access\n"
                  "  • Your system supports Docker\n"
                  "Or manually start Docker: sudo systemctl start docker")
            return False
        
        # Try each VPN config in Docker until one works
        result = find_working_vpn_config_docker(vpn_dir, ip_before)
        if result:
            # Setup was successful, result is the VPN IP
            runtime_state["vpn_container"] = "aurora-vpn"
            runtime_state["vpn_running"] = True
            os.environ["AURORA_VPN_PROXY"] = "socks5://127.0.0.1:1080"
            
            print("\n" + "=" * 50)
            print("✓ VPN DOCKER SETUP COMPLETE!")
            print(f"  • Docker container: aurora-vpn (reused, no waste)")
            print(f"  • SOCKS5 proxy: socks5://127.0.0.1:1080")
            print("=" * 50)
            return True
        else:
            return False
    
    else:
        # Namespace approach
        print("\n🔐 VPN SETUP WITH NAMESPACE ISOLATION")
        print("=" * 50)
        
        # PREFLIGHT: Find working config
        print("\n🔍 PREFLIGHT: Testing VPN configs for working tunnel...")
        config_path = find_working_vpn_config(vpn_dir)
        if not config_path:
            print("\n✗ No working VPN configs available.")
            print("  Please test your VPN configs manually:")
            print("  $ sudo openvpn --config /path/to/file.ovpn")
            return False
        
        # STEP 1: Create isolated namespace
        print("\nSTEP 1: Creating isolated network namespace...")
        ns_name = setup_vpn_namespace()
        if not ns_name:
            print("✗ Failed to create namespace")
            return False
        
        # STEP 2: Start VPN in namespace
        print("\nSTEP 2: Starting VPN in isolated namespace...")
        if not start_vpn_in_namespace(ns_name, config_path):
            print("✗ Failed to start VPN in namespace")
            subprocess.run(["ip", "netns", "delete", ns_name], stderr=subprocess.DEVNULL)
            return False
        
        # STEP 3: Test VPN tunnel
        print("\nSTEP 3: Testing VPN tunnel (waiting up to 60 seconds for tunnel...)...")
        vpn_ip = None
        for attempt in range(12):
            print(f"  Attempt {attempt + 1}/12...", end='\r')
            result = subprocess.run(
                ["ip", "netns", "exec", ns_name, "curl", "-s", "--max-time", "15",
                 "https://api.ipify.org?format=json"],
                timeout=20,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                text=True
            )
            if result.returncode == 0:
                try:
                    import json
                    vpn_ip = json.loads(result.stdout).get('ip', 'unknown')
                    if vpn_ip != "unknown":
                        print(f"  ✓ Got VPN IP: {vpn_ip}    ")
                        break
                except:
                    pass
            time.sleep(5)
        
        if not vpn_ip or vpn_ip == "unknown":
            print("✗ CRITICAL: VPN tunnel NEVER ESTABLISHED!")
            print("  This config was tested manually but failed in namespace.")
            print("  Try a different VPN config.")
            subprocess.run(["ip", "netns", "delete", ns_name], stderr=subprocess.DEVNULL)
            return False
        
        # STEP 4: Start SOCKS5 proxy
        print("\nSTEP 4: Starting SOCKS5 proxy in namespace...")
        if not start_proxy_in_namespace(ns_name, proxy_port=1080):
            print("✗ Failed to start SOCKS5 proxy")
            subprocess.run(["ip", "netns", "delete", ns_name], stderr=subprocess.DEVNULL)
            return False
        
        # STEP 5: Verify your PC is PROTECTED
        print("\nSTEP 5: Verifying YOUR PC is PROTECTED...")
        ip_after = check_public_ip()
        if ip_after:
            print(f"✓ Your public IP: {ip_after}")
        else:
            print("⚠ Could not check")
            ip_after = "unknown"
        
        # STEP 6: Final comparison
        print("\nSTEP 6: FINAL VERIFICATION:")
        print(f"  Your PC before: {ip_before}")
        print(f"  Your PC after:  {ip_after}")
        print(f"  VPN in ns:      {vpn_ip}")
        
        # Check 1: PC must stay same
        if ip_before != "unknown" and ip_after != "unknown":
            if ip_before != ip_after:
                print("\n✗ CRITICAL: Your PC's IP CHANGED!")
                print("  Namespace isolation FAILED")
                subprocess.run(["ip", "netns", "delete", ns_name], stderr=subprocess.DEVNULL)
                return False
            print("  ✓ Your PC IP unchanged (PC protected)")
        
        # Check 2: VPN must be DIFFERENT
        if ip_before != "unknown" and vpn_ip != "unknown":
            if ip_before == vpn_ip:
                print("\n✗ CRITICAL: VPN IP = Your IP!")
                print("  VPN is NOT WORKING - same IP means no tunnel")
                subprocess.run(["ip", "netns", "delete", ns_name], stderr=subprocess.DEVNULL)
                return False
            print("  ✓ ✓ ✓ VPN IP DIFFERENT - VPN IS WORKING!")
        
        runtime_state["vpn_namespace"] = ns_name
        runtime_state["vpn_running"] = True
        os.environ["AURORA_VPN_PROXY"] = "socks5://192.168.100.2:1080"
        
        print("\n" + "=" * 50)
        print("✓ VPN NAMESPACE SETUP COMPLETE!")
        print(f"  • Your PC IP: {ip_after} (isolated)")
        print(f"  • VPN IP: {vpn_ip} (crawler uses)")
        print(f"  • SOCKS5: socks5://192.168.100.2:1080")
        print("=" * 50)
        
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
        # Set VPN SOCKS5 proxy environment variable if VPN is running
        if runtime_state.get("vpn_running"):
            os.environ["AURORA_VPN_PROXY"] = "socks5://192.168.100.2:1080"
        
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
    
    # Clean up Docker VPN container
    if runtime_state.get("vpn_container"):
        container_name = runtime_state["vpn_container"]
        print(f"\n🧹 Cleaning up VPN Docker container: {container_name}")
        
        result = subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10
        )
        
        if result.returncode == 0:
            print("✓ VPN Docker container cleaned up")
        else:
            print("⚠ Error cleaning up Docker container (may already be removed)")
    
    # Clean up old namespace-based VPN if exists (migration from old setup)
    if runtime_state.get("vpn_namespace"):
        ns_name = runtime_state["vpn_namespace"]
        print(f"\n🧹 Cleaning up legacy VPN namespace: {ns_name}")
        
        # Kill proxy process
        proxy_proc = runtime_state.get("proxy_process")
        if proxy_proc and proxy_proc.poll() is None:
            try:
                proxy_proc.terminate()
                proxy_proc.wait(timeout=2)
            except:
                pass
        
        # Kill VPN in namespace
        pid_file = f"/tmp/vpn-{ns_name}.pid"
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    pid = int(f.read().strip())
                os.kill(pid, 15)  # SIGTERM
            except:
                pass
        
        # Clean up iptables rules
        subprocess.run(["iptables", "-t", "nat", "-D", "POSTROUTING", "-j", "MASQUERADE"],
                       stderr=subprocess.DEVNULL)
        subprocess.run(["iptables", "-D", "FORWARD", "-i", "veth-host", "-j", "ACCEPT"],
                       stderr=subprocess.DEVNULL)
        subprocess.run(["iptables", "-D", "FORWARD", "-o", "veth-host", "-j", "ACCEPT"],
                       stderr=subprocess.DEVNULL)
        
        # Delete namespace 
        subprocess.run(["ip", "netns", "delete", ns_name], stderr=subprocess.DEVNULL)
        print("✓ Legacy VPN namespace cleaned up")
    
    # Kill simple VPN if it was started (legacy)
    if runtime_state.get("vpn_running") and not runtime_state.get("vpn_namespace"):
        if os.path.exists("/tmp/vpn.pid"):
            try:
                with open("/tmp/vpn.pid") as f:
                    pid = int(f.read().strip())
                os.kill(pid, 15)  # SIGTERM
            except:
                pass

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
