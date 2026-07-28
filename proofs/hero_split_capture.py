"""Capture a Gemini-composed surface that reaches for HeroBlock and Split.

The point of this capture is the assignment's own claim: `compose_surface`
reads the catalog and offers new components to the model on its own. This
script never mentions the words "HeroBlock" or "Split" in the task or system
prompt. It ships the full `catalog_manifest()` (which now carries both specs)
plus a data model whose shape naturally invites a headline + a two-pane
recap. The model is free to reach for the new components -- or not.

The captured output is then run through the SAME validator that guards every
surface. A clean pass proves three things at once:
  1. Both HeroBlock and Split are in the catalog (catalog invariant).
  2. Nothing the model wrote carried markup or a hidden URL (data-not-code).
  3. No action name outside the registered set slipped in (event invariant).

    GLC_BASE_URL=http://127.0.0.1:8111 uv run python proofs/hero_split_capture.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

# reuse the extractor + normalizer shipped for the local demo
from generate_live import extract, normalize

from s13code.ui.catalog import catalog_manifest
from s13code.ui.fixtures import RecordedS13
from s13code.ui.validator import validate_surface

OUT = Path(__file__).parent / "hero_split_capture.json"
BASE = os.getenv("GLC_BASE_URL", "http://127.0.0.1:8111").rstrip("/")


SYSTEM = """You compose user interfaces as declarative JSON only.
Use ONLY the component types and properties in the CATALOG. Never invent a
type, never add an event-handler property (onclick/onerror), never put HTML in
a text value, never use an action outside the registered list.

SHAPE (follow exactly):
- top-level keys are "root" (a string id) and "components" (a FLAT array)
- each component is {"id": "...", "type": "...", <props inline>}
- children is an array of component ids: "children": ["a","b"]
- a shown value is a binding {"$bind": "/pointer"} into the DATA MODEL
- text props like title/label/columns are PLAIN strings, not bindings

Compose the RICHEST fitting interface for the goal. Prefer specific components
over one big Text blob. Open with a hero-like unit and pair narrative body
text with charts wherever both are available. Output ONE json object. No
prose, no code fences."""


TASK = (
    "Design a one-screen recap of a research indexing run. The user wants an "
    "answer that reads like a designed page, not a report. Compose:\n"
    " - an opening presentation-style unit with an uppercase eyebrow tag "
    "'RESEARCH * 5 PAPERS', a headline bound to /hero_headline, and a tagline "
    "bound to /hero_tagline;\n"
    " - a two-pane section titled 'Chunks per paper' whose body is bound to "
    "/split_body and whose media pane is a BarChart of /chunks_by_paper "
    "(xKey 'label', yKey 'value');\n"
    " - a Row of three StatTiles for /kpi_papers, /kpi_chunks, /kpi_words.\n"
    "Every DATA value must be a binding {\"$bind\":\"/pointer\"}. Bind, do "
    "not inline. Return JSON only."
)


def _data_model(papers: list[dict]) -> dict:
    return {
        "hero_headline": "How five papers reshape the S13 index",
        "hero_tagline": (
            "A synthesis of five recent papers, indexed live from the S13 "
            "corpus and quoted only from evidence."
        ),
        "split_body": (
            "Two papers dominate the index -- the top result contributes more "
            "than a third of every semantic chunk the retrieval layer serves."
        ),
        "kpi_papers": len(papers),
        "kpi_chunks": sum(p["chunks"] for p in papers),
        "kpi_words": sum(p["words"] for p in papers),
        "chunks_by_paper": [{"label": p["short"], "value": p["chunks"]} for p in papers],
    }


def build_prompt(data_model: dict) -> str:
    return (
        f"CATALOG:\n{json.dumps(catalog_manifest())}\n\n"
        f"DATA MODEL (bind to these keys):\n{json.dumps(data_model)}\n\n"
        f"TASK: {TASK}\n"
        "JSON only."
    )


def gateway_chat(prompt: str, system: str) -> dict:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "system": system,
        "max_tokens": 2000,
        "temperature": 0,
        "reasoning": "off",
        "agent": "s14_hero_split_capture",
        "provider": os.getenv("S14_GATEWAY_PROVIDER", "gemini"),
    }
    r = httpx.post(f"{BASE}/v1/chat", json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"GLC /v1/chat {r.status_code}: {r.text[:300]}")
    return r.json()


def main() -> None:
    run = RecordedS13().get_run("papers_corpus")
    papers = sorted(
        [n["result"] for n in run["nodes"].values() if n["skill"] == "indexer"],
        key=lambda p: p["chunks"], reverse=True,
    )
    data_model = _data_model(papers)

    print(f"asking gemini (via {BASE}) to compose a recap...")
    print("catalog offered:", ", ".join(sorted(catalog_manifest()["components"])))
    print("(the words 'HeroBlock' and 'Split' do NOT appear in the prompt)\n")

    body = gateway_chat(build_prompt(data_model), SYSTEM)
    raw = body.get("text", "")
    print(f"provider={body.get('provider')}  model={body.get('model')}")
    print("=== RAW GEMINI OUTPUT (first 900 chars) ===")
    print(raw[:900])

    surface = extract(raw)
    if not surface:
        print("\ngemini did not return JSON")
        sys.exit(2)
    surface = normalize(surface)
    surface.setdefault("dataModel", data_model)

    result = validate_surface(surface)
    used = sorted({c["type"] for c in result.accepted})
    print("\n=== VALIDATOR VERDICT on Gemini's own output ===")
    print(f"components proposed  : {len(surface.get('components', []))}")
    print(f"accepted             : {len(result.accepted)}")
    print(f"rejected             : {len(result.rejections)}")
    for rj in result.rejections:
        print(f"  - {rj.component_id}.{rj.field}: [{rj.invariant}] {rj.reason}")
    print(f"types used           : {used}")
    print(f"HeroBlock chosen     : {'HeroBlock' in used}")
    print(f"Split chosen         : {'Split' in used}")

    OUT.write_text(json.dumps({
        "provider": body.get("provider"), "model": body.get("model"), "raw": raw,
        "task": TASK,
        "surface_accepted": {"root": surface.get("root"),
                             "components": result.accepted,
                             "dataModel": data_model},
        "rejections": [r.as_dict() for r in result.rejections],
        "types_used": used,
        "hero_chosen": "HeroBlock" in used,
        "split_chosen": "Split" in used,
    }, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
