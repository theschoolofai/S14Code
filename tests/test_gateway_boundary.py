from __future__ import annotations

import json

import httpx
import pytest

from s13code.gateway import GatewayClient


@pytest.mark.asyncio
async def test_s13code_calls_gateway_without_owning_provider_keys(monkeypatch):
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"text": "done", "provider": "gemini_2", "model": "gemini"})

    monkeypatch.setenv("S13_GATEWAY_PROVIDER", "gemini")
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        result = await GatewayClient("http://127.0.0.1:8111", client=http).complete(
            "Investigate the papers", "Use evidence", session="proof-run"
        )

    assert captured["url"] == "http://127.0.0.1:8111/v1/chat"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["provider"] == "gemini"
    assert payload["agent"] == "s13_answer"
    assert payload["session"] == "proof-run"
    assert not any("key" in field.lower() or "secret" in field.lower() for field in payload)
    assert result["provider"] == "gemini_2"


def test_s13code_does_not_reimplement_gateway_routes(app_client):
    assert app_client.post("/v1/chat", json={}).status_code == 404
    assert app_client.get("/v1/providers").status_code == 404


def test_bare_hostport_gets_a_scheme_added(monkeypatch):
    """Render's fromService hostport resolves to "host:port" with no scheme --
    httpx raises UnsupportedProtocol on that. Regression for the deployed
    runtime hitting the gateway with GLC_BASE_URL=glc-gateway:10000."""
    monkeypatch.setenv("GLC_BASE_URL", "glc-gateway:10000")
    assert GatewayClient().base_url == "http://glc-gateway:10000"


def test_a_url_that_already_has_a_scheme_is_untouched(monkeypatch):
    monkeypatch.setenv("GLC_BASE_URL", "https://glc-gateway.onrender.com/")
    assert GatewayClient().base_url == "https://glc-gateway.onrender.com"
