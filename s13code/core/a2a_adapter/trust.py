"""Agent Card signing and verification seam.

The A2A card signature is a detached JWS: the protected header and signature
are stored in ``card.signatures`` while the canonicalised card is the payload.
This intentionally keeps trust outside discovery and task execution.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class CardTrustError(ValueError):
    """A discovered card did not meet the caller's trust policy."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical_card(card: Mapping[str, object]) -> bytes:
    """Return the deterministic payload used by this S13Core implementation.

    Agent Cards contain no numbers in this implementation, so Python's compact
    sorted JSON is equivalent to the relevant RFC 8785/JCS form.  Production
    adapters should swap this function for a full RFC 8785 implementation.
    """

    payload = deepcopy(dict(card))
    payload.pop("signatures", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_card(card: Mapping[str, object], private_key_pem: bytes, *, kid: str) -> dict:
    """Return a card with a detached RS256 JWS signature."""

    signed = deepcopy(dict(card))
    header = {"alg": "RS256", "kid": kid, "typ": "JOSE"}
    protected = _b64(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    payload = _b64(canonical_card(signed))
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = key.sign(f"{protected}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    signed["signatures"] = [{"protected": protected, "signature": _b64(signature)}]
    return signed


KeyResolver = Callable[[str], bytes | None]


@dataclass(frozen=True)
class AgentCardTrustPolicy:
    """Caller-owned trust decision.  Discovery alone is never authorization."""

    key_resolver: KeyResolver
    require_signature: bool = True
    allowed_algorithms: frozenset[str] = frozenset({"RS256"})

    def verify(self, card: Mapping[str, object]) -> None:
        signatures = card.get("signatures", [])
        if not signatures:
            if self.require_signature:
                raise CardTrustError("Agent Card is unsigned")
            return
        payload = _b64(canonical_card(card))
        errors: list[str] = []
        for item in signatures:
            try:
                protected = str(item["protected"])
                header = json.loads(_unb64(protected))
                algorithm, kid = header.get("alg"), header.get("kid")
                if algorithm not in self.allowed_algorithms or not kid:
                    raise CardTrustError("unacceptable signature algorithm or missing kid")
                public_pem = self.key_resolver(kid)
                if not public_pem:
                    raise CardTrustError(f"no trusted key for kid={kid}")
                public_key = serialization.load_pem_public_key(public_pem)
                public_key.verify(
                    _unb64(str(item["signature"])),
                    f"{protected}.{payload}".encode(),
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
                return
            except (KeyError, ValueError, InvalidSignature, TypeError, CardTrustError) as error:
                errors.append(str(error))
        raise CardTrustError("No Agent Card signature could be verified: " + "; ".join(errors))
