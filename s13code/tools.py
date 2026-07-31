"""Small, inspectable non-browser skills used by the S13 live graph."""
from __future__ import annotations

import html
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.parts: list[str] = []; self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}: self.skip += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr"}: self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip: self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip(): self.parts.append(data.strip() + " ")

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", value)).strip()


def sandbox_path(path: str) -> Path:
    configured = os.getenv("S13_SANDBOX_ROOT")
    if not configured:
        raise PermissionError("local file skills require S13_SANDBOX_ROOT")
    root = Path(configured).expanduser().resolve()
    candidate = (root / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise PermissionError(f"path escapes S13_SANDBOX_ROOT: {path}")
    if not candidate.is_file():
        raise FileNotFoundError(path)
    return candidate


def sandbox_files(path: str, *, suffix: str = ".md") -> list[Path]:
    """Enumerate a sandbox directory without granting arbitrary traversal."""
    configured = os.getenv("S13_SANDBOX_ROOT")
    if not configured:
        raise PermissionError("local file skills require S13_SANDBOX_ROOT")
    root = Path(configured).expanduser().resolve()
    candidate = (root / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise PermissionError(f"path escapes S13_SANDBOX_ROOT: {path}")
    if not candidate.is_dir():
        raise NotADirectoryError(path)
    return sorted(item for item in candidate.iterdir() if item.is_file() and item.suffix.lower() == suffix.lower())


async def fetch_url(url: str, *, max_chars: int = 60_000) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("fetch_url permits only http(s)")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "GLC-S13/0.3 educational-agent"}) as client:
        response = await client.get(url)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        parser = _TextExtractor(); parser.feed(response.text); text = parser.text()
    else:
        text = response.text
    return {"url": str(response.url), "status": response.status_code,
            "content_type": content_type, "text": text[:max_chars], "truncated": len(text) > max_chars}


class _DDGParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.hits: list[dict] = []; self.current: dict | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs); classes = values.get("class", "")
        if tag == "a" and "result__a" in classes:
            href = values.get("href", "")
            target = parse_qs(urlparse(href).query).get("uddg", [href])[0]
            self.current = {"title": "", "url": unquote(target), "snippet": ""}; self.hits.append(self.current)
        elif tag in {"a", "div"} and "result__snippet" in classes and self.hits:
            self.current = self.hits[-1]

    def handle_data(self, data):
        if self.current and data.strip():
            key = "title" if not self.current["title"] else "snippet"
            self.current[key] = (self.current[key] + " " + data.strip()).strip()


async def _tavily_search(query: str, max_results: int, api_key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.tavily.com/search",
                                     headers={"Authorization": f"Bearer {api_key}"},
                                     json={"query": query, "max_results": max_results})
        response.raise_for_status()
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in response.json().get("results", [])]


async def _duckduckgo_search(query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 GLC-S13"}) as client:
        response = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
        response.raise_for_status()
    parser = _DDGParser(); parser.feed(response.text)
    return [hit for hit in parser.hits if hit["url"]]


async def web_search(query: str, *, max_results: int = 5) -> dict:
    """DuckDuckGo's scraping endpoint needs no key but is unreachable from some
    cloud egress ranges (Render's among them: a ConnectTimeout, not even a
    4xx -- an IP-range block, not a code bug). TAVILY_API_KEY opts into a real
    search API instead; unset, behavior is exactly what it always was."""
    max_results = max(1, min(max_results, 5))
    api_key = os.getenv("TAVILY_API_KEY")
    hits = await (_tavily_search(query, max_results, api_key) if api_key
                  else _duckduckgo_search(query))
    return {"query": query, "hits": hits[:max_results]}
