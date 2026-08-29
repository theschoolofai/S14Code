"""Capture a REAL multi-turn Wayfarer (trip planner) conversation, live.

Session 14, Part 2: a UI-only application built on the existing architecture
with no backend changes — same S13Runtime, same compose_surface skill, same
catalog/validator, same real Gemini calls through glc_v3 that Part 1's
harness proofs use. This script drives the exact goal-building logic
``client/trip.html`` drives over HTTP (mirrored here in Python: ``goal_safe``
and ``build_goal``), for THREE sequential turns, where each turn's goal is
built from a real choice made in the PREVIOUS turn's composed interface —
proving the four Part 2 requirements against a live model, not a mock:

  1. every turn answers as a composed, catalog-validated interface, never text,
  2. the richest component matches each turn's content shape,
  3. a turn's answer shapes the next turn's goal (tap becomes context),
  4. it runs end to end against the real gateway.

Run with a live gateway:

    GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
      uv run python proofs/generate_trip_gemini.py

Writes proofs/trip_gemini_run.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

S13CODE = Path(os.environ.get("S13CODE_PATH") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(S13CODE))

from s13code.core.memory import MemoryScope
from s13code.gateway import GatewayClient
from s13code.runtime import S13Runtime

OUT = Path(__file__).parent / "trip_gemini_run.json"

RULES = ("Give a short, clean title (just the destination or the specific thing being covered — never "
         "mentioning turns, this being a conversation, or these instructions). Any next-step choice you offer "
         "must be a short plain label only — no numbering, no meta-commentary.")


def goal_safe(text: str) -> str:
    """Mirrors client/trip.html's goalSafe(): runtime.py's _ENTITY_LIST heuristic
    (built to detect a real "compare A, B and C" prompt) misreads an ordinary
    "City, Country" destination as a two-entity comparison request and reroutes
    the run into the multi-entity research path instead of the single-goal
    content path this app needs. Neutralizing the comma is a client-side
    workaround, not a change to that shared heuristic."""
    return re.sub(r",\s*", " in ", text)


def build_goal(convo: list[str], max_turns: int = 6) -> str:
    turn = len(convo)
    trip = goal_safe(convo[0])
    if turn == 1:
        return (f"Plan a trip: {trip}\n\nGive a compelling short overview of the destination, then a day-by-day "
                "itinerary covering the whole trip — one entry per day, each with a short highlight; this is a "
                "real ordered sequence of days, so structure it that way. Include a few trip-level stats if you "
                "can reasonably estimate them (e.g. an approximate total budget, the number of days, a count of "
                "must-see highlights). Then offer the traveler 3-4 things they could explore next — for example a "
                "specific day in more detail, comparing accommodation options, local food recommendations, or a "
                f"packing list; choose whichever genuinely fit this trip. {RULES}")
    path = goal_safe(" › ".join(convo[1:]))
    picked = goal_safe(convo[-1])
    if turn < max_turns:
        return (f"The traveler is planning this trip: {trip}. So far in this planning conversation they've "
                f"chosen to explore: {path}. Give rich, useful detail specifically about \"{picked}\" — use "
                "whichever structure actually fits the content (a further day-by-day breakdown, a comparison "
                "table of options, a cost breakdown, a checklist, or whatever else fits) rather than one long "
                f"paragraph. Then offer 3-4 NEW things they could explore next — don't just repeat options "
                f"already picked. {RULES}")
    return (f"The traveler is planning this trip: {trip}. So far they've explored: {path}. This is the FINAL "
            f"turn of this planning session — give rich, useful detail specifically about \"{picked}\", then a "
            f"short concluding summary of the whole trip plan. Do not ask the user to pick anything further. "
            f"{RULES}")


def resolve(value: Any, data_model: dict[str, Any]) -> Any:
    if isinstance(value, dict) and "$bind" in value:
        return data_model.get(str(value["$bind"]).lstrip("/"))
    return value


def pick_button(components: list[dict], data_model: dict[str, Any], prefer: str | None) -> str | None:
    """Choose which Button to 'tap' for the next turn: the first whose label
    contains `prefer` (case-insensitive), else the first Button offered."""
    buttons = [c for c in components if c.get("type") == "Button"]
    labels = [str(resolve(b.get("label"), data_model) or "") for b in buttons]
    if prefer:
        for label in labels:
            if prefer.lower() in label.lower():
                return label
    return labels[0] if labels else None


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")
    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s13-trip-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"data dir : {data_dir}")
    print(f"gateway  : {gateway.base_url}\n")

    convo = ["5 days in Kyoto, Japan"]
    # Deliberately steer turn 2 toward an accommodation comparison (a table-
    # shaped ask); turn 3 takes whatever the interface actually offers next.
    prefer_for_next_turn = [None, "accommodation", None]
    turns: list[dict[str, Any]] = []

    for i in range(3):
        goal = build_goal(convo)
        result = await runtime.run(
            prompt=goal,
            scope=MemoryScope("s14-proof", "wayfarer", "composer", "s13code"),
            llm=lambda prompt, system: gateway.complete(prompt, system),
            source_uri="proof://wayfarer/compose_surface",
            source_author="s14-proof",
            respond_as="ui",
        )
        snapshot = runtime.graph.snapshot(result["run_id"])
        surface_node = snapshot.nodes.get("surface", {})
        surface_result = surface_node.get("result") or {}
        surface = surface_result.get("surface") or {}
        components = surface.get("components", [])
        data_model = surface_result.get("data_model") or {}
        types_used = sorted({c.get("type") for c in components})
        validator = surface_result.get("validator") or {}

        turns.append({
            "turn": i + 1,
            "goal": goal,
            "run_id": result["run_id"],
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "component_types_used": types_used,
            "validator": validator,
            "surface": {"root": surface.get("root"), "components": components, "dataModel": data_model},
        })
        print(f"turn {i + 1}: run_id={result['run_id']}")
        print(f"  types     : {types_used}")
        print(f"  validator : accepted={validator.get('accepted')} rejected={validator.get('rejected')} "
              f"ok={validator.get('ok')}")

        if i < 2:
            want = prefer_for_next_turn[i + 1]
            picked = pick_button(components, data_model, want)
            if not picked:
                print("  no Button choice found in this surface; stopping early")
                break
            print(f"  tapping   : {picked!r}")
            convo.append(picked)

    proof = {"domain": "trip planner (Wayfarer, Session 14 Part 2)", "conversation": convo, "turns": turns}
    OUT.write_text(json.dumps(proof, indent=2))

    await gateway.close()
    runtime.close()

    all_clean = all(t["validator"].get("rejected", 0) == 0 for t in turns)
    all_composed = all(t["component_types_used"] for t in turns)
    all_types: set[str] = set()
    for t in turns:
        all_types.update(t["component_types_used"])
    print(f"\nturns captured        : {len(turns)}")
    print(f"all turns clean        : {all_clean}")
    print(f"all turns composed UI  : {all_composed}")
    print(f"component types seen   : {sorted(all_types)}")
    print(f"conversation           : {' › '.join(convo)}")
    print(f"\nwrote {OUT}")
    return 0 if len(turns) >= 3 and all_clean and all_composed else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
