"""Official A2A 1.x Agent Card validation and interface negotiation."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict, ParseError
from google.protobuf.message import DecodeError


class AgentCardError(ValueError):
    pass


def validate_agent_card(card: dict[str, Any]) -> AgentCard:
    """Validate JSON with the official Linux Foundation A2A SDK type."""
    try:
        parsed = ParseDict(card, AgentCard(), ignore_unknown_fields=False)
    except (DecodeError, ParseError, TypeError, ValueError) as error:
        raise AgentCardError(f"Invalid A2A 1.x Agent Card: {error}") from error
    if not parsed.name or not parsed.description or not parsed.version:
        raise AgentCardError("Agent Card requires name, description, and version")
    if not parsed.supported_interfaces:
        raise AgentCardError("Agent Card requires at least one supportedInterfaces entry")
    for interface in parsed.supported_interfaces:
        if not interface.url or not interface.protocol_binding or not interface.protocol_version:
            raise AgentCardError("Every AgentInterface requires url, protocolBinding, and protocolVersion")
    return parsed


def negotiate_interface(
    card: dict[str, Any], *, bindings: Iterable[str] = ("JSONRPC",), versions: Iterable[str] = ("1.0",)
) -> dict[str, Any]:
    validate_agent_card(card)
    wanted_bindings = {item.upper() for item in bindings}
    wanted_versions = tuple(versions)
    candidates = [
        item for item in card["supportedInterfaces"]
        if str(item.get("protocolBinding", "")).upper() in wanted_bindings
        and str(item.get("protocolVersion", "")) in wanted_versions
    ]
    if not candidates:
        offered = [f"{x.get('protocolBinding')}/{x.get('protocolVersion')}" for x in card["supportedInterfaces"]]
        raise AgentCardError(f"No mutually supported A2A interface; offered={offered}, supported={list(wanted_versions)}")
    # Caller order is preference order, not lexical version ordering.
    rank = {version: index for index, version in enumerate(wanted_versions)}
    return min(candidates, key=lambda item: rank[str(item["protocolVersion"])])
