"""
Web collection utilities for the local collector script.

Optional dependencies (gracefully degraded when absent):
  - requests       : faster HTTP with connection pooling
  - trafilatura    : article body extraction (recommended)
  - beautifulsoup4 : HTML parsing fallback
  - duckduckgo-search : zero-config web search library

Search backend priority (search_web):
  1. SerpAPI          (env: SERPAPI_KEY)
  2. Bing Search API  (env: BING_API_KEY)
  3. Google CSE       (env: GOOGLE_API_KEY + GOOGLE_CSE_ID)
  4. duckduckgo-search library  (if installed)
  5. DuckDuckGo HTML scraping   (stdlib-only fallback)
"""
from __future__ import annotations

import html
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_UA = (
    "Mozilla/5.0 (compatible; DatasetSkill/1.0; "
    "+https://github.com/Bhanunamikaze/ai-dataset-generator)"
)
_DEFAULT_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Optional dependency flags
# ---------------------------------------------------------------------------

try:
    import requests as _requests  # type: ignore[import]
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import trafilatura as _trafilatura  # type: ignore[import]
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    from bs4 import BeautifulSoup as _BS4  # type: ignore[import]
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from ddgs import DDGS as _DDGS  # type: ignore[import]
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS as _DDGS  # type: ignore[import]
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False
        _DDGS = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WebPage:
    url: str
    status: int
    content_type: str
    html_content: str
    error: str | None = None


@dataclass
class ExtractedContent:
    url: str
    title: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class LocalFile:
    path: str
    content: str
    extension: str


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch_url(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    max_bytes: int = 2_000_000,
    allowed_content_types: tuple[str, ...] = ("text/html", "application/xhtml+xml", "text/plain"),
) -> WebPage:
    """Fetch a URL and return its raw HTML content.

    Uses ``requests`` if available, falls back to ``urllib``.
    """
    headers = {"User-Agent": _DEFAULT_UA}

    if HAS_REQUESTS:
        try:
            resp = _requests.get(
                url, headers=headers, timeout=timeout, allow_redirects=True, stream=True
            )
            ct = resp.headers.get("content-type", "")
            ct_base = ct.split(";")[0].strip()
            if allowed_content_types and not any(ct.startswith(prefix) for prefix in allowed_content_types):
                return WebPage(
                    url=str(resp.url),
                    status=resp.status_code,
                    content_type=ct,
                    html_content="",
                    error=f"disallowed content-type: {ct_base}",
                )
            chunks: list[bytes] = []
            total = 0
            truncated = False
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    total += len(chunk)
                    chunks.append(chunk)
                    if total > max_bytes:
                        truncated = True
                        break
            raw_bytes = b"".join(chunks)
            text = raw_bytes.decode("utf-8", errors="replace")
            error: str | None = "max_bytes exceeded" if truncated else None
            return WebPage(
                url=str(resp.url),
                status=resp.status_code,
                content_type=ct,
                html_content=text,
                error=error,
            )
        except Exception as exc:
            return WebPage(url=url, status=0, content_type="", html_content="", error=str(exc))

    # stdlib fallback
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("content-type", "")
            ct_base = content_type.split(";")[0].strip()
            if allowed_content_types and not any(content_type.startswith(prefix) for prefix in allowed_content_types):
                return WebPage(
                    url=url,
                    status=resp.status,
                    content_type=content_type,
                    html_content="",
                    error=f"disallowed content-type: {ct_base}",
                )
            raw = resp.read(max_bytes + 1)
            truncated = len(raw) > max_bytes
            if truncated:
                raw = raw[:max_bytes]
            encoding = "utf-8"
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            try:
                text = raw.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = raw.decode("utf-8", errors="replace")
            return WebPage(
                url=url,
                status=resp.status,
                content_type=content_type,
                html_content=text,
                error="max_bytes exceeded" if truncated else None,
            )
    except Exception as exc:
        return WebPage(url=url, status=0, content_type="", html_content="", error=str(exc))


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(html_content: str, url: str = "") -> ExtractedContent:
    """Extract meaningful text from raw HTML.

    Priority:
      1. trafilatura  (best for article bodies)
      2. BeautifulSoup (structural fallback)
      3. regex strip  (last resort / stdlib only)
    """
    title = ""
    text = ""

    # 1. trafilatura
    if HAS_TRAFILATURA and html_content:
        extracted = _trafilatura.extract(
            html_content,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            url=url or None,
        )
        if extracted:
            text = extracted.strip()
        meta = _trafilatura.extract_metadata(html_content, default_url=url or None)
        if meta:
            title = meta.title or ""

    # 2. BeautifulSoup
    if not text and HAS_BS4 and html_content:
        soup = _BS4(html_content, "html.parser")
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

    # 3. Regex strip (stdlib only)
    if not text and html_content:
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if not title:
            m = re.search(r"<title[^>]*>([^<]+)</title>", html_content, re.IGNORECASE)
            if m:
                title = html.unescape(m.group(1)).strip()

    return ExtractedContent(url=url, title=title or url, text=text)


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------

