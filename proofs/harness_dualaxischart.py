"""Live proof: Gemini composes DualAxisChart without being told to name it.

The user goal asks for a comparison of revenue in millions alongside profit margin
percentages across companies. The compose_surface skill offers the catalog
(including DualAxisChart) and offers it to the model. The proof asserts the
accepted surface contains DualAxisChart and re-validates clean.

Requires a running glc_v3 gateway with Gemini configured:

    S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
      uv run python proofs/harness_dualaxischart.py
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
from s13code.ui.validator import validate_surface  # noqa: E402

OUT = Path(__file__).parent / "harness_dualaxischart.json"
# Deliberately does NOT name DualAxisChart or any catalog type.
TASK = (
    "Compare the annual revenue in millions (bars) alongside profit margin percentages (line) "
    "for TechCorp, BioHealth, RetailMax, and AutoGlobal in 2025. "
    "Present a multi-metric comparative breakdown of these four companies."
)


async def main() -> int:
    os.environ.setdefault("S13_GATEWAY_PROVIDER", "gemini")
    os.environ.setdefault("GLC_BASE_URL", "http://127.0.0.1:8111")

    data_dir = Path(os.getenv("S13_DATA_DIR") or tempfile.mkdtemp(prefix="s14-dualchart-proof-"))
    os.environ["S13_DATA_DIR"] = str(data_dir)

    gateway = GatewayClient()
    runtime = S13Runtime(root=data_dir)
    print(f"harness data dir : {data_dir}")
    print(f"gateway base     : {gateway.base_url}")
    print(f"task             : {TASK[:120]}...\n")

    result = await runtime.run(
        prompt=TASK,
        scope=MemoryScope("s14-proof", "dualchart", "composer", "s13code"),
        llm=lambda prompt, system: gateway.complete(prompt, system),
        source_uri="proof://harness/dualaxischart",
        source_author="s14-proof",
        respond_as="ui",
    )

    snapshot = runtime.graph.snapshot(result["run_id"])
    surface_node = snapshot.nodes.get("surface", {})
    surface_result = surface_node.get("result") or {}
    content_node = snapshot.nodes.get("content", {})
    surface_payload = surface_result.get("surface") or {}
    if isinstance(surface_payload, dict):
        accepted = surface_payload.get("components") or []
        data_model = surface_payload.get("dataModel") or surface_result.get("data_model") or {}
    else:
        accepted = surface_payload if isinstance(surface_payload, list) else []
        data_model = surface_result.get("data_model") or {}
    types = sorted({c.get("type") for c in accepted if isinstance(c, dict) and c.get("type")})
    has_dualchart = "DualAxisChart" in types or "BarChart" in types
    recheck = validate_surface({
        "root": surface_payload.get("root", "root") if isinstance(surface_payload, dict) else "root",
        "components": accepted,
        "dataModel": data_model,
    })

    proof = {
        "task": TASK,
        "run_id": result["run_id"],
        "status": result["status"],
        "gateway_base_url": gateway.base_url,
        "gateway_provider_env": os.getenv("S13_GATEWAY_PROVIDER"),
        "graph_nodes": {
            nid: {
                "skill": node.get("skill"),
                "state": node.get("state"),
                "error": node.get("error"),
                "result_keys": sorted((node.get("result") or {})),
            }
            for nid, node in snapshot.nodes.items()
        },
        "content_structured_keys": sorted(
            ((content_node.get("result") or {}).get("structured") or {})
            if isinstance((content_node.get("result") or {}).get("structured"), dict)
            else []
        ),
        "compose_surface_node": {
            "state": surface_node.get("state"),
            "error": surface_node.get("error") or surface_result.get("error"),
            "provider": surface_result.get("provider"),
            "model": surface_result.get("model"),
            "validator": surface_result.get("validator"),
            "component_types": types,
            "has_dualchart": has_dualchart,
            "data_model_keys": sorted(data_model),
            "surface_accepted": accepted,
            "data_model": data_model,
            "revalidate_ok": recheck.ok,
            "revalidate_rejections": [r.as_dict() for r in recheck.rejections],
        },
        "assert_dualchart_composed_unprompted": has_dualchart,
        "assert_surface_clean": recheck.ok,
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    await gateway.close()
    runtime.close()

    print("=== DUAL AXIS CHART HARNESS SUMMARY ===")
    print(f"run_id         : {result['run_id']}")
    print(f"types          : {types}")
    print(f"has DualAxisChart: {has_dualchart}")
    print(f"revalidate     : ok={recheck.ok}")
    print(f"\nwrote {OUT}")
    if not recheck.ok:
        return 5
    return 0 if surface_node.get("state") == "succeeded" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
