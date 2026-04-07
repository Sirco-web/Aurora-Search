import ssl
import threading
import hashlib

import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    _create_unverified_https_context = None
else:
    ssl._create_default_https_context = _create_unverified_https_context

_nltk_lock = threading.Lock()
_nltk_ready = False
_stop_words = None
_stemmer = PorterStemmer()


def ensure_nltk_resources():
    """Download and cache NLTK resources once for all indexing work."""
    global _nltk_ready, _stop_words

    if _nltk_ready:
        return

    with _nltk_lock:
        if _nltk_ready:
            return

        try:
            stopwords.words("english")
        except LookupError:
            nltk.download("stopwords", quiet=True)

        try:
            word_tokenize("test")
        except LookupError:
            nltk.download("punkt", quiet=True)
            try:
                word_tokenize("test")
            except LookupError:
                nltk.download("punkt_tab", quiet=True)

        _stop_words = set(stopwords.words("english"))
        _nltk_ready = True


def index_page(webpage, webpage_url):
    ensure_nltk_resources()

    title_tag = webpage.find("title")
    title = title_tag.get_text().strip() if title_tag else "No Title"

    meta_description = webpage.find("meta", attrs={"name": "description"})
    og_description = webpage.find("meta", attrs={"property": "og:description"})
    if meta_description and "content" in meta_description.attrs:
        description = meta_description["content"]
    elif og_description and "content" in og_description.attrs:
        description = og_description["content"]
    else:
        text_content = webpage.get_text(separator=" ", strip=True)
        description = text_content[:200] + "..." if len(text_content) > 200 else text_content

    text_content = webpage.get_text(separator=" ", strip=True)
    
    # Store full content (up to 100KB to avoid huge files)
    # Truncate to keep file sizes manageable
    max_content_chars = 100000
    full_content = text_content[:max_content_chars]
    
    # Word count from ORIGINAL text before stemming
    original_word_count = len(text_content.split())
    
    tokens = word_tokenize(text_content.lower())
    filtered_words = [
        _stemmer.stem(word)
        for word in tokens
        if word.isalpha() and word not in _stop_words
    ]

    return {
        "url": webpage_url,
        "title": title,
        "description": description,
        "content": full_content,              # NEW: Store full content for Panda/Penguin scoring
        "words": filtered_words,              # Stemmed words for inverted index
        "word_count": original_word_count,    # NEW: Actual word count for Panda
        "content_fingerprint": hashlib.sha1(text_content.encode("utf-8", errors="ignore")).hexdigest(),
    }
