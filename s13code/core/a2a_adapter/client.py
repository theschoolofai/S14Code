"""A minimal A2A client suitable for a future live-graph remote-node adapter."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .schema import negotiate_interface
from .trust import AgentCardTrustPolicy


@dataclass(frozen=True)
class DiscoveredAgent:
    card: dict[str, Any]
    endpoint: str


class A2AClient:
    def __init__(self, http: httpx.AsyncClient, trust: AgentCardTrustPolicy, *,
                 protocol_versions: tuple[str, ...] = ("1.0",), auth_headers: dict[str, str] | None = None) -> None:
        self.http, self.trust = http, trust
        self.protocol_versions, self.auth_headers = protocol_versions, (auth_headers or {})

    async def discover(self, agent_base_url: str) -> DiscoveredAgent:
        response = await self.http.get(agent_base_url.rstrip("/") + "/.well-known/agent-card.json")
        response.raise_for_status()
        card = response.json()
        self.trust.verify(card)
        interface = negotiate_interface(card, bindings=("JSONRPC",), versions=self.protocol_versions)
        return DiscoveredAgent(card=card, endpoint=interface["url"])

    async def send(self, agent: DiscoveredAgent, text: str, *, push_url: str | None = None) -> dict[str, Any]:
        configuration: dict[str, Any] = {}
        if push_url:
            configuration["pushNotificationConfig"] = {"url": push_url}
        return await self._rpc(agent.endpoint, "message/send", self._message(text, configuration))

    async def cancel(self, agent: DiscoveredAgent, task_id: str) -> dict[str, Any]:
        return await self._rpc(agent.endpoint, "tasks/cancel", {"id": task_id})

    async def get(self, agent: DiscoveredAgent, task_id: str) -> dict[str, Any]:
        return await self._rpc(agent.endpoint, "tasks/get", {"id": task_id})

    async def stream(self, agent: DiscoveredAgent, text: str):
        request_id = str(uuid.uuid4())
        payload = {"jsonrpc": "2.0", "id": request_id, "method": "message/stream", "params": self._message(text, {})}
        async with self.http.stream("POST", agent.endpoint, json=payload, headers=self.auth_headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])["result"]

    async def _rpc(self, endpoint: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
        response = await self.http.post(endpoint, json=payload, headers=self.auth_headers)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(body["error"]["message"])
        return body["result"]

    @staticmethod
    def _message(text: str, configuration: dict[str, Any]) -> dict[str, Any]:
        return {"message": {"kind": "message", "messageId": str(uuid.uuid4()), "role": "user", "parts": [{"kind": "text", "text": text}]}, "configuration": configuration}
