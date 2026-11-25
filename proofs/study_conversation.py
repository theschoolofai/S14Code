"""Part 2 proof: the Study Planner answers ONLY in composed interfaces.

Drives 3 turns of a study-planning conversation. Each turn posts a goal to
Gemini (via its REST API directly — no gateway required), asks it to compose
a surface, and validates the result. Turn 1 shows a schedule overview
(GanttChart), turn 2 drills into grade details (DataTable + BarChart), and
turn 3 shows an exam prep plan (Timeline + StatTile + Notice).

Every surface is validated before it is "shown". The conversation proves:
  - Every turn is a composed, validated interface (never a text paragraph)
  - Distinct component types appear across turns (3 unique signatures)
  - GanttChart, DataTable, BarChart, Timeline, StatTile are all used

    GEMINI_API_KEY=<key> UV_LINK_MODE=copy uv run --no-dev python proofs/study_conversation.py
    # or with key in ~/Desktop/.env — the script reads it automatically
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.catalog import catalog_manifest  # noqa: E402
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "study_conversation.json"

SYSTEM = """You compose user interfaces as declarative JSON only.
Use ONLY the component types and properties in the CATALOG. Never invent a type,
never add an event-handler property (onclick/onerror), never put HTML in a text
value, never use an action outside the registered list.

SHAPE (follow exactly):
- top-level keys are "root" (a string id) and "components" (a FLAT array)
- each component is {"id": "...", "type": "...", <props inline>}  — NO "props" wrapper
- children is an array of component ids: "children": ["a","b"]
- a bound value is a binding object {"$bind": "/key"} into the DATA MODEL below
- text props (title, label, caption, xKey, yKey, columns) are PLAIN strings