def _search_serpapi(query: str, max_results: int) -> list[SearchResult]:
    """SerpAPI backend (env: SERPAPI_KEY + requests)."""
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key or not HAS_REQUESTS:
        return []
    try:
        resp = _requests.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": api_key, "num": max_results, "engine": "google"},
            timeout=15,
        )
        data = resp.json()
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
            for item in data.get("organic_results", [])[:max_results]
        ]
    except Exception:
        return []


def _search_bing(query: str, max_results: int) -> list[SearchResult]:
    """Bing Search API backend (env: BING_API_KEY + requests)."""
    api_key = os.environ.get("BING_API_KEY", "")
    if not api_key or not HAS_REQUESTS:
        return []
    try:
        resp = _requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={"q": query, "count": max_results},
            timeout=15,
        )
        data = resp.json()
        return [
            SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
            )
            for item in data.get("webPages", {}).get("value", [])[:max_results]
        ]
    except Exception:
        return []


def _search_google_cse(query: str, max_results: int) -> list[SearchResult]:
    """Google Custom Search backend (env: GOOGLE_API_KEY + GOOGLE_CSE_ID + requests)."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    cse_id = os.environ.get("GOOGLE_CSE_ID", "")
    if not api_key or not cse_id or not HAS_REQUESTS:
        return []
    try:
        resp = _requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"q": query, "key": api_key, "cx": cse_id, "num": min(max_results, 10)},
            timeout=15,
        )
        data = resp.json()
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
            for item in data.get("items", [])[:max_results]
        ]
    except Exception:
        return []


def _search_duckduckgo_lib(query: str, max_results: int) -> list[SearchResult]:
    """duckduckgo-search library backend (zero-config, optional dep)."""
    if not HAS_DDGS:
        return []
    try:
        with _DDGS() as ddgs:
            raw = ddgs.text(query, max_results=max_results)
            return [
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    snippet=item.get("body", ""),
                )
                for item in (raw or [])
            ]
    except Exception:
        return []


def _search_duckduckgo_html(query: str, max_results: int) -> list[SearchResult]:
    """Stdlib-only DuckDuckGo HTML scraping — final fallback, no deps required."""
    encoded = urllib.parse.urlencode({"q": query, "kl": "us-en"})
    url = f"https://html.duckduckgo.com/html/?{encoded}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _DEFAULT_UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    results: list[SearchResult] = []

    if HAS_BS4:
        soup = _BS4(raw_html, "html.parser")
        for div in soup.select(".result")[:max_results]:
            a = div.select_one(".result__title a")
            snip = div.select_one(".result__snippet")
            if not a:
                continue
            raw_href = a.get("href", "")
            href = str(raw_href[0]) if isinstance(raw_href, list) else str(raw_href)
            if "uddg=" in href:
                try:
                    href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                except Exception:
                    pass
            results.append(
                SearchResult(
                    title=str(a.get_text(strip=True)),
                    url=str(href),
                    snippet=str(snip.get_text(strip=True)) if snip else "",
                )
            )
    else:
        # Pure regex — no deps
        pattern = re.compile(
            r'class="result__title">.*?<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
            r'.*?class="result__snippet">([^<]*)',
            re.DOTALL,
        )
        for m in pattern.finditer(raw_html):
            href = m.group(1)
            if "uddg=" in href:
                try:
                    href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                except Exception:
                    pass
            results.append(
                SearchResult(
                    title=html.unescape(m.group(2)).strip(),
                    url=href,
                    snippet=html.unescape(m.group(3)).strip(),
                )
            )
            if len(results) >= max_results:
                break

    return results


def search_web(
    query: str,
    *,
    max_results: int = 10,
    rate_limit_seconds: float = 1.0,
) -> list[SearchResult]:
    """Search the web using the first available backend.

    Priority order:
      1. SerpAPI          (SERPAPI_KEY env var)
      2. Bing Search API  (BING_API_KEY env var)
      3. Google CSE       (GOOGLE_API_KEY + GOOGLE_CSE_ID env vars)
      4. duckduckgo-search library (if installed; pip install duckduckgo-search)
      5. DuckDuckGo HTML scraping (stdlib only, always available)

    Note: In the agentic skill workflow, the host IDE's native search tools are
    preferred (see sub-skills/local-collector.md). This function is the fallback
    used when the script is invoked directly or the IDE search is unavailable.
    """
    for backend in (
        _search_serpapi,
        _search_bing,
        _search_google_cse,
        _search_duckduckgo_lib,
        _search_duckduckgo_html,
    ):
        results = backend(query, max_results)
        if results:
            time.sleep(rate_limit_seconds)
            return results

    return []


# ---------------------------------------------------------------------------
# Local file utilities
# ---------------------------------------------------------------------------

def read_local_file(path: str | Path) -> str:
    """Read a local file, trying UTF-8 encodings before falling back."""
    file_path = Path(path)
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return file_path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return file_path.read_text(encoding="utf-8", errors="replace")


_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".txt", ".rst", ".py", ".js", ".ts", ".java", ".go", ".rb",
    ".rs", ".c", ".cpp", ".h", ".cs", ".sh", ".bash", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".json", ".html", ".xml", ".sql",
})

_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
})


def walk_repo(
    root: str | Path,
    *,
    extensions: set[str] | None = None,
    max_files: int = 200,
    skip_dirs: set[str] | None = None,
) -> list[LocalFile]:
    """Walk a directory tree and return text file contents."""
    root_path = Path(root)
    allowed = extensions or _TEXT_EXTENSIONS
    allowed = frozenset(e if e.startswith(".") else f".{e}" for e in allowed)
    skip = skip_dirs or _SKIP_DIRS

    files: list[LocalFile] = []
    for file_path in sorted(root_path.rglob("*")):
        if not file_path.is_file():
            continue
        if any(part in skip for part in file_path.parts):
            continue
        if file_path.suffix.lower() not in allowed:
            continue
        try:
            content = read_local_file(file_path)
            files.append(LocalFile(
                path=str(file_path),
                content=content,
                extension=file_path.suffix.lower(),
            ))
        except Exception:
            continue
        if len(files) >= max_files:
            break

    return files


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    *,
    max_chars: int = 3000,
    overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph boundaries.

    Args:
        text: Source text to split.
        max_chars: Maximum characters per chunk.
        overlap: Approximate character overlap between consecutive chunks.

    Returns:
        List of text chunks, each at most ``max_chars`` characters.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len + 2 > max_chars and current:
            chunks.append("\n\n".join(current))
            # Carry over last paragraph(s) that fit within overlap budget
            carry: list[str] = []
            carry_len = 0
            for p in reversed(current):
                if carry_len + len(p) <= overlap:
                    carry.insert(0, p)
                    carry_len += len(p)
                else:
                    break
            current = carry
            current_len = carry_len

        current.append(para)
        current_len += para_len + 2

    if current:
        chunks.append("\n\n".join(current))

    # Second pass: split any chunk still over limit by sentences
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final.append(chunk)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", chunk)
        sub: list[str] = []
        sub_len = 0
        for sent in sentences:
            if sub_len + len(sent) > max_chars and sub:
                final.append(" ".join(sub))
                sub = [sent]
                sub_len = len(sent)
            else:
                sub.append(sent)
                sub_len += len(sent) + 1
        if sub:
            final.append(" ".join(sub))

    return [c for c in final if c.strip()]


# ---------------------------------------------------------------------------
# Research-module helpers
# ---------------------------------------------------------------------------

def is_url_fetchable(url: str, *, allow_private_network: bool = False) -> bool:
    """Return whether a URL is safe for default research fetching."""
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if allow_private_network:
        return True
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return False
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False
    except ValueError:
        pass
    return True


class RateLimiter:
    """Per-domain rate limiter. Thread-safe within a single process."""

    def __init__(self, per_domain_seconds: float = 1.0) -> None:
        self._per_domain_seconds = per_domain_seconds
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        if self._per_domain_seconds <= 0:
            return
        host = urllib.parse.urlsplit(str(url or "")).hostname or ""
        now = time.monotonic()
        last = self._last.get(host, 0.0)
        gap = now - last
        if gap < self._per_domain_seconds:
            time.sleep(self._per_domain_seconds - gap)
        self._last[host] = time.monotonic()


def search_web_all_backends(
    query: str,
    *,
    max_results: int = 10,
    rate_limit_seconds: float = 1.0,
) -> list[SearchResult]:
    """Search all available backends and deduplicate results by URL.

    Unlike search_web(), this does not stop at the first backend. It is intended
    for research/evidence collection where domain diversity matters more than a
    single fallback chain result.
    """
    all_results: list[SearchResult] = []
    for backend in (
        _search_serpapi,
        _search_bing,
        _search_google_cse,
        _search_duckduckgo_lib,
        _search_duckduckgo_html,
    ):
        try:
            results = backend(query, max_results)
        except Exception:
            results = []
        if results:
            all_results.extend(results)
            time.sleep(rate_limit_seconds)

    seen: set[str] = set()
    unique: list[SearchResult] = []
    for result in all_results:
        url = str(result.url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(result)
        if len(unique) >= max_results:
            break
    return unique
