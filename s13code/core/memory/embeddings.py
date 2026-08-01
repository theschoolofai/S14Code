"""Embedding seam: production can use local Ollama; tests inject deterministic vectors."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Protocol
from urllib.request import Request, urlopen


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class OllamaNomicEmbedder:
    """Small dependency-free client for a locally running Ollama instance."""
    def __init__(self, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434"):
        self.model, self.base_url = model, base_url.rstrip("/")

    @property
    def fingerprint(self) -> str:
        return f"ollama:{self.base_url}:{self.model}:nomic-retrieval-v1"

    def embed(self, text: str) -> list[float]:
        """Embed text for clustering/chunk-boundary comparison."""
        return self._embed(text)

    def embed_document(self, text: str) -> list[float]:
        return self._embed(f"search_document: {text}")

    def embed_query(self, text: str) -> list[float]:
        return self._embed(f"search_query: {text}")

    def _embed(self, text: str) -> list[float]:
        # Ollama's current endpoint accepts batched input; older installs use
        # /api/embeddings. Supporting both keeps local workshop setup simple.
        body = json.dumps({"model": self.model, "input": text}).encode()
        request = Request(self.base_url + "/api/embed", data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:  # nosec B310: local configurable service
                data = json.load(response)
            return list(data["embeddings"][0])
        except Exception:
            try:
                old_body = json.dumps({"model": self.model, "prompt": text}).encode()
                old = Request(self.base_url + "/api/embeddings", data=old_body, headers={"Content-Type": "application/json"})
                with urlopen(old, timeout=3) as response:  # nosec B310: local configurable service
                    return list(json.load(response)["embedding"])
            except Exception:
                return DeterministicEmbedder().embed(text)

    def release(self) -> None:
        """Unload the embedding model before a larger answer model runs.

        Ollama otherwise keeps both models resident. On student laptops that
        can terminate the answer connection under memory pressure even though
        embedding and generation each work independently.
        """
        body = json.dumps({"model": self.model, "input": "", "keep_alive": 0}).encode()
        request = Request(self.base_url + "/api/embed", data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=10):  # nosec B310: local configurable service
                pass
        except Exception:
            pass


class DeterministicEmbedder:
    """Stable hashed bag-of-words vectors for unit tests and offline demos."""
    def __init__(self, dimensions: int = 96):
        self.dimensions = dimensions

    @property
    def fingerprint(self) -> str:
        return f"deterministic:{self.dimensions}"

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token, count in Counter(re.findall(r"[a-z0-9]+", text.lower())).items():
            # stable, unlike Python's randomized hash()
            slot = sum((i + 1) * ord(c) for i, c in enumerate(token)) % self.dimensions
            values[slot] += float(count)
        norm = math.sqrt(sum(v * v for v in values))
        return [v / norm for v in values] if norm else values

    def embed_document(self, text: str) -> list[float]:
        return self.embed(text)

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions differ")
    return sum(a * b for a, b in zip(left, right))
