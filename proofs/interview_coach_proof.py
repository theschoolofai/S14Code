"""Produce the submission proof for the Interview Coach Rating component.

Run with ``uv run python proofs/interview_coach_proof.py``.  It proves both the
clean coach flow and that malformed Rating controls are stopped at the same
validator boundary as every other component.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.interview_coach import build_interview_coach_surface  # noqa: E402
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "interview_coach_proof.json"


def main() -> None:
    coach = build_interview_coach_surface()
    clean = validate_surface(coach)
    attacks = {
        "unbounded_rating": {
            "root": "rating",
            "components": [{"id": "rating", "type": "Rating", "label": "Score", "value": {"$bind": "/score"}, "max": 500}],
        },
        "unregistered_rating_event": {
            "root": "rating",
            "components": [{"id": "rating", "type": "Rating", "label": "Score", "value": {"$bind": "/score"}, "max": 5, "onRate": {"action": "exfiltrate"}}],
        },
    }
    results = {name: validate_surface(surface) for name, surface in attacks.items()}
    proof = {
        "coach": {"component_count": len(coach["components"]), "clean": clean.ok, "surface": coach},
        "attacks": {
            name: {"rejected": not result.ok, "rejections": [r.as_dict() for r in result.rejections]}
            for name, result in results.items()
        },
    }
    OUT.write_text(json.dumps(proof, indent=2))
    print(f"coach clean={clean.ok}; attacks rejected={all(not r.ok for r in results.values())}")
    sys.exit(0 if clean.ok and all(not result.ok for result in results.values()) else 1)


if __name__ == "__main__":
    main()
