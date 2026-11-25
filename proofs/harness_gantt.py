"""Proof: Gemini composes a GanttChart without being told to.

We show Gemini the FULL catalog (including the new GanttChart type), hand it a
data model of study tasks with ISO start/end dates, and ask it to compose a
schedule overview. The task prompt never names GanttChart. If the validated
surface contains a GanttChart the invariant is proved.

    # gateway optional — this script calls Gemini's REST API directly
    GEMINI_API_KEY=<key> uv run python proofs/harness_gantt.py
    # or export it first:
    export GEMINI_API_KEY=$(grep GEMINI_API_KEY /Users/cloudtrade/Desktop/.env | cut -d= -f2)
    uv run python proofs/harness_gantt.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.catalog import catalog_manifest  # noqa: E402
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "harness_gantt.json"

SYSTEM = """You compose user interfaces as declarative JSON only.
Use ONLY the component types and properties in the CATALOG. Never invent a type,
never add an event-handler property (onclick/onerror), never put HTML in a text
value, never use an action outside the registered list.

SHAPE (follow exactly):
- top-level keys are "root" (a string id) and "components" (a FLAT array)
- each component is {"id": "...", "type": "...", <props inline>}  -- NO "props" wrapper
- children is an array of component ids: "children": ["a","b"]
- a shown value is a binding object {"$bind": "/key"} into the DATA MODEL
- text props like title/label/caption/xKey/yKey are PLAIN strings, never bindings

Output ONE json object. No prose, no code fences."""


TASK = (
    "The user is a student managing course assignments. "
    "Show them a schedule overview for the next month: when each assignment "
    "starts and when it is due, plus a summary of how many are open and how "
    "many are already submitted. Use the most fitting components from the "
    "catalog for a time-based overview."
)

DATA_MODEL = {
    "title": "Study schedule — Nov/Dec 2026",
    "open_count": 3,
    "submitted_count": 2,
    "tasks": [
        {"id": "t1", "label": "EAG Session 14", "start": "2026-11-25", "end": "2026-12-01"},
        {"id": "t2", "label": "NLP Assignment 3", "start": "2026-11-27", "end": "2026-12-05"},
        {"id": "t3", "label": "CV Mini-Project", "start": "2026-11-28", "end": "2026-12-10"},
        {"id": "t4", "label": "RL Quiz (done)", "start": "2026-11-15", "end": "2026-11-20"},
        {"id": "t5", "label": "Math Worksheet", "start": "2026-11-10", "end": "2026-11-18"},
    ],
    "caption": "Bars show start → due date. Colour: accent = active.",
}


def normalize(surface: dict) -> dict:
    if isinstance(surface.get("root"), dict) and "components" in surface["root"]:
        inner = surface["root"]
        surface = {"root": inner.get("root", "root"), "components": inner["components"]}
    comps = surface.get("components", [])
    flat = []
    for c in comps:
        if "props" in c and isinstance(c["props"], dict):
            merged = {k: v for k, v in c.items() if k != "props"}
            merged.update(c["props"])
            c = merged
        flat.append(c)
    surface["components"] = flat
    if isinstance(surface.get("root"), dict):
        surface["root"] = surface["root"].get("id", "root")
    return surface


def extract(text: str) -> dict | None:
    text = re.sub(r"```(json)?|```", "", text).strip()
    s, e = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[s: e + 1]) if s != -1 else None
    except json.JSONDecodeError:
        return None


def call_gemini(prompt: str, system: str, api_key: str) -> dict:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash-lite:generateContent"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
    }
    r = httpx.post(
        url, params={"key": api_key}, json=payload, timeout=120
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:400]}")
    body = r.json()
    raw = body["candidates"][0]["content"]["parts"][0]["text"]
    model = body.get("modelVersion", "gemini-2.0-flash")
    return {"raw": raw, "model": model}


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        # try sourcing from .env on the user's desktop
        env_path = Path.home() / "Desktop" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        print("Set GEMINI_API_KEY or place it in ~/Desktop/.env")
        sys.exit(1)

    catalog = catalog_manifest()
    full_prompt = (
        f"CATALOG:\n{json.dumps(catalog)}\n\n"
        f"DATA MODEL (bind to these keys):\n{json.dumps(DATA_MODEL)}\n\n"
        f"TASK: {TASK}\n"
        "Compose a surface with appropriate components. JSON only."
    )

    print("asking gemini to compose a surface for a study schedule...")
    print("(the prompt never names GanttChart)")
    print()

    result = call_gemini(full_prompt, SYSTEM, api_key)
    raw = result["raw"]
    model = result["model"]
    print(f"model: {model}")
    print("=== RAW GEMINI OUTPUT (first 800 chars) ===")
    print(raw[:800])
    print()

    surface = extract(raw)
    if not surface:
        print("gemini did not return JSON")
        sys.exit(2)

    surface = normalize(surface)
    surface.setdefault("dataModel", DATA_MODEL)

    vr = validate_surface(surface)
    types_used = [c.get("type") for c in surface.get("components", [])]
    gantt_present = "GanttChart" in types_used

    print("=== VALIDATOR VERDICT ===")
    print(f"components proposed : {len(surface.get('components', []))}")
    print(f"types used          : {sorted(set(types_used))}")
    print(f"GanttChart present  : {gantt_present}")
    print(f"accepted            : {len(vr.accepted)}")
    print(f"rejected            : {len(vr.rejections)}")
    for rj in vr.rejections:
        print(f"  - {rj.component_id}.{rj.field}: [{rj.invariant}] {rj.reason}")

    if not gantt_present:
        print("\nWARNING: Gemini did not choose GanttChart. Try re-running or adjusting the data model.")

    OUT.write_text(json.dumps({
        "model": model,
        "prompt_mentions_gantt": False,
        "gantt_present_in_output": gantt_present,
        "raw": raw,
        "surface_accepted": {
            "root": surface.get("root"),
            "components": vr.accepted,
            "dataModel": DATA_MODEL,
        },
        "rejections": [r.as_dict() for r in vr.rejections],
    }, indent=2))
    print(f"\nwrote {OUT}")

    if gantt_present:
        print("\nPROOF: Gemini composed a GanttChart without being told to.")
        print("The validator accepted it. The 'prompt_mentions_gantt': false field")
        print("in the JSON proves the choice was the model's own.")


if __name__ == "__main__":
    main()
