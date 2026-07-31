"""SQLite event journal and materialised graph state for S13Core live graphs."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .core import Event, GraphPatch, GraphSnapshot, NodeState, TaskSpec


class GraphMutationError(ValueError):
    pass


class GraphStore:
    """Durable graph storage. A patch and its journal entry commit together."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        # FastAPI's test/client boundary (and a local server's worker thread)
        # may resume a durable run from a different thread than construction.
        # Graph mutations remain transaction-scoped; callers do not share a
        # patch transaction across awaits.
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self.db.close()

    def _create_schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, finished INTEGER NOT NULL DEFAULT 0,
                                         context_json TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS nodes (
          run_id TEXT NOT NULL, id TEXT NOT NULL, skill TEXT NOT NULL,
          input_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
          state TEXT NOT NULL, result_json TEXT,
          PRIMARY KEY (run_id, id), FOREIGN KEY (run_id) REFERENCES runs(id));
        CREATE TABLE IF NOT EXISTS edges (
          run_id TEXT NOT NULL, parent_id TEXT NOT NULL, child_id TEXT NOT NULL,
          PRIMARY KEY (run_id, parent_id, child_id), FOREIGN KEY (run_id) REFERENCES runs(id));
        CREATE TABLE IF NOT EXISTS events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          kind TEXT NOT NULL, node_id TEXT, payload_json TEXT NOT NULL,
          FOREIGN KEY (run_id) REFERENCES runs(id));
        CREATE TABLE IF NOT EXISTS patches (
          run_id TEXT NOT NULL, trigger_event INTEGER NOT NULL, patch_json TEXT NOT NULL,
          PRIMARY KEY (run_id, trigger_event), FOREIGN KEY (run_id) REFERENCES runs(id));
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(runs)")}
        if "context_json" not in columns:
            self.db.execute("ALTER TABLE runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")
        # Additive: existing rows read back NULL (no timing recorded before
        # this column existed), every prior caller is unaffected.
        node_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(nodes)")}
        if "started_at" not in node_columns:
            self.db.execute("ALTER TABLE nodes ADD COLUMN started_at REAL")
        if "duration_ms" not in node_columns:
            self.db.execute("ALTER TABLE nodes ADD COLUMN duration_ms REAL")
        event_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(events)")}
        if "duration_ms" not in event_columns:
            self.db.execute("ALTER TABLE events ADD COLUMN duration_ms REAL")
        self.db.commit()

    def start(self, run_id: str, *, context: dict[str, Any] | None = None) -> bool:
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO runs(id, context_json) VALUES (?, ?)",
                                     (run_id, json.dumps(context or {})))
            if cursor.rowcount:
                self._event(run_id, "run_started", None, {})
                return True
        return False

    def context(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT context_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row["context_json"])

    def resume(self, run_id: str) -> None:
        with self.db:
            found = self.db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone()
            if not found:
                raise KeyError(f"cannot resume unknown run {run_id!r}")
            self.db.execute("UPDATE nodes SET state=? WHERE run_id=? AND state=?",
                            (NodeState.PENDING, run_id, NodeState.RUNNING))
            self._event(run_id, "run_resumed", None, {})

    def latest_event(self, run_id: str) -> Event | None:
        row = self.db.execute("SELECT * FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
        return self._event_from_row(row) if row else None

    def snapshot(self, run_id: str) -> GraphSnapshot:
        run = self.db.execute("SELECT finished FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise KeyError(run_id)
        rows = self.db.execute("SELECT * FROM nodes WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        nodes = {r["id"]: {"id": r["id"], "skill": r["skill"], "input": json.loads(r["input_json"]),
                            "metadata": json.loads(r["metadata_json"]), "state": r["state"],
                            "result": json.loads(r["result_json"]) if r["result_json"] else None,
                            "duration_ms": r["duration_ms"]}
                 for r in rows}
        edges = tuple((r["parent_id"], r["child_id"]) for r in self.db.execute(
            "SELECT parent_id, child_id FROM edges WHERE run_id=? ORDER BY parent_id, child_id", (run_id,)))
        return GraphSnapshot(run_id, bool(run["finished"]), nodes, edges)

    def ready(self, run_id: str, *, limit: int) -> list[TaskSpec]:
        # A task becomes ready only when every parent has actually succeeded.
        rows = self.db.execute("""
          SELECT n.* FROM nodes n WHERE n.run_id=? AND n.state=?
          AND NOT EXISTS (SELECT 1 FROM edges e JOIN nodes p ON p.run_id=e.run_id AND p.id=e.parent_id
                          WHERE e.run_id=n.run_id AND e.child_id=n.id AND p.state != ?)
          ORDER BY n.id LIMIT ?
        """, (run_id, NodeState.PENDING, NodeState.SUCCEEDED, limit)).fetchall()
        return [TaskSpec(r["id"], r["skill"], json.loads(r["input_json"]), json.loads(r["metadata_json"])) for r in rows]

    def mark_running(self, run_id: str, tasks: list[TaskSpec]) -> None:
        with self.db:
            for task in tasks:
                self.db.execute("UPDATE nodes SET state=?, started_at=? WHERE run_id=? AND id=? AND state=?",
                                (NodeState.RUNNING, time.time(), run_id, task.id, NodeState.PENDING))
                self._event(run_id, "task_started", task.id,
                            {"skill": task.skill, "agent": task.metadata.get("agent", task.skill)})

    def record_outcome(self, run_id: str, node_id: str, success: bool, payload: dict[str, Any]) -> Event:
        state = NodeState.SUCCEEDED if success else NodeState.FAILED
        with self.db:
            started = self.db.execute("SELECT started_at FROM nodes WHERE run_id=? AND id=?",
                                      (run_id, node_id)).fetchone()
            duration_ms = (time.time() - started["started_at"]) * 1000 if started and started["started_at"] else None
            row = self.db.execute(
                "UPDATE nodes SET state=?, result_json=?, duration_ms=? WHERE run_id=? AND id=? AND state=?",
                (state, json.dumps(payload), duration_ms, run_id, node_id, NodeState.RUNNING))
            if row.rowcount != 1:
                raise GraphMutationError(f"cannot record outcome for {node_id}: it is not running")
            return self._event(run_id, "task_succeeded" if success else "task_failed", node_id, payload,
                               duration_ms=duration_ms)

    def pending_planner_events(self, run_id: str) -> list[Event]:
        """Events whose graph mutation was not committed yet."""
        rows = self.db.execute("""
          SELECT e.* FROM events e WHERE e.run_id=?
          AND e.kind IN ('run_started', 'task_succeeded', 'task_failed')
          AND NOT EXISTS (SELECT 1 FROM patches p WHERE p.run_id=e.run_id AND p.trigger_event=e.sequence)
          ORDER BY e.sequence
        """, (run_id,)).fetchall()
        return [self._event_from_row(row) for row in rows]

    def apply_patch(self, run_id: str, patch: GraphPatch, *, trigger_event: int) -> bool:
        with self.db:
            if self.db.execute("SELECT 1 FROM patches WHERE run_id=? AND trigger_event=?", (run_id, trigger_event)).fetchone():
                return False
            existing = self.snapshot(run_id)
            if existing.finished:
                raise GraphMutationError("cannot mutate a finished graph")
            ids = set(existing.nodes)
            add_ids = [task.id for task in patch.add]
            if len(add_ids) != len(set(add_ids)) or ids.intersection(add_ids):
                raise GraphMutationError("patch adds duplicate task id")
            all_ids = ids.union(add_ids)
            for parent, child in patch.connect:
                if parent not in all_ids or child not in all_ids:
                    raise GraphMutationError(f"edge {parent}->{child} references unknown task")
                if parent == child:
                    raise GraphMutationError("a task cannot depend on itself")
            for nid in (*patch.cancel, *patch.wait, *patch.resume):
                if nid not in all_ids:
                    raise GraphMutationError(f"patch references unknown task {nid}")
            for nid in patch.cancel:
                state = existing.nodes[nid]["state"]
                if state not in (NodeState.PENDING, NodeState.WAITING, NodeState.RUNNING):
                    raise GraphMutationError(f"can only cancel pending/waiting/running task {nid}, got {state}")
            for nid in patch.wait:
                if nid in ids and existing.nodes[nid]["state"] != NodeState.PENDING:
                    raise GraphMutationError(f"can only wait pending task {nid}")
            for nid in patch.resume:
                if nid in ids and existing.nodes[nid]["state"] != NodeState.WAITING:
                    raise GraphMutationError(f"can only resume waiting task {nid}")

            for task in patch.add:
                self.db.execute("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                                (run_id, task.id, task.skill, json.dumps(task.input), json.dumps(task.metadata), NodeState.PENDING))
            for parent, child in patch.connect:
                self.db.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, ?)", (run_id, parent, child))
            # Detect cycles after adding all edges, while the transaction can still roll back.
            if self._has_cycle(run_id):
                raise GraphMutationError("patch would create a dependency cycle")
            for nid in patch.cancel:
                self.db.execute("UPDATE nodes SET state=? WHERE run_id=? AND id=?", (NodeState.CANCELLED, run_id, nid))
                self._event(run_id, "task_cancelled", nid,
                            {"reason": patch.reason, "was_running": existing.nodes[nid]["state"] == NodeState.RUNNING})
            for nid in patch.wait:
                self.db.execute("UPDATE nodes SET state=? WHERE run_id=? AND id=?", (NodeState.WAITING, run_id, nid))
            for nid in patch.resume:
                self.db.execute("UPDATE nodes SET state=? WHERE run_id=? AND id=?", (NodeState.PENDING, run_id, nid))
            if patch.finish:
                # A planner may conclude that an answer is final while a
                # speculative sibling is still running. Finish is therefore
                # a durable cancellation boundary, not permission to leave a
                # coroutine recorded as running after the executor returns.
                leftovers = self.db.execute(
                    "SELECT id, state FROM nodes WHERE run_id=? AND state IN (?, ?, ?)",
                    (run_id, NodeState.PENDING, NodeState.WAITING, NodeState.RUNNING),
                ).fetchall()
                for leftover in leftovers:
                    self.db.execute("UPDATE nodes SET state=? WHERE run_id=? AND id=?",
                                    (NodeState.CANCELLED, run_id, leftover["id"]))
                    self._event(run_id, "task_cancelled", leftover["id"],
                                {"reason": "graph finished", "was_running": leftover["state"] == NodeState.RUNNING})
                self.db.execute("UPDATE runs SET finished=1 WHERE id=?", (run_id,))
            self._event(run_id, "graph_patched", None, {"trigger_event": trigger_event, "reason": patch.reason,
                        "add": add_ids, "connect": list(patch.connect), "cancel": list(patch.cancel),
                        "wait": list(patch.wait), "resume": list(patch.resume), "finish": patch.finish})
            self.db.execute("INSERT INTO patches(run_id, trigger_event, patch_json) VALUES (?, ?, ?)",
                            (run_id, trigger_event, json.dumps({"reason": patch.reason, "add": add_ids,
                                "connect": list(patch.connect), "cancel": list(patch.cancel),
                                "wait": list(patch.wait), "resume": list(patch.resume), "finish": patch.finish})))
            return True

    def is_finished(self, run_id: str) -> bool:
        row = self.db.execute("SELECT finished FROM runs WHERE id=?", (run_id,)).fetchone()
        return bool(row and row["finished"])

    def node_state(self, run_id: str, node_id: str) -> str:
        row = self.db.execute("SELECT state FROM nodes WHERE run_id=? AND id=?", (run_id, node_id)).fetchone()
        if not row:
            raise KeyError(f"unknown task {node_id!r} in run {run_id!r}")
        return row["state"]

    def events(self, run_id: str) -> list[Event]:
        return [self._event_from_row(r) for r in self.db.execute("SELECT * FROM events WHERE run_id=? ORDER BY sequence", (run_id,))]

    def record_external_event(self, run_id: str, kind: str, node_id: str, payload: dict[str, Any]) -> Event:
        """Journal a trusted transport event before it mutates a waiting graph."""
        with self.db:
            if not self.db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
                raise KeyError(run_id)
            return self._event(run_id, kind, node_id, payload)

    def _event(self, run_id: str, kind: str, node_id: str | None, payload: dict[str, Any],
              *, duration_ms: float | None = None) -> Event:
        cursor = self.db.execute(
            "INSERT INTO events(run_id, kind, node_id, payload_json, duration_ms) VALUES (?, ?, ?, ?, ?)",
            (run_id, kind, node_id, json.dumps(payload), duration_ms))
        return Event(cursor.lastrowid, kind, node_id, payload, duration_ms)

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> Event:
        return Event(row["sequence"], row["kind"], row["node_id"], json.loads(row["payload_json"]),
                     row["duration_ms"])

    def _has_cycle(self, run_id: str) -> bool:
        edges: dict[str, list[str]] = {}
        for row in self.db.execute("SELECT parent_id, child_id FROM edges WHERE run_id=?", (run_id,)):
            edges.setdefault(row["parent_id"], []).append(row["child_id"])
        seen, active = set(), set()
        def visit(nid: str) -> bool:
            if nid in active: return True
            if nid in seen: return False
            seen.add(nid); active.add(nid)
            cycle = any(visit(child) for child in edges.get(nid, ()))
            active.remove(nid)
            return cycle
        return any(visit(nid) for nid in edges)