The DATA MODEL contains the actual data values. Use bindings ({"$bind": "/key"})
to reference them. Output ONE json object. No prose, no code fences."""

CATALOG_JSON = json.dumps(catalog_manifest())

TURNS = [
    {
        "user": "Show my assignment schedule for November and December",
        "data_model": {
            "title": "Study schedule — Nov/Dec 2026",
            "open_count": 3,
            "submitted_count": 2,
            "tasks": [
                {"id":"t1","label":"EAG Session 14","start":"2026-11-25","end":"2026-12-01"},
                {"id":"t2","label":"NLP Assignment 3","start":"2026-11-27","end":"2026-12-05"},
                {"id":"t3","label":"CV Mini-Project","start":"2026-11-28","end":"2026-12-10"},
                {"id":"t4","label":"RL Quiz","start":"2026-11-15","end":"2026-11-20"},
                {"id":"t5","label":"Math Worksheet","start":"2026-11-10","end":"2026-11-18"},
            ],
            "caption": "Bars show start → due date",
        },
        "hint": (
            "Show a time-based schedule overview. "
            "Use GanttChart for the tasks (bind tasks to /tasks, caption to /caption). "
            "Use two StatTile components for open_count (/open_count) and submitted_count (/submitted_count). "
            "Do NOT use the delta or unit props on StatTile."
        ),
    },
    {
        "user": "Show my grades across all courses",
        "data_model": {
            "title": "Semester grades",
            "gpa": "8.6",
            "courses_count": 5,
            "grade_rows": [
                {"Course":"EAG v3","Grade":"A","Score":"92","Credits":"4"},
                {"Course":"NLP","Grade":"A-","Score":"88","Credits":"3"},
                {"Course":"Computer Vision","Grade":"B+","Score":"85","Credits":"4"},
                {"Course":"Reinforcement Learning","Grade":"A","Score":"91","Credits":"3"},
                {"Course":"Mathematics","Grade":"B","Score":"82","Credits":"4"},
            ],
            "score_bars": [
                {"label":"EAG","value":92},
                {"label":"NLP","value":88},
                {"label":"CV","value":85},
                {"label":"RL","value":91},
                {"label":"Math","value":82},
            ],
        },
        "hint": (
            "Show a grade summary. "
            "Use ONE StatTile for GPA (value bound to /gpa, do NOT use delta or unit). "
            "Use DataTable for grade_rows (columns 'Course,Grade,Score,Credits', rows bound to /grade_rows). "
            "Use BarChart for score_bars (data bound to /score_bars, xKey 'label', yKey 'value')."
        ),
    },
    {
        "user": "Build an exam prep timeline for my RL exam next week",
        "data_model": {
            "title": "RL Exam Prep Plan",
            "days_left": 5,
            "readiness_score": 72,
            "study_events": [
                {"label":"Day 1 — Review Q-learning","detail":"Chapters 1–3, 2 hours"},
                {"label":"Day 2 — Policy Gradient methods","detail":"Chapters 4–5, 2 hours"},
                {"label":"Day 3 — Deep RL (DQN, PPO)","detail":"Chapters 6–7, 3 hours"},
                {"label":"Day 4 — Past papers","detail":"3 past exams, timed"},
                {"label":"Day 5 — Weak spots + rest","detail":"Focus on policy gradients"},
            ],
            "notice": "Start early — policy gradient questions appeared in 4 of the last 5 exams.",
        },
        "hint": "Show an exam prep plan: StatTile for days_left and readiness, Timeline for study_events, Notice for the warning.",
    },
]


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
    r = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
        params={"key": api_key},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
        },
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:400]}")
    body = r.json()
    return {
        "raw": body["candidates"][0]["content"]["parts"][0]["text"],
        "model": body.get("modelVersion", "gemini-2.5-flash-lite"),
    }


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        env_path = Path.home() / "Desktop" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        print("Set GEMINI_API_KEY or place it in ~/Desktop/.env")
        sys.exit(1)

    turn_records = []
    convo_history: list[str] = []

    for i, turn in enumerate(TURNS):
        convo_history.append(turn["user"])
        goal = (turn["user"] if len(convo_history) == 1
                else "Original: " + convo_history[0] + "\nNow: " + turn["user"])

        prompt = (
            f"CATALOG:\n{CATALOG_JSON}\n\n"
            f"DATA MODEL:\n{json.dumps(turn['data_model'])}\n\n"
            f"CONVERSATION TURN {i+1}: {goal}\n"
            f"HINT: {turn['hint']}\n"
            "Compose a surface. JSON only."
        )

        t0 = time.time()
        result = call_gemini(prompt, SYSTEM, api_key)
        raw = result["raw"]
        model = result["model"]
        latency = round(time.time() - t0, 1)

        surface = extract(raw)
        if not surface:
            print(f"turn {i+1}: Gemini did not return JSON")
            sys.exit(2)
        surface = normalize(surface)
        surface.setdefault("dataModel", turn["data_model"])

        vr = validate_surface(surface)
        types = sorted({c.get("type") for c in surface.get("components", [])})
        clean = len(vr.rejections) == 0

        print(f"turn {i+1}: {len(vr.accepted):>2} components, clean={clean}, {latency}s  {types}")
        if vr.rejections:
            for rj in vr.rejections:
                print(f"  REJECT: {rj.component_id}.{rj.field}: [{rj.invariant}] {rj.reason}")

        turn_records.append({
            "turn": i + 1,
            "user_said": turn["user"],
            "model": model,
            "latency_s": latency,
            "clean": clean,
            "component_count": len(vr.accepted),
            "component_types": types,
            "rejections": [r.as_dict() for r in vr.rejections],
            "surface": {"root": surface.get("root"), "components": vr.accepted,
                        "dataModel": turn["data_model"]},
        })

    # Proof summary
    signatures = [tuple(t["component_types"]) for t in turn_records]
    union = {t for sig in signatures for t in sig}
    report = {
        "every_turn_composed": all(t["component_count"] > 0 for t in turn_records),
        "every_turn_clean": all(t["clean"] for t in turn_records),
        "distinct_signatures": len(set(signatures)),
        "union_component_types": sorted(union),
        "gantt_in_turn_1": "GanttChart" in turn_records[0]["component_types"],
        "datatable_in_turn_2": "DataTable" in turn_records[1]["component_types"],
        "timeline_in_turn_3": "Timeline" in turn_records[2]["component_types"],
        "turns": turn_records,
    }

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\ndistinct interface signatures: {report['distinct_signatures']}/{len(TURNS)}")
    print(f"types across all turns: {report['union_component_types']}")
    print(f"GanttChart in turn 1: {report['gantt_in_turn_1']}")
    print(f"DataTable in turn 2 : {report['datatable_in_turn_2']}")
    print(f"Timeline in turn 3  : {report['timeline_in_turn_3']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
