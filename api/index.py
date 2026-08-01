"""The hosted Trading Systems Academy.

This is the Vercel entrypoint for the Part 2 application. It exists because the
full runtime cannot run on a serverless host, and it is careful about which parts
it keeps and which it drops.

KEPT — everything the assignment's invariants live in, imported from the repo, not
reimplemented:

  * ``s13code.ui.catalog``   the trusted 25-type catalog and the registered actions
  * ``s13code.ui.validator`` the injection wall, unmodified
  * ``s13code.ui.compose``   the content-role schema, the compose system prompt,
                             the compose instruction, and the data-model builder
  * ``s13code/ui/client/academy.html``  the same page, the same renderers

DROPPED, and why:

  * the live task graph and its journal — a serverless request has no durable
    process to own them, and the Academy never needed cross-request state anyway:
    the conversation trail is client-side and each turn is a fresh composition;
  * FAISS memory, semantic chunking and the A2A gRPC server — 130 MB of wheels
    and a long-lived listener, neither of which a 250 MB function with one port
    can host;
  * the planner's self-correction node — it costs a third model call, and two
    already sit close to the 60 s ceiling.

So: the boundary is the real one, the composer is the real one, the prompts are
byte-identical to the local run. What the hosted page does NOT demonstrate is the
graph, and the README and PR say so plainly rather than letting the URL imply it.

A turn is split across two requests — ``/api/content`` then ``/api/compose`` —
because each is one model call of 10-30 s and Vercel caps a function at 60 s.
Doing both in one request times out; the browser chains them instead.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from s13code.ui.catalog import catalog_manifest
from s13code.ui.compose import (
    COMPOSE_SYSTEM,
    CONTENT_SCHEMA_SYSTEM,
    build_compose_instruction,
    merge_content_into_data_model,
    parse_json_object,
)
from s13code.ui.validator import validate_surface

GLC_BASE_URL = os.getenv("GLC_BASE_URL", "").rstrip("/")
CONTENT_MAX_TOKENS = int(os.getenv("S13_MAX_TOKENS", "6000"))
SURFACE_MAX_TOKENS = int(os.getenv("S14_SURFACE_MAX_TOKENS", "20000"))
CLIENT = ROOT / "s13code" / "ui" / "client" / "academy.html"

app = FastAPI(title="Trading Systems Academy (hosted)")


async def _chat(prompt: str, system: str, max_tokens: int) -> dict[str, Any]:
    """One gateway call. The app holds no provider credential; it knows a URL."""
    if not GLC_BASE_URL:
        return {"error": "GLC_BASE_URL is not configured on this deployment"}
    payload = {"messages": [{"role": "user", "content": prompt}], "system": system,
               "max_tokens": max_tokens, "temperature": 0, "reasoning": "off",
               "agent": "s14_hosted_academy", "provider": "gemini"}
    async with httpx.AsyncClient(timeout=55) as client:
        try:
            response = await client.post(f"{GLC_BASE_URL}/v1/chat", json=payload)
        except Exception as error:                                        # noqa: BLE001
            return {"error": f"gateway unreachable: {type(error).__name__}"}
    if response.status_code == 429:
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        return {"error": body.get("detail") or "the demo's free-tier quota is spent", "quota": True}
    if response.status_code >= 400:
        return {"error": f"gateway HTTP {response.status_code}"}
    body = response.json()
    return {"text": body.get("text", ""), "provider": body.get("provider"), "model": body.get("model")}


def _notice_surface(message: str) -> dict[str, Any]:
    """An honest interface for a turn that could not be composed.

    The same discipline the runtime applies to missing evidence: say what is not
    available in a real catalog component, rather than drawing something that
    implies an answer exists.
    """
    return {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["h", "n"]},
            {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            {"id": "n", "type": "Notice", "text": {"$bind": "/notice"}, "tone": "warn"},
        ],
        "dataModel": {"title": "This turn could not be composed",
                      "notice": message + " Nothing was invented to fill the gap."},
    }


class TurnBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


class ComposeBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    dataModel: dict = Field(default_factory=dict)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "s14-hosted-academy",
            "gateway_configured": bool(GLC_BASE_URL),
            "catalog_types": len(catalog_manifest()["components"])}


@app.get("/v1/catalog")
async def catalog():
    """The same trusted catalog the local runtime serves."""
    return catalog_manifest()


@app.post("/api/content")
async def content(body: TurnBody):
    """Step 1 of a turn: the content role's generic structured answer -> a data model."""
    result = await _chat(body.goal, CONTENT_SCHEMA_SYSTEM, CONTENT_MAX_TOKENS)
    if "error" in result:
        return JSONResponse({"error": result["error"], "quota": result.get("quota", False)},
                            status_code=503)
    structured = parse_json_object(result.get("text", "")) or {}
    data_model: dict[str, Any] = {"title": body.goal, "goal": body.goal,
                                  "summary": "", "progress_value": 1, "progress_max": 2}
    merge_content_into_data_model(data_model, structured)
    if not data_model.get("summary"):
        data_model["summary"] = data_model.get("intro") or body.goal
    return {"dataModel": data_model, "structured_keys": sorted(structured),
            "model": result.get("model"), "provider": result.get("provider")}


@app.post("/api/compose")
async def compose(body: ComposeBody):
    """Step 2 of a turn: the model composes a surface; the wall checks it."""
    data_model = dict(body.dataModel or {})
    data_model["progress_value"] = 2
    instruction = build_compose_instruction(body.goal, catalog_manifest(), data_model)
    result = await _chat(json.dumps(instruction), COMPOSE_SYSTEM, SURFACE_MAX_TOKENS)
    if "error" in result:
        surface = _notice_surface(result["error"] + ".")
        return {"surface": surface, "component_count": len(surface["components"]),
                "clean": True, "degraded": True,
                "validator": {"proposed": 0, "accepted": len(surface["components"]),
                              "rejected": 0, "rejections": []}}

    proposed = parse_json_object(result.get("text", ""))
    if not isinstance(proposed, dict) or not proposed.get("components"):
        surface = _notice_surface("The composer did not return a parseable interface.")
        return {"surface": surface, "component_count": len(surface["components"]),
                "clean": True, "degraded": True, "model": result.get("model"),
                "validator": {"proposed": 0, "accepted": len(surface["components"]),
                              "rejected": 0, "rejections": []}}

    # The injection wall, unmodified, exactly as the local runtime applies it.
    validation = validate_surface(proposed)
    surface = {"root": proposed.get("root", "root"),
               "components": validation.accepted, "dataModel": data_model}
    return {
        "surface": surface,
        "component_count": len(validation.accepted),
        "clean": validation.ok,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "validator": {
            "proposed": len(proposed.get("components", [])),
            "accepted": len(validation.accepted),
            "rejected": len(validation.rejections),
            "rejections": [rejection.as_dict() for rejection in validation.rejections],
        },
    }


@app.post("/v1/validate")
async def validate(payload: dict):
    """The injection wall, callable directly — the same route the runtime exposes."""
    result = validate_surface(payload.get("surface") or {})
    return {"ok": result.ok, "accepted": [c.get("id") for c in result.accepted],
            "rejections": [r.as_dict() for r in result.rejections]}


@app.get("/", response_class=HTMLResponse)
@app.get("/academy", response_class=HTMLResponse)
async def academy():
    """The same page as the local /academy, told to drive the two-step turn."""
    return CLIENT.read_text(encoding="utf-8").replace("__TURN_MODE__", "hosted")
