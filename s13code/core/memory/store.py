from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from .embeddings import DeterministicEmbedder, Embedder, cosine
from .models import MemoryKind, MemoryRecord, MemoryScope, Principal, SourceRef, utcnow
from .vector_index import PersistentFaissIndex

if TYPE_CHECKING:
    from .chunking import DocumentChunk


class PermissionDenied(PermissionError):
    pass


class MemoryStore:
    """Local SQLite memory with explicit scope, provenance and lifecycle rules.

    SQLite FTS is the lexical retrieval path. Embeddings are persisted beside
    records and searched by a deliberately small brute-force adapter; replacing
    `_vector_candidates` with FAISS/Milvus changes no memory semantics.
    """
    def __init__(self, path: str | Path = ":memory:", *, embedder: Embedder | None = None):
        self.path = Path(path) if str(path) != ":memory:" else None
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.embedder = embedder or DeterministicEmbedder()
        self._create_schema()
        self.vectors = PersistentFaissIndex(self.path.parent if self.path else None)
        self._ensure_vector_index()
        self.last_retrieval_stats: dict[str, int] = {"index_candidates": 0, "authorized_records": 0}

    def close(self) -> None:
        self.db.close()

    def _create_schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS records (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL,
          tenant_id TEXT NOT NULL, project_id TEXT, user_id TEXT, agent_id TEXT, run_id TEXT,
          sources_json TEXT NOT NULL, metadata_json TEXT NOT NULL, embedding_json TEXT,
          created_at TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT,
          confidence REAL, status TEXT NOT NULL, supersedes_id TEXT,
          principal_id TEXT NOT NULL, principal_role TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS records_scope ON records(tenant_id, project_id, user_id, agent_id, run_id);
        CREATE INDEX IF NOT EXISTS records_lifecycle ON records(kind, status, valid_to);
        CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(id UNINDEXED, text);
        CREATE TABLE IF NOT EXISTS documents (
          document_id TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL,
          tenant_id TEXT NOT NULL, project_id TEXT, user_id TEXT, agent_id TEXT, run_id TEXT,
          source_uri TEXT NOT NULL, source_sha256 TEXT NOT NULL, prepared_sha256 TEXT NOT NULL,
          preprocessing TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY (document_id, version)
        );
        CREATE INDEX IF NOT EXISTS documents_active ON documents(document_id, state);
        """)
        self.db.commit()

    @staticmethod
    def _assert_write_allowed(record: MemoryRecord) -> None:
        if not record.sources and record.kind not in {MemoryKind.WORKING, MemoryKind.AUDIT}:
            raise ValueError("every durable memory record needs at least one source")
        if record.kind is MemoryKind.POLICY and record.principal.role not in {"operator", "system"}:
            raise PermissionDenied("only operator/system may write policy")
        if record.kind is MemoryKind.AUDIT and record.principal.role != "gateway":
            raise PermissionDenied("only gateway may append audit events")

    def write(self, record: MemoryRecord, *, audit: bool = True) -> MemoryRecord:
        self._write(record, audit=audit)
        self.db.commit()
        self._ensure_vector_index()
        return record

    def _write(self, record: MemoryRecord, *, audit: bool = True) -> MemoryRecord:
        self._assert_write_allowed(record)
        if record.supersedes_id:
            old = self.get(record.supersedes_id)
            if old is None:
                raise ValueError("superseded record does not exist")
            if old.scope != record.scope or old.kind != record.kind:
                raise ValueError("a record may supersede only the same kind in the same scope")
            if old.status != "current":
                raise ValueError("only a current record may be superseded")
        self.db.execute("""INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            record.id, record.kind.value, record.text, record.scope.tenant_id, record.scope.project_id,
            record.scope.user_id, record.scope.agent_id, record.scope.run_id,
            json.dumps([s.__dict__ for s in record.sources]), json.dumps(record.metadata),
            json.dumps(self._pack_embedding(self._embed_document(record.text))), record.created_at, record.valid_from,
            record.valid_to, record.confidence, record.status, record.supersedes_id,
            record.principal.id, record.principal.role,
        ))
        self.db.execute("INSERT INTO records_fts(id, text) VALUES (?, ?)", (record.id, record.text))
        if record.supersedes_id:
            self.db.execute("UPDATE records SET status='superseded' WHERE id=?", (record.supersedes_id,))
        if audit and record.kind is not MemoryKind.AUDIT:
            self._append_audit(record)
        return record

    def _append_audit(self, record: MemoryRecord) -> None:
        # This is an internal gateway action, not an agent-controlled write.
        audit = MemoryRecord(
            kind=MemoryKind.AUDIT, scope=record.scope,
            text=f"write {record.kind.value} {record.id}", sources=[],
            principal=Principal("memory-gateway", "gateway"),
            metadata={"record_id": record.id, "actor": record.principal.id},
        )
        self._write(audit, audit=False)

    def _ensure_vector_index(self) -> None:
        """Rebuild only when persisted ids disagree with active vector records."""
        rows = self.db.execute("SELECT id, embedding_json FROM records WHERE status='current' AND embedding_json IS NOT NULL "
                               "AND kind NOT IN ('audit', 'policy')").fetchall()
        ids = [row["id"] for row in rows]
        if ids == self.vectors.ids:
            return
        pairs = []
        for row in rows:
            vector, stale = self._unpack_embedding(row["embedding_json"])
            if not stale:
                pairs.append((row["id"], vector))
        self.vectors.rebuild(pairs)

    @staticmethod
    def _document_id(scope: MemoryScope, source_uri: str) -> str:
        owner = "\x1f".join(str(value or "") for value in (
            scope.tenant_id, scope.project_id, scope.user_id, scope.agent_id, scope.run_id, source_uri,
        ))
        return "doc_" + hashlib.sha256(owner.encode()).hexdigest()[:24]

    def ingest_document(self, *, source_text: str, prepared_text: str, chunks: list[DocumentChunk],
                        source_uri: str, scope: MemoryScope, source_author: str,
                        preprocessing: str) -> dict[str, object]:
        """Atomically replace a source's active chunks with a new content version."""
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        prepared_hash = hashlib.sha256(prepared_text.encode("utf-8")).hexdigest()
        document_id = self._document_id(scope, source_uri)
        active = self.db.execute("SELECT * FROM documents WHERE document_id=? AND state='active'", (document_id,)).fetchone()
        if active and active["source_sha256"] == source_hash and active["prepared_sha256"] == prepared_hash:
            rows = self.db.execute("SELECT id FROM records WHERE status='current' AND kind='document_chunk' "
                                   "AND json_extract(metadata_json, '$.document_id')=? ORDER BY json_extract(metadata_json, '$.ordinal')", (document_id,)).fetchall()
            return {"document_id": document_id, "version": active["version"], "idempotent": True,
                    "record_ids": [row["id"] for row in rows], "source_sha256": source_hash,
                    "prepared_sha256": prepared_hash}
        version = (int(active["version"]) + 1) if active else 1
        record_ids: list[str] = []
        # `with self.db` rolls back documents, chunks and the one audit record
        # together on any failure. The existing vector sidecar remains valid.
        with self.db:
            if active:
                self.db.execute("UPDATE documents SET state='superseded' WHERE document_id=? AND state='active'", (document_id,))
                self.db.execute("UPDATE records SET status='superseded' WHERE status='current' AND json_extract(metadata_json, '$.document_id')=?", (document_id,))
            self.db.execute("INSERT INTO documents VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                document_id, version, scope.tenant_id, scope.project_id, scope.user_id, scope.agent_id, scope.run_id,
                source_uri, source_hash, prepared_hash, preprocessing, utcnow(),
            ))
            for chunk in chunks:
                metadata = {
                    "document_id": document_id, "document_version": version, "heading": chunk.heading,
                    "ordinal": chunk.ordinal, "previous": chunk.previous_ordinal, "next": chunk.next_ordinal,
                    "segmentation": chunk.segmentation, "preprocessing": preprocessing,
                    "source_sha256": source_hash, "prepared_sha256": prepared_hash,
                    "source_start_char": chunk.source_start_char, "source_end_char": chunk.source_end_char,
                    "source_start_word": chunk.source_start_word, "source_end_word": chunk.source_end_word,
                }
                record = MemoryRecord(MemoryKind.DOCUMENT_CHUNK, scope, chunk.text,
                    [SourceRef(source_uri, source_author, excerpt=chunk.text)], Principal("gateway", "gateway"), metadata=metadata)
                self._write(record, audit=False)
                record_ids.append(record.id)
            audit = MemoryRecord(MemoryKind.AUDIT, scope, f"index document {document_id} v{version}", [],
                Principal("memory-gateway", "gateway"), metadata={"document_id": document_id, "version": version,
                "chunks": len(record_ids), "source_sha256": source_hash})
            self._write(audit, audit=False)
        self._ensure_vector_index()
        return {"document_id": document_id, "version": version, "idempotent": False, "record_ids": record_ids,
                "source_sha256": source_hash, "prepared_sha256": prepared_hash}

    def get(self, record_id: str) -> MemoryRecord | None:
        row = self.db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        return self._to_record(row) if row else None

    @staticmethod
    def _to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"], kind=MemoryKind(row["kind"]), text=row["text"],
            scope=MemoryScope(row["tenant_id"], row["project_id"], row["user_id"], row["agent_id"], row["run_id"]),
            sources=[SourceRef(**source) for source in json.loads(row["sources_json"])],
            metadata=json.loads(row["metadata_json"]), created_at=row["created_at"], valid_from=row["valid_from"],
            valid_to=row["valid_to"], confidence=row["confidence"], status=row["status"],
            supersedes_id=row["supersedes_id"], principal=Principal(row["principal_id"], row["principal_role"]),
        )

    @staticmethod
    def _scope_where(scope: MemoryScope) -> tuple[str, list[str | None]]:
        # A broader record (NULL at lower levels) may be read inside a narrower
        # request; a narrower record can never leak upward or sideways.
        clauses, values = ["tenant_id=?"], [scope.tenant_id]
        for column, value in (("project_id", scope.project_id), ("user_id", scope.user_id),
                              ("agent_id", scope.agent_id), ("run_id", scope.run_id)):
            clauses.append(f"({column} IS NULL OR {column}=?)")
            values.append(value)
        return " AND ".join(clauses), values

    def recall(self, query: str, scope: MemoryScope, *, kinds: Iterable[MemoryKind] | None = None,
               limit: int = 8, include_history: bool = False, expand_neighbors: int = 0) -> list[MemoryRecord]:
        where, values = self._scope_where(scope)
        if not include_history:
            where += " AND status='current' AND (valid_to IS NULL OR valid_to > ?)"
            values.append(utcnow())
        if kinds:
            kind_values = [k.value for k in kinds]
            where += " AND kind IN (" + ",".join("?" for _ in kind_values) + ")"
            values.extend(kind_values)
        else:
            # Audit/policy records are control-plane data, never ambient
            # answer evidence. Callers such as `audit_events` request them
            # explicitly.
            where += " AND kind NOT IN ('audit', 'policy')"
        rows = self.db.execute(f"SELECT * FROM records WHERE {where}", values).fetchall()
        if not rows:
            return []
        query_embedding = self._embed_query(query)
        self._ensure_vector_index()
        # FAISS is global and contains ids only. Scope authorization still
        # happens before a record is returned; a wider search merely avoids a
        # foreign tenant consuming the first few approximate candidates.
        vector_hits = self.vectors.search(query_embedding, max(128, limit * 16))
        vector_scores = {record_id: score for record_id, score in vector_hits}
        self.last_retrieval_stats = {"index_candidates": len(vector_hits), "authorized_records": len(rows)}
        terms = [term for term in query.lower().replace("'", " ").split() if term.isalnum()]
        # We deliberately score only scope-authorized rows. FTS is a boost, not
        # an authorization mechanism and never gets to choose the tenant.
        lexical = set()
        if terms:
            try:
                match = " OR ".join(terms)
                lexical = {r[0] for r in self.db.execute("SELECT id FROM records_fts WHERE records_fts MATCH ?", (match,))}
            except sqlite3.OperationalError:
                pass
        scored = []
        changed = False
        for row in rows:
            vector, stale = self._unpack_embedding(row["embedding_json"])
            # A new embedding model must not make old memory unsearchable.
            # Re-embed lazily from the retained source text and persist the
            # new provenance marker; never compare incompatible vectors.
            if stale or len(vector) != len(query_embedding):
                vector = self._embed_document(row["text"])
                self.db.execute("UPDATE records SET embedding_json=? WHERE id=?",
                                (json.dumps(self._pack_embedding(vector)), row["id"]))
                changed = True
            # If a vector is absent from the ANN candidate pool, exact cosine
            # remains the safe recall fallback for this authorized scope.
            score = vector_scores.get(row["id"], cosine(query_embedding, vector)) + (0.20 if row["id"] in lexical else 0.0)
            score += self._content_quality(row["text"])
            scored.append((score, self._to_record(row)))
        if changed:
            self.db.commit()
        scored.sort(key=lambda pair: (-pair[0], pair[1].created_at))
        selected = [record for _, record in scored[:limit]]
        if not expand_neighbors:
            return selected
        seen = {record.id for record in selected}
        expanded = list(selected)
        for record in selected:
            metadata = record.metadata
            document_id, version, ordinal = metadata.get("document_id"), metadata.get("document_version"), metadata.get("ordinal")
            if document_id is None or version is None or ordinal is None:
                continue
            neighbour_rows = self.db.execute(
                "SELECT * FROM records WHERE status='current' AND kind='document_chunk' AND json_extract(metadata_json, '$.document_id')=? "
                "AND json_extract(metadata_json, '$.document_version')=? "
                "AND json_extract(metadata_json, '$.ordinal') BETWEEN ? AND ? ORDER BY json_extract(metadata_json, '$.ordinal')",
                (document_id, version, int(ordinal) - expand_neighbors, int(ordinal) + expand_neighbors),
            ).fetchall()
            for row in neighbour_rows:
                neighbour = self._to_record(row)
                if neighbour.id not in seen:
                    seen.add(neighbour.id)
                    expanded.append(neighbour)
        return expanded

    def _pack_embedding(self, values: list[float]) -> dict[str, object]:
        return {"fingerprint": getattr(self.embedder, "fingerprint", type(self.embedder).__name__), "values": values}

    def _unpack_embedding(self, raw: str) -> tuple[list[float], bool]:
        payload = json.loads(raw)
        current = getattr(self.embedder, "fingerprint", type(self.embedder).__name__)
        if isinstance(payload, list):  # migration path for S13's first local stores
            return payload, True
        return list(payload["values"]), payload.get("fingerprint") != current

    def _embed_document(self, text: str) -> list[float]:
        method = getattr(self.embedder, "embed_document", self.embedder.embed)
        return method(text)

    def _embed_query(self, text: str) -> list[float]:
        method = getattr(self.embedder, "embed_query", self.embedder.embed)
        return method(text)

    @staticmethod
    def _content_quality(text: str) -> float:
        """Small generic quality prior; relevance still comes from retrieval.

        Extracted web pages often contain tiny navigation chunks whose titles
        repeat query terms. They should remain inspectable in memory, but must
        not outrank the article body merely because they say "Access Paper".
        """
        words = text.split()
        lowered = text.lower()
        penalty = 0.0
        if len(words) < 35:
            penalty -= 0.12
        if lowered.startswith(("skip to main content", "quick links", "access paper")):
            penalty -= 0.30
        links = len(re.findall(r"\[[^]]*\]\([^)]+\)", text))
        if links and links / max(1, len(words)) > 0.12:
            penalty -= 0.20
        if any(marker in lowered for marker in ("arxivlabs", "bibliographic tools", "current browse context")):
            penalty -= 0.20
        return penalty

    def audit_events(self, scope: MemoryScope) -> list[MemoryRecord]:
        return self.recall("write", scope, kinds=[MemoryKind.AUDIT], include_history=True, limit=100)
