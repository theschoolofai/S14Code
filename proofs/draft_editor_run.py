"""Prove Gemini composes the DraftEditor component ON ITS OWN, from the catalog.

Session 14 Part 1 asks for a captured run where the model composes a newly added
component "without being told to name it, because compose_surface reads the
catalog and offers your component to the model on its own".

This script makes that claim FALSIFIABLE rather than anecdotal:

  1. It names the component NOWHERE. Every prompt is checked, and so is the
     whole of runtime.py — the module that builds the compose instruction. If
     "DraftEditor" appears in either, the proof fails loudly. The only place the
     model can learn the component exists is the catalog manifest that
     compose_surface passes it.
  2. It runs SEVERAL drafting prompts, so the result is a rate, not one lucky
     screenshot.
  3. It runs a CONTROL prompt that should NOT produce a draft. A component that
     fires on every long piece of text has not been "chosen"; one that stays
     away when the data does not fit has.

Same real path as harness_run.py: a real S13Runtime (durable memory + live graph
+ skills), respond_as="ui", the model call routed through the glc_v3 gateway.

S14_CONTENT_MAX_TOKENS is REQUIRED here and is not a fix in disguise: the
gateway's shipped default of 700 truncates a structured answer that carries a
long drafted message, so its JSON never closes, nothing parses, and no draft
ever reaches the data model. Raising the cap for the duration of a proof run
changes no committed behaviour — the default is untouched — and the value used
is recorded in the output so the number below can be checked against it.

    S14_CONTENT_MAX_TOKENS=2000 S13_GATEWAY_PROVIDER=gemini \
      GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/draft_editor_run.py

Writes proofs/draft_editor_run.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

S13CODE = Path(os.environ.get("S13CODE_PATH") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(S13CODE))

from s13code.core.memory import MemoryScope  # noqa: E402
from s13code.gateway import GatewayClient  # noqa: E402
from s13code.runtime import S13Runtime  # noqa: E402
from s13code.ui.catalog import COMPONENTS  # noqa: E402

OUT = Path(__file__).parent / "draft_editor_run.json"
COMPONENT = "DraftEditor"
ATTEMPTS = 3          # a free-tier key pool returns HTTP 429 often enough to need retries
BACKOFF = 12.0

# Five drafting goals plus one control. Synthetic identities only — no real
# names, employers or addresses ever enter a committed proof.
CASES = [
    {"id": "time_off",  "expect_draft": True,
     "prompt": "Draft me an email about my time off for next week. my manager name is sam"},
    {"id": "thank_you", "expect_draft": True,
     "prompt": "Write a short thank-you note to my professor for a recommendation letter."},
    {"id": "linkedin",  "expect_draft": True,
     "prompt": "Draft a LinkedIn post announcing I finished an AI course."},
    {"id": "invoice",   "expect_draft": True,
     "prompt": "Write a polite reminder message about an unpaid invoice."},
    {"id": "bio",       "expect_draft": True,
     "prompt": "Draft a two-line bio for a conference programme."},
    {"id": "control_explain", "expect_draft": False,
     "prompt": "Explain how photosynthesis works."},
]


def _no_leak_checks() -> dict:
    """The component name must appear in the CATALOG and nowhere in the prompts
    or in the module that builds the compose instruction."""
    runtime_src = (S13CODE / "s13code" / "runtime.py").read_text(encoding="utf-8")
    catalog_src = (S13CODE / "s13code" / "ui" / "catalog.py").read_text(encoding="utf-8")
    prompt_hits = [c["id"] for c in CASES if COMPONENT.lower() in c["prompt"].lower()]
    return {
        "component": COMPONENT,
        "in_catalog": COMPONENT in COMPONENTS,
        "named_in_catalog_source": COMPONENT in catalog_src,
        "named_in_runtime_source": COMPONENT in runtime_src,
        "prompts_naming_component": prompt_hits,
        "clean": (COMPONENT in COMPONENTS
                  and COMPONENT in catalog_src
                  and COMPONENT not in runtime_src
                  and not prompt_hits),
    }


async def _run_case(runtime: S13Runtime, gateway: GatewayClient, case: dict) -> dict:
    last_error = ""
    for attempt in range(1, ATTEMPTS + 1):
        result = await runtime.run(
            prompt=case["prompt"],
            scope=MemoryScope("s14-proof", "draft-editor", "composer", "s13code"),
            llm=lambda prompt, system: gateway.complete(prompt, system),
            source_uri="proof://draft_editor/compose_surface",
            source_author="s14-proof",
            respond_as="ui",
        )
        snapshot = runtime.graph.snapshot(result["run_id"])
        node = snapshot.nodes.get("surface", {})
        payload = node.get("result") or {}
        if node.get("state") == "succeeded":
            surface = payload.get("surface") or {}
            components = surface.get("components", [])
            types = sorted({c.get("type") for c in components})
            mine = [c for c in components if c.get("type") == COMPONENT]
            return {
                "id": case["id"], "prompt": case["prompt"],
                "expect_draft": case["expect_draft"], "ok": True,
                "attempts": attempt, "run_id": result["run_id"],
                "provider": payload.get("provider"), "model": payload.get("model"),
                "component_types": types,
                "composed_component": bool(mine),
                "component_instances": mine,
                "validator": payload.get("validator"),
                "draft_in_data_model": "draft" in (payload.get("data_model") or {}),
                "draft_title": (payload.get("data_model") or {}).get("draft_title"),
                "surface": surface,
                "raw_surface": payload.get("raw_surface"),
            }
        last_error = payload.get("error", "") or "surface node did not succeed"
        if attempt < ATTEMPTS:
            await asyncio.sleep(BACKOFF)
    return {"id": case["id"], "prompt": case["prompt"], "expect_draft": case["expect_draft"],
            "ok": False, "attempts": ATTEMPTS, "error": last_error[:400]}


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")
    # Document indexing is not exercised here; keep the heavy local segmenter off.
    os.environ.setdefault("S13_LIVE_SEMANTIC_CHUNKING", "0")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-draft-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    leak = _no_leak_checks()
    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)

    content_max_tokens = int(os.getenv("S14_CONTENT_MAX_TOKENS", "700"))
    print(f"component        : {COMPONENT}")
    print(f"data dir         : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"provider (env)   : {os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"content max_tokens: {content_max_tokens}")
    if content_max_tokens < 1500:
        print("  ! at this cap a long draft truncates before its JSON closes; expect a low rate.\n"
              "    re-run with S14_CONTENT_MAX_TOKENS=2000 for a representative result.")
    print(f"named in catalog : {leak['named_in_catalog_source']}   "
          f"named in runtime.py: {leak['named_in_runtime_source']}")
    print(f"prompts naming it: {leak['prompts_naming_component'] or 'none'}\n")

    runs = []
    for case in CASES:
        print(f"  running {case['id']} ...", flush=True)
        runs.append(await _run_case(runtime, gateway, case))

    await gateway.close()
    runtime.close()

    drafting = [r for r in runs if r["expect_draft"] and r["ok"]]
    controls = [r for r in runs if not r["expect_draft"] and r["ok"]]
    hits = sum(1 for r in drafting if r["composed_component"])
    control_hits = sum(1 for r in controls if r["composed_component"])
    rejected = sum((r.get("validator") or {}).get("rejected", 0) for r in runs if r["ok"])

    proof = {
        "claim": (f"Gemini composed {COMPONENT} from the catalog alone. The component name appears "
                  f"in the catalog and in no prompt and nowhere in runtime.py, which builds the "
                  f"compose instruction."),
        "component": COMPONENT,
        "no_leak_checks": leak,
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "content_max_tokens": content_max_tokens,
        "summary": {
            "drafting_prompts": len([c for c in CASES if c["expect_draft"]]),
            "drafting_succeeded": len(drafting),
            "drafting_composed_component": hits,
            "control_prompts": len([c for c in CASES if not c["expect_draft"]]),
            "control_succeeded": len(controls),
            "control_composed_component": control_hits,
            "total_validator_rejections": rejected,
        },
        "runs": runs,
    }
    OUT.write_text(json.dumps(proof, indent=2))

    print("\n=== DRAFT EDITOR PROOF ===")
    print(f"{'case':<18}{'ok':<5}{'composed':<10}{'model':<20}{'proposed/acc/rej'}")
    for r in runs:
        v = r.get("validator") or {}
        counts = f"{v.get('proposed')}/{v.get('accepted')}/{v.get('rejected')}" if r["ok"] else "-"
        print(f"{r['id']:<18}{str(r['ok']):<5}{str(r.get('composed_component','-')):<10}"
              f"{str(r.get('model','-')):<20}{counts}")
    print(f"\ndrafting prompts : {hits}/{len(drafting)} composed {COMPONENT}")
    print(f"control prompts  : {control_hits}/{len(controls)} composed {COMPONENT}  (0 is the good result)")
    print(f"validator        : {rejected} total rejections")
    print(f"no-leak checks   : {'PASS' if leak['clean'] else 'FAIL'}")
    print(f"\nwrote {OUT}")

    return 0 if (leak["clean"] and hits >= 1) else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
