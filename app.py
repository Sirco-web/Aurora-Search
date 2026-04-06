import subprocess
import sys
import configparser
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# List of required packages
REQUIRED_PACKAGES = {
    'flask': 'flask',
    'flask_cors': 'flask-cors',
    'nltk': 'nltk',
    'requests': 'requests',
    'bs4': 'beautifulsoup4'
}

def install_dependencies():
    """Install missing dependencies with --break-system-packages flag"""
    missing_packages = []
    
    for module_name, package_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing_packages.append(package_name)
    
    if missing_packages:
        print(f"Installing missing packages: {', '.join(missing_packages)}")
        for package in missing_packages:
            try:
                subprocess.check_call([
                    sys.executable, '-m', 'pip', 'install',
                    '--break-system-packages', package
                ])
                print(f"✓ Successfully installed {package}")
            except subprocess.CalledProcessError as e:
                print(f"✗ Failed to install {package}: {e}")
                sys.exit(1)
    else:
        print("✓ All dependencies are already installed")

def load_config():
    """Load configuration from config.txt"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.txt')
    
    if os.path.exists(config_path):
        config.read(config_path)
        print(f"✓ Loaded config from {config_path}")
    else:
        print(f"⚠ Config file not found at {config_path}")
    
    return config

# Install dependencies before importing
install_dependencies()

from flask import Flask, request, jsonify, send_from_directory
import csv
import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
import ssl
from flask_cors import CORS
import os
import gzip
import json

# Load configuration
CONFIG = load_config()

# Initialize Flask app with static folder
app = Flask(__name__, static_folder='public', static_url_path='')

CORS(app)

# NLTK setup (handles SSL certificate issues)
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# Download NLTK data only if not already downloaded
def download_nltk_resources():
    try:
        stopwords.words('english')
    except LookupError:
        print("Downloading NLTK data...")
        nltk.download('stopwords')
    try:
        word_tokenize('test')
    except LookupError:
        nltk.download('punkt')

def run_crawler():
    """Auto-run the crawler to generate index files (parallel mode)"""
    print("\n📡 Starting web crawler to generate search index (PARALLEL MODE)...")
    print("All scripts running simultaneously like Google's indexing system...\n")
    try:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Run crawler asynchronously (all scripts in parallel)
        result = subprocess.run(
            [sys.executable, 'scripts/advanced_crawler.py'],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            # Print crawler output
            if result.stdout:
                print(result.stdout)
            print("✓ Crawler completed successfully!")
            return True
        else:
            print(f"✗ Crawler failed:")
            if result.stderr:
                print(result.stderr)
            return False
    except subprocess.TimeoutExpired:
        print("✗ Crawler timed out (exceeded 300 seconds)")
        return False
    except Exception as e:
        print(f"✗ Error running crawler: {e}")
        return False
        
# Initialize NLTK components
print("\n🔤 NLTK SETUP")
print("=" * 50)
download_nltk_resources()
stop_words = set(stopwords.words('english'))
ps = PorterStemmer()
print("✓ NLTK initialized")


def load_inverted_index(file_path):
    """Load compressed JSON inverted index"""
    inverted_index = {}
    try:
        with gzip.open(file_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
            for word, doc_ids in data.items():
                inverted_index[word] = set(doc_ids)
            print(f"   ✓ Loaded inverted index ({len(inverted_index)} words)")
    except FileNotFoundError:
        print(f"   ✗ File not found: {file_path}")
    except json.JSONDecodeError as e:
        print(f"   ✗ JSON decode error: {e}")
    except OSError as e:
        print(f"   ✗ File read error: {e}")
    return inverted_index

def load_document_info(file_path):
    """Load compressed JSON document info"""
    document_info = {}
    try:
        with gzip.open(file_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
            for doc_id, info in data.items():
                document_info[int(doc_id)] = {
                    'url': info['url'],
                    'title': info['title'],
                    'description': info['description'],
                    'pagerank': float(info.get('pagerank', 0))
                }
            print(f"   ✓ Loaded document info ({len(document_info)} documents)")
    except FileNotFoundError:
        print(f"   ✗ File not found: {file_path}")
    except json.JSONDecodeError as e:
        print(f"   ✗ JSON decode error: {e}")
    except OSError as e:
        print(f"   ✗ File read error: {e}")
    return document_info

def parse_query(query):
    # Tokenize the query
    tokens = word_tokenize(query.lower())
    # Remove non-alphabetic tokens and stop words, then stem the words
    query_words = [
        ps.stem(word) for word in tokens if word.isalpha() and word not in stop_words
    ]
    return query_words

def search(query, inverted_index, document_info, num_results=10, page=1):
    query_words = parse_query(query)
    if not query_words:
        return []
    # Find documents that contain any of the query words
    matched_doc_ids = set()
    for word in query_words:
        if word in inverted_index:
            matched_doc_ids.update(inverted_index[word])
    if not matched_doc_ids:
        return []
    # Retrieve documents and their PageRank scores
    results = []
    for doc_id in matched_doc_ids:
        info = document_info[doc_id]
        results.append({
            'doc_id': doc_id,
            'url': info['url'],
            'title': info['title'],
            'description': info['description'],
            'pagerank': info['pagerank']
        })
    # Sort documents by PageRank score 
    sorted_results = sorted(results, key=lambda x: x['pagerank'], reverse=True)
    # Pagination
    start = (page - 1) * num_results
    end = start + num_results
    paginated_results = sorted_results[start:end]
    return paginated_results

# Global index state (updated in background)
inverted_index = {}
document_info = {}
indexing_status = {
    'status': 'initializing',  # initializing, indexing, ready, error
    'progress': 0,
    'message': 'Starting up...',
    'docs_indexed': 0,
    'words_indexed': 0
}

# Get paths in /data directory
root_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(root_dir, 'data')

# Ensure data directory exists
os.makedirs(data_dir, exist_ok=True)

idx_file = os.path.join(data_dir, 'advanced_inverted_index.json.gz')
doc_file = os.path.join(data_dir, 'advanced_doc_info.json.gz')

# Auto-setup VPN and proxies on startup
def auto_setup_vpn():
    """Automatically download VPN configs and start VPN manager"""
    vpn_configs_dir = os.path.join(root_dir, 'data', 'vpn_configs')
    
    # Check if VPN configs exist
    if os.path.exists(vpn_configs_dir):
        configs = [f for f in os.listdir(vpn_configs_dir) if f.endswith('.ovpn')]
        if configs:
            print(f"\n✅ Found {len(configs)} VPN configs in {vpn_configs_dir}")
            # Try to start VPN manager
            try:
                print("🔐 Starting VPN Manager in background...")
                vpn_manager_path = os.path.join(root_dir, 'scripts', 'vpn-manager.py')
                subprocess.Popen(
                    [sys.executable, vpn_manager_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print("✅ VPN Manager started (runs in background)")
                time.sleep(10)  # Wait for VPNs to connect
                # Auto-configure proxies
                print("🔧 Auto-configuring proxies...")
                # Update config with VPN proxies (will auto-detect active ones)
                configure_openvpn_proxies()
                return True
            except Exception as e:
                print(f"⚠️  Could not start VPN Manager: {e}")
                return False
    else:
        print(f"\n📥 No VPN configs found. Attempting auto-download...")
        try:
            download_vpn_configs_script = os.path.join(root_dir, 'scripts', 'download-vpn-configs.py')
            print("🔐 Downloading OpenVPN configs from GitHub...")
            # Note: In production, this could be silent. For now, we'll notify user.
            print("   Run: python3 scripts/download-vpn-configs.py")
            print("   To download VPN configs for distributed crawling")
        except Exception as e:
            print(f"⚠️  Could not download VPN configs: {e}")
        return False

def configure_openvpn_proxies():
    """Auto-configure OpenVPN proxies in config.txt"""
    # Look for active VPN connections on localhost:1090+
    proxies = []
    for port in range(1090, 1110):  # Check ports 1090-1109
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                proxies.append(f'socks5://127.0.0.1:{port}')
        except:
            pass
    
    if proxies:
        print(f"✅ Detected {len(proxies)} active VPN connections")
        # Update config.txt
        update_config_proxies(proxies)
    else:
        print("⚠️  No active VPN connections detected on localhost:1090-1109")
        print("   Run: python3 scripts/vpn-manager.py (in separate terminal)")

def update_config_proxies(proxy_list):
    """Update config.txt with proxy list"""
    config_path = os.path.join(root_dir, 'config.txt')
    try:
        with open(config_path, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        in_proxy_section = False
        updated_proxy_list = False
        updated_use_proxy = False
        
        for line in lines:
            if line.strip().startswith('[Proxy]'):
                in_proxy_section = True
                new_lines.append(line)
            elif in_proxy_section and line.strip().startswith('proxy_list'):
                new_lines.append(f'proxy_list = {"".join(proxy_list)}\n')
                updated_proxy_list = True
            elif in_proxy_section and line.strip().startswith('use_proxy'):
                new_lines.append('use_proxy = true\n')
                updated_use_proxy = True
            elif in_proxy_section and line.strip().startswith('['):
                in_proxy_section = False
                new_lines.append(line)
            else:
                new_lines.append(line)
        
        with open(config_path, 'w') as f:
            f.writelines(new_lines)
        
        print(f"✅ Updated config.txt with {len(proxy_list)} VPN proxies")
    except Exception as e:
        print(f"⚠️  Could not update config: {e}")

def background_indexing():
    """Run crawler and indexing in background (non-blocking)"""
    global inverted_index, document_info, indexing_status
    
    print("\n⚙️ BACKGROUND INDEXING STARTED (NON-BLOCKING)")
    print("=" * 50)
    
    # Try to load existing indexes first
    if os.path.exists(idx_file) and os.path.exists(doc_file):
        print("Loading existing index files from cache...")
        inverted_index = load_inverted_index(idx_file)
        document_info = load_document_info(doc_file)
        if inverted_index and document_info:
            indexing_status['status'] = 'ready'
            indexing_status['docs_indexed'] = len(document_info)
            indexing_status['words_indexed'] = len(inverted_index)
            indexing_status['message'] = f"✓ Ready! {len(inverted_index)} words, {len(document_info)} documents"
            print(f"✓ Index loaded from cache: {indexing_status['message']}")
            return
    
    # No indexes found - run crawler
    indexing_status['status'] = 'indexing'
    indexing_status['message'] = 'Crawling and indexing (running in background)...'
    
    print("\n🤖 No indexes found - Starting crawler in BACKGROUND MODE")
    print("🚀 Server starting immediately - indexing happens live!\n")
    
    if run_crawler():
        # Crawler finished - reload indexes
        inverted_index = load_inverted_index(idx_file)
        document_info = load_document_info(doc_file)
        
        if inverted_index and document_info:
            indexing_status['status'] = 'ready'
            indexing_status['docs_indexed'] = len(document_info)
            indexing_status['words_indexed'] = len(inverted_index)
            indexing_status['message'] = f"✓ Ready! {len(inverted_index)} words, {len(document_info)} documents"
            print(f"\n✅ INDEXING COMPLETE: {indexing_status['message']}")
        else:
            indexing_status['status'] = 'error'
            indexing_status['message'] = 'Failed to load indexes after crawling'
            print(f"\n❌ {indexing_status['message']}")
    else:
        indexing_status['status'] = 'error'
        indexing_status['message'] = 'Crawler failed'
        print(f"\n❌ {indexing_status['message']}")

# Auto-setup VPN proxies if available
print("\n🔐 VPN SETUP")
print("=" * 50)
auto_setup_vpn()

# Start indexing in background thread immediately
indexing_thread = threading.Thread(target=background_indexing, daemon=True)
indexing_thread.start()
print("📚 Started background indexing thread...")

# Serve the main index.html
@app.route('/')
def serve_index():
    return send_from_directory('public', 'index.html')

# Serve search.html
@app.route('/search.html')
def serve_search():
    return send_from_directory('public', 'search.html')

@app.route('/search')
def search_api():
    global inverted_index, document_info, indexing_status
    
    query = request.args.get('q', '')
    num_results = int(request.args.get('num_results', 10))
    page = int(request.args.get('page', 1))
    
    # Log search request
    print(f"\n🔍 SEARCH REQUEST: '{query}' (page {page})")
    
    if not query:
        print(f"   ✗ Empty query")
        return jsonify({'error': 'No query provided'}), 400
    
    # Check if indexing is complete
    if indexing_status['status'] != 'ready':
        print(f"   ⏳ Indexing in progress...")
        return jsonify({
            'error': 'Search index not ready yet',
            'message': indexing_status['message'],
            'status': indexing_status['status'],
            'docs_indexed': indexing_status['docs_indexed'],
            'words_indexed': indexing_status['words_indexed'],
            'query': query,
            'results': []
        }), 202  # 202 = Accepted (processing)
    
    # Perform search
    if not inverted_index or not document_info:
        print(f"   ✗ Index not available")
        return jsonify({
            'error': 'Search index not available',
            'query': query,
            'results': []
        }), 503
    
    print(f"   Searching {len(inverted_index)} words, {len(document_info)} documents")
    results = search(query, inverted_index, document_info, num_results=num_results, page=page)
    print(f"   ✓ Found {len(results)} results")
    
    return jsonify({
        'query': query,
        'page': page,
        'num_results': num_results,
        'results': results
    })

@app.route('/status')
def status_api():
    """Get current indexing status (live progress)"""
    return jsonify(indexing_status)

if __name__ == '__main__':
    # Get server settings from config
    try:
        host = CONFIG.get('Server', 'host', fallback='0.0.0.0')
        port = CONFIG.getint('Server', 'port', fallback=5000)
        debug = CONFIG.getboolean('Server', 'debug', fallback=True)
    except:
        host = '0.0.0.0'
        port = 5000
        debug = True
    
    print(f"\n" + "="*50)
    print(f"🚀 AURORA SEARCH SERVER - PARALLEL MODE")
    print(f"="*50)
    print(f"   🌐 URL: http://localhost:{port}")
    print(f"   📡 Host: {host}:{port}")
    print(f"   🔧 Debug: {debug}")
    print(f"   ⏳ Status API: http://localhost:{port}/status")
    print(f"\n⚡ Server LIVE with background indexing...")
    print(f"   🤖 Crawler running in BACKGROUND")
    print(f"   🔄 Everything parallel (like Google!)")
    print(f"   📊 Check /status endpoint to see progress")
    print(f"="*50 + "\n")
    
    app.run(host=host, port=port, debug=debug)