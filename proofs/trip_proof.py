"""Trip Planner proof: StepWizard component + injection-wall demo.

Runs three proofs without a live server:

  1. catalog  StepWizard is the 24th component, source="custom", correct props
  2. valid    A well-formed StepWizard surface with binding/text props validates clean
  3. wall     Three hostile mutations are each rejected under the right invariant

Writes trip_proof.json and prints a human table.

    uv run python proofs/trip_proof.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.catalog import COMPONENTS, catalog_manifest  # noqa: E402
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "trip_proof.json"


# ---------------------------------------------------------------------------
# Proof 1: StepWizard is in the catalog with the right props
# ---------------------------------------------------------------------------
def proof_catalog() -> dict:
    spec = COMPONENTS.get("StepWizard")
    assert spec is not None, "StepWizard missing from catalog"
    assert spec.source == "custom"
    assert spec.props["title"].kind == "text"
    assert spec.props["steps"].kind == "binding"
    assert spec.props["current"].kind == "binding"
    manifest = catalog_manifest()
    entry = manifest["components"]["StepWizard"]
    return {
        "total_components": len(COMPONENTS),
        "source": spec.source,
        "props": {name: p.kind for name, p in spec.props.items()},
        "in_manifest": "StepWizard" in manifest["components"],
        "manifest_source": entry["source"],
    }


# ---------------------------------------------------------------------------
# Proof 2: A valid trip-planner surface with StepWizard passes the wall
# ---------------------------------------------------------------------------
def proof_valid_surface() -> dict:
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["title", "stats", "wiz", "table", "tip"]},
            {"id": "title", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            {"id": "stats", "type": "Row", "children": ["s_days", "s_budget", "s_cities"]},
            {"id": "s_days",   "type": "StatTile", "label": "Days",   "value": {"$bind": "/days"},   "unit": "days"},
            {"id": "s_budget", "type": "StatTile", "label": "Budget", "value": {"$bind": "/budget"}, "unit": "USD"},
            {"id": "s_cities", "type": "StatTile", "label": "Cities", "value": {"$bind": "/cities"}},
            {"id": "wiz", "type": "StepWizard", "title": "Arrival checklist",
             "steps": {"$bind": "/steps"}, "current": {"$bind": "/current_step"}},
            {"id": "table", "type": "DataTable", "columns": "place,category,entry fee,time",
             "rows": {"$bind": "/places"}, "sortable": True},
            {"id": "tip", "type": "Notice", "text": {"$bind": "/tip"}, "tone": "warn"},
        ],
        "dataModel": {
            "title": "5-Day Japan First-Timer",
            "days": 5, "budget": 1200, "cities": 3,
            "steps": [
                {"label": "Visa", "detail": "No visa required for stays under 90 days (most passports)"},
                {"label": "Currency", "detail": "Withdraw JPY at airport ATM — cards not widely accepted"},
                {"label": "SIM card", "detail": "Pick up a prepaid data SIM at Narita arrivals"},
                {"label": "IC card", "detail": "Load a Suica/Pasmo card for all train/bus travel"},
                {"label": "Accommodation", "detail": "Check in, drop bags, refresh before heading out"},
            ],
            "current_step": 0,
            "places": [
                {"place": "Senso-ji Temple", "category": "Culture", "entry fee": "Free", "time": "1-2 h"},
                {"place": "teamLab Planets", "category": "Art/Tech", "entry fee": "¥3200", "time": "1.5 h"},
                {"place": "Fushimi Inari", "category": "Shrine", "entry fee": "Free", "time": "2-4 h"},
            ],
            "tip": "Carry cash. Many temples, small restaurants, and vending machines are cash-only.",
        },
    }
    result = validate_surface(surface)
    step_wizard = next((c for c in surface["components"] if c["type"] == "StepWizard"), None)
    return {
        "clean": result.ok,
        "accepted": len(result.accepted),
        "rejected": len(result.rejections),
        "step_wizard_present": step_wizard is not None,
        "step_count": len(surface["dataModel"]["steps"]),
        "rejections": [r.as_dict() for r in result.rejections],
        "surface": surface,
    }


# ---------------------------------------------------------------------------
# Proof 3: Three injection attempts — each refused under the right invariant
# ---------------------------------------------------------------------------
def proof_injection_wall() -> dict:
    cases = [
        {
            "name": "unknown_type",
            "expect": "catalog",
            "surface": {
                "root": "bad",
                "components": [
                    {"id": "bad", "type": "RawHtml",
                     "html": "<img src=x onerror=alert(1)>"}
                ],
            },
        },
        {
            "name": "inline_literal_where_binding_required",
            "expect": "data-not-code",
            "surface": {
                "root": "bad",
                "components": [
                    {"id": "bad", "type": "StepWizard",
                     "title": "Arrival",
                     "steps": ["Visa", "Currency", "SIM"],  # must be {"$bind": "..."}, not inline list
                     "current": {"$bind": "/current_step"}}
                ],
            },
        },
        {
            "name": "undeclared_handler_property",
            "expect": "data-not-code",
            "surface": {
                "root": "bad",
                "components": [
                    {"id": "bad", "type": "StepWizard",
                     "title": "Checklist",
                     "steps": {"$bind": "/steps"},
                     "current": {"$bind": "/current_step"},
                     "onclick": "alert(document.cookie)"}  # handler — never declared on StepWizard
                ],
            },
        },
    ]

    rows = []
    for case in cases:
        result = validate_surface(case["surface"])
        broke = sorted({r.invariant for r in result.rejections})
        rows.append({
            "name": case["name"],
            "expected": case["expect"],
            "rejected": not result.ok,
            "invariants_broken": broke,
            "correct": case["expect"] in broke,
        })
    return {
        "all_rejected": all(r["rejected"] for r in rows),
        "all_correct": all(r["correct"] for r in rows),
        "cases": rows,
    }


def main() -> None:
    proof = {
        "catalog": proof_catalog(),
        "valid_surface": proof_valid_surface(),
        "injection_wall": proof_injection_wall(),
    }
    OUT.write_text(json.dumps(proof, indent=2))

    print("\n=== Trip Planner / StepWizard proof ===\n")
    c = proof["catalog"]
    print(f"catalog       : {c['total_components']} components, StepWizard source={c['source']}, props={c['props']}")
    print(f"in manifest   : {c['in_manifest']}")

    v = proof["valid_surface"]
    print(f"\nvalid surface : {v['accepted']} accepted, {v['rejected']} rejected, clean={v['clean']}")
    print(f"StepWizard    : present={v['step_wizard_present']}, {v['step_count']} steps bound to /steps")

    print("\ninjection wall:")
    for r in proof["injection_wall"]["cases"]:
        mark = "REJECTED" if r["rejected"] else "PASSED (!)"
        ok = "ok" if r["correct"] else "WRONG INVARIANT"
        print(f"  {r['name']:<40} {mark:<12} broke {r['invariants_broken']}  [{ok}]")
    w = proof["injection_wall"]
    print(f"  all_rejected={w['all_rejected']} all_correct={w['all_correct']}")

    print(f"\nwrote {OUT}\n")
    ok = (
        proof["catalog"]["in_manifest"]
        and proof["valid_surface"]["clean"]
        and proof["injection_wall"]["all_rejected"]
        and proof["injection_wall"]["all_correct"]
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
