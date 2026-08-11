"""Generate a REAL A2UI surface with Gemini, through the glc_v3 gateway, and
check whether it reaches for the newly catalogued Accordion component on its
own — the same way generate_gemini.py proved the original catalog.

This uses the EXACT system + "compose" instruction text compose_surface uses
in runtime.py (copied verbatim), and the EXACT shared validator, against a
dataModel shaped the way a genuinely completed "content" role run leaves it:
an ordered /sections array of {heading, points} — the same generic shape
compose_surface already builds from a real structured answer (see
runtime.py's compose_surface, "content_structured" handling). Nothing here
tells the model to use "Accordion"; it only ever sees the type listed in
catalog_manifest(), like every other component, and a per-pointer hint that
now also names Accordion as one of three valid layouts for grouped content
(alongside Timeline and Cards) — the same kind of multi-option hint /series
and /metrics already get.

    GLC_BASE_URL=http://127.0.0.1:8111 uv run python proofs/generate_accordion.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.runtime import _parse_json_object  # noqa: E402
from s13code.ui.catalog import catalog_manifest  # noqa: E402
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "generated_accordion.json"
BASE = os.getenv("GLC_BASE_URL", "http://127.0.0.1:8111").rstrip("/")

GOAL = (
    "Answer these frequently asked questions about getting started with open-source "
    "contribution, so a reader can open one question at a time: "
    "why contribute, what the common early challenges are, and what the first steps are."
)

# The real content a "content" role run leaves behind for this goal, in the
# generic {"sections": [{"heading", "points"}]} shape compose_surface reads
# off content_structured (runtime.py, compose_surface).
SECTIONS = [
    {"heading": "Why contribute?", "points": [
        "Learn real-world codebases and review practices",
        "Build a public track record of shipped work",
        "Meet maintainers and other contributors",
    ]},
    {"heading": "What are the common early challenges?", "points": [
        "Finding an issue scoped for a first-time contributor",
        "Understanding the project's contribution guidelines",
        "Getting a pull request reviewed in a busy project",
    ]},
    {"heading": "What are the first steps?", "points": [
        "Read CONTRIBUTING.md and the code of conduct",
        "Look for issues labeled good-first-issue",
        "Open a small pull request and ask for review",
    ]},
]

DATA_MODEL = {
    "title": "Getting started with open-source contribution",
    "goal": GOAL,
    "summary": "A short FAQ for a first-time open-source contributor.",
    "sections": SECTIONS,
    "section_events": [{"time": s["heading"], "label": "; ".join(s["points"])} for s in SECTIONS],
    **{f"section_{i}_heading": s["heading"] for i, s in enumerate(SECTIONS)},
    **{f"section_{i}_points": "\n".join(f"• {p}" for p in s["points"]) for i, s in enumerate(SECTIONS)},
}

# The EXACT system prompt compose_surface uses (runtime.py), copied verbatim
# so this proof exercises the real production prompt, not an approximation.
SYSTEM = (
    "You compose declarative A2UI interfaces for a goal, binding every value to a provided "
    'dataModel. Output ONLY one JSON object {"root":"root","components":[...]}. Each component '
    'is a FLAT object whose fields sit DIRECTLY on it: {"id":..., "type":..., <prop>:<value>, '
    '...}. Do NOT wrap fields in a "props" object and do NOT nest a "properties" key. The '
    'catalog uses A2UI Basic names: use "Text" with "variant":"heading" for titles (there is NO '
    '"Heading" type), "Row"/"Column"/"List"/"Card" for layout (there is NO "Grid" type), "Tabs" '
    'whose "children" are the panels directly (there is NO separate "Tab" type), and "Button" '
    'for tappable choices. Shape examples (fields inline): '
    '{"id":"h","type":"Text","variant":"heading","text":{"$bind":"/title"}}  '
    '{"id":"r","type":"Row","align":"stretch","justify":"spaceBetween","children":["a","b"]}  '
    '{"id":"b1","type":"Button","label":"Choice A","onPress":{"action":"request_data"}}  '
    '{"id":"body","type":"Text","variant":"body","text":{"$bind":"/summary"}}  '
    '{"id":"tabs","type":"Tabs","labels":"One,Two","children":["p0","p1"]}. '
    "Use ONLY the component types and props named in the catalog. Every DATA value a component "
    'shows MUST be a binding {"$bind":"/pointer"} into the dataModel; a Button/Card/Tabs '
    "label/title and column names may be literal UI strings. An onPress action MUST be one of the "
    "registered actions (use \"request_data\" for choices); never invent an action, component "
    "type, prop, event handler, URL, or markup. children/labels reference component ids. "
    "Prefer the RICHEST fitting component for each piece of data, NEVER one big Text blob: a "
    "Timeline or a List/Column of Cards for ordered groups, StatTiles in a Row for key numbers, "
    "a BarChart or Sparkline for a numeric series, a DataTable for tabular rows, and Buttons for "
    "tappable choices. Fall back to a single Text only when the data has no structure. Return "
    "JSON only: no prose, no fences."
)

# The EXACT per-pointer "compose" instruction compose_surface uses (runtime.py),
# copied verbatim (including the Accordion option added alongside it).
COMPOSE_INSTRUCTION = (
    "Compose the RICHEST interface that serves the goal above, using ONLY catalog types, "
    "and choose components from the data that is actually present in available_pointers. "
    'Start with a Text (variant "heading") bound to /title, then a Text (variant "body") '
    "bound to /intro or /summary if present. Then map the structured data to rich "
    "components (skip any pointer that is absent): "
    "for /sections (ordered groups) render a Timeline bound to /section_events, a "
    "List/Column of Cards (one Card per section titled with the literal "
    "/section_N_heading and a Text bound to /section_N_points), or — when the sections "
    "read like separate questions or topics a user would open one at a time — an "
    "Accordion bound to /sections with a literal title; pick whichever genuinely fits "
    "the content best; "
    "for /metrics render a Row of StatTiles, each StatTile value bound to /metric_N_value "
    "with a literal label; "
    "for /series render a BarChart (data bound to /series, xKey \"label\", yKey \"value\") "
    "or a Sparkline bound to /series_values; "
    "for /table_rows render a DataTable (rows bound to /table_rows, columns the literal "
    "/table_columns joined by commas); "
    "for /choices (the goal asks the user to pick) render one tappable Button per entry, "
    "label the literal /choice_N_label, onPress action \"request_data\"; "
    "you may also add a ProgressBar bound to /progress_value (max /progress_max) and a "
    "Timeline bound to /timeline for the run's own steps. Do NOT dump everything into one "
    "Text. Bind every DATA value to a /pointer listed in available_pointers."
)


def build_instruction() -> dict:
    manifest = catalog_manifest()
    pointers = sorted("/" + key for key in DATA_MODEL)
    return {
        "goal": GOAL,
        "catalog": manifest,
        "dataModel": DATA_MODEL,
        "available_pointers": pointers,
        "compose": COMPOSE_INSTRUCTION,
    }


def gateway_chat(prompt: str, system: str) -> dict:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "system": system,
        "max_tokens": 1500,
        "temperature": 0,
        "reasoning": "off",
        "agent": "s14_surface",
        "provider": os.getenv("S14_GATEWAY_PROVIDER", "gemini"),
    }
    r = httpx.post(f"{BASE}/v1/chat", json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"GLC /v1/chat {r.status_code}: {r.text[:300]}")
    return r.json()


def main() -> None:
    instruction = build_instruction()
    print(f"asking gemini (via {BASE}) to compose an A2UI surface for:\n  {GOAL}\n")
    body = gateway_chat(json.dumps(instruction), SYSTEM)
    raw = body.get("text", "")
    print(f"provider={body.get('provider')}  model={body.get('model')}")
    print("=== RAW GEMINI OUTPUT (first 900 chars) ===")
    print(raw[:900])

    surface = _parse_json_object(raw)
    if not surface:
        print("\ngemini did not return parseable JSON")
        sys.exit(2)
    surface.setdefault("dataModel", DATA_MODEL)

    result = validate_surface(surface)
    types_used = sorted({c["type"] for c in result.accepted})
    print("\n=== VALIDATOR VERDICT ===")
    print(f"components proposed : {len(surface.get('components', []))}")
    print(f"accepted            : {len(result.accepted)}")
    print(f"rejected            : {len(result.rejections)}")
    print(f"component types used: {types_used}")
    for rj in result.rejections:
        print(f"  - {rj.component_id}.{rj.field}: [{rj.invariant}] {rj.reason}")

    used_accordion = "Accordion" in types_used
    print(f"\nAccordion chosen by the model (unprompted by name): {used_accordion}")

    ids = {c["id"] for c in result.accepted}
    dangling = [ch for c in result.accepted for ch in c.get("children", []) if ch not in ids]
    print(f"dangling child refs : {dangling}")

    OUT.write_text(json.dumps({
        "goal": GOAL, "provider": body.get("provider"), "model": body.get("model"),
        "raw": raw,
        "surface_accepted": {"root": surface.get("root"), "components": result.accepted, "dataModel": DATA_MODEL},
        "rejections": [r.as_dict() for r in result.rejections],
        "component_types_used": types_used, "used_accordion": used_accordion,
        "dangling_child_refs": dangling,
    }, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
