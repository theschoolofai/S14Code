"""Produce the real, inspectable output that backs Session 14.

Runs four proofs against the actual S14Code code and a recorded S13 journal:

  1. surface build   the three-city run becomes a validated component tree
  2. agui stream     the S13 journal maps to AG-UI events
  3. injection wall  every hostile surface in the fixture is rejected by name
                     (four against the base catalog, three against the
                     Map/Calendar/Rating student extensions)
  4. hitl approval   a matching approval resumes; a widened one is refused

Writes proof.json and prints a human table. This is the source the widgets
replay: no imagined content.

    uv run python proofs/run_surface_proof.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.agui import stream_agui  # noqa: E402
from s13code.ui.hitl import PendingAction, decide_resume  # noqa: E402
from s13code.ui.fixtures import RecordedS13, load_injections  # noqa: E402
from s13code.ui.showcase import build_corpus_dashboard  # noqa: E402
from s13code.ui.surface import build_run_surface  # noqa: E402
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "proof.json"


def proof_surface() -> dict:
    run = RecordedS13().get_run("three_cities")
    built = build_run_surface(run)
    result = validate_surface(built)
    return {
        "run_id": run["run_id"],
        "component_count": len(built["components"]),
        "types_used": sorted({c["type"] for c in built["components"]}),
        "clean": result.ok,
        "answer": built["dataModel"].get("answer", ""),
        "surface": built,
    }


def proof_showcase() -> dict:
    run = RecordedS13().get_run("papers_corpus")
    built = build_corpus_dashboard(run)
    result = validate_surface(built)
    types = sorted({c["type"] for c in built["components"]})
    chart_types = [t for t in types if t in ("BarChart", "LineChart", "Sparkline", "ProgressBar", "Timeline")]
    return {
        "component_count": len(built["components"]),
        "distinct_types": len(types),
        "types_used": types,
        "chart_types": chart_types,
        "executable_nodes": 0 if result.ok else len(result.rejections),
        "clean": result.ok,
        "data_model_keys": len(built["dataModel"]),
        "surface": built,
    }


def proof_agui() -> dict:
    run = RecordedS13().get_run("three_cities")
    events = list(stream_agui(run["events"], finished=run["finished"]))
    counts: dict[str, int] = {}
    for ev in events:
        counts[ev["type"]] = counts.get(ev["type"], 0) + 1
    return {"event_count": len(events), "by_type": counts, "events": events}


def proof_injections() -> dict:
    cases = load_injections()["cases"]
    rows = []
    for case in cases:
        result = validate_surface(case["surface"])
        broke = sorted({r.invariant for r in result.rejections})
        rows.append(
            {
                "name": case["name"],
                "expected_invariant": case["expect_invariant"],
                "rejected": not result.ok,
                "invariants_broken": broke,
                "accepted_ids": [c.get("id") for c in result.accepted],
                "rejections": [r.as_dict() for r in result.rejections],
                "correct": case["expect_invariant"] in broke,
            }
        )
    return {"all_rejected": all(r["rejected"] for r in rows),
            "all_correct": all(r["correct"] for r in rows), "cases": rows}


def proof_hitl() -> dict:
    pending = PendingAction(
        run_id="birthday_run",
        node_id="calendar_writer",
        summary="Create two calendar reminders for mom's birthday",
        params={"dates": ["2026-05-01", "2026-05-15"], "title": "Mom's birthday"},
    )
    ok = decide_resume(pending, "approve", dict(pending.params))
    widened = decide_resume(
        pending, "approve", {"dates": ["2026-05-01", "2026-05-15", "2026-06-01"], "title": "Mom's birthday"}
    )
    rejected = decide_resume(pending, "reject", {})
    return {
        "matching_approve": {"allowed": ok.allowed, "reason": ok.reason},
        "widened_approve": {"allowed": widened.allowed, "reason": widened.reason},
        "reject": {"allowed": rejected.allowed, "reason": rejected.reason},
        "safe": ok.allowed and not widened.allowed,
    }


def main() -> None:
    proof = {
        "surface": proof_surface(),
        "showcase": proof_showcase(),
        "agui": proof_agui(),
        "injections": proof_injections(),
        "hitl": proof_hitl(),
    }
    OUT.write_text(json.dumps(proof, indent=2))

    print("\n=== S14 surface proof ===\n")
    s = proof["surface"]
    print(f"surface       : {s['component_count']} components, types {s['types_used']}, clean={s['clean']}")
    print(f"answer        : {s['answer'][:70]}...")

    sc = proof["showcase"]
    print(f"\nSHOWCASE      : {sc['component_count']} components, {sc['distinct_types']} distinct types")
    print(f"  chart types : {sc['chart_types']}")
    print(f"  executable  : {sc['executable_nodes']} nodes  ·  clean={sc['clean']}  ·  {sc['data_model_keys']} data-model keys")

    a = proof["agui"]
    print(f"agui stream   : {a['event_count']} events  {a['by_type']}")

    print("\ninjection wall:")
    for c in proof["injections"]["cases"]:
        mark = "REJECTED" if c["rejected"] else "PASSED (!)"
        ok = "ok" if c["correct"] else "WRONG INVARIANT"
        print(f"  {c['name']:<20} {mark:<12} broke {c['invariants_broken']}  [{ok}]")
    print(f"  all_rejected={proof['injections']['all_rejected']} all_correct={proof['injections']['all_correct']}")

    h = proof["hitl"]
    print("\nhitl approval :")
    print(f"  matching approve  allowed={h['matching_approve']['allowed']}  ({h['matching_approve']['reason']})")
    print(f"  widened  approve  allowed={h['widened_approve']['allowed']}  ({h['widened_approve']['reason']})")
    print(f"  safe={h['safe']}")

    print(f"\nwrote {OUT}\n")
    ok = (
        proof["surface"]["clean"]
        and proof["showcase"]["clean"]
        and proof["injections"]["all_rejected"]
        and proof["injections"]["all_correct"]
        and proof["hitl"]["safe"]
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
