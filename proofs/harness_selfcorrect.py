"""Prove the S13 live-graph planner is OUTCOME-AWARE and DOMAIN-AGNOSTIC: a weak
research outcome must EARN a CORRECTIVE re-research node, not flow to the UI.

Same real S13Runtime path as harness_run.py, but one designated subject's FIRST
research attempt returns EMPTY evidence flagged insufficient (gated by env:
S14_SELFCORRECT + S14_SELFCORRECT_SUBJECT). The DeterministicPlanner sees the
weak outcome, ADDS research_<subject>_retry with a reworded/stronger query, and
holds distill until the corrected evidence lands. The demo prompt below happens
to name three places, but NOTHING in the engine is population/city specific.

    cd EAGV3/S14/S14CodeBuild
    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      S14_SELFCORRECT=1 S14_SELFCORRECT_SUBJECT=Berlin \
      uv run python proofs/harness_selfcorrect.py

Writes proofs/harness_selfcorrect.json (NOT harness_run.json).
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
from s13code.runtime import S13Runtime, _weak_evidence

OUT = Path(__file__).parent / "harness_selfcorrect.json"
TASK = "Research the profiles of London, Berlin and Paris, then compose a comparison dashboard."


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")
    os.environ.setdefault("S14_SELFCORRECT", "1")
    os.environ.setdefault("S14_SELFCORRECT_SUBJECT", "Berlin")
    target = os.environ["S14_SELFCORRECT_SUBJECT"]

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s13-selfcorrect-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir     : {data_dir}")
    print(f"gateway base         : {gateway.base_url}")
    print(f"self-correct subject : {target}")
    print(f"task                 : {TASK}\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-selfcorrect", "harness", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://harness/self_correct",
        source_author="s14-selfcorrect",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    events = [event.__dict__ for event in runtime.graph.events(result["run_id"])]
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}

    # Per research node: the domain-agnostic evidence quality the PLANNER read
    # from that node's own outcome (exactly what the corrective gate inspects).
    research_readings = {}
    for nid, node in sorted(snapshot.nodes.items()):
        if node.get("skill") != "researcher":
            continue
        result_obj = node.get("result")
        research_readings[nid] = {
            "subject": (node.get("input") or {}).get("subject"),
            "query": (node.get("input") or {}).get("query"),
            "corrective_for": (node.get("input") or {}).get("corrective_for"),
            "state": node.get("state"),
            "weak_evidence_seen_by_planner": _weak_evidence(result_obj),
            "has_text": bool((result_obj or {}).get("text")),
            "hit_count": len((result_obj or {}).get("hits") or []),
        }

    # The corrective story for the target subject: weak original -> strong retry.
    original_id = next((nid for nid, r in research_readings.items()
                        if r["subject"] == target and not nid.endswith("_retry")), None)
    retry_id = next((nid for nid, r in research_readings.items() if nid.endswith("_retry")), None)
    before_after = {
        "target_subject": target,
        "original_node": original_id,
        "before_weak_evidence": research_readings.get(original_id, {}).get("weak_evidence_seen_by_planner"),
        "retry_node": retry_id,
        "after_weak_evidence": research_readings.get(retry_id, {}).get("weak_evidence_seen_by_planner"),
    }

    corrective_patches = [
        {"sequence": e["sequence"], "reason": e["payload"].get("reason"),
         "add": e["payload"].get("add"), "connect": e["payload"].get("connect")}
        for e in events if e["kind"] == "graph_patched"
        and any(str(a).endswith("_retry") for a in (e["payload"].get("add") or []))
    ]

    proof = {
        "task": TASK,
        "self_correct_subject": target,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "before_after": before_after,
        "research_readings": research_readings,
        "corrective_patches": corrective_patches,
        "graph": {
            "finished": result["graph"]["finished"],
            "nodes": {
                nid: {"skill": node["skill"], "state": node["state"],
                      "agent": node.get("metadata", {}).get("agent", node["skill"]),
                      "corrective_for": (node.get("input") or {}).get("corrective_for")}
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
            "validator": surface_result.get("validator"),
            "results": (surface_result.get("data_model") or {}).get("results"),
            "table_rows": (surface_result.get("data_model") or {}).get("table_rows"),
            "raw_surface": surface_result.get("raw_surface"),
            "surface_accepted": surface_result.get("surface"),
        },
        "full_events": events,
    }
    OUT.write_text(json.dumps(proof, indent=2))

    await gateway.close()
    runtime.close()

    print("=== SELF-CORRECT SUMMARY ===")
    print(f"run_id             : {result['run_id']}")
    print(f"status             : {result['status']}   finished={result['graph']['finished']}")
    print(f"nodes              : {sorted(snapshot.nodes)}")
    print(f"corrective patches : {len(corrective_patches)}")
    for reading_id, reading in research_readings.items():
        print(f"  {reading_id:26s} subj={reading['subject']!s:8s} "
              f"state={reading['state']:9s} weak={reading['weak_evidence_seen_by_planner']} "
              f"hits={reading['hit_count']}")
    print(f"\nBEFORE ({before_after['original_node']}): weak={before_after['before_weak_evidence']}  "
          f"-> AFTER ({before_after['retry_node']}): weak={before_after['after_weak_evidence']}")
    print("\n--- ordered event journal ---")
    for e in events:
        print(f"  {e['sequence']:>2} {e['kind']:<16} {e['node_id'] or ''}")
    print(f"\nwrote {OUT}")
    ok = (surface_node.get("state") == "succeeded"
          and len(corrective_patches) >= 1
          and before_after["before_weak_evidence"] is True
          and before_after["after_weak_evidence"] is False)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
