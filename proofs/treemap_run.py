"""Capture a real Treemap composition through the live S14Code + glc_v3 path.

Drives the ordinary HTTP surface a UI-only app uses — no in-process shortcut:

  1. POST /v1/agent/runs   respond_as="ui", a budget prompt that never says
                           "treemap"; the planner runs content -> compose_surface
  2. GET  /v1/runs/{id}/composed   the same tree re-validated on the way out

Then replays three hostile surfaces through the SAME validator that guards the
live path, one per invariant, to show the wall holds for the new component.

Writes treemap_run.json and prints a human table. Nothing here is imagined: if
Gemini does not reach for Treemap on its own, this script says so and fails.

    uv run s14code serve                      # 8113, needs glc_v3 on 8111
    uv run python proofs/treemap_run.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.runtime import _normalize_breakdown, _parse_json_object
from s13code.ui.validator import validate_surface

OUT = Path(__file__).parent / "treemap_run.json"
BASE = os.getenv("S14_BASE_URL", "http://127.0.0.1:8113").rstrip("/")

# Synthetic identity only — never a real tenant, user or project.
REQUEST: dict[str, object] = {
    "prompt": (
        "Create a visual monthly household budget for INR 120,000: rent 42,000, food 18,000, "
        "transport 10,000, savings 25,000, healthcare 8,000, utilities 9,000, and leisure 8,000. "
        "Make the dominant costs immediately obvious."
    ),
    "respond_as": "ui",
    "tenant_id": "course",
    "project_id": "s14-treemap",
    "user_id": "student-01",
    "agent_id": "assistant",
}

# The node ids / skills that carry the content role's structured answer. Mirrors
# the selection compose_surface itself makes in runtime.py.
_CONTENT_NODES = {"distill", "content", "answer"}
_CONTENT_SKILLS = {"distiller", "content"}


def start_run() -> dict:
    """POST the goal and return the full run report (graph, trace, events)."""
    response = httpx.post(f"{BASE}/v1/agent/runs", json=REQUEST, timeout=300)
    if response.status_code >= 400:
        raise RuntimeError(f"S14Code /v1/agent/runs {response.status_code}: {response.text[:300]}")
    return response.json()


def fetch_composed(run_id: str) -> dict:
    """GET the composed interface the way the render client does."""
    response = httpx.get(f"{BASE}/v1/runs/{run_id}/composed", timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"S14Code /v1/runs/{run_id}/composed {response.status_code}: {response.text[:300]}")
    return response.json()


def content_structured(nodes: dict) -> dict:
    """The structured answer the content role produced, before composition."""
    for node_id, node in sorted(nodes.items()):
        if node.get("skill") in _CONTENT_SKILLS or node_id in _CONTENT_NODES:
            structured = (node.get("result") or {}).get("structured")
            if isinstance(structured, dict):
                return structured
    return {}


def surface_node(nodes: dict) -> dict:
    """The compose_surface node's result: raw model text, accepted tree, verdict."""
    return (nodes.get("surface") or {}).get("result") or {}


def proposed_surface(node_result: dict) -> dict:
    """The tree Gemini actually emitted, parsed but not yet filtered.

    The node stores the model's raw text under ``raw_surface``; parsing it with
    the runtime's own parser is what the validator saw as input.
    """
    return _parse_json_object(node_result.get("raw_surface") or "") or {}


def agent_assignments(trace: dict) -> list[dict]:
    """Every node's agent, skill, state and the provider slot that served it."""
    return [
        {"node": node_id, "agent": entry.get("agent"), "skill": entry.get("skill"),
         "state": entry.get("state"), "provider": entry.get("provider"), "model": entry.get("model")}
        for node_id, entry in sorted((trace or {}).items())
    ]


def event_trace(events: list) -> list[dict]:
    """The ordered journal the AG-UI stream projects."""
    return [
        {"seq": index, "kind": event.get("kind"), "node": event.get("node_id")}
        for index, event in enumerate(events or [])
    ]


