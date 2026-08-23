"""Adversarial proof: Injection wall refuses hostile resume surfaces while preserving safe components.

Proves the three invariants:
  1. Catalog invariant: RawHtml refused
  2. Data-not-code invariant: markup in StatTile value refused
  3. Event invariant: unregistered action refused
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

S13CODE = Path(os.environ.get("S13CODE_PATH") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(S13CODE))

from s13code.ui.validator import Invariant, validate_surface  # noqa: E402

OUT = Path(__file__).parent / "adversarial_resume.json"

HOSTILE_SURFACE = {
    "root": "root",
    "components": [
        {
            "id": "root",
            "type": "Column",
            "children": ["header", "poison_rawhtml", "poison_markup", "poison_action", "safe_notice"],
        },
        {
            "id": "header",
            "type": "Text",
            "text": "Executive Resume Preview (Injection Defense Test)",
            "variant": "heading",
        },
        {
            "id": "poison_rawhtml",
            "type": "RawHtml",
            "html": "<script>alert('pwned_resume')</script>",
        },
        {
            "id": "poison_markup",
            "type": "StatTile",
            "label": "Experience",
            "value": "<b onclick='alert(1)'>8 Years</b>",
            "tone": "good",
        },
        {
            "id": "poison_action",
            "type": "Button",
            "label": "Execute Payload",
            "onPress": {"action": "eval_malicious_code"},
        },
        {
            "id": "safe_notice",
            "type": "Notice",
            "text": "Valid Profile: Senior AI Systems Engineer (PyTorch, Distributed Training, 96% Match)",
            "tone": "good",
        },
    ],
    "dataModel": {},
}


def main() -> None:
    result = validate_surface(HOSTILE_SURFACE)
    accepted_ids = [c.get("id") for c in result.accepted]
    rejections = [r.as_dict() for r in result.rejections]

    invariants_broken = {r["invariant"] for r in rejections}

    report = {
        "ok": result.ok,
        "proposed_components": len(HOSTILE_SURFACE["components"]),
        "accepted_count": len(result.accepted),
        "accepted_ids": accepted_ids,
        "rejection_count": len(rejections),
        "rejections": rejections,
        "assert_rawhtml_refused": "poison_rawhtml" not in accepted_ids,
        "assert_markup_refused": "poison_markup" not in accepted_ids,
        "assert_unregistered_action_refused": "poison_action" not in accepted_ids,
        "assert_safe_notice_rendered": "safe_notice" in accepted_ids,
        "assert_all_three_invariants_tested": {
            Invariant.CATALOG: Invariant.CATALOG in invariants_broken,
            Invariant.DATA_NOT_CODE: Invariant.DATA_NOT_CODE in invariants_broken,
            Invariant.EVENT: Invariant.EVENT in invariants_broken,
        },
    }

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("=== ADVERSARIAL RESUME INJECTION PROOF ===")
    print(f"Accepted components : {accepted_ids}")
    print(f"Rejections          : {len(rejections)}")
    for r in rejections:
        print(f"  [{r['component_id']}] {r['field']}: {r['invariant']} -> {r['reason']}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
