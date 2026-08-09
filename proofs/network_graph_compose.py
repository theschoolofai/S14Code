"""Live proof: Gemini composes NetworkGraph without being told the type name.

Runs a real S13Runtime graph (content → compose_surface) through glc_v3/Gemini.
The prompt never contains the string ``NetworkGraph``; the content role emits
nodes/edges, and compose_surface offers the catalog so the model picks the type.

    GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
      uv run python proofs/network_graph_compose.py

Writes proofs/network_graph_compose.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

S14 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S14))

from s13code.core.memory import MemoryScope
from s13code.gateway import GatewayClient
from s13code.runtime import S13Runtime

OUT = Path(__file__).parent / "network_graph_compose.json"

# Deliberately does NOT name NetworkGraph — relationship language only.
TASK = (
    "Compose a UI that shows how these software job roles relate by shared skills "
    "as a network of connections: Backend Engineer, Frontend Engineer, Data Engineer, "
    "ML Engineer, and DevOps Engineer. Prefer a relationship network of the roles "
    "with weighted links for skill overlap."
)


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")
    os.environ.setdefault("S14_SURFACE_MAX_TOKENS", "12000")
    # Proof needs the graph + Gemini only; episode embedding stays offline.
    os.environ.setdefault("S13_EMBEDDER", "deterministic")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-network-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"data dir : {data_dir}")
    print(f"gateway  : {gateway.base_url}")
    print(f"provider : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"task     : {TASK}\n")
    assert "NetworkGraph" not in TASK, "proof prompt must not name the component"

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "network-graph", "student-01", "assistant"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://network_graph/compose",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    events = [event.__dict__ for event in runtime.graph.events(result["run_id"])]
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    surface = surface_result.get("surface") or {}
    types_used = sorted({c.get("type") for c in surface.get("components", []) if c.get("type")})
    used_network = "NetworkGraph" in types_used

    proof = {
        "task": TASK,
        "prompt_contains_NetworkGraph": "NetworkGraph" in TASK,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "graph": {
            "finished": result["graph"]["finished"],
            "nodes": {
                nid: {
                    "skill": node["skill"],
                    "state": node["state"],
                    "agent": node.get("metadata", {}).get("agent", node["skill"]),
                    "provider": (node.get("result") or {}).get("provider"),
                    "model": (node.get("result") or {}).get("model"),
                }
                for nid, node in snapshot.nodes.items()
            },
            "edges": [list(edge) for edge in snapshot.edges],
        },
        "event_journal": [
            {"sequence": e["sequence"], "kind": e["kind"], "node_id": e["node_id"]}
            for e in events
        ],
        "compose_surface_node": {
            "id": "surface",
            "skill": surface_node.get("skill"),
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "validator": surface_result.get("validator"),
            "component_types": types_used,
            "used_NetworkGraph": used_network,
            "data_model_keys": sorted((surface_result.get("data_model") or {}).keys()),
            "surface_accepted": surface,
            "raw_surface": surface_result.get("raw_surface"),
        },
        "full_events": events,
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    await gateway.close()
    runtime.close()

    print("=== NETWORK GRAPH COMPOSE SUMMARY ===")
    print(f"run_id     : {result['run_id']}")
    print(f"status     : {result['status']}")
    print(f"types used : {types_used}")
    print(f"NetworkGraph composed (unprompted by name): {used_network}")
    print(f"wrote {OUT}")
    return 0 if surface_node.get("state") == "succeeded" and used_network else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
