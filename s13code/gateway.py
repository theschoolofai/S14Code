"""The only S13Code → GLC seam: ordinary authenticated HTTP."""
from __future__ import annotations

import os
from typing import Any

import httpx


def gateway_headers() -> dict[str, str]:
    """The bearer this service uses to identify itself to ``glc_v3``.

    On a laptop both processes sit on loopback and no token is needed, so an
    unset ``GLC_AUTH_TOKEN`` yields no header and nothing changes. Once the
    gateway is deployed the situation inverts: ``/v1/chat`` spends real provider
    quota, and an unauthenticated public URL is an open proxy to whoever finds
    it. This token is what makes the deployed seam closed.

    Note what it is not. It is a shared secret between two of our own services,
    never a provider credential — ``glc_v3`` still owns every provider key, and
    S14Code still cannot talk to a model without going through it.
    """
    token = os.getenv("GLC_AUTH_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


class GatewayClient:
    def __init__(self, base_url: str | None = None, *, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = (base_url or os.getenv("GLC_BASE_URL", "http://127.0.0.1:8111")).rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=120)
        self._owns_client = client is None

    async def complete(self, prompt: str, system: str, *, session: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "system": system,
            "max_tokens": 700,
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
        response = await self._client.post(f"{self.base_url}/v1/chat", json=payload,
                                           headers=gateway_headers())
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
