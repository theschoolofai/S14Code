"""Capture a run in which Gemini composes the contributed Kanban component.

The point of the capture is that nothing tells the model to use Kanban. The
compose_surface skill publishes the whole catalog manifest and a domain-neutral
data model; the instruction describes the *shape* of the data (``/board_columns``
is "items grouped into named buckets") and never names a component type. If a
Kanban appears in the accepted surface, the model chose it off the catalog.

    # compose a fresh one live (needs glc_v3 on 8111 and S14Code on 8113)
    uv run python proofs/kanban_compose.py

    # or re-export a run that already happened, straight from the durable journal
    uv run python proofs/kanban_compose.py --run-id run-6b14550dcca6

Writes proofs/kanban_compose.json. Synthetic identity only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

BASE = "http://127.0.0.1:8113"
OUT = Path(__file__).parent / "kanban_compose.json"

PROMPT = ("Help me run a job search for a senior backend engineer role. Show the pipeline "
          "stages and which companies sit in each stage.")


def start_run(client: httpx.Client) -> str:
    response = client.post(f"{BASE}/v1/agent/runs", json={
        "prompt": PROMPT, "respond_as": "ui",
        "tenant_id": "course", "project_id": "s14",
        "user_id": "student-01", "agent_id": "assistant",
    })
    response.raise_for_status()
    return response.json()["run_id"]


def export(client: httpx.Client, run_id: str) -> dict[str, Any]:
    run = client.get(f"{BASE}/v1/agent/runs/{run_id}")
    run.raise_for_status()
    nodes = run.json()["nodes"]
    node = nodes.get("surface") or {}
    result = node.get("result") or {}
    surface = result.get("surface") or {}
    components = surface.get("components") or []
    kanban = [c for c in components if c.get("type") == "Kanban"]
    data_model = result.get("data_model") or {}
    return {
        "run_id": run_id,
        "prompt": PROMPT,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "unprompted": {
            "catalog_offered_to_model": True,
            "component_named_in_prompt": "Kanban" in PROMPT,
            "component_named_in_instruction": False,
            "note": ("compose_surface sends the catalog manifest and describes /board_columns "
                     "by shape only; the component type is the model's choice."),
        },
        "validator": result.get("validator"),
        "kanban_components": kanban,
        "board_data": data_model.get("board_columns"),
        "surface": surface,
        "raw_surface": result.get("raw_surface"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", help="export an existing run instead of composing a new one")
    args = parser.parse_args()

    with httpx.Client(timeout=300) as client:
        try:
            client.get(f"{BASE}/healthz").raise_for_status()
        except Exception as error:
            print(f"S14Code is not serving on {BASE}: {error}", file=sys.stderr)
            return 2

        run_id = args.run_id
        if not run_id:
            print(f"composing live: {PROMPT}")
            started = time.perf_counter()
            run_id = start_run(client)
            print(f"  run {run_id} finished in {time.perf_counter() - started:.1f}s")

        payload = export(client, run_id)

    validator = payload["validator"] or {}
    kanban = payload["kanban_components"]
    print(f"\nrun        {payload['run_id']}")
    print(f"provider   {payload['provider']} / {payload['model']}")
    print(f"validator  proposed {validator.get('proposed')} → accepted {validator.get('accepted')}, "
          f"refused {validator.get('rejected')}")
    print(f"types      {' '.join(validator.get('component_types') or [])}")
    if kanban:
        print("\nthe model chose Kanban off the catalog, unprompted:")
        print("  " + json.dumps(kanban[0]))
        columns = payload["board_data"] or []
        print(f"  bound to /board_columns · {len(columns)} columns · "
              f"{sum(len(c.get('cards') or []) for c in columns)} cards")
    else:
        print("\nno Kanban in this surface — the model chose other components this time")

    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT}")
    return 0 if kanban else 1


if __name__ == "__main__":
    raise SystemExit(main())
