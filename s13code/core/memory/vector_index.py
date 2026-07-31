"""Persistent FAISS seam for local S13 document memory.

The store owns scope checks and lifecycle filtering.  This module only maps
embedding vectors to record ids; it never authorizes a retrieval result.
"""
from __future__ import annotations

import json
from pathlib import Path

import faiss  # type: ignore[import-untyped]
import numpy as np


class PersistentFaissIndex:
    def __init__(self, directory: Path | None) -> None:
        self.directory = directory
        self.index_path = directory / "memory.faiss" if directory else None
        self.ids_path = directory / "memory.faiss.ids.json" if directory else None
        self.index: faiss.IndexFlatIP | None = None
        self.ids: list[str] = []
        if directory:
            directory.mkdir(parents=True, exist_ok=True)
            self._load()

    def _load(self) -> None:
        if self.index_path and self.ids_path and self.index_path.exists() and self.ids_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            self.ids = json.loads(self.ids_path.read_text(encoding="utf-8"))

    @staticmethod
    def _matrix(vectors: list[list[float]]) -> np.ndarray:
        matrix = np.asarray(vectors, dtype="float32")
        faiss.normalize_L2(matrix)
        return matrix

    def rebuild(self, pairs: list[tuple[str, list[float]]]) -> None:
        self.ids = [record_id for record_id, _ in pairs]
        if not pairs:
            self.index = None
        else:
            matrix = self._matrix([vector for _, vector in pairs])
            self.index = faiss.IndexFlatIP(matrix.shape[1])
            self.index.add(matrix)
        self.persist()

    def persist(self) -> None:
        if not self.index_path or not self.ids_path:
            return
        if self.index is None:
            self.index_path.unlink(missing_ok=True)
            self.ids_path.unlink(missing_ok=True)
            return
        faiss.write_index(self.index, str(self.index_path))
        self.ids_path.write_text(json.dumps(self.ids))

    def search(self, vector: list[float], limit: int) -> list[tuple[str, float]]:
        if self.index is None or self.index.ntotal == 0:
            return []
        query = self._matrix([vector])
        scores, positions = self.index.search(query, min(limit, self.index.ntotal))
        return [(self.ids[position], float(score)) for score, position in zip(scores[0], positions[0]) if position >= 0]

    @property
    def size(self) -> int:
        return 0 if self.index is None else int(self.index.ntotal)
