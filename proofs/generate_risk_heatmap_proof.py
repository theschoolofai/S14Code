"""Run a REAL end-to-end risk-vs-opportunity task and capture the unprompted
composition proof — the agent picks RiskHeatmap on its own, without being told.

This is the same harness as proofs/harness_run.py, pointed at a comparison task.
The compose_surface skill builds a generic data model from the real upstream
research outcomes, then asks the model to compose an A2UI interface for the goal
against that data model. The model chooses RiskHeatmap autonomously; the
validator accepts it because it is a real catalog type.

Run it with S13Code's environment (it owns faiss / a2a deps):

    cd EAGV3/S13/S13Code
    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python ../../S14/S14Code/proofs/generate_risk_heatmap_proof.py

Writes EAGV3/S14/S14Code/proofs/risk_heatmap_composition.json.
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

OUT = Path(__file__).parent / "risk_heatmap_composition.json"
TASK = "Compare these three companies on risk versus opportunity: Stripe, Plaid, Brex"


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-risk-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"provider (env)   : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"task             : {TASK}\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "risk", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://risk/compose_surface",
        source_author="s14-proof",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}

    proof = {
        "task": TASK,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_provider": os.getenv("S13_GATEWAY_PROVIDER"),
        "graph": {
            "finished": result["graph"]["finished"],
            "nodes": {
                nid: {"skill": node["skill"], "state": node["state"]}
                for nid, node in snapshot.nodes.items()
            },
        },
        "compose_surface_node": {
            "id": "surface",
            "skill": surface_node.get("skill"),
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "validator": surface_result.get("validator"),
            "data_model": surface_result.get("data_model"),
            "surface_accepted": surface_result.get("surface"),
        },
    }
    OUT.write_text(json.dumps(proof, indent=2))

    await gateway.close()
    runtime.close()

    validator = surface_result.get("validator") or {}
    print("=== RISK HEATMAP COMPOSITION PROOF ===")
    print(f"run_id           : {result['run_id']}")
    print(f"status           : {result['status']}   finished={result['graph']['finished']}")
    print(f"surface provider : {surface_result.get('provider')}  model={surface_result.get('model')}")
    print(f"validator        : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')} ok={validator.get('ok')}")
    print(f"types used       : {validator.get('component_types')}")
    print(f"\nwrote {OUT}")
    return 0 if surface_node.get("state") == "succeeded" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))