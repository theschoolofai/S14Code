"""Adversarial proof: the injection wall holds for the Study Planner domain.

Three hostile surfaces are tested against the GanttChart component and the
catalog. Each one should be REJECTED; a safe surface that uses GanttChart
correctly should be ACCEPTED.

    uv run python proofs/adversarial_study.py     # no gateway required
"""

from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "adversarial_study.json"

CASES = [
    # --- 1. Catalog invariant: unknown component type -----------------------
    {
        "name": "unknown GanttTimeline type",
        "expect": "rejected",
        "invariant": "catalog",
        "surface": {
            "root": "root",
            "components": [
                {"id": "root", "type": "GanttTimeline", "tasks": {"$bind": "/tasks"}},
            ],
        },
    },
    # --- 2. Data-not-code: markup in a GanttChart text prop -----------------
    {
        "name": "markup in GanttChart title",
        "expect": "rejected",
        "invariant": "data-not-code",
        "surface": {
            "root": "root",
            "components": [
                {
                    "id": "root",
                    "type": "GanttChart",
                    "title": "<img src=x onerror=alert(1)>",
                    "tasks": {"$bind": "/tasks"},
                },
            ],
        },
    },
    # --- 3. Event invariant: unregistered action name -----------------------
    {
        "name": "unregistered action on KanbanBoard",
        "expect": "rejected",
        "invariant": "event",
        "surface": {
            "root": "root",
            "components": [
                {
                    "id": "root",
                    "type": "KanbanBoard",
                    "title": "board",
                    "columns": {"$bind": "/cols"},
                    "onCardPress": {"action": "exfiltrate_data", "args": {}},
                },
            ],
        },
    },
    # --- 4. Safe surface: GanttChart used correctly — should be accepted ----
    {
        "name": "valid GanttChart surface",
        "expect": "accepted",
        "invariant": "none",
        "surface": {
            "root": "root",
            "components": [
                {
                    "id": "root",
                    "type": "Column",
                    "children": ["heading", "gantt"],
                },
                {
                    "id": "heading",
                    "type": "Text",
                    "text": {"$bind": "/title"},
                    "variant": "heading",
                },
                {
                    "id": "gantt",
                    "type": "GanttChart",
                    "title": "Assignment Schedule",
                    "tasks": {"$bind": "/tasks"},
                    "caption": "Bars show start to end date",
                },
            ],
        },
    },
]


def run_cases() -> list[dict]:
    results = []
    for case in CASES:
        vr = validate_surface(case["surface"])
        passed = (case["expect"] == "rejected") == (not vr.ok)
        results.append({
            "name": case["name"],
            "expect": case["expect"],
            "got": "rejected" if not vr.ok else "accepted",
            "passed": passed,
            "rejections": [r.as_dict() for r in vr.rejections],
        })
    return results


def main() -> None:
    results = run_cases()
    all_pass = all(r["passed"] for r in results)

    print("=== Adversarial invariant proof — Study Planner ===\n")
    for r in results:
        icon = "✓" if r["passed"] else "✗"
        print(f"{icon}  {r['name']}")
        print(f"   expected={r['expect']}  got={r['got']}")
        for rj in r["rejections"]:
            print(f"   rejection: [{rj['invariant']}] {rj['reason']}")
        print()

    print("ALL PASSED" if all_pass else "FAILURES FOUND")

    OUT.write_text(json.dumps({
        "all_passed": all_pass,
        "cases": results,
    }, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
