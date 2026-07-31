"""The only S13Code → GLC seam: ordinary authenticated HTTP."""
from __future__ import annotations

import os
from typing import Any

import httpx


class GatewayClient:
    def __init__(self, base_url: str | None = None, *, client: httpx.AsyncClient | None = None) -> None:
        resolved = (base_url or os.getenv("GLC_BASE_URL", "http://127.0.0.1:8111")).rstrip("/")
        # Render's `fromService: {property: hostport}` resolves to a bare
        # "host:port" for its internal private network, with no scheme --
        # httpx rejects that outright (UnsupportedProtocol). A value that
        # already carries a scheme (the default, or any manually-set URL) is
        # untouched; only a bare host:port gets one added.
        if not resolved.startswith(("http://", "https://")):
            resolved = f"http://{resolved}"
        self.base_url = resolved
        self._client = client or httpx.AsyncClient(timeout=120)
        self._owns_client = client is None

    async def complete(self, prompt: str, system: str, *, session: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "system": system,
            # 700 truncated any answer that had to cover several subjects: a
            # three-way database comparison ran out mid-sentence and the THIRD
            # entity vanished from the summary entirely, so the composed
            # interface silently dropped a third of what the user asked about.
            # Env-overridable rather than a new hardcoded number.
            "max_tokens": int(os.getenv("S13_MAX_TOKENS", "2000")),
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
