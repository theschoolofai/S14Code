from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class MemoryKind(StrEnum):
    WORKING = "working"
    EPISODE = "episode"
    FACT = "fact"
    PLAYBOOK = "playbook"
    POLICY = "policy"
    AUDIT = "audit"
    DOCUMENT_CHUNK = "document_chunk"


@dataclass(frozen=True)
class MemoryScope:
    """The complete ownership path. Missing lower levels mean broader scope."""
    tenant_id: str
    project_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class Principal:
    """Identity of the caller, not an LLM-supplied string in a prompt."""
    id: str
    role: str  # agent, gateway, operator, system


@dataclass(frozen=True)
class SourceRef:
    uri: str
    author: str
    captured_at: str = field(default_factory=utcnow)
    excerpt: str | None = None


@dataclass
class MemoryRecord:
    kind: MemoryKind
    scope: MemoryScope
    text: str
    sources: list[SourceRef]
    principal: Principal
    metadata: dict[str, Any] = field(default_factory=dict)
    valid_from: str = field(default_factory=utcnow)
    valid_to: str | None = None
    confidence: float | None = None
    id: str = field(default_factory=lambda: f"mem_{uuid4().hex}")
    created_at: str = field(default_factory=utcnow)
    status: str = "current"  # current, superseded, expired
    supersedes_id: str | None = None

