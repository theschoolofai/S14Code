"""HTTP + SSE UI surface, folded into the S13 runtime.

  GET  /v1/catalog                  the trusted component catalog
  GET  /v1/runs/{id}/surface        build + validate a declarative surface
  GET  /v1/runs/{id}/dashboard      build + validate the rich showcase dashboard
  GET  /v1/runs/{id}/events         AG-UI event stream over SSE
  GET  /v1/harness/surface          the real surface a recorded S13 harness composed
  POST /v1/validate                 validate an arbitrary surface (injection wall)
  POST /v1/action                   a validated user action (approve/reject/rerun)
  GET  /s/{id}                      the render client, pointed at a run

The data source is the runtime's own graph, read in-process off
``request.app.state.s13_runtime`` — the same attribute S13's ``GET
/v1/agent/runs/{id}`` route reads. No HTTP hop, no second service.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agui import run_data_model, state_snapshot, stream_agui
from .catalog import catalog_manifest
from .hitl import PendingAction, decide_resume
from .showcase import build_corpus_dashboard
from .surface import build_run_surface
from .validator import validate_surface

router = APIRouter()
_CLIENT = Path(__file__).parent / "client" / "index.html"


def _read_run(request: Request, run_id: str) -> dict:
    """Read one run from the runtime's in-process graph, in S13's journal shape.

    Mirrors S13's ``GET /v1/agent/runs/{id}``: ``{run_id, finished, nodes,
    edges, events}``. Events are ``Event(sequence, kind, node_id, payload)``
    dataclasses; convert to plain dicts so the UI builders see the same shape a
    recorded fixture carries.
    """
    runtime = request.app.state.s13_runtime
    try:
        snapshot = runtime.graph.snapshot(run_id)
    except KeyError:
        raise HTTPException(404, "run not found") from None
    events = [
        {"sequence": e.sequence, "kind": e.kind, "node_id": e.node_id, "payload": e.payload}
        for e in runtime.graph.events(run_id)
    ]
    return {
        "run_id": run_id,
        "finished": snapshot.finished,
        "nodes": snapshot.nodes,
        "edges": snapshot.edges,
        "events": events,
    }


@router.get("/v1/catalog")
async def catalog():
    return catalog_manifest()


@router.get("/v1/runs/{run_id}/surface")
async def surface(run_id: str, request: Request):
    run = _read_run(request, run_id)
    built = build_run_surface(run)
    result = validate_surface(built)
    # The builder's own surface is always clean; validating it here proves the
    # service treats even its own output as untrusted before serving.
    return {
        "run_id": run_id,
        "surface": {"root": built["root"], "components": result.accepted, "dataModel": built["dataModel"]},
        "rejections": [r.as_dict() for r in result.rejections],
    }


@router.get("/v1/runs/{run_id}/dashboard")
async def dashboard(run_id: str, request: Request):
    """Build the rich showcase dashboard from a corpus run, validated."""
    run = _read_run(request, run_id)
    built = build_corpus_dashboard(run)
    result = validate_surface(built)
    return {
        "run_id": run_id,
        "surface": {"root": built["root"], "components": result.accepted, "dataModel": built["dataModel"]},
        "component_count": len(result.accepted),
        "executable_nodes": len(result.rejections),
        "clean": result.ok,
    }


@router.get("/v1/runs/{run_id}/snapshot")
async def snapshot(run_id: str, request: Request):
    """The COMPLETE current data model as a single AG-UI STATE_SNAPSHOT event.

    A client that reconnects fetches this once and is whole, instead of replaying
    the entire event tape. The data model is the fold of the run's own AG-UI
    stream (``run_data_model``), so it is byte-identical to what a full delta
    replay would produce. We also build the run's surface in-process so the
    caller learns how many components that state renders into.
    """
    run = _read_run(request, run_id)
    built = build_run_surface(run)  # in-process graph read, same source as /surface
    data_model = run_data_model(run)
    return {
        "run_id": run_id,
        "event": state_snapshot(data_model),
        "component_count": len(built["components"]),
    }


@router.get("/v1/runs/{run_id}/events")
async def events(run_id: str, request: Request, reconnect: int = 0):
    run = _read_run(request, run_id)
    # On reconnect the stream leads with ONE STATE_SNAPSHOT carrying the full
    # current data model; the client rebuilds from that single frame rather than
    # folding every delta again. Normal (first-connect) streaming is unchanged.
    snap = run_data_model(run) if reconnect else None

    async def gen():
        for ev in stream_agui(run["events"], finished=run["finished"], snapshot=snap):
            yield f"data: {json.dumps(ev)}\n\n"
            await asyncio.sleep(0.25)  # pace the tape so a browser can render it

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/v1/harness/surface")
async def harness_surface():
    """Serve the real surface composed by a recorded S13 harness run.

    Reads ``proofs/harness_run.json`` and re-validates on serve, so what renders
    is provably the model's own output passed through the same wall that guards
    injection. The render client uses this to show the real harness output.
    """
    path = Path(__file__).resolve().parents[2] / "proofs" / "harness_run.json"
    if not path.exists():
        raise HTTPException(404, "harness_run.json not found — run proofs/harness_run.py first")
    data = json.loads(path.read_text())
    node = data["compose_surface_node"]
    acc = node["surface_accepted"]
    surface = {"root": acc["root"], "components": acc["components"], "dataModel": node["data_model"]}
    result = validate_surface(surface)
    return {
        "run_id": data.get("run_id"),
        "surface": surface,
        "component_count": len(result.accepted),
        "validator": {"proposed": len(surface["components"]), "accepted": len(result.accepted),
                      "rejected": len(result.rejections)},
        "clean": result.ok,
        "provider": node.get("provider"),
        "model": node.get("model"),
    }


class ValidateBody(BaseModel):
    surface: dict


@router.post("/v1/validate")
async def validate(body: ValidateBody):
    result = validate_surface(body.surface)
    return {
        "ok": result.ok,
        "accepted": [c.get("id") for c in result.accepted],
        "rejections": [r.as_dict() for r in result.rejections],
    }


class ActionBody(BaseModel):
    run_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    args: dict = Field(default_factory=dict)
    # In a live system the pending params come from the parked node in S13. For
    # the recorded demo the caller supplies them so the binding check is real.
    pending_params: dict = Field(default_factory=dict)
    pending_summary: str = ""


@router.post("/v1/action")
async def action(body: ActionBody):
    pending = PendingAction(body.run_id, body.node_id, body.pending_summary, body.pending_params)
    decision = decide_resume(pending, body.action, body.args)
    if not decision.allowed:
        # A tamper attempt is refused; the node stays waiting.
        raise HTTPException(409, decision.reason)
    return {"resumed": True, "node_id": body.node_id, "reason": decision.reason}


@router.get("/v1/runs/{run_id}/composed")
async def composed(run_id: str, request: Request):
    """The interface the agent COMPOSED for this run (the compose_surface node's
    output), re-validated. Distinct from /surface, which is the run's progress
    view. This is what a UI-only app renders."""
    run = _read_run(request, run_id)
    node = run["nodes"].get("surface") or {}
    res = node.get("result") or {}
    surf = res.get("surface") or {}
    if not surf.get("components"):
        raise HTTPException(404, "run has no composed interface (no compose_surface node)")
    result = validate_surface(surf)
    return {
        "run_id": run_id,
        "finished": run["finished"],
        "surface": {"root": surf.get("root"), "components": result.accepted,
                    "dataModel": res.get("data_model") or surf.get("dataModel") or {}},
        "component_count": len(result.accepted),
        "clean": result.ok,
        "provider": res.get("provider"),
        "model": res.get("model"),
    }


@router.get("/s/{run_id}", response_class=HTMLResponse)
async def client(run_id: str):
    if not _CLIENT.exists():
        raise HTTPException(500, "render client missing")
    return _CLIENT.read_text().replace("__RUN_ID__", run_id)


@router.get("/app", response_class=HTMLResponse)
@router.get("/app/", response_class=HTMLResponse)
async def app_viewer():
    """A bare-minimal UI-only app shell: it starts a run, renders the composed
    interface, and turns a tap into the next turn. The protocol does the work."""
    path = Path(__file__).parent / "client" / "app.html"
    if not path.exists():
        raise HTTPException(500, "app viewer missing")
    return path.read_text(encoding="utf-8")
