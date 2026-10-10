"""Unit tests for Part 1: DualAxisChart catalog component and the 3 invariants."""
from __future__ import annotations

from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS, catalog_manifest
from s13code.ui.validator import Invariant, validate_surface


def test_dualaxischart_registered_in_catalog():
    """Invariant 1: DualAxisChart is registered in the trusted catalog."""
    assert "DualAxisChart" in COMPONENTS
    spec = COMPONENTS["DualAxisChart"]
    assert spec.source == "custom"
    assert "title" in spec.props
    assert "data" in spec.props
    assert "xKey" in spec.props
    assert "barKey" in spec.props
    assert "lineKey" in spec.props
    assert spec.props["data"].kind == "binding"


def test_dualaxischart_valid_surface_passes_validator():
    """Valid DualAxisChart surface passes validator cleanly."""
    surface = {
        "root": "chart1",
        "components": [
            {
                "id": "chart1",
                "type": "DualAxisChart",
                "title": "Revenue vs Growth Rate",
                "data": {"$bind": "/table_rows"},
                "xKey": "Item",
                "barKey": "Sources",
                "lineKey": "Growth",
                "barLabel": "Revenue ($M)",
                "lineLabel": "Growth (%)",
            }
        ],
        "dataModel": {"table_rows": [{"Item": "Product A", "Sources": 150, "Growth": 12}]},
    }
    res = validate_surface(surface)
    assert res.ok
    assert len(res.accepted) == 1
    assert res.accepted[0]["id"] == "chart1"


def test_dualaxischart_refuses_markup_smuggling():
    """Invariant 2 (Data-not-Code): Validator refuses bound values or title text carrying markup/scripts."""
    surface = {
        "root": "chart1",
        "components": [
            {
                "id": "chart1",
                "type": "DualAxisChart",
                "title": "<script>alert('pwned')</script>",
                "data": {"$bind": "/table_rows"},
            }
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    assert len(res.rejections) == 1
    rej = res.rejections[0]
    assert rej.invariant == Invariant.DATA_NOT_CODE
    assert "markup" in rej.reason.lower() or "handler" in rej.reason.lower()


def test_dualaxischart_refuses_unregistered_actions():
    """Invariant 3 (Event Safety): Unregistered actions are rejected by the validator."""
    surface = {
        "root": "btn1",
        "components": [
            {
                "id": "btn1",
                "type": "Button",
                "label": "Click Me",
                "onPress": {"action": "malicious_eval_action"},
            }
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    assert len(res.rejections) == 1
    assert res.rejections[0].invariant == Invariant.EVENT


def test_dualaxischart_manifest_export():
    """Manifest exports DualAxisChart correctly for client discovery."""
    manifest = catalog_manifest()
    assert "DualAxisChart" in manifest["components"]
    assert manifest["components"]["DualAxisChart"]["source"] == "custom"
