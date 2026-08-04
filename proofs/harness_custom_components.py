"""Part 1 proof: Gemini reaches for Map / Calendar / Rating on its own.

This runs a REAL live-graph task (the same `S13Runtime` + `LiveGraphExecutor` +
gateway path as `harness_run.py`) with a prompt that describes a *situation* and
never a *component*. The word "Map", "Calendar" and "Rating" appear nowhere in the
prompt, nowhere in the compose system prompt, and nowhere in the compose
instruction — `compose_surface` sends the catalog manifest and a data model, and
the model has to notice that `Map.points`, `Calendar.events` and `Rating.value`
fit the shape of the data it is holding.

What is engineered here is DATA, not instructions: the content role may emit
`places` / `schedule` / `ratings`, and `compose_surface` exposes them as
`/map_points`, `/calendar_events` and `/ratings`. Which component draws them is
the model's decision, and the validator — not the model — decides what renders.

    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/harness_custom_components.py

Writes proofs/custom_component_run.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

S13CODE = Path(os.environ.get("S13CODE_PATH") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(S13CODE))

from s13code.core.memory import MemoryScope  # noqa: E402
from s13code.gateway import GatewayClient  # noqa: E402
from s13code.runtime import S13Runtime  # noqa: E402
from s13code.ui.catalog import COMPONENTS  # noqa: E402

# A situation, not an interface. No component type is named, and no UI verb tells
# the model which widget to reach for. Both defaults below describe a trip; the
# second leans on the dates because a month grid is what dated entries want, and
# a component only gets chosen when the data it fits is actually present.
TASK = os.environ.get("S14_TASK") or (
    "I am spending three days in Kyoto from 21 September 2026. Give me where to go on each "
    "of those days, roughly where those places sit geographically, and how well reviewed "
    "each place I would stay is."
)
OUT = Path(__file__).parent / (os.environ.get("S14_OUT") or "custom_component_run.json")

STUDENT_TYPES = {name for name, spec in COMPONENTS.items() if spec.source == "student-extension"}


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-custom-components-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"data dir      : {data_dir}")
    print(f"gateway base  : {gateway.base_url}")
    print(f"provider      : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"student types : {sorted(STUDENT_TYPES)}")
    print(f"task          : {TASK}\n")

    # respond_as="ui" is the only thing that says "answer as an interface". It does
    # not say WHICH interface.
    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "custom-components", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://harness/custom_components",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    events = [event.__dict__ for event in runtime.graph.events(result["run_id"])]
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    accepted = (surface_result.get("surface") or {}).get("components") or []
    data_model = surface_result.get("data_model") or {}

    types_used = sorted({comp.get("type") for comp in accepted})
    student_used = sorted(set(types_used) & STUDENT_TYPES)
    content_result = (snapshot.nodes.get("content", {}).get("result") or {})

    proof = {
        "task": TASK,
        "claim": ("the prompt, the compose system prompt and the compose instruction name no "
                  "component type; the model chose these from the catalog manifest alone"),
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "prompt_names_no_component": {
            name: (name.lower() in TASK.lower()) for name in sorted(STUDENT_TYPES)
        },
        "graph": {
            "finished": result["graph"]["finished"],
            "nodes": {
                nid: {"skill": node["skill"], "state": node["state"],
                      "provider": (node.get("result") or {}).get("provider"),
                      "model": (node.get("result") or {}).get("model")}
                for nid, node in snapshot.nodes.items()
            },
            "edges": [list(edge) for edge in snapshot.edges],
        },
        "event_journal": [{"sequence": e["sequence"], "kind": e["kind"], "node_id": e["node_id"]}
                          for e in events],
        # The data the model was holding, in the shapes that make the new types fit.
        "structured_shapes_offered": {
            "map_points": data_model.get("map_points"),
            "calendar_events": data_model.get("calendar_events"),
            "calendar_month": data_model.get("calendar_month"),
            "ratings": data_model.get("ratings"),
        },
        "content_structured": content_result.get("structured"),
        "compose_surface_node": {
            "id": "surface",
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "parse_ok": surface_result.get("parse_ok"),
            "raw_surface": surface_result.get("raw_surface"),
            "validator": surface_result.get("validator"),
            "data_model": data_model,
            "surface_accepted": surface_result.get("surface"),
        },
        "component_types": types_used,
        "new_component_types": student_used,
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    await gateway.close()
    runtime.close()

    validator = surface_result.get("validator") or {}
    print("=== CUSTOM COMPONENT RUN ===")
    print(f"run_id            : {result['run_id']}")
    print(f"status            : {result['status']}   finished={result['graph']['finished']}")
    print(f"nodes             : {sorted(snapshot.nodes)}")
    print(f"surface model     : {surface_result.get('provider')} / {surface_result.get('model')}")
    print(f"validator         : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')} ok={validator.get('ok')}")
    print(f"types used        : {types_used}")
    print(f"shapes offered    : "
          f"map_points={len(data_model.get('map_points') or [])} "
          f"calendar_events={len(data_model.get('calendar_events') or [])} "
          f"ratings={len(data_model.get('ratings') or [])}")
    print(f"STUDENT TYPES USED: {student_used or 'NONE — the model did not reach for them'}")
    print(f"\nwrote {OUT}")

    if surface_node.get("state") != "succeeded":
        return 3
    return 0 if student_used else 4  # 4: composed, but not with a new component


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