def _hostile(component: dict, data_model: dict | None = None) -> dict:
    return {
        "root": "root",
        "components": [{"id": "root", "type": "Column", "children": ["tree"]}, component],
        "dataModel": data_model if data_model is not None else {"breakdown": [
            {"label": "Rent", "value": 42000}, {"label": "Food", "value": 18000},
        ], "breakdown_unit": "INR"},
    }


def _clean_treemap() -> dict:
    return {"id": "tree", "type": "Treemap", "title": "Allocation", "data": {"$bind": "/breakdown"},
            "labelKey": "label", "valueKey": "value", "unit": {"$bind": "/breakdown_unit"}}


def verify_grounded_treemap(surface: dict, normalized: dict) -> None:
    """Require one rendered Treemap to bind the normalized content breakdown.

    The unit is optional end to end: runtime.py publishes /breakdown_unit only
    when the content role gave one, and the composer is told to bind unit only
    when that pointer is present. So a unitless breakdown must prove the pointer
    is absent and the Treemap omits ``unit`` — not that both are there.
    """
    unit = normalized["unit"]
    data_model = surface.get("dataModel")
    if not isinstance(data_model, dict):
        raise SystemExit(f"served surface has no dataModel object: {data_model!r}")

    expected_data = {"breakdown": normalized["items"], "breakdown_total": normalized["total"]}
    if unit:
        expected_data["breakdown_unit"] = unit
    # Project the breakdown keys only: the dataModel legitimately carries the
    # rest of the content role's output. Absent keys stay absent, so a missing
    # pointer and a stray one both read as a mismatch.
    observed_data = {
        key: data_model[key]
        for key in ("breakdown", "breakdown_total", "breakdown_unit")
        if key in data_model
    }
    if observed_data != expected_data:
        raise SystemExit(
            f"served dataModel does not match the normalized breakdown: "
            f"expected={expected_data!r}, observed={observed_data!r}"
        )

    components = surface.get("components")
    if not isinstance(components, list):
        raise SystemExit("accepted surface has no component list")
    by_id = {
        component.get("id"): component
        for component in components
        if isinstance(component, dict) and isinstance(component.get("id"), str)
    }
    root_id = surface.get("root")
    if root_id not in by_id:
        raise SystemExit(f"accepted surface dropped its root component {root_id!r}; nothing renders")
    reachable: set[str] = set()
    pending = [root_id]
    while pending:
        component_id = pending.pop()
        if not isinstance(component_id, str) or component_id in reachable:
            continue
        component = by_id.get(component_id)
        if not component:
            continue
        reachable.add(component_id)
        children = component.get("children")
        if isinstance(children, list):
            pending.extend(child for child in children if isinstance(child, str))

    expected_contract = {
        "data": {"$bind": "/breakdown"},
        "labelKey": "label",
        "valueKey": "value",
    }
    if unit:
        expected_contract["unit"] = {"$bind": "/breakdown_unit"}
    reachable_treemaps = [
        component for component_id, component in by_id.items()
        if component_id in reachable and component.get("type") == "Treemap"
    ]
    # Without a unit the pointer does not exist, and validator.py lets a missing
    # pointer through as a nullable binding — so a Treemap still binding it
    # renders no unit at all and is not grounded.
    if not any(
        all(component.get(field) == value for field, value in expected_contract.items())
        and (unit or "unit" not in component)
        for component in reachable_treemaps
    ):
        raise SystemExit(
            "accepted surface has no reachable Treemap grounded in /breakdown: "
            f"reachable_treemaps={reachable_treemaps!r}"
        )


