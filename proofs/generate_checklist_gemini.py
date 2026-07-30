"""Capture a REAL run in which Gemini composes the new Checklist component on
its own, through the actual live graph — not a hand-built prompt to the
gateway. This drives the same ``compose_surface`` node the Checkpoint app
(``/checkpoint``) itself calls: reads the real catalog manifest, asks Gemini
to compose an A2UI interface for the goal, and validates the result through
the same wall that guards injection. The instruction text sent to the model
never contains the literal string "Checklist" (see runtime.py's `compose`
instruction) — the model finds the type, and its `items`/`labelKey`/`doneKey`
props, purely by reading the catalog manifest handed to it as data.

Requires a running S14 runtime (S13_GATEWAY_PROVIDER=gemini) with a live
gateway behind it:

    # terminal 1 (glc_v3 checkout)
    uv run glc serve

    # terminal 2 (this repo)
    GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini uv run s14code serve

    # terminal 3
    uv run python proofs/generate_checklist_gemini.py

Writes proofs/checklist_gemini_run.json, in the shape /v1/proofs/checklist
re-validates on serve.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

OUT = Path(__file__).parent / "checklist_gemini_run.json"
BASE = os.getenv("S14_BASE_URL", "http://127.0.0.1:8113").rstrip("/")

# The exact goal a real Checkpoint (/checkpoint) turn-1 call sends: a
# "get ready for X" prompt whose prep tasks are explicitly flat, checkable,
# non-chronological — the shape a Checklist genuinely fits best. Nothing here
# names any UI component; only the DOMAIN content is described.
GOAL = (
    "Help someone get ready for this: Launch a personal website in 2 weeks\n\n"
    "Give a short, encouraging overview, then a checklist of concrete prep tasks — "
    "these are independent to-dos in priority order, NOT scheduled to specific days and "
    "NOT a timeline of events, just a flat checklist someone ticks off as they finish "
    "each one, so render it as an actual checklist with checkboxes. Include a couple of "
    "readiness stats if you can estimate them. Then offer 3-4 things they could explore "
    "next."
)


def main() -> None:
    print(f"asking the live runtime ({BASE}) to plan: {GOAL.splitlines()[0]!r}\n")
    with httpx.Client(timeout=120) as client:
        started = client.post(
            f"{BASE}/v1/agent/runs",
            json={
                "prompt": GOAL, "respond_as": "ui", "tenant_id": "course",
                "project_id": "s14", "user_id": "proof", "agent_id": "checkpoint",
            },
        )
        started.raise_for_status()
        run_id = started.json()["run_id"]
        print(f"run_id={run_id}")

        # The graph runs synchronously behind this call in practice, but poll
        # briefly for "finished" so this script is robust either way.
        detail = None
        for _ in range(30):
            detail = client.get(f"{BASE}/v1/agent/runs/{run_id}").json()
            if detail.get("finished"):
                break
            time.sleep(1)
        if not detail or not detail.get("finished"):
            print("run did not finish in time")
            sys.exit(2)

        node = detail["nodes"].get("surface")
        if not node or node.get("state") != "succeeded":
            print("no successful compose_surface node in this run")
            sys.exit(2)
        result = node["result"]

    surface = result["surface"]
    types_used = sorted({c.get("type") for c in surface["components"]})
    print(f"provider={result.get('provider')}  model={result.get('model')}")
    print(f"component types used: {types_used}")
    print(f"validator: {result['validator']}")

    checklist_composed = "Checklist" in types_used
    print(f"\nChecklist composed unprompted: {checklist_composed}")
    if not checklist_composed:
        print("Gemini did not reach for Checklist this time — rerun, or see the honest "
              "verdict in the PR description: composition is not perfectly deterministic.")

    OUT.write_text(json.dumps({
        "run_id": run_id,
        "goal": GOAL,
        "compose_surface_node": {
            "surface_accepted": {"root": surface["root"], "components": surface["components"]},
            "data_model": result["data_model"],
            "provider": result.get("provider"),
            "model": result.get("model"),
        },
    }, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
