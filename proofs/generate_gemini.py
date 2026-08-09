"""Generate a surface with GEMINI, through the glc_v3 gateway, and validate it.

Same generative loop as generate_live.py, but the model call routes through the
running gateway on 8111 with provider=gemini (S13's exact path). Captures the
raw Gemini output, normalizes structure only, runs it through the SAME validator
that guards injection, and writes gemini_surface.json.

    GLC_BASE_URL=http://127.0.0.1:8111 uv run python proofs/generate_gemini.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

# reuse the prompt + normalizer already written for the local demo
from generate_live import SYSTEM, build_prompt, extract, normalize

from s13code.ui.fixtures import RecordedS13
from s13code.ui.validator import validate_surface

OUT = Path(__file__).parent / "gemini_surface.json"
BASE = os.getenv("GLC_BASE_URL", "http://127.0.0.1:8111").rstrip("/")


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
    run = RecordedS13().get_run("papers_corpus")
    papers = sorted(
        [n["result"] for n in run["nodes"].values() if n["skill"] == "indexer"],
        key=lambda p: p["chunks"], reverse=True,
    )
    data_model = {
        "title": "Research corpus — composed by Gemini",
        "kpi_papers": len(papers),
        "kpi_chunks": sum(p["chunks"] for p in papers),
        "kpi_words": sum(p["words"] for p in papers),
        "chunks_by_paper": [{"label": p["short"], "value": p["chunks"]} for p in papers],
        "table_rows": [{"Paper": p["paper"], "Chunks": p["chunks"], "Year": p["year"]} for p in papers],
    }

    print(f"asking gemini (via {BASE}) to compose an A2UI surface...\n")
    body = gateway_chat(build_prompt(f"Summarize {len(papers)} indexed papers.", data_model), SYSTEM)
    raw = body.get("text", "")
    print(f"provider={body.get('provider')}  model={body.get('model')}")
    print("=== RAW GEMINI OUTPUT (first 700 chars) ===")
    print(raw[:700])

    surface = extract(raw)
    if not surface:
        print("\ngemini did not return JSON")
        sys.exit(2)
    surface = normalize(surface)
    surface.setdefault("dataModel", data_model)

    result = validate_surface(surface)
    print("\n=== VALIDATOR VERDICT on Gemini's own output ===")
    print(f"components proposed : {len(surface.get('components', []))}")
    print(f"accepted            : {len(result.accepted)}")
    print(f"rejected            : {len(result.rejections)}")
    for rj in result.rejections:
        print(f"  - {rj.component_id}.{rj.field}: [{rj.invariant}] {rj.reason}")

    # coherence check: do root.children resolve?
    ids = {c["id"] for c in result.accepted}
    dangling = [ch for c in result.accepted for ch in c.get("children", []) if ch not in ids]
    print(f"dangling child refs : {dangling}")

    OUT.write_text(json.dumps({
        "provider": body.get("provider"), "model": body.get("model"), "raw": raw,
        "surface_accepted": {"root": surface.get("root"), "components": result.accepted, "dataModel": data_model},
        "rejections": [r.as_dict() for r in result.rejections], "dangling_child_refs": dangling,
    }, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
