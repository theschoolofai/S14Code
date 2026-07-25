"""Run a REAL end-to-end task through the S13 live-graph harness and capture proof
that Gemini reaches for the new HeatMap component on its own.

This is deliverable 3 of the HeatMap catalog contribution: catalog.py declares
HeatMap, both render clients draw it, and THIS script proves compose_surface's
generative loop offers it to a real model without ever naming it. The task
prompt below asks for a comparison across several numeric criteria and never
says "heatmap" or "matrix" -- those words appear nowhere in the prompt, and
compose_surface's own system/compose instructions (runtime.py) never mention
HeatMap either. The only way the word can reach the model is through the
catalog manifest every compose_surface call already sends, which is exactly
the claim catalog.py makes: "compose_surface reads the catalog and offers
[a component] to the model on its own."

The prompt is phrased to avoid _entity_list() matching (no comma/and-joined
capitalized phrases), so the run takes the single-goal compose_answer path
(content -> surface) rather than the multi-entity compose_research path --
only the content role's structured schema produces the `table` field that
_matrix_from_table() (runtime.py) turns into /matrix_rows, /matrix_columns,
/matrix_cells.

Run it with S13Code's environment (it owns faiss / a2a deps):

    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/heatmap_run.py

Writes proofs/heatmap_run.json.
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

from s13code.core.memory import MemoryScope
from s13code.gateway import GatewayClient
from s13code.runtime import S13Runtime

OUT = Path(__file__).parent / "heatmap_run.json"
TASK = ("Build a dashboard comparing four database index types by write throughput, "
        "read latency, and storage overhead, each scored 1 to 10.")


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s13-heatmap-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"provider (env)   : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"task             : {TASK}\n")
    assert "heatmap" not in TASK.lower() and "matrix" not in TASK.lower(), \
        "the prompt must never name the component under test"

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "heatmap", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        respond_as="ui",
        source_uri="proof://heatmap/compose_surface",
        source_author="s14-proof",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    events = [event.__dict__ for event in runtime.graph.events(result["run_id"])]
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    validator = surface_result.get("validator") or {}
    types_used = validator.get("component_types") or []

    proof = {
        "task": TASK,
        "task_names_the_component": False,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "heatmap_chosen_by_model": "HeatMap" in types_used,
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
            "skill": surface_node.get("skill"),
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "upstream_used": surface_result.get("upstream_used"),
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

    print("=== HEATMAP PROOF RUN SUMMARY ===")
    print(f"run_id             : {result['run_id']}")
    print(f"status             : {result['status']}   finished={result['graph']['finished']}")
    print(f"nodes              : {sorted(snapshot.nodes)}")
    print(f"surface provider   : {surface_result.get('provider')}  model={surface_result.get('model')}")
    print(f"validator          : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')} ok={validator.get('ok')}")
    print(f"types used         : {types_used}")
    print(f"HeatMap chosen     : {'HeatMap' in types_used}")
    print(f"dangling refs      : {validator.get('dangling_child_refs')}")
    print(f"\nwrote {OUT}")
    if "HeatMap" not in types_used:
        print("\nNOTE: the model did not reach for HeatMap this run. It was never told the "
              "name; re-running (or the backup prompt in the conversation) may produce a "
              "different composition -- that variance is the honest cost of not scripting it.")
    return 0 if surface_node.get("state") == "succeeded" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
