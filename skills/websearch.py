"""
websearch — a shared, key-free web search helper (used by several skills).

This is a plain module (a *file*, not a skill folder) so the registry never
loads it as a skill; multiple skills import ``search`` from here — the same
pattern as ``skills/geolocation.py``.

It uses DuckDuckGo's free endpoints, which need no API key:

  1. Instant Answer API (``api.duckduckgo.com``) — great for definitions,
     facts, and "what is X" style questions; returns an abstract + related
     topics.
  2. HTML "lite" results (``html.duckduckgo.com/html``) — a fallback that
     yields ordinary result snippets when the Instant Answer is empty.

All network work is blocking ``urllib`` and is meant to be called from a skill
via ``asyncio.to_thread`` so the event loop is never blocked.
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("meryna.skills.websearch")

_INSTANT_URL = "https://api.duckduckgo.com/"
_HTML_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TIMEOUT = 8  # seconds per HTTP request


@dataclass
class SearchResult:
    """One search hit — a short title/snippet pair with an optional URL."""

    title: str
    snippet: str
    url: str = ""


@dataclass
class SearchResponse:
    """Aggregated search output.

    ``answer`` is DuckDuckGo's Instant Answer (a direct definition/fact) when
    one exists; ``results`` holds ordinary result snippets. Either may be empty.
    """

    query: str
    answer: str = ""
    results: List[SearchResult] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.answer and not self.results

    def as_text(self, max_results: int = 3) -> str:
        """Flatten into a compact, TTS-friendly block of text for the AI/user."""
        parts: List[str] = []
        if self.answer:
            parts.append(self.answer)
        for r in self.results[:max_results]:
            snippet = r.snippet or r.title
            if snippet:
                parts.append(snippet)
        return "\n".join(parts).strip()


def search(query: str, max_results: int = 5) -> SearchResponse:
    """Search the web for *query* (blocking). Never raises — returns empty
    :class:`SearchResponse` on any failure so callers can degrade gracefully."""
    query = (query or "").strip()
    if not query:
        return SearchResponse(query="")

    response = SearchResponse(query=query)

    # 1. Instant Answer API — direct facts/definitions.
    try:
        response.answer = _instant_answer(query)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Instant Answer lookup failed: %s", exc)

    # 2. HTML results — ordinary snippets (also fills related topics).
    try:
        response.results = _html_results(query, max_results)
    except Exception as exc:  # noqa: BLE001
        logger.debug("HTML results lookup failed: %s", exc)

    return response


# ----------------------------------------------------------------------
# Providers
# ----------------------------------------------------------------------

def _instant_answer(query: str) -> str:
    params = urllib.parse.urlencode(
        {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    )
    data = _get_json(f"{_INSTANT_URL}?{params}")
    if not data:
        return ""

    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        return abstract

    answer = (data.get("Answer") or "").strip()
    if answer:
        return answer

    definition = (data.get("Definition") or "").strip()
    if definition:
        return definition

    # Fall back to the first related topic's text, if present.
    for topic in data.get("RelatedTopics", []) or []:
        text = (topic.get("Text") or "").strip() if isinstance(topic, dict) else ""
        if text:
            return text
    return ""


def _html_results(query: str, max_results: int) -> List[SearchResult]:
    body = urllib.parse.urlencode({"q": query}).encode("utf-8")
    raw = _post(_HTML_URL, body)
    if not raw:
        return []

    results: List[SearchResult] = []
    # Result titles/links: <a class="result__a" href="...">Title</a>
    link_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    # Snippets: <a class="result__snippet" ...>text</a>
    snippet_re = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    links = link_re.findall(raw)
    snippets = snippet_re.findall(raw)

    for i, (url, title_html) in enumerate(links[:max_results]):
        title = _strip_tags(title_html)
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        if title:
            results.append(
                SearchResult(title=title, snippet=snippet, url=_clean_ddg_url(url))
            )
    return results


# ----------------------------------------------------------------------
# HTTP + parsing helpers
# ----------------------------------------------------------------------

def _get_json(url: str) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _post(url: str, body: bytes) -> str:
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment or "")
    return html.unescape(text).strip()


def _clean_ddg_url(url: str) -> str:
    """DuckDuckGo wraps result links as /l/?uddg=<encoded real url>."""
    if "uddg=" in url:
        try:
            qs = urllib.parse.urlparse(url).query
            uddg = urllib.parse.parse_qs(qs).get("uddg", [])
            if uddg:
                return urllib.parse.unquote(uddg[0])
        except Exception:  # noqa: BLE001
            pass
    if url.startswith("//"):
        return "https:" + url
    return url
