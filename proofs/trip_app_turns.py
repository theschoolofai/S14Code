"""Part 2 proof: three turns of the trip planner, end to end against the gateway.

A screen recording cannot be tested, so this drives exactly the loop
``s13code/ui/client/trip.html`` drives, over the same HTTP surface:

    POST /v1/agent/runs   {prompt, respond_as: "ui"}
    GET  /v1/runs/{id}/composed        -> the validated component tree
    a tap on that tree becomes turn N+1's prompt

Turn 2's prompt is built from a tap the model's OWN turn-1 interface offered (the
first Button label, or the first Calendar date, or the first Rating), so the
conversation is genuinely shaped by the interface rather than by a script that
decided the path in advance. An action name the catalog never registered is
refused here exactly as the browser refuses it.

Requires the runtime on 8113 and the gateway on 8111.

    uv run python proofs/trip_app_turns.py

Writes proofs/trip_app_turns.json.
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

OUT = Path(__file__).parent / "trip_app_turns.json"
BASE = os.getenv("S14_BASE_URL", "http://127.0.0.1:8113").rstrip("/")

# The application's own phrasing. Asking to be offered a pick is an application
# decision, not an architectural one: a UI-only app has to hand the user somewhere
# to go next, and the model is the one that knows what the branches are.
GOAL = os.environ.get("S14_GOAL") or (
    "Plan a five-day trip through Japan from 21 September 2026: what to do on each date, "
    "roughly where those places sit geographically, how well reviewed each place I would stay "
    "is, and what each day costs. Then let me choose which day to open in detail."
)


def _first_tap(components: list[dict], data_model: dict) -> dict | None:
    """Read the tap a human would most likely make, the way the browser would: a
    Button's label, a Calendar day, or a Rating star. Only a registered action name
    is ever returned.

    A choice is preferred over a refresh. ``rerun`` re-asks the same question and
    would make the conversation stand still, so a ``request_data`` button (the
    model's way of offering the user a real next step) is taken first.
    """
    def buttons(only_choices: bool):
        for comp in components:
            if comp.get("type") != "Button" or not isinstance(comp.get("onPress"), dict):
                continue
            action = comp["onPress"].get("action")
            if only_choices and action != "request_data":
                continue
            if not only_choices and action == "request_data":
                continue  # already considered
            label = comp.get("label")
            if isinstance(label, dict):  # a bound label: resolve it like the client does
                label = _pointer(data_model, label.get("$bind", ""))
            if label:
                yield {"action": action, "args": {"choice": str(label)},
                       "phrase": str(label), "from": comp.get("id")}

    for tap in buttons(only_choices=True):
        return tap
    for comp in components:
        if comp.get("type") == "Calendar" and isinstance(comp.get("onSelect"), dict):
            events = _pointer(data_model, (comp.get("events") or {}).get("$bind", ""))
            if isinstance(events, list) and events and isinstance(events[0], dict):
                date, label = events[0].get("date"), events[0].get("label", "")
                if date:
                    return {"action": comp["onSelect"].get("action"), "args": {"date": date},
                            "phrase": f"the day {date} ({label})", "from": comp.get("id")}
    for comp in components:
        if comp.get("type") == "Rating" and isinstance(comp.get("onRate"), dict):
            return {"action": comp["onRate"].get("action"), "args": {"value": 5},
                    "phrase": f"{comp.get('label') or 'this option'} rated 5 of {comp.get('max', 5)}",
                    "from": comp.get("id")}
    for tap in buttons(only_choices=False):
        return tap
    # Any other component the model bound an action to still counts as a tap: the
    # catalog decides which props are actions, not this script.
    for comp in components:
        for prop, value in comp.items():
            if isinstance(value, dict) and isinstance(value.get("action"), str):
                label = comp.get("label") or comp.get("title") or comp.get("id")
                return {"action": value["action"], "args": {},
                        "phrase": f"{comp.get('type')} “{label}”", "from": comp.get("id"),
                        "via_prop": prop}
    return None


def _pointer(data_model: dict, pointer: str):
    if not pointer.startswith("/"):
        return None
    current = data_model
    for segment in pointer.split("/")[1:]:
        if current is None:
            return None
        current = current.get(segment) if isinstance(current, dict) else None
    return current


def _turn_prompt(trail: list[dict]) -> str:
    if not trail:
        return GOAL
    taps = ", then ".join(tap["phrase"] for tap in trail)
    return (f"{GOAL}\nThe traveller has since tapped: {taps}."
            "\nCompose the next interface for exactly that, going one level deeper than the last one.")


async def run_turn(client: httpx.AsyncClient, prompt: str, registered: set[str]) -> dict:
    response = await client.post(f"{BASE}/v1/agent/runs", json={
        "prompt": prompt, "respond_as": "ui", "tenant_id": "course", "project_id": "s14-trip",
        "user_id": "traveller-01", "agent_id": "wayfare"})
    response.raise_for_status()
    run_id = response.json()["run_id"]

    composed = await client.get(f"{BASE}/v1/runs/{run_id}/composed")
    if composed.status_code == 404:
        return {"prompt": prompt, "run_id": run_id, "composed": False,
                "note": "no compose_surface node; nothing was drawn and nothing was invented"}
    composed.raise_for_status()
    body = composed.json()
    surface = body.get("surface") or {}
    components = surface.get("components") or []
    data_model = surface.get("dataModel") or {}

    tap = _first_tap(components, data_model)
    # The client-side half of the event invariant: a tap whose action the catalog
    # never registered is dropped before it can become the next turn.
    if tap and tap.get("action") not in registered:
        tap = {**tap, "refused": True, "reason": f"action {tap.get('action')!r} is not registered"}

    return {
        "prompt": prompt,
        "run_id": run_id,
        "composed": True,
        "provider": body.get("provider"),
        "model": body.get("model"),
        "component_count": body.get("component_count"),
        "clean": body.get("clean"),
        "component_types": sorted({comp.get("type") for comp in components}),
        "is_only_text": sorted({comp.get("type") for comp in components}) in (["Text"], ["Column", "Text"]),
        "data_pointers": sorted(data_model),
        "tap_offered": tap,
        "surface": surface,
    }


async def main() -> int:
    async with httpx.AsyncClient(timeout=300) as client:
        catalog = (await client.get(f"{BASE}/v1/catalog")).json()
        registered = set(catalog.get("actions") or [])
        print(f"runtime          : {BASE}")
        print(f"registered actions: {sorted(registered)}\n")

        turns: list[dict] = []
        trail: list[dict] = []
        for index in range(3):
            prompt = _turn_prompt(trail)
            print(f"--- turn {index + 1} ---")
            print(f"prompt: {prompt.splitlines()[-1][:110]}")
            turn = await run_turn(client, prompt, registered)
            turns.append(turn)
            if not turn.get("composed"):
                print("  no composed interface; stopping here\n")
                break
            print(f"  run={turn['run_id']} components={turn['component_count']} clean={turn['clean']}")
            print(f"  types={turn['component_types']}")
            tap = turn.get("tap_offered")
            print(f"  tap  ={tap['phrase'] if tap and not tap.get('refused') else tap}")
            if not tap or tap.get("refused"):
                print("  the interface offered no usable tap; stopping here\n")
                break
            trail.append(tap)

    type_sets = [tuple(t["component_types"]) for t in turns if t.get("composed")]
    proof = {
        "goal": GOAL,
        "base_url": BASE,
        "registered_actions": sorted(registered),
        "turns": turns,
        "summary": {
            "turns_composed": len(type_sets),
            "all_composed_non_empty": all(t.get("component_count", 0) > 0 for t in turns if t.get("composed")),
            "no_turn_is_only_text": all(not t.get("is_only_text") for t in turns if t.get("composed")),
            "distinct_interfaces": len(set(type_sets)),
            "types_per_turn": [list(s) for s in type_sets],
        },
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    print("=== SUMMARY ===")
    for key, value in proof["summary"].items():
        print(f"{key:24}: {value}")
    print(f"\nwrote {OUT}")

    summary = proof["summary"]
    ok = (summary["turns_composed"] >= 3 and summary["all_composed_non_empty"]
          and summary["no_turn_is_only_text"] and summary["distinct_interfaces"] >= 2)
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
