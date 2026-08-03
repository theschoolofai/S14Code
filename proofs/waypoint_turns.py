"""Capture Waypoint answering three turns, each one only as a composed interface.

This drives the SAME loop the ``/trip`` shell drives, in-process and against the
real gateway: send a goal with ``respond_as="ui"``, read the interface the agent
composed, then take a real Button out of that interface and make its label the
next turn. Nothing about the next turn is hardcoded here — turn 2's prompt is
whatever turn 1 actually offered the user to tap, so the capture fails honestly
if the agent never composed anything tappable.

    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/waypoint_turns.py

Writes proofs/waypoint_turns.json. Needs a live glc_v3 and a live Ollama
(nomic-embed-text) because every run writes a real episode to durable memory.
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

OUT = Path(__file__).parent / "waypoint_turns.json"

# Turn 1 only. Turns 2 and 3 are whatever the user taps in the interface the
# previous turn composed.
GOAL = "Plan a 5-day trip to Japan. Ask me which region to focus on."
TURNS = 3
# Which offered choice to tap on each subsequent turn (0 = the first Button).
TAP = [int(v) for v in os.getenv("WAYPOINT_TAPS", "0,0").split(",")]


ONWARD = ("\nAlways finish by offering 3 to 5 short, concrete choices the user could tap"
          " to go one level deeper. Keep each choice label under about eight words.")


def next_goal(convo: list[str]) -> str:
    """Byte-for-byte the chaining the /trip shell performs in nextGoal()."""
    if len(convo) == 1:
        return convo[0] + ONWARD
    return (
        convo[0]
        + "\nThe user has since tapped, in order: " + " → ".join(convo[1:]) + "."
        + "\nProduce the content for that next step of the plan. Go one level deeper than the"
        + " previous step rather than repeating it, and include real locations with coordinates"
        + " whenever the step involves places."
        + ONWARD
    )


def resolve(value, data_model: dict):
    if isinstance(value, dict) and "$bind" in value:
        cursor = data_model
        for segment in str(value["$bind"]).split("/")[1:]:
            if not isinstance(cursor, dict):
                return None
            cursor = cursor.get(segment)
        return cursor
    return value


def tappable(surface: dict) -> list[str]:
    """The labels a user could actually tap in this interface."""
    labels = []
    for comp in surface.get("components", []):
        if comp.get("type") != "Button":
            continue
        label = resolve(comp.get("label"), surface.get("dataModel") or {})
        if isinstance(label, dict):
            label = label.get("label") or label.get("name") or label.get("id")
        if label and str(label).strip():
            labels.append(str(label).strip())
    return labels


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="waypoint-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    scope = MemoryScope("course", "s14-waypoint", "traveller-01", "waypoint")

    print(f"data dir  : {data_dir}")
    print(f"gateway   : {gateway.base_url}  provider={os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"turn 1    : {GOAL}\n")

    convo: list[str] = []
    turns: list[dict] = []
    exit_code = 0

    for index in range(TURNS):
        if index:
            # Each turn spends two model calls, and the course gateway runs a
            # single Gemini key on a per-minute limit. Pacing the turns keeps a
            # three-turn capture inside the quota instead of spending half of it
            # on backoff, which is also roughly the rhythm of a person tapping.
            await asyncio.sleep(float(os.getenv("WAYPOINT_TURN_PAUSE", "8")))
        if index == 0:
            convo.append(GOAL)
        else:
            offered = tappable(turns[-1]["surface"])
            if not offered:
                print(f"turn {index + 1}: the previous interface offered nothing to tap — stopping honestly")
                exit_code = 3
                break
            choice = offered[min(TAP[index - 1] if index - 1 < len(TAP) else 0, len(offered) - 1)]
            print(f"  ↳ tapped: {choice!r}  (offered: {offered})")
            convo.append(choice)

        prompt = next_goal(convo)
        result = await runtime.run(
            prompt=prompt, scope=scope,
            llm=lambda p, s: gateway.complete(p, s),
            source_uri="proof://waypoint/turn", source_author="traveller-01",
            respond_as="ui",
        )
        snapshot = runtime.graph.snapshot(result["run_id"])
        events = [event.__dict__ for event in runtime.graph.events(result["run_id"])]
        node = snapshot.nodes.get("surface", {})
        node_result = node.get("result") or {}
        surface = node_result.get("surface") or {"components": [], "dataModel": {}}
        types = sorted({comp.get("type") for comp in surface.get("components", [])})

        turns.append({
            "turn": index + 1,
            "tapped": None if index == 0 else convo[-1],
            "prompt_sent": prompt,
            "run_id": result["run_id"],
            "status": result["status"],
            "graph": {
                "nodes": {nid: {"skill": n["skill"], "state": n["state"],
                                "agent": n.get("metadata", {}).get("agent", n["skill"]),
                                "provider": (n.get("result") or {}).get("provider"),
                                "model": (n.get("result") or {}).get("model")}
                          for nid, n in snapshot.nodes.items()},
                "edges": [list(edge) for edge in snapshot.edges],
            },
            "event_journal": [{"sequence": e["sequence"], "kind": e["kind"], "node_id": e["node_id"]}
                              for e in events],
            "provider": node_result.get("provider"),
            "model": node_result.get("model"),
            "error": node_result.get("error"),
            "compose_attempts": node_result.get("compose_attempts"),
            "validator": node_result.get("validator"),
            "component_types": types,
            "component_count": len(surface.get("components", [])),
            "offers_taps": tappable(surface),
            "surface": surface,
        })
        validator = node_result.get("validator") or {}
        print(f"turn {index + 1}: run={result['run_id']} status={result['status']} "
              f"components={len(surface.get('components', []))} "
              f"rejected={validator.get('rejected')} types={types}")
        if node.get("state") != "succeeded":
            exit_code = 3

    all_types = sorted({t for turn in turns for t in turn["component_types"]})
    shapes = [tuple(turn["component_types"]) for turn in turns]
    runtime_source = (S13CODE / "s13code" / "runtime.py").read_text()

    proof = {
        "application": "Waypoint — a UI-only trip planner",
        "goal": GOAL,
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "turns_captured": len(turns),
        "every_turn_is_a_composed_interface": all(t["component_count"] > 0 for t in turns),
        "every_turn_validated_clean": all((t["validator"] or {}).get("ok") for t in turns),
        "distinct_component_types_used": all_types,
        "each_turn_composed_a_different_interface": len(set(shapes)) == len(shapes),
        "routemap_composed": "RouteMap" in all_types,
        "routemap_never_named_in_runtime": "RouteMap" not in runtime_source,
        "turns": turns,
    }
    OUT.write_text(json.dumps(proof, indent=2))

    await gateway.close()
    runtime.close()

    print("\n=== WAYPOINT SUMMARY ===")
    print(f"turns captured          : {proof['turns_captured']}")
    print(f"all turns are interfaces: {proof['every_turn_is_a_composed_interface']}")
    print(f"all turns clean         : {proof['every_turn_validated_clean']}")
    print(f"interfaces all differ   : {proof['each_turn_composed_a_different_interface']}")
    print(f"component types used    : {all_types}")
    print(f"RouteMap composed       : {proof['routemap_composed']}  "
          f"(runtime.py never names it: {proof['routemap_never_named_in_runtime']})")
    print(f"\nwrote {OUT}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
