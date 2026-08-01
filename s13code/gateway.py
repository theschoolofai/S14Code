"""The only S13Code → GLC seam: ordinary authenticated HTTP."""
from __future__ import annotations

import os
from typing import Any

import httpx


class GatewayClient:
    def __init__(self, base_url: str | None = None, *, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = (base_url or os.getenv("GLC_BASE_URL", "http://127.0.0.1:8111")).rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=120)
        self._owns_client = client is None

    async def complete(self, prompt: str, system: str, *, session: str | None = None) -> dict[str, Any]:
        # ``max_tokens`` is a budget for EVERYTHING the provider generates, and on a
        # thinking-capable model (gemini-2.5-flash) the reasoning tokens are drawn
        # from it first. Asking for "reasoning": "off" does not change that: the
        # gateway simply omits thinkingConfig, which leaves Gemini on its DEFAULT
        # dynamic thinking budget. At 700 the model spent nearly all of it thinking
        # and returned ~120 characters, so the content role's JSON came back
        # truncated and unparseable. The ceiling is therefore configurable, with a
        # default that leaves room for a structured answer after the thinking.
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "system": system,
            "max_tokens": int(os.getenv("S13_MAX_TOKENS", "4000")),
            "temperature": 0,
            "reasoning": "off",
            "agent": "s13_answer",
            "session": session,
        }
        # "gemini" is a logical gateway provider. GLC expands it to the
        # independently metered gemini_1..N key pool; S13Code never sees keys.
        # Default to gemini so an unset env never falls through to the gateway's
        # default provider order (which may put a heavy local model first).
        payload["provider"] = os.getenv("S13_GATEWAY_PROVIDER", "gemini")
        response = await self._client.post(f"{self.base_url}/v1/chat", json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"GLC /v1/chat returned {response.status_code}: {response.text[:500]}")
        body = response.json()
        return {"text": body.get("text", ""), "provider": body.get("provider"), "model": body.get("model")}

    async def health(self) -> dict[str, Any]:
        response = await self._client.get(f"{self.base_url}/healthz", timeout=3)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
