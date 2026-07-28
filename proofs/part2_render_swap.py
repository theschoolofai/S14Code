"""Swap a captured Part 2 turn into harness_run.json shape for rendering.

Reads proofs/part2/turn_N.json and writes proofs/harness_run.json in the shape
the /v1/harness/surface route expects. Backs up the original once.

Usage:  python proofs/part2_render_swap.py <N>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
BAK = HERE / "harness_run.json.bak"
LIVE = HERE / "harness_run.json"


def swap(turn_no: int) -> None:
    if not BAK.exists():
        shutil.copy(LIVE, BAK)
    src = HERE / "part2" / f"turn_{turn_no}.json"
    turn = json.loads(src.read_text(encoding="utf-8"))
    harness = {
        "run_id": f"part2_turn_{turn_no}",
        "compose_surface_node": {
            "provider": turn["provider"],
            "model": turn["model"],
            "surface_accepted": {
                "root": turn["surface_accepted"]["root"],
                "components": turn["surface_accepted"]["components"],
            },
            "data_model": turn["surface_accepted"]["dataModel"],
        },
    }
    LIVE.write_text(json.dumps(harness, indent=2), encoding="utf-8")
    print(f"swapped turn {turn_no} into harness_run.json "
          f"({len(harness['compose_surface_node']['surface_accepted']['components'])} components)")


def restore() -> None:
    if BAK.exists():
        shutil.move(BAK, LIVE)
        print("restored harness_run.json from backup")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        restore()
    else:
        swap(int(sys.argv[1]))
