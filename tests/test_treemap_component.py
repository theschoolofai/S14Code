"""Focused, hermetic contract tests for the trusted Treemap component."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from s13code.runtime import _normalize_breakdown, _surface_composition_prompt
from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS, catalog_manifest
from s13code.ui.routes import router as ui_router
from s13code.ui.validator import Invariant, validate_surface

_ROOT = Path(__file__).resolve().parent.parent
_SAFE_DATA = [
    {"label": "Rent", "value": 42000},
    {"label": "Food", "value": 18000},
    {"label": "Savings", "value": 25000},
]


def _treemap_surface(data=None, *, pointer: str = "/breakdown") -> dict:
    return {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["tree"]},
            {
                "id": "tree",
                "type": "Treemap",
                "title": "Allocation",
                "data": {"$bind": pointer},
                "labelKey": "label",
                "valueKey": "value",
                "unit": {"$bind": "/breakdown_unit"},
            },
        ],
        "dataModel": {"breakdown": data if data is not None else _SAFE_DATA, "breakdown_unit": "INR"},
    }


def test_normalize_breakdown_preserves_order_and_computes_total():
    result = _normalize_breakdown({
        "unit": " INR ",
        "items": [
            {"label": " Rent ", "value": "42000"},
            {"label": "Food", "value": 18000.5},
        ],
    })
    assert result == {
        "items": [{"label": "Rent", "value": 42000}, {"label": "Food", "value": 18000.5}],
        "unit": "INR",
        "total": 60000.5,
    }


def test_normalize_breakdown_allows_an_empty_optional_unit():
    result = _normalize_breakdown({
        "items": [{"label": "A", "value": 2}, {"label": "B", "value": 1}],
    })
    assert result == {
        "items": [{"label": "A", "value": 2}, {"label": "B", "value": 1}],
        "unit": "",
        "total": 3,
    }


@pytest.mark.parametrize("bad", [True, False, None, "", "nan", float("nan"), float("inf"), 0, -1])
def test_normalize_breakdown_rejects_invalid_values_without_partial_output(bad):
    value = {
        "unit": "items",
        "items": [{"label": "Good", "value": 2}, {"label": "Bad", "value": bad}],
    }
    assert _normalize_breakdown(value) is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"unit": 42, "items": [{"label": "A", "value": 2}, {"label": "B", "value": 1}]},
        {"items": [{"label": "Only", "value": 1}]},
        {"items": [{"label": "", "value": 2}, {"label": "B", "value": 1}]},
        {"items": [{"label": "Rent", "value": 2}, {"label": " rent ", "value": 1}]},
        {"items": [{"label": "A", "value": 2}, "not-an-item"]},
    ],
)
def test_normalize_breakdown_rejects_malformed_or_ambiguous_wholes(value):
    assert _normalize_breakdown(value) is None


def test_composition_prompt_maps_breakdown_only_to_treemap():
    data_model = {
        "title": "Budget",
        "breakdown": _SAFE_DATA,
        "breakdown_unit": "INR",
        "series": [{"label": "January", "value": 1}],
    }
    system, instruction = _surface_composition_prompt("show allocation", catalog_manifest(), data_model)
    assert "a Treemap for a positive part-to-whole breakdown" in system
    assert set(instruction["available_pointers"]) >= {"/breakdown", "/breakdown_unit", "/series"}
    compose = instruction["compose"]
    assert "for /breakdown" in compose
    assert 'labelKey "label", valueKey "value"' in compose
    assert "do not use Treemap for /series" in compose
    assert "for /series render a BarChart" in compose


def test_catalog_exposes_exact_treemap_contract_without_a_new_action():
    spec = COMPONENTS["Treemap"]
    assert spec.source == "custom"
    assert {name: prop.kind for name, prop in spec.props.items()} == {
        "title": "text",
        "data": "binding",
        "labelKey": "text",
        "valueKey": "text",
        "unit": "binding",
    }
    assert REGISTERED_ACTIONS == frozenset({"approve", "reject", "rerun", "request_data"})
    assert catalog_manifest()["components"]["Treemap"]["source"] == "custom"


def test_safe_treemap_validates_clean():
    assert validate_surface(_treemap_surface()).ok


def test_treemap_requires_an_explicit_binding():
    surface = _treemap_surface()
    surface["components"][1]["data"] = _SAFE_DATA
    rejection = validate_surface(surface).rejections[0]
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert rejection.field == "data"


def test_treemap_inline_title_markup_is_rejected():
    surface = _treemap_surface()
    surface["components"][1]["title"] = "<img src=x onerror=steal()>"
    rejection = validate_surface(surface).rejections[0]
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert rejection.field == "title"


def test_treemap_unknown_handler_is_rejected():
    surface = _treemap_surface()
    surface["components"][1]["onclick"] = "steal()"
    rejection = validate_surface(surface).rejections[0]
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert rejection.field == "onclick"


def test_resolved_nested_markup_rejects_only_the_bound_component():
    surface = _treemap_surface([
        {"label": "Rent", "value": 2},
        {"label": "<img src=x onerror=steal()>", "value": 1},
    ])
    result = validate_surface(surface)
    assert {component["id"] for component in result.accepted} == {"root"}
    assert result.rejections[0].component_id == "tree"
    assert result.rejections[0].reason == "bound value carries markup"


@pytest.mark.parametrize("payload", ["javascript:steal()", "data:text/html,x", "vbscript:steal()"])
def test_resolved_script_or_data_url_is_rejected(payload):
    surface = _treemap_surface()
    surface["dataModel"]["breakdown_unit"] = payload
    rejection = validate_surface(surface).rejections[0]
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert rejection.reason == "bound value is a script/data URL"


def test_unreferenced_hostile_data_does_not_reject_a_surface():
    surface = _treemap_surface()
    surface["dataModel"]["unused"] = {"nested": ["<script>unused()</script>"]}
    assert validate_surface(surface).ok


def test_missing_pointer_preserves_nullable_binding_compatibility():
    surface = _treemap_surface(pointer="/not_present")
    assert validate_surface(surface).ok


def _function_source(html: str, name: str) -> str:
    start = html.index(f"function {name}")
    end = html.find("\nfunction ", start + len(name) + 9)
    return html[start:] if end < 0 else html[start:end]


@pytest.mark.parametrize("filename", ["index.html", "app.html"])
def test_both_render_clients_have_a_safe_dom_svg_treemap_renderer(filename):
    html = (_ROOT / "s13code" / "ui" / "client" / filename).read_text()
    assert "Treemap:(c," in html
    assert "function squarifyTreemap" in html
    renderer = _function_source(html, "renderTreemap")
    assert "createElementNS" in renderer
    assert ".textContent=" in renderer
    assert "Treemap unavailable: breakdown data is invalid" in renderer
    assert "innerHTML" not in renderer
    assert "eval(" not in renderer


class _TreemapSnapshot:
    def __init__(self):
        self.finished = True
        self.edges: list = []
        self.nodes = {
            "surface": {
                "state": "succeeded",
                "skill": "compose_surface",
                "result": {
                    "provider": "gemini_1",
                    "model": "fake-gemini",
                    "surface": _treemap_surface(),
                    "data_model": _treemap_surface()["dataModel"],
                },
            }
        }


class _TreemapGraph:
    def snapshot(self, run_id: str):
        if run_id != "treemap":
            raise KeyError(run_id)
        return _TreemapSnapshot()

    def events(self, run_id: str):
        if run_id != "treemap":
            raise KeyError(run_id)
        return []


class _TreemapRuntime:
    graph = _TreemapGraph()


def test_composed_route_revalidates_and_serves_a_mocked_treemap():
    app = FastAPI()
    app.include_router(ui_router)
    app.state.s13_runtime = _TreemapRuntime()
    body = TestClient(app).get("/v1/runs/treemap/composed").json()
    assert body["clean"] is True
    assert body["component_count"] == 2
    assert {component["type"] for component in body["surface"]["components"]} == {"Column", "Treemap"}


def test_sanitized_live_proof_records_an_ordinary_grounded_treemap_run():
    proof = json.loads((_ROOT / "proofs" / "treemap_run.json").read_text())
    assert proof["schema_version"] == 1
    assert proof["request"]["respond_as"] == "ui"
    assert "treemap" not in proof["request"]["prompt"].casefold()
    assert proof["normalized_breakdown"]["unit"] == "INR"
    assert proof["normalized_breakdown"]["total"] == 120000
    assert sum(item["value"] for item in proof["normalized_breakdown"]["items"]) == 120000
    assert proof["validator"]["rejected"] == 0
    assert proof["validator"]["ok"] is True
    assert "Treemap" in proof["component_types"]
    assert any(component["type"] == "Treemap" for component in proof["raw_surface"]["components"])
    assert any(component["type"] == "Treemap" for component in proof["accepted_surface"]["components"])
