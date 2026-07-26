"""Capture a REAL Gemini run where StepWizard is composed unprompted.

The task does not name StepWizard. compose_surface reads the catalog manifest
(which lists StepWizard) and the available_pointers (which include /steps when
the content node returns ordered sections). The compose instruction says:
  'for /steps render a StepWizard (steps bound to /steps, current bound to
   /current_step)'
Gemini picks it from the catalog on its own.

    GLC_BASE_URL=http://127.0.0.1:8111 S14_GATEWAY_PROVIDER=gemini \
      uv run python proofs/stepwizard_run.py

Writes proofs/stepwizard_run.json.
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

OUT = Path(__file__).parent / "stepwizard_run.json"

# Task does NOT mention StepWizard. "compose" triggers the compose_surface path;
# the step-by-step phrasing makes the content node return ordered sections →
# runtime.py derives /steps → compose_surface sees /steps in available_pointers
# and the compose hint says "for /steps render a StepWizard" → Gemini picks it.
TASK = (
    "Research and compose a step-by-step guide for applying for a Japan tourist visa: "
    "eligibility, required documents, application process, fees, and processing time."
)


async def main() -> int:
    os.environ.setdefault("S14_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-stepwizard-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)

    print(f"task     : {TASK}")
    print(f"provider : {os.getenv('S14_GATEWAY_PROVIDER')}\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "stepwizard", "composer", "s14code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://stepwizard/compose_surface",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    events = [e.__dict__ for e in runtime.graph.events(result["run_id"])]
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    validator = surface_result.get("validator") or {}

    # Check that StepWizard was actually used
    accepted = (surface_result.get("surface") or {}).get("components") or []
    types_used = sorted({c.get("type") for c in accepted if c.get("type")})
    stepwizard_used = "StepWizard" in types_used

    proof = {
        "task": TASK,
        "stepwizard_used_unprompted": stepwizard_used,
        "run_id": result["run_id"],
        "status": result["status"],
        "provider": surface_result.get("provider"),
        "model": surface_result.get("model"),
        "graph": {
            "finished": result["graph"]["finished"],
            "nodes": {
                nid: {
                    "skill": node["skill"],
                    "state": node["state"],
                    "agent": node.get("metadata", {}).get("agent", node["skill"]),
                    "provider": (node.get("result") or {}).get("provider"),
                }
                for nid, node in snapshot.nodes.items()
            },
            "edges": [list(e) for e in snapshot.edges],
        },
        "event_journal": [
            {"sequence": e["sequence"], "kind": e["kind"], "node_id": e["node_id"]}
            for e in events
        ],
        "compose_surface_node": {
            "skill": surface_node.get("skill"),
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "validator": validator,
            "types_used": types_used,
            "stepwizard_used": stepwizard_used,
            "data_model_keys": sorted(surface_result.get("data_model", {}).keys()),
            "steps_in_data_model": "steps" in (surface_result.get("data_model") or {}),
            "surface_accepted": surface_result.get("surface"),
            "data_model": surface_result.get("data_model"),
        },
    }

    OUT.write_text(json.dumps(proof, indent=2))
    await gateway.close()
    runtime.close()

    print("=== StepWizard captured run ===")
    print(f"run_id           : {result['run_id']}")
    print(f"status           : {result['status']}")
    print(f"provider         : {surface_result.get('provider')}  model={surface_result.get('model')}")
    print(f"nodes            : {sorted(snapshot.nodes)}")
    print(f"validator        : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')}")
    print(f"types used       : {types_used}")
    print(f"steps in model   : {'steps' in (surface_result.get('data_model') or {})}")
    print(f"StepWizard used  : {stepwizard_used}  ← key claim")
    print(f"\nwrote {OUT}")

    if not stepwizard_used:
        print("\nNOTE: Gemini did not use StepWizard this run.")
        print("This can happen when the content node returns no sections.")
        print("Re-run once or try a task with more explicit step structure.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
