"""Map S13 graph journal events onto AG-UI events.

The Session 13 graph already records a durable, ordered journal. AG-UI is
CopilotKit's event-based agent-UI protocol. We do not invent a stream; we
translate the one that exists into AG-UI's vocabulary so a browser can render
it. The S13 event shape is ``{sequence, kind, node_id, payload}``.

AG-UI event names use SCREAMING_SNAKE_CASE. We use the handful the surface
needs and leave the rest of the ~30-event protocol available:

  run_started    -> RUN_STARTED
  graph_patched  -> STATE_DELTA          (the graph structure changed)
  task_started   -> STEP_STARTED
  task_succeeded -> STEP_FINISHED (+ STATE_DELTA with the node result)
  task_failed    -> STEP_FINISHED (error) + RUN_ERROR
  task_cancelled -> CUSTOM (step_cancelled)
  run_resumed    -> CUSTOM (run_resumed)

RUN_FINISHED is not a journal event in S13 (finished is a run flag), so it is
derived from the snapshot after the last event rather than invented. That is
the honest mapping: we emit exactly what the graph recorded plus one derived
terminal event.

STATE_SNAPSHOT vs STATE_DELTA
-----------------------------
AG-UI draws a sharp line between the two. A ``STATE_DELTA`` carries one
incremental change; a client stays whole only by folding every delta in order
from the run's start. A ``STATE_SNAPSHOT`` carries the COMPLETE current state,
so a client that dropped its connection can rebuild in a single message instead
of replaying the whole tape. Here the "state" is the run's own data model: the
``/results/<node>`` map the task_succeeded deltas write, plus the graph patches.
``replay_state`` is the reducer that folds a stream into that model;
``run_data_model`` is the same fold over a whole run; ``state_snapshot`` wraps a
complete data model as the single event a reconnecting client needs.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

_KIND_TO_AGUI = {
    "run_started": "RUN_STARTED",
    "run_resumed": "CUSTOM",
    "graph_patched": "STATE_DELTA",
    "task_started": "STEP_STARTED",
    "task_succeeded": "STEP_FINISHED",
    "task_failed": "STEP_FINISHED",
    "task_cancelled": "CUSTOM",
}


def to_agui_event(s13_event: dict) -> dict:
    """Translate one S13 journal event into one AG-UI event."""
    kind = s13_event["kind"]
    node = s13_event.get("node_id")
    payload = s13_event.get("payload") or {}
    seq = s13_event["sequence"]
    name = _KIND_TO_AGUI.get(kind, "CUSTOM")

    base = {"type": name, "seq": seq, "source_kind": kind}

    if kind == "run_started":
        return {**base}
    if kind == "graph_patched":
        return {**base, "delta": {"op": "graph_patched", "reason": payload.get("reason", ""),
                                  "trigger": payload.get("trigger_event")}}
    if kind == "task_started":
        return {**base, "stepName": node}
    if kind == "task_succeeded":
        # Two AG-UI meanings: the step finished, and the data model gained the
        # node's result. We fold the STATE_DELTA into the same event so the
        # client patches its data model at /results/<node>.
        return {**base, "stepName": node, "delta": {"op": "add", "path": f"/results/{node}", "value": payload}}
    if kind == "task_failed":
        return {**base, "stepName": node, "error": payload.get("error", "task failed")}
    if kind == "task_cancelled":
        return {**base, "custom": "step_cancelled", "stepName": node}
    if kind == "run_resumed":
        return {**base, "custom": "run_resumed"}
    return base


def empty_state() -> dict[str, Any]:
    """The zero value a client starts from before it has folded any delta."""
    return {"results": {}, "patches": []}


def apply_state_delta(state: dict, agui_event: dict) -> dict:
    """Fold one AG-UI event's ``delta`` into ``state`` in place, and return it.

    Only events that carry a ``delta`` move the data model:
      - ``{"op": "add", "path": "/results/<node>", "value": ...}`` sets the
        node's result. Re-applying the same node is idempotent (overwrite), so a
        replayed history never corrupts the map.
      - ``{"op": "graph_patched", ...}`` appends to the ordered patch log. This
        one is NOT idempotent — replaying it twice would double the log, which is
        exactly why a reconnecting client must seed from a snapshot, not replay.
    Events without a delta (RUN_STARTED, STEP_STARTED, RUN_FINISHED) are state-
    neutral and pass through untouched.
    """
    delta = agui_event.get("delta")
    if not delta:
        return state
    op = delta.get("op")
    if op == "add" and isinstance(delta.get("path"), str) and delta["path"].startswith("/results/"):
        node = delta["path"][len("/results/"):]
        state["results"][node] = delta.get("value")
    elif op == "graph_patched":
        state["patches"].append({"reason": delta.get("reason", ""), "trigger": delta.get("trigger")})
    return state


def replay_state(agui_events: Iterable[dict], *, state: dict | None = None) -> dict:
    """Fold a stream of AG-UI events into a complete data model."""
    state = empty_state() if state is None else state
    for ev in agui_events:
        apply_state_delta(state, ev)
    return state


def run_data_model(run: dict) -> dict:
    """The complete current data model for a run, as a reconnecting client would
    hold it: exactly the fold of the run's own AG-UI stream. Computing it this
    way (rather than reading nodes directly) guarantees the snapshot a client
    receives is byte-identical to the state a full delta replay would produce."""
    return replay_state(stream_agui(run["events"], finished=False))


def state_snapshot(surface_or_datamodel: dict, *, seq: int = 0) -> dict:
    """One AG-UI ``STATE_SNAPSHOT`` event carrying the COMPLETE data model.

    Accepts either a raw data model or a full surface (``{root, components,
    dataModel}``); from a surface it snapshots the bound ``dataModel``. This is
    the single frame a reconnecting client adopts wholesale instead of replaying
    every delta from the start of the run.
    """
    if {"components", "dataModel"} <= set(surface_or_datamodel):
        state = surface_or_datamodel["dataModel"]
    else:
        state = surface_or_datamodel
    return {"type": "STATE_SNAPSHOT", "seq": seq, "source_kind": "snapshot", "state": state}


def stream_agui(
    events: Iterable[dict], *, finished: bool, snapshot: dict | None = None
) -> Iterator[dict]:
    """Yield AG-UI events for a whole journal, then a derived RUN_FINISHED.

    When ``snapshot`` is given (a complete data model, i.e. a reconnect), a
    leading ``STATE_SNAPSHOT`` is emitted first so the client is whole after one
    frame; the normal event stream then resumes unchanged. With ``snapshot=None``
    the behaviour is exactly as before.
    """
    last_seq = 0
    if snapshot is not None:
        yield state_snapshot(snapshot)
    for ev in events:
        last_seq = ev["sequence"]
        yield to_agui_event(ev)
    if finished:
        yield {"type": "RUN_FINISHED", "seq": last_seq + 1, "source_kind": "derived"}
