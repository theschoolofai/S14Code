"""GaugeCluster: the component this submission contributes to the catalog.

A gauge is the right form for a bounded measurement against a limit, which the
existing catalog had no way to draw. Adding it to the shared vocabulary is only
safe if it holds the same three invariants every other component holds, so those
are what these tests assert.
"""
from __future__ import annotations

from s13code.ui.catalog import COMPONENTS, catalog_manifest
from s13code.ui.validator import Invariant, validate_surface


def _cluster(**props) -> dict:
    component = {"id": "g0", "type": "GaugeCluster", "title": "Powertrain",
                 "gauges": {"$bind": "/gauges"}}
    component.update(props)
    return {"root": "g0", "components": [component]}


def test_the_catalog_offers_gauge_cluster_as_a_custom_extension() -> None:
    assert COMPONENTS["GaugeCluster"].source == "custom"
    assert catalog_manifest()["components"]["GaugeCluster"]["props"]["gauges"]["kind"] == "binding"


def test_a_gauge_cluster_bound_to_the_data_model_validates() -> None:
    result = validate_surface(_cluster())

    assert result.ok
    assert [c["id"] for c in result.accepted] == ["g0"]


def test_a_handler_smuggled_onto_a_gauge_cluster_is_refused() -> None:
    result = validate_surface(_cluster(onclick="steal()"))

    assert [r.invariant for r in result.rejections] == [Invariant.DATA_NOT_CODE]
    assert result.accepted == []


def test_a_title_carrying_markup_is_refused() -> None:
    result = validate_surface(_cluster(title="<img src=x onerror=fetch('http://a.example')>"))

    assert [r.invariant for r in result.rejections] == [Invariant.DATA_NOT_CODE]


def test_gauges_must_arrive_as_a_binding_not_inline_values() -> None:
    """Structure comes from the model; every displayed number stays in the
    harness-owned data model behind a pointer."""
    result = validate_surface(_cluster(gauges=[{"label": "CoreTemp", "value": 96}]))

    assert [r.invariant for r in result.rejections] == [Invariant.DATA_NOT_CODE]


def test_an_unknown_gauge_property_is_refused() -> None:
    result = validate_surface(_cluster(redline="steal"))

    assert [r.invariant for r in result.rejections] == [Invariant.DATA_NOT_CODE]


def test_the_safe_part_of_a_surface_still_renders_beside_a_poisoned_gauge() -> None:
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["g0", "t0"]},
            {"id": "g0", "type": "GaugeCluster", "title": "Powertrain",
             "gauges": {"$bind": "/gauges"}, "onclick": "steal()"},
            {"id": "t0", "type": "Text", "text": {"$bind": "/summary"}},
        ],
    }

    result = validate_surface(surface)

    assert [c["id"] for c in result.accepted] == ["root", "t0"]
    assert [r.component_id for r in result.rejections] == ["g0"]
