"""web_search has two backends: DuckDuckGo scraping (default, no key) and
Tavily (opt-in via TAVILY_API_KEY). Added when DuckDuckGo's scraping endpoint
turned out to be unreachable -- ConnectTimeout, not a 4xx -- from Render's
egress network, killing every research/comparison turn in production."""
from __future__ import annotations

import json

import httpx
import pytest

import s13code.tools as tools_module
from s13code.tools import web_search


def _patch_transport(monkeypatch, handler):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(tools_module.httpx, "AsyncClient",
                        lambda *a, **kw: real_client(*a, transport=transport, **kw))


@pytest.mark.asyncio
async def test_default_still_uses_duckduckgo_with_no_key_set(monkeypatch):
    """Local behavior must not change: no TAVILY_API_KEY, no surprise."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=(
            '<div class="result"><a class="result__a" href="https://example.test/a">Example</a>'
            '<a class="result__snippet">a snippet</a></div>'
        ))

    _patch_transport(monkeypatch, handler)
    result = await web_search("solar vs wind")
    assert captured["url"].startswith("https://html.duckduckgo.com/html/")


@pytest.mark.asyncio
async def test_tavily_used_when_key_is_set(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [
            {"title": "Solar output 2024", "url": "https://source.test/solar", "content": "grid-scale solar grew"},
        ]})

    _patch_transport(monkeypatch, handler)
    result = await web_search("solar vs wind", max_results=3)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["auth"] == "Bearer tvly-test-key"
    assert captured["body"] == {"query": "solar vs wind", "max_results": 3}
    assert result == {"query": "solar vs wind", "hits": [
        {"title": "Solar output 2024", "url": "https://source.test/solar", "snippet": "grid-scale solar grew"},
    ]}


@pytest.mark.asyncio
async def test_tavily_results_are_capped_at_max_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"title": f"result {i}", "url": f"https://source.test/{i}", "content": "x"} for i in range(5)
        ]})

    _patch_transport(monkeypatch, handler)
    result = await web_search("broad query", max_results=2)
    assert len(result["hits"]) == 2
