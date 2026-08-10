"""Part 2 proof: the job-hunt tracker answers ONLY in composed interfaces.

Drives the real gateway exactly the way the ``/app`` shell does — POST a goal to
``/v1/agent/runs`` with ``respond_as="ui"``, read the composed interface from
``/v1/runs/{id}/composed`` — and carries a conversation across three turns, where
a tap in one interface shapes the next.

Every identity in here is synthetic.

    S14_BASE=http://127.0.0.1:8123 uv run python proofs/jobhunt_conversation.py
      -> proofs/jobhunt_conversation.json
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

BASE = os.getenv("S14_BASE", "http://127.0.0.1:8113").rstrip("/")
OUT = Path(__file__).parent / "jobhunt_conversation.json"

# Turn 1 is the opening goal. Turns 2 and 3 are TAPS: the label of a card the
# previous interface drew. The shell replays the conversation as context, so the
# next interface is shaped by what the user touched.
OPENING = ("Track my job hunt. I have six applications out for senior backend engineer roles — "
           "a couple just submitted, two in interview loops, one at offer stage and one rejected. "
           "Show me where each application currently stands.")
# Each tap is chosen to have a genuinely different SHAPE of data behind it, so
# the interface has to change component, not just content: one item (detail),
# rows (comparison), a numeric series (chart), an ordered sequence (timeline).
TAPS = [
    "Future Systems Co.",                       # a card in the Interviewing lane
    "Compare the compensation of my three strongest options",
    "Score my interview performance out of 10 across my last six onsite loops",
    "Walk me through the hiring process stages at Future Systems Co. in order",
]


def goal_for(convo: list[str]) -> str:
    """Exactly the context the app shell builds (see client/jobhunt.html)."""
    if len(convo) == 1:
        return convo[0]
    last, trail = convo[-1], convo[1:-1]
    return ("Original goal: " + convo[0] + "\n" +
            (("The user already drilled into: " + ", then ".join(trail) + ".\n") if trail else "") +
            'The user has now tapped: "' + last + '".\n' +
            "Compose the interface that answers THAT tap specifically. Go one level deeper: if it names a "
            "single item, show that one item's detail and history; if it asks to compare or analyse, show "
            "the comparison. Do not simply redraw the previous screen.")


def turn(client: httpx.Client, convo: list[str]) -> dict:
    started = time.time()
    run = client.post(f"{BASE}/v1/agent/runs", json={
        "tenant_id": "course", "project_id": "s14", "user_id": "student-synthetic-01",
        "agent_id": "jobhunt", "respond_as": "ui", "prompt": goal_for(convo),
    }).json()
    run_id = run["run_id"]
    composed = client.get(f"{BASE}/v1/runs/{run_id}/composed").json()
    journal = client.get(f"{BASE}/v1/agent/runs/{run_id}").json()
    validator = ((journal.get("nodes", {}).get("surface") or {}).get("result") or {}).get("validator") or {}
    surface = composed["surface"]
    types = sorted({c["type"] for c in surface["components"]})
    return {
        "user_said": convo[-1],
        "goal_sent": goal_for(convo),
        "run_id": run_id,
        "latency_s": round(time.time() - started, 1),
        "provider": composed.get("provider"),
        "model": composed.get("model"),
        "clean": composed.get("clean"),
        "component_count": composed.get("component_count"),
        "component_types": types,
        "validator": validator,
        "data_pointers": sorted(surface.get("dataModel", {}).keys()),
        "surface": surface,
    }


def main() -> None:
    convo: list[str] = [OPENING]
    turns = []
    with httpx.Client(timeout=300) as client:
        for index in range(len(TAPS) + 1):
            if index:
                convo.append(TAPS[index - 1])
            record = turn(client, convo)
            turns.append(record)
            unresolved = (record["validator"] or {}).get("unresolved_bindings") or []
            print(f"turn {index + 1}: {record['component_count']:>2} components, "
                  f"clean={record['clean']}, {record['latency_s']}s  {record['component_types']}"
                  + (f"  !! bound to nothing: {unresolved}" if unresolved else ""))

    # The claim this proof exists to support: every turn is a composed, validated
    # interface, and the turns are genuinely DIFFERENT interfaces.
    signatures = [tuple(t["component_types"]) for t in turns]
    union = {t for sig in signatures for t in sig}
    # The variety claim, checked rather than asserted: the right RICH component
    # for each shape of data the conversation actually produced.
    coverage = {
        "stages -> KanbanBoard": sorted(union & {"KanbanBoard"}),
        "rows -> DataTable": sorted(union & {"DataTable"}),
        "series -> BarChart/Sparkline": sorted(union & {"BarChart", "Sparkline"}),
        "sequence -> Timeline": sorted(union & {"Timeline"}),
        "key numbers -> StatTile": sorted(union & {"StatTile"}),
    }
    report = {
        "base": BASE,
        "turns": turns,
        "every_turn_composed": all(t["component_count"] > 0 for t in turns),
        "every_turn_clean": all(t["clean"] for t in turns),
        "distinct_component_signatures": len(set(signatures)),
        "union_of_component_types": sorted(union),
        "rich_component_coverage": coverage,
        "every_shape_got_its_component": all(bool(v) for v in coverage.values()),
        "every_binding_resolved": all(
            not ((t["validator"] or {}).get("unresolved_bindings") or []) for t in turns),
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\ndistinct interface shapes: {report['distinct_component_signatures']}/{len(turns)}")
    print(f"components used across the conversation: {report['union_of_component_types']}")
    for shape, hit in coverage.items():
        print(f"  {shape:32} {hit if hit else '** ABSENT **'}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
