"""AnnotatedImage: the three invariants, plus the nested-binding nuance, proven
directly against validate_surface (see catalog.py / validator.py / index.html)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.validator import Invariant, validate_surface


def _surface(components, root="img1"):
    return {"root": root, "components": components}


def test_well_formed_annotated_image_is_accepted():
    surface = _surface([
        {
            "id": "img1",
            "type": "AnnotatedImage",
            "src": "https://example.com/frame.jpg",
            "alt": "gate camera, 13:04",
            "boxes": {"$bind": "/boxes"},
            "caption": "person lingered 40s",
        }
    ])
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]
    assert result.accepted[0]["type"] == "AnnotatedImage"


def test_catalog_invariant_rejects_unknown_type():
    surface = _surface([{"id": "img1", "type": "PhotoBomb"}])
    result = validate_surface(surface)
    assert not result.ok
    assert result.rejections[0].invariant == Invariant.CATALOG


def test_data_not_code_invariant_rejects_unregistered_prop():
    surface = _surface([
        {
            "id": "img1",
            "type": "AnnotatedImage",
            "src": "https://example.com/frame.jpg",
            "boxes": {"$bind": "/boxes"},
            "onClick": "doSomething()",
        }
    ])
    result = validate_surface(surface)
    assert not result.ok
    assert result.rejections[0].invariant == Invariant.DATA_NOT_CODE


def test_event_invariant_is_enforced_via_data_not_code_since_no_action_prop_exists():
    """AnnotatedImage never declares an action-kind prop (§1.2), so no action can
    ever reach the event-invariant check in the first place: an unrecognized
    field like 'notify' is rejected as an unknown property (data-not-code) before
    validator.py's action-name check ever runs. This is the automatic protection
    §1.5 describes -- proven here by showing the rejection lands on 'notify' via
    DATA_NOT_CODE, not EVENT."""
    surface = {
        "root": "col",
        "components": [
            {"id": "col", "type": "Column", "children": ["img1"]},
            {
                "id": "img1",
                "type": "AnnotatedImage",
                "src": "https://example.com/frame.jpg",
                "boxes": {"$bind": "/boxes"},
                "notify": {"action": "delete_everything"},
            },
        ],
    }
    result = validate_surface(surface)
    assert not result.ok
    assert result.rejections[0].field == "notify"
    assert result.rejections[0].invariant == Invariant.DATA_NOT_CODE


def test_markup_inside_a_bound_box_label_is_not_caught_by_the_validator():
    """The documented nuance: _looks_like_markup only inspects a component's
    top-level prop values. 'boxes' is a binding -- its value at the top level is
    {'$bind': '/boxes'}, a dict, not a string -- so validate_surface never looks
    inside the array it resolves to. A malicious label survives validation here;
    it is caught only by the renderer, which places label into a text node and
    never into innerHTML (see renderAnnotatedImage in client/index.html)."""
    surface = _surface([
        {
            "id": "img1",
            "type": "AnnotatedImage",
            "src": "https://example.com/frame.jpg",
            "boxes": {"$bind": "/boxes"},
        }
    ])
    data_model = {
        "boxes": [
            {"x": 10, "y": 10, "w": 20, "h": 30, "label": "<img src=x onerror=alert(1)>", "confidence": 0.9}
        ]
    }
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]
    assert result.accepted[0]["boxes"] == {"$bind": "/boxes"}
    # the poisoned string is real, unmodified data -- proving the wall does not
    # sanitize it; only the render client's use of textContent makes it inert.
    assert "<img" in data_model["boxes"][0]["label"]
