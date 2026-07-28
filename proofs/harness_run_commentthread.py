"""Run a REAL end-to-end task through the S13 live-graph harness and capture proof
that the new CommentThread component enters a live Gemini-composed surface on
its own.

Same harness as harness_run_map.py / harness_run_codediff.py, but a
single-goal, reviews-flavored prompt (no named entity list, so the run takes
the compose_answer path through the `content` role) that legitimately earns a
`comments` field in the content schema. The compose_surface prompt is NOT
told about CommentThread or /comments: it only ever gets the catalog manifest
and the available data pointers, exactly like every other component.
Whatever Gemini picks for /comments here is its own choice.

Run it with S13Code's environment (it owns faiss / a2a deps):

    cd S14Code
    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/harness_run_commentthread.py

Writes proofs/harness_run_commentthread.json.
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

OUT = Path(__file__).parent / "harness_run_commentthread.json"
TASK = "Build an interface showing customer reviews for a popular noise-cancelling headphone."


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s13-harness-commentthread-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"provider (env)   : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"task             : {TASK}\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "harness-commentthread", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://harness/compose_surface_commentthread",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    events = [event.__dict__ for event in runtime.graph.events(result["run_id"])]
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}

    proof = {
        "task": TASK,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
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
            "validator": surface_result.get("validator"),
            "data_model": surface_result.get("data_model"),
            "surface_accepted": surface_result.get("surface"),
        },
        "full_events": events,
    }
    OUT.write_text(json.dumps(proof, indent=2))

    await gateway.close()
    runtime.close()

    validator = surface_result.get("validator") or {}
    print("=== HARNESS RUN SUMMARY (CommentThread proof) ===")
    print(f"run_id           : {result['run_id']}")
    print(f"status           : {result['status']}   finished={result['graph']['finished']}")
    print(f"nodes            : {sorted(snapshot.nodes)}")
    print(f"surface provider : {surface_result.get('provider')}  model={surface_result.get('model')}")
    print(f"validator        : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')} ok={validator.get('ok')}")
    print(f"types used       : {validator.get('component_types')}")
    print(f"comments in dm   : {(surface_result.get('data_model') or {}).get('comments')}")
    print(f"commentthread?   : {'CommentThread' in (validator.get('component_types') or [])}")
    print(f"dangling refs    : {validator.get('dangling_child_refs')}")
    print(f"\nwrote {OUT}")
    return 0 if surface_node.get("state") == "succeeded" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
