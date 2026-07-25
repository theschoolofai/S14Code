"""Capture a REAL run where Gemini composes the new `Rating` catalog
component into a live interface, without compose_surface's prompt ever
naming it — it is offered to the model only via the catalog manifest and a
generic, non-naming instruction clause for the /ratings data shape (see
`# --- S14 additive` in s13code/runtime.py, the `compose` instruction's
"for /ratings (a bounded 0-5 quality/confidence score per item...)" clause).
This mirrors harness_run.py / calendar_proof.py exactly, with a task phrased
to invite a per-item confidence/evidence display without ever saying
"rating" or "stars".

Run it with S13Code's environment (glc_v3 must be running on 8111):

    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/rating_proof.py

Writes proofs/rating_proof.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s13code.core.memory import MemoryScope  # noqa: E402
from s13code.gateway import GatewayClient  # noqa: E402
from s13code.runtime import S13Runtime  # noqa: E402
from s13code.ui.catalog import COMPONENTS  # noqa: E402

OUT = Path(__file__).parent / "rating_proof.json"
TASK = "Compare the safety records of Tesla, Ford, and Toyota."


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s13-rating-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"provider (env)   : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"task             : {TASK}\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "rating", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://rating/compose_surface",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    events = [event.__dict__ for event in runtime.graph.events(result["run_id"])]
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    validator = surface_result.get("validator") or {}
    types_used = validator.get("component_types") or []

    proof = {
        "task": TASK,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "new_component": "Rating",
        "rating_in_catalog": "Rating" in COMPONENTS,
        "rating_named_in_prompt": False,  # verified by the regression test in tests/test_s14_ui.py
        "graph": {
            "finished": result["graph"]["finished"],
            "nodes": {
                nid: {"skill": node["skill"], "state": node["state"],
                      "agent": node.get("metadata", {}).get("agent", node["skill"]),
                      "provider": (node.get("result") or {}).get("provider"),
                      "model": (node.get("result") or {}).get("model")}
                for nid, node in snapshot.nodes.items()
            },
            "edges": [list(edge) for edge in snapshot.edges],
        },
        "event_journal": [{"sequence": e["sequence"], "kind": e["kind"], "node_id": e["node_id"]}
                          for e in events],
        "compose_surface_node": {
            "id": "surface",
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "parse_ok": surface_result.get("parse_ok"),
            "raw_surface": surface_result.get("raw_surface"),
            "validator": validator,
            "data_model": surface_result.get("data_model"),
            "surface_accepted": surface_result.get("surface"),
        },
        "full_events": events,
    }
    OUT.write_text(json.dumps(proof, indent=2))

    await gateway.close()
    runtime.close()

    print("=== RATING PROOF SUMMARY ===")
    print(f"run_id         : {result['run_id']}   status={result['status']}")
    print(f"surface state  : {surface_node.get('state')}")
    print(f"provider/model : {surface_result.get('provider')} / {surface_result.get('model')}")
    print(f"validator      : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')} ok={validator.get('ok')}")
    print(f"types used     : {types_used}")
    print(f"Rating used    : {'Rating' in types_used}")
    print(f"\nwrote {OUT}")
    return 0 if ("Rating" in types_used and validator.get("ok")) else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
