"""Capture a REAL end-to-end run where GEMINI composes the new Stepper component.

Same harness as harness_run.py (a real S13Runtime, the real live graph, the real
compose_surface skill), but it drives the exact "teach me X" single-goal path
that the S14 app viewer (client/app.html) sends for a level-1 topic — this is
the same request a real user typing into the app would produce, not a special
prompt built for this proof.

Nothing here tells the model to use "Stepper". The system + instruction prompt
compose_surface sends is completely unmodified: it never mentions the new
component by name. The model can only find it by reading the catalog manifest
that every compose_surface call already includes — the same channel every
other custom component (BarChart, Timeline, DataTable, ...) is offered
through. The topic is chosen only because it is naturally a short sequential
procedure, so a step wizard is the richest honest fit for the content the
content role actually produces (a "sections" list of ordered steps).

Run it with S14Code's environment, against a live glc_v3 gateway:

    GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
      uv run python proofs/generate_stepper_gemini.py

Writes proofs/stepper_gemini_run.json.
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

OUT = Path(__file__).parent / "stepper_gemini_run.json"

# The EXACT goal text the app viewer (client/app.html: buildGoal(), depth===1)
# sends for a level-1 topic — no mention of any component, catalog, or "Stepper".
TOPIC = "Change a flat tire on a car"
RULES = ("Give a short, clean title (a few words naming the subject matter, "
         "never mentioning levels, drill-downs or these instructions). Any subtopic "
         "choice you offer must be a short plain subtopic name only — no numbering, "
         "no \"Level\" prefix, no meta-commentary.")
GOAL = (TOPIC + "\n\nTeach this topic as a hierarchical drill-down lesson of up to 5 "
        "levels. This is level 1 of 5: give focused introductory teaching content for "
        "the topic overall, then ask the user to pick a subtopic of it to go deeper "
        "into next. " + RULES)


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s13-stepper-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"provider (env)   : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"goal             : {GOAL[:90]}...\n")

    result = await runtime.run(
        prompt=GOAL,
        scope=MemoryScope("s14-proof", "stepper", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://stepper/compose_surface",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    accepted = ((surface_result.get("surface") or {}).get("components")) or []
    types_used = sorted({c.get("type") for c in accepted})

    proof = {
        "topic": TOPIC,
        "goal": GOAL,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "compose_surface_node": {
            "id": "surface",
            "skill": surface_node.get("skill"),
            "state": surface_node.get("state"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "parse_ok": surface_result.get("parse_ok"),
            "raw_surface": surface_result.get("raw_surface"),
            "validator": surface_result.get("validator"),
            "data_model": surface_result.get("data_model"),
            "surface_accepted": surface_result.get("surface"),
        },
        "component_types_used": types_used,
        "stepper_composed_unprompted": "Stepper" in types_used,
    }
    OUT.write_text(json.dumps(proof, indent=2))

    await gateway.close()
    runtime.close()

    validator = surface_result.get("validator") or {}
    print("=== STEPPER CAPTURE SUMMARY ===")
    print(f"run_id           : {result['run_id']}")
    print(f"status           : {result['status']}")
    print(f"surface provider : {surface_result.get('provider')}  model={surface_result.get('model')}")
    print(f"validator        : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')} ok={validator.get('ok')}")
    print(f"types used       : {types_used}")
    print(f"catalog knows Stepper : {'Stepper' in COMPONENTS}")
    print(f"Stepper composed, unprompted : {'Stepper' in types_used}")
    print(f"\nwrote {OUT}")
    return 0 if surface_node.get("state") == "succeeded" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
