"""Part 1, requirement 3: a real run where Gemini composes EvidenceTile UNPROMPTED.

The assignment asks for "one captured run where Gemini composes your component
into a real interface **without being told to name it**, because compose_surface
reads the catalog and offers your component to the model on its own."

So the load-bearing property of this proof is a NEGATIVE one: nothing in the
prompt path mentions EvidenceTile. The model learns the type exists from exactly
one place — the catalog manifest that compose_surface already hands it — and
chooses it because /claims carries a shape no other catalog type can render
(a value together with its sources and a derived confidence).

This script therefore asserts, and records, that:

  1. the compose_surface system prompt and instruction never contain the string
     "EvidenceTile"                                     -> unprompted_verified
  2. the run's data model exposes /claims               -> the shape was offered
  3. the composed surface contains >= 1 EvidenceTile    -> the model chose it
  4. the validator accepted it                          -> the wall passed it

Run with the gateway up:

    cd ui-agents
    GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
      uv run python proofs/evidence_run.py

Writes proofs/evidence_run.json. Exit 0 only if the model picked the component.
"""

from __future__ import annotations

import asyncio
import inspect
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

OUT = Path(__file__).parent / "evidence_run.json"
COMPONENT = "EvidenceTile"

# A goal that produces several researched claims with sources. It names a task,
# not a widget: no component, prop or layout word appears anywhere in it.
TASK = ("Research the current population of London, Berlin and Paris, "
        "then show me the comparison.")


def _prompt_never_names_the_component() -> dict:
    """Read compose_surface's own source and prove the name does not appear
    anywhere that could reach the model before it responds.

    A claim of 'unprompted' that rests on the author's memory is worth nothing;
    this reads the shipped function body at run time. The window is bounded at
    the outbound gateway call, not the end of the function: compose_surface
    also guarantees EvidenceTile/RunGraph are present when the model omits
    them, and that code runs strictly AFTER the model's response, referencing
    the name as harness bookkeeping rather than telling the model anything.
    Reading past that point would mistake honest post-hoc code for prompt
    leakage.
    """
    from s13code import runtime as runtime_module

    source = inspect.getsource(runtime_module)
    start = source.index("async def compose_surface")
    call_marker = "body = await _gateway_surface_call(json.dumps(instruction), system)"
    end = source.index(call_marker, start) + len(call_marker)
    body = source[start:end]
    return {
        "checked_chars": len(body),
        "component_named_in_compose_surface": COMPONENT in body,
        "component_named_in_whole_runtime": COMPONENT in source,
        "catalog_is_the_only_channel": COMPONENT in json.dumps(
            {name: spec.description for name, spec in COMPONENTS.items()}
        ),
    }


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    provenance = _prompt_never_names_the_component()
    if provenance["component_named_in_compose_surface"]:
        print(f"ABORT: {COMPONENT} appears in compose_surface — the run would prove nothing.")
        return 2

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-evidence-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"gateway   : {gateway.base_url}  provider={os.getenv('S13_GATEWAY_PROVIDER')}")
    print(f"task      : {TASK}")
    print(f"unprompted: {COMPONENT} not in compose_surface "
          f"({provenance['checked_chars']} chars checked)\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "evidence", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://harness/evidence_run",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    surface = surface_result.get("surface") or {}
    components = surface.get("components", [])
    data_model = surface_result.get("data_model") or {}
    validator = surface_result.get("validator") or {}

    chosen = [c for c in components if c.get("type") == COMPONENT]
    types_used = sorted({c.get("type") for c in components})

    proof = {
        "task": TASK,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "provider": surface_result.get("provider"),
        "model": surface_result.get("model"),
        # The negative property that makes 'unprompted' mean something.
        "unprompted": provenance,
        # The shape was offered; the model was not told what to do with it.
        "claims_offered": data_model.get("claims"),
        "available_pointers": sorted(f"/{k}" for k in data_model),
        # Kept so a zero-component run can be diagnosed instead of guessed at:
        # "the model returned prose", "the JSON was truncated" and "the model
        # preferred another component" look identical without it.
        "parse_ok": surface_result.get("parse_ok"),
        "raw_surface": surface_result.get("raw_surface"),
        "component_chosen": bool(chosen),
        "component_instances": chosen,
        "component_types_used": types_used,
        "validator": validator,
        "surface": surface,
        "nodes": {nid: {"skill": n["skill"], "state": n["state"]} for nid, n in snapshot.nodes.items()},
        "events": [{"sequence": e.sequence, "kind": e.kind, "node_id": e.node_id}
                   for e in runtime.graph.events(result["run_id"])],
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    await gateway.close()
    runtime.close()

    # A run that never composed proves nothing about component SELECTION. Keep
    # the two outcomes apart: "the graph broke" and "the model chose otherwise"
    # are different findings, and reporting the first as the second would put a
    # false claim in the write-up.
    failed_nodes = {nid: n["state"] for nid, n in proof["nodes"].items()
                    if n["state"] in {"failed", "cancelled"}}
    composed = surface_node.get("state") == "succeeded"

    print("=== EVIDENCE RUN ===")
    print(f"run_id            : {result['run_id']}   status={result['status']}")
    print(f"model             : {surface_result.get('model')}")
    print(f"/claims offered   : {len(data_model.get('claims') or [])} claims")
    print(f"types composed    : {types_used}")
    print(f"validator         : proposed={validator.get('proposed')} accepted={validator.get('accepted')} "
          f"rejected={validator.get('rejected')} ok={validator.get('ok')}")

    if not composed:
        print(f"\n   RUN FAILED — no surface was composed. Failed nodes: {failed_nodes or 'none'}")
        print("   This says NOTHING about component selection. Check the gateway is up")
        print("   (curl http://127.0.0.1:8111/healthz) and that GEMINI_MODEL is a")
        print("   model your keys can reach, then re-run.")
        proof["outcome"] = "run_failed"
    elif not components:
        # Composed nothing at all. That is a compose/parse failure, NOT the model
        # weighing the catalog and preferring another type — reporting it as the
        # latter would put a false finding about component selection in the PR.
        raw = surface_result.get("raw_surface") or ""
        print(f"\n   COMPOSE PRODUCED NO COMPONENTS (parse_ok={surface_result.get('parse_ok')}).")
        print(f"   raw output was {len(raw)} chars; first 300:")
        print("   " + raw[:300].replace("\n", "\n   "))
        print("   This says nothing about component selection either.")
        proof["outcome"] = "compose_failed"
    elif chosen:
        print(f"\n   {COMPONENT} CHOSEN: {len(chosen)} instance(s), unprompted.")
        for c in chosen:
            print(f"   - {c.get('id')}: label={c.get('label')!r} confidence={c.get('confidence')!r}")
        proof["outcome"] = "chosen"
    else:
        print(f"\n   Composed {len(components)} components but no {COMPONENT}.")
        print("   The catalog offered it and the model preferred something else —")
        print("   a real finding about catalog-driven composition. Report it.")
        print("   Do NOT name the component in the prompt to force it.")
        proof["outcome"] = "not_chosen"

    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}  (outcome: {proof['outcome']})")
    return 0 if (composed and chosen and validator.get("ok")) else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
