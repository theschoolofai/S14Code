"""Three different prompts, three different interfaces.

`trip_app_turns.py` proves the other half of the requirement: one goal carried
across three turns, where a tap shapes the next. This proves the first half —
that the *shape of the question* changes the interface, not just the depth of the
conversation. Three independent starting prompts in the same domain, one turn
each, no shared trail:

  1. a dated itinerary          -> places, dates and scores
  2. a three-city comparison    -> rows to compare
  3. a budget breakdown         -> a numeric series

Nothing tells the model which components to use. The interfaces differ because
the data differs.

Requires the runtime on 8113 and the gateway on 8111.

    uv run python proofs/three_prompts.py

Writes proofs/three_prompts.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

S13CODE = Path(os.environ.get("S13CODE_PATH") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(S13CODE))

OUT = Path(__file__).parent / "three_prompts.json"
BASE = os.getenv("S14_BASE_URL", "http://127.0.0.1:8113").rstrip("/")

PROMPTS = [
    {
        "name": "dated-itinerary",
        "prompt": ("Plan a five-day trip through Japan from 21 September 2026: what to do on each "
                   "date, roughly where those places sit geographically, how well reviewed each "
                   "place I would stay is, and what each day costs. Then let me choose which day to "
                   "open in detail."),
    },
    {
        "name": "city-comparison",
        "prompt": ("I have one week in November and I am deciding between Lisbon, Porto and Madrid. "
                   "Compare them on cost, weather and how walkable each one is."),
    },
    {
        "name": "budget-breakdown",
        "prompt": ("What will two weeks in Peru cost me, broken down by category, and how does each "
                   "category compare against the others?"),
    },
]


async def one_turn(client: httpx.AsyncClient, case: dict) -> dict:
    response = await client.post(f"{BASE}/v1/agent/runs", json={
        "prompt": case["prompt"], "respond_as": "ui", "tenant_id": "course",
        "project_id": "s14-trip", "user_id": "traveller-01", "agent_id": "wayfare"})
    response.raise_for_status()
    run_id = response.json()["run_id"]

    composed = await client.get(f"{BASE}/v1/runs/{run_id}/composed")
    if composed.status_code != 200:
        return {"name": case["name"], "prompt": case["prompt"], "run_id": run_id, "composed": False,
                "note": "no compose_surface node; nothing drawn and nothing invented"}
    body = composed.json()
    surface = body.get("surface") or {}
    components = surface.get("components") or []
    types = sorted({comp.get("type") for comp in components})
    return {
        "name": case["name"],
        "prompt": case["prompt"],
        "run_id": run_id,
        "composed": True,
        "provider": body.get("provider"),
        "model": body.get("model"),
        "component_count": body.get("component_count"),
        "clean": body.get("clean"),
        "component_types": types,
        # A single Text (with or without its wrapper) is the failure mode the
        # assignment calls out: one text blob dumped into one component.
        "is_only_text": types in (["Text"], ["Column", "Text"]),
        "data_pointers": sorted(surface.get("dataModel") or {}),
        "surface": surface,
    }


async def main() -> int:
    results = []
    async with httpx.AsyncClient(timeout=300) as client:
        print(f"runtime : {BASE}\n")
        for case in PROMPTS:
            print(f"--- {case['name']} ---")
            print(f"  {case['prompt'][:110]}…")
            turn = await one_turn(client, case)
            results.append(turn)
            if turn["composed"]:
                print(f"  run={turn['run_id']} components={turn['component_count']} clean={turn['clean']}")
                print(f"  types={turn['component_types']}")
            else:
                print(f"  {turn['note']}")
            print()

    composed = [r for r in results if r.get("composed")]
    type_sets = [tuple(r["component_types"]) for r in composed]
    proof = {
        "claim": ("three different questions in one domain produce three different interfaces; "
                  "no prompt names a component type"),
        "base_url": BASE,
        "prompts": results,
        "summary": {
            "prompts_sent": len(results),
            "all_composed": len(composed) == len(results),
            "distinct_interfaces": len(set(type_sets)),
            "no_prompt_produced_only_text": all(not r["is_only_text"] for r in composed),
            "all_clean": all(r.get("clean") for r in composed),
            "types_per_prompt": {r["name"]: r["component_types"] for r in composed},
            # What each interface reached for that the others did not.
            "types_unique_to_one_interface": sorted(
                t for t in set().union(*[set(s) for s in type_sets] or [set()])
                if sum(1 for s in type_sets if t in s) == 1),
        },
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    print("=== SUMMARY ===")
    for key, value in proof["summary"].items():
        print(f"{key:32}: {value}")
    print(f"\nwrote {OUT}")

    summary = proof["summary"]
    ok = (summary["all_composed"] and summary["distinct_interfaces"] == 3
          and summary["no_prompt_produced_only_text"] and summary["all_clean"])
    return 0 if ok else 7


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