def adversarial() -> list[dict]:
    """One hostile surface per invariant, judged by the live validator."""
    unknown_type = _hostile({"id": "tree", "type": "RawHtml", "html": "<script>steal()</script>"})

    bound_markup = _hostile(_clean_treemap(), {
        "breakdown": [{"label": "Rent", "value": 42000},
                      {"label": "<img src=x onerror=steal()>", "value": 18000}],
        "breakdown_unit": "INR",
    })

    smuggled_action = _hostile(_clean_treemap())
    smuggled_action["components"].append(
        {"id": "btn", "type": "Button", "label": "Export", "onPress": {"action": "exfiltrate_memory"}}
    )
    smuggled_action["components"][0]["children"] = ["tree", "btn"]

    cases = [
        (
            "catalog",
            "Treemap swapped for an uncatalogued RawHtml node",
            unknown_type,
            False,
            {"component_id": "tree", "field": "type", "invariant": "catalog",
             "reason": "unknown component type 'RawHtml'"},
            ["root"],
        ),
        ("data-not-code", "markup smuggled through the dataModel behind a $bind pointer",
         bound_markup, True,
         {"component_id": "tree", "field": "data", "invariant": "data-not-code",
          "reason": "bound value carries markup"},
         ["root"]),
        ("event", "an action the catalog never registered, riding beside a clean Treemap",
         smuggled_action, False,
         {"component_id": "btn", "field": "onPress", "invariant": "event",
          "reason": "unregistered action 'exfiltrate_memory'"},
         ["root", "tree"]),
    ]

    out = []
    for invariant, description, surface, newly_closed, expected_rejection, expected_survivors in cases:
        result = validate_surface(surface)
        rejections = [rejection.as_dict() for rejection in result.rejections]
        survivors = sorted(component["id"] for component in result.accepted)
        if rejections != [expected_rejection] or survivors != expected_survivors:
            raise SystemExit(
                f"{invariant} adversarial check failed: "
                f"expected_rejections={[expected_rejection]!r}, observed_rejections={rejections!r}, "
                f"expected_survivors={expected_survivors!r}, observed_survivors={survivors!r}"
            )
        out.append({
            "invariant": invariant,
            "attack": description,
            "refused": not result.ok,
            "rejections": rejections,
            "surviving_components": survivors,
            # True for the one attack this change newly defends against; the
            # pre-change validator only inspected inline literals, so a bound
            # value carrying markup reached the client. README documents the
            # git command that reproduces the before state.
            "newly_closed_by_this_change": newly_closed,
        })
    return out


def main() -> None:
    report = start_run()
    if report.get("status") != "completed":
        raise SystemExit(f"run did not complete: status={report.get('status')!r}")

    run_id = report["run_id"]
    nodes = report["graph"]["nodes"]
    node_result = surface_node(nodes)
    proposed = proposed_surface(node_result)
    if not proposed.get("components"):
        raise SystemExit("run produced no composed surface")

    composed = fetch_composed(run_id)
    accepted = composed["surface"]

    structured = content_structured(nodes)
    breakdown = structured.get("breakdown")
    normalized = _normalize_breakdown(breakdown)
    if not normalized:
        raise SystemExit("the content role produced no usable breakdown; nothing for Treemap to bind")

    types = sorted({component["type"] for component in accepted["components"]})
    if "Treemap" not in types:
        raise SystemExit(f"Gemini did not reach for Treemap unprompted; it composed {types}")
    verify_grounded_treemap(accepted, normalized)

    proof = {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request": REQUEST,
        "run_id": run_id,
        "provider": composed.get("provider") or report.get("provider"),
        "model": composed.get("model") or report.get("model"),
        "content_breakdown": breakdown,
        "normalized_breakdown": normalized,
        "raw_surface": proposed,
        "accepted_surface": accepted,
        # The runtime's own verdict, recorded verbatim rather than recomputed —
        # this is the judgement the live path actually acted on.
        "validator": node_result["validator"],
        "component_types": types,
        "agents": agent_assignments(report.get("trace", {}).get("agents", {})),
        "events": event_trace(report.get("events", [])),
        "adversarial": adversarial(),
    }

    OUT.write_text(json.dumps(proof, indent=2) + "\n")

    print(f"run {run_id}  provider={proof['provider']}  model={proof['model']}")
    print(f"prompt names 'treemap': {'treemap' in str(REQUEST['prompt']).casefold()}")
    print(f"breakdown: {len(normalized['items'])} parts, total {normalized['total']} {normalized['unit']}")
    print(f"validator: {proof['validator']['accepted']}/{proof['validator']['proposed']} accepted, "
          f"{proof['validator']['rejected']} rejected")
    print(f"types: {', '.join(types)}")
    print()
    print(f"{'invariant':<14} {'refused':<8} attack")
    for case in proof["adversarial"]:
        print(f"{case['invariant']:<14} {case['refused']!s:<8} {case['attack']}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
