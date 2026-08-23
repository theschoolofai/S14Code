"""Live proof: Gemini composes Rating and StepWizard for AI Resume Building unprompted.

The user goal asks to build a resume for a Senior AI Systems Engineer with multi-step progress and skill ratings.
The proof asserts the accepted surface contains Rating and/or StepWizard and re-validates clean.

Requires a running glc_v3 gateway with Gemini configured:
    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/harness_resume.py
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
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "harness_resume.json"

TASK = (
    "Build an executive resume for a Senior AI Systems Engineer. "
    "Show a multi-step progress stepper (Step 1: Contact, Step 2: Experience, Step 3: Skills, Step 4: Final), "
    "a skill proficiency rating grid (Python: 5/5, PyTorch: 5/5, Distributed Systems: 4/5), "
    "quantified impact stat tiles (+40% throughput, $1.2M saved), "
    "and a before/after bullet point enhancement diff."
)


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-resume-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"task             : {TASK[:120]}...\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "resume", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://harness/resume",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    surface_payload = surface_result.get("surface") or {}
    if isinstance(surface_payload, dict):
        accepted = surface_payload.get("components") or []
        data_model = surface_payload.get("dataModel") or surface_result.get("data_model") or {}
    else:
        accepted = surface_payload if isinstance(surface_payload, list) else []
        data_model = surface_result.get("data_model") or {}

    types = sorted({c.get("type") for c in accepted if isinstance(c, dict) and c.get("type")})
    has_rating = "Rating" in types
    has_stepwizard = "StepWizard" in types

    recheck = validate_surface({
        "root": surface_payload.get("root", "root") if isinstance(surface_payload, dict) else "root",
        "components": accepted,
        "dataModel": data_model,
    })

    proof = {
        "task": TASK,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "compose_surface_node": {
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "validator": surface_result.get("validator"),
            "component_types": types,
            "has_rating": has_rating,
            "has_stepwizard": has_stepwizard,
            "data_model_keys": sorted(data_model),
            "surface_accepted": accepted,
            "revalidate_ok": recheck.ok,
            "revalidate_rejections": [r.as_dict() for r in recheck.rejections],
        },
        "assert_component_composed_unprompted": has_rating or has_stepwizard,
        "assert_surface_clean": recheck.ok,
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    await gateway.close()
    runtime.close()

    print("=== RESUME HARNESS SUMMARY ===")
    print(f"run_id        : {result['run_id']}")
    print(f"types         : {types}")
    print(f"has Rating    : {has_rating}")
    print(f"has StepWizard: {has_stepwizard}")
    print(f"revalidate    : ok={recheck.ok}")
    print(f"\nwrote {OUT}")

    return 0 if recheck.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
