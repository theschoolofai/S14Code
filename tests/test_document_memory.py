from __future__ import annotations

from pathlib import Path

import pytest

from s13code.core.memory import MemoryKind, MemoryScope, MemoryStore
from s13code.core.memory.chunking import DocumentChunk
from s13code.core.memory.embeddings import DeterministicEmbedder

SCOPE = MemoryScope("tenant", "project", "user")


def chunk(text: str, ordinal: int, *, start: int = 0) -> DocumentChunk:
    return DocumentChunk(text=text, heading=None, ordinal=ordinal,
        previous_ordinal=ordinal - 1 if ordinal else None, next_ordinal=None,
        segmentation={"mode": "test", "outcome": "one_topic"},
        source_start_char=start, source_end_char=start + len(text),
        source_start_word=start, source_end_word=start + len(text.split()))


def ingest(store: MemoryStore, text: str, chunks: list[DocumentChunk]):
    return store.ingest_document(source_text=text, prepared_text=text, chunks=chunks,
        source_uri="file://manual.md", scope=SCOPE, source_author="test", preprocessing="none")


def test_reindex_versions_supersede_old_chunks_and_preserve_spans(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite", embedder=DeterministicEmbedder(128))
    try:
        first = ingest(store, "old quota is 50", [chunk("old quota is 50", 0)])
        second = ingest(store, "new quota is 75", [chunk("new quota is 75", 0)])
        again = ingest(store, "new quota is 75", [chunk("new quota is 75", 0)])
        assert first["version"] == 1 and second["version"] == 2
        assert again["idempotent"] is True and again["record_ids"] == second["record_ids"]
        assert store.get(first["record_ids"][0]).status == "superseded"
        active = store.recall("quota", SCOPE, kinds=[MemoryKind.DOCUMENT_CHUNK])
        assert [record.text for record in active] == ["new quota is 75"]
        metadata = active[0].metadata
        assert metadata["document_version"] == 2
        assert (metadata["source_start_char"], metadata["source_end_char"]) == (0, len("new quota is 75"))
    finally:
        store.close()


def test_document_ingestion_rolls_back_everything_on_embedding_failure(tmp_path: Path):
    class FailingEmbedder(DeterministicEmbedder):
        def __init__(self):
            super().__init__(64); self.calls = 0
        def embed_document(self, text: str) -> list[float]:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("embedding failed")
            return super().embed_document(text)

    store = MemoryStore(tmp_path / "memory.sqlite", embedder=FailingEmbedder())
    try:
        with pytest.raises(RuntimeError, match="embedding failed"):
            ingest(store, "one two", [chunk("one", 0), chunk("two", 1, start=4)])
        assert store.db.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM records WHERE kind='document_chunk'").fetchone()[0] == 0
    finally:
        store.close()


def test_neighbour_expansion_and_persistent_faiss_scale(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite", embedder=DeterministicEmbedder(128))
    try:
        texts = [f"topic {i} evidence alpha" for i in range(200)]
        result = ingest(store, "\n".join(texts), [chunk(text, i, start=i * 30) for i, text in enumerate(texts)])
        assert store.vectors.size == 200
        hits = store.recall("topic 100 evidence", SCOPE, kinds=[MemoryKind.DOCUMENT_CHUNK], limit=1,
                            expand_neighbors=1)
        assert hits[0].metadata["document_id"] == result["document_id"]
        assert len(hits) >= 2
        assert store.last_retrieval_stats == {"index_candidates": 128, "authorized_records": 200}
    finally:
        store.close()
