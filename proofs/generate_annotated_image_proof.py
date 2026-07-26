"""Part 1 proof (§1.4): show Gemini composing AnnotatedImage UNPROMPTED.

Same generative loop as generate_gemini.py -- routes through the running
glc_v3 gateway (provider=gemini), validates the model's raw output through the
real validator -- but the task and data model here describe a CCTV-incident
frame with pre-computed detection boxes, and the word "AnnotatedImage" never
appears in the prompt. The model is only shown the catalog manifest (which now
includes AnnotatedImage, once registered in catalog.py) and asked to compose an
interface for reviewing the incident; picking AnnotatedImage over Image is the
model's own judgment call, not an instruction.

    GLC_BASE_URL=http://127.0.0.1:8111 uv run python proofs/generate_annotated_image_proof.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_live import SYSTEM, extract, normalize

from s13code.ui.catalog import catalog_manifest
from s13code.ui.validator import validate_surface

OUT = Path(__file__).parent / "annotated_image_surface.json"
BASE = os.getenv("GLC_BASE_URL", "http://127.0.0.1:8111").rstrip("/")

# frame_url is a real stock photo (picsum.photos id 342: a person with a cream
# backpack in a street scene), standing in for staged CCTV footage per §2.1's
# documented limitation. The box coordinates were hand-placed by visually
# inspecting that exact photo -- not run through a real detector -- which is
# §2.3's documented fallback, named here rather than left implicit. A prior
# version of this proof used a stock photo (walrus id 1084) with box
# coordinates that were never checked against its actual content; this was
# caught in PR review and fixed by verifying image content before authoring
# boxes for it.
DATA_MODEL = {
    "title": "Incident evt_003 -- gate camera, 13:04",
    "camera": "gate",
    "time": "13:04",
    "summary": "person carrying a backpack detected near the gate camera",
    "frame_url": "https://picsum.photos/id/342/640/400",
    "boxes": [
        {"x": 34.0, "y": 22.0, "w": 27.0, "h": 75.0, "label": "person", "confidence": 0.91},
        {"x": 39.0, "y": 49.0, "w": 19.0, "h": 33.0, "label": "backpack", "confidence": 0.74},
    ],
    "cross_camera_matches": [
        {"camera": "driveway", "time": "13:02", "label": "person"},
        {"camera": "porch", "time": "13:07", "label": "person"},
    ],
}


TASK = (
    "A CCTV incident investigator app just loaded one incident's full "
    "record: a camera frame at /frame_url, a list of detected objects at "
    "/boxes (each with x,y,w,h as percentages of the frame, a label, and a "
    "confidence score), a one-line /summary, and cross-camera matches at "
    "/cross_camera_matches. Compose the review interface a security operator "
    "would see for this one incident: the frame with its detections visibly "
    "marked on top of the image itself (not listed separately in a table), "
    "plus the summary text and the cross-camera matches. Pick whichever "
    "catalog component types best fit each piece of data. JSON only."
)  # deliberately never names a component type -- the model must pick from the catalog itself


def build_prompt(data_model: dict) -> str:
    return (
        f"CATALOG:\n{json.dumps(catalog_manifest())}\n\n"
        f"DATA MODEL (bind to these keys):\n{json.dumps(data_model)}\n\n"
        f"TASK: {TASK}"
    )


def gateway_chat(prompt: str, system: str) -> dict:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "system": system,
        "max_tokens": 2500,
        # temperature=0 reproducibly truncated gemini-2.5-flash's output mid-JSON
        # for this prompt (stop_reason="end_turn" despite the cut, twice in a
        # row) -- a small nonzero temperature avoided it in testing.
        "temperature": 0.2,
        "reasoning": "off",
        "agent": "s14_surface",
        "provider": os.getenv("S14_GATEWAY_PROVIDER", "gemini"),
    }
    r = httpx.post(f"{BASE}/v1/chat", json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"GLC /v1/chat {r.status_code}: {r.text[:300]}")
    return r.json()


def main() -> None:
    print(f"asking gemini (via {BASE}) to compose an interface for a CCTV incident...\n")
    print("(the word 'AnnotatedImage' does not appear anywhere in the prompt below)\n")
    body = gateway_chat(build_prompt(DATA_MODEL), SYSTEM)
    raw = body.get("text", "")
    print(f"provider={body.get('provider')}  model={body.get('model')}")
    print("=== RAW GEMINI OUTPUT (first 900 chars) ===")
    print(raw[:900])

    surface = extract(raw)
    if not surface:
        print("\ngemini did not return JSON")
        sys.exit(2)
    surface = normalize(surface)
    surface.setdefault("dataModel", DATA_MODEL)

    result = validate_surface(surface)
    print("\n=== VALIDATOR VERDICT on Gemini's own output ===")
    print(f"components proposed : {len(surface.get('components', []))}")
    print(f"accepted            : {len(result.accepted)}")
    print(f"rejected            : {len(result.rejections)}")
    for rj in result.rejections:
        print(f"  - {rj.component_id}.{rj.field}: [{rj.invariant}] {rj.reason}")

    used_annotated_image = any(c.get("type") == "AnnotatedImage" for c in result.accepted)
    print(f"\nused AnnotatedImage unprompted : {used_annotated_image}")

    ids = {c["id"] for c in result.accepted}
    dangling = [ch for c in result.accepted for ch in c.get("children", []) if ch not in ids]
    print(f"dangling child refs            : {dangling}")

    OUT.write_text(json.dumps({
        "provider": body.get("provider"), "model": body.get("model"), "raw": raw,
        "task_instruction_names_annotated_image": "AnnotatedImage" in TASK,
        "note": "the catalog manifest sent with every prompt necessarily lists "
                "AnnotatedImage by name (the model must be able to discover it "
                "exists); what matters is the TASK instruction above never tells "
                "the model to use it -- that choice is the model's own.",
        "surface_accepted": {"root": surface.get("root"), "components": result.accepted, "dataModel": DATA_MODEL},
        "rejections": [r.as_dict() for r in result.rejections],
        "dangling_child_refs": dangling,
        "used_annotated_image_unprompted": used_annotated_image,
    }, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
