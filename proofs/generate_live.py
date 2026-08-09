"""Generate a surface with a REAL model and validate its output.

Calls a live model (through the glc_v3 gateway if it can complete, else a
direct Ollama fallback so the generative loop can be demonstrated locally),
then runs the model's raw output through the SAME validator that guards against
injection. Proves the surface was composed by a model, not by Python.

    uv run python proofs/generate_live.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.catalog import catalog_manifest
from s13code.ui.fixtures import RecordedS13
from s13code.ui.validator import validate_surface

OUT = Path(__file__).parent / "generated_surface.json"

SYSTEM = """You compose user interfaces as declarative JSON only.
Use ONLY the component types and properties in the CATALOG. Never invent a type,
never add an event-handler property (onclick/onerror), never put HTML in a text
value, never use an action outside the registered list.

SHAPE (follow exactly):
- top-level keys are "root" (a string id) and "components" (a FLAT array)
- each component is {"id": "...", "type": "...", <props inline>}  -- NO "props" wrapper
- children is an array of component ids: "children": ["a","b"]
- a shown value is a binding object {"$bind": "/key"} into the DATA MODEL
- text props like columns/xKey/yKey/title/label are PLAIN strings, not bindings

EXAMPLE:
{"root":"root","components":[
  {"id":"root","type":"Column","children":["h","g","bc"]},
  {"id":"h","type":"Heading","text":{"$bind":"/title"}},
  {"id":"g","type":"Grid","cols":2,"children":["t1"]},
  {"id":"t1","type":"StatTile","label":"Papers","value":{"$bind":"/kpi_papers"},"tone":"good"},
  {"id":"bc","type":"BarChart","title":"Chunks","data":{"$bind":"/chunks_by_paper"},"xKey":"label","yKey":"value"}
]}
Output ONE json object. No prose, no code fences."""


def build_prompt(task, data_model):
    return (
        f"CATALOG:\n{json.dumps(catalog_manifest())}\n\n"
        f"DATA MODEL (bind to these keys):\n{json.dumps(data_model)}\n\n"
        f"TASK: {task}\n"
        "Compose a dashboard with: a Heading bound to /title; a Grid (cols 3) of "
        "StatTiles for kpi_papers, kpi_chunks, kpi_words; a BarChart of "
        "chunks_by_paper (xKey label, yKey value); and a DataTable of table_rows "
        "with columns 'Paper,Chunks,Year'. JSON only."
    )


def normalize(surface):
    """Structural-only normalization of a model's output. It unwraps common
    shapes (root.components, a "props" wrapper) so the surface can be validated.
    It NEVER edits a value to fix a security violation -- hallucinated types,
    handlers, or actions must still reach the validator and be rejected."""
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
    # ensure a root id exists
    if isinstance(surface.get("root"), dict):
        surface["root"] = surface["root"].get("id", "root")
    return surface


def ollama(prompt, system, model="llama3.2:latest"):
    r = httpx.post(
        "http://127.0.0.1:11434/api/generate",
        json={"model": model, "system": system, "prompt": prompt, "stream": False,
              "options": {"temperature": 0}, "format": "json"},
        timeout=180,
    )
    r.raise_for_status()
    return r.json().get("response", "")


def extract(text):
    text = re.sub(r"```(json)?|```", "", text).strip()
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s : e + 1]) if s != -1 else None


def main():
    run = RecordedS13().get_run("papers_corpus")
    papers = sorted(
        [n["result"] for n in run["nodes"].values() if n["skill"] == "indexer"],
        key=lambda p: p["chunks"], reverse=True,
    )
    data_model = {
        "title": "Research corpus — composed by a live model",
        "kpi_papers": len(papers),
        "kpi_chunks": sum(p["chunks"] for p in papers),
        "kpi_words": sum(p["words"] for p in papers),
        "chunks_by_paper": [{"label": p["short"], "value": p["chunks"]} for p in papers],
        "table_rows": [{"Paper": p["paper"], "Chunks": p["chunks"], "Year": p["year"]} for p in papers],
    }

    model_name = "gemma4:26b"
    print(f"asking {model_name} to compose an A2UI surface...\n")
    raw = ollama(build_prompt(f"Summarize {len(papers)} indexed papers.", data_model), SYSTEM, model_name)
    print("=== RAW MODEL OUTPUT (first 600 chars) ===")
    print(raw[:600])

    surface = extract(raw)
    if not surface:
        print("\nmodel did not return JSON")
        sys.exit(2)
    surface = normalize(surface)
    if "components" not in surface:
        print("\nmodel did not return a usable surface object")
        sys.exit(2)
    surface.setdefault("dataModel", data_model)

    result = validate_surface(surface)
    print("\n=== VALIDATOR VERDICT on the model's own output ===")
    print(f"components proposed : {len(surface.get('components', []))}")
    print(f"accepted            : {len(result.accepted)}")
    print(f"rejected            : {len(result.rejections)}")
    for rj in result.rejections:
        print(f"  - {rj.component_id}.{rj.field}: [{rj.invariant}] {rj.reason}")

    OUT.write_text(json.dumps(
        {"model": model_name, "raw": raw, "surface_accepted": {
            "root": surface.get("root"),
            "components": result.accepted,
            "dataModel": data_model,
        }, "rejections": [r.as_dict() for r in result.rejections]}, indent=2))
    print(f"\nwrote {OUT}")
    print("\nThis surface was composed by a model. The validator — not the model —"
          "\ndecided which of its components are legal to render.")


if __name__ == "__main__":
    main()
