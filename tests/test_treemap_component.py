"""Focused, hermetic contract tests for the trusted Treemap component."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proofs import treemap_run
from s13code.runtime import _normalize_breakdown, _surface_composition_prompt
from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS, catalog_manifest
from s13code.ui.routes import router as ui_router
from s13code.ui.validator import Invariant, Rejection, ValidationResult, validate_surface

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


def test_composition_prompt_never_names_treemap_outside_the_catalog():
    goal = "show allocation"
    data_model = {
        "title": "Budget",
        "breakdown": _SAFE_DATA,
        "breakdown_unit": "INR",
        "series": [{"label": "January", "value": 1}],
    }
    system, instruction = _surface_composition_prompt(goal, catalog_manifest(), data_model)
    assert "treemap" not in goal.casefold()
    assert "treemap" not in system.casefold()
    assert "treemap" not in instruction["compose"].casefold()
    assert "Treemap" in instruction["catalog"]["components"]
    assert set(instruction["available_pointers"]) >= {"/breakdown", "/breakdown_unit", "/series"}
    compose = instruction["compose"]
    assert "for /breakdown" in compose
    assert "part-to-whole composition rather than a plain ranking" in compose
    assert "/breakdown is a composition while /series is an ordinary numeric series" in compose
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


def _grounded_proof_surface() -> tuple[dict, dict]:
    surface = _treemap_surface()
    normalized = {"items": _SAFE_DATA, "unit": "INR", "total": 85000}
    surface["dataModel"]["breakdown_total"] = normalized["total"]
    return surface, normalized


def test_live_proof_accepts_a_reachable_grounded_treemap():
    surface, normalized = _grounded_proof_surface()
    treemap_run.verify_grounded_treemap(surface, normalized)


def test_live_proof_accepts_omitted_default_label_and_value_keys():
    surface, normalized = _grounded_proof_surface()
    surface["components"][1].pop("labelKey")
    surface["components"][1].pop("valueKey")
    treemap_run.verify_grounded_treemap(surface, normalized)


@pytest.mark.parametrize(("field", "value"), [("labelKey", "name"), ("valueKey", "amount")])
def test_live_proof_rejects_explicitly_wrong_treemap_keys(field, value):
    surface, normalized = _grounded_proof_surface()
    surface["components"][1][field] = value
    with pytest.raises(SystemExit, match="no reachable Treemap grounded in /breakdown"):
        treemap_run.verify_grounded_treemap(surface, normalized)


def test_live_proof_rejects_an_orphaned_treemap():
    surface, normalized = _grounded_proof_surface()
    surface["components"][0]["children"] = []
    with pytest.raises(SystemExit, match="no reachable Treemap grounded in /breakdown"):
        treemap_run.verify_grounded_treemap(surface, normalized)


@pytest.mark.parametrize("binding", [None, {"$bind": "/not_present"}])
def test_live_proof_rejects_a_missing_or_wrong_treemap_binding(binding):
    surface, normalized = _grounded_proof_surface()
    if binding is None:
        surface["components"][1].pop("data")
    else:
        surface["components"][1]["data"] = binding
    with pytest.raises(SystemExit, match="no reachable Treemap grounded in /breakdown"):
        treemap_run.verify_grounded_treemap(surface, normalized)


def test_live_proof_rejects_a_mismatched_served_data_model():
    surface, normalized = _grounded_proof_surface()
    surface["dataModel"]["breakdown_total"] = 1
    with pytest.raises(SystemExit, match="dataModel does not match"):
        treemap_run.verify_grounded_treemap(surface, normalized)


def test_live_proof_rejects_a_surface_whose_root_was_dropped():
    surface, normalized = _grounded_proof_surface()
    surface["components"] = surface["components"][1:]
    with pytest.raises(SystemExit, match="dropped its root component"):
        treemap_run.verify_grounded_treemap(surface, normalized)


def _unitless_proof_surface() -> tuple[dict, dict]:
    """The shape runtime.py produces when the content role gave no unit."""
    surface, normalized = _grounded_proof_surface()
    normalized["unit"] = ""
    del surface["dataModel"]["breakdown_unit"]
    del surface["components"][1]["unit"]
    return surface, normalized


def test_live_proof_accepts_a_grounded_treemap_with_no_unit():
    surface, normalized = _unitless_proof_surface()
    treemap_run.verify_grounded_treemap(surface, normalized)


def test_live_proof_rejects_a_unitless_treemap_still_binding_the_absent_pointer():
    surface, normalized = _unitless_proof_surface()
    surface["components"][1]["unit"] = {"$bind": "/breakdown_unit"}
    with pytest.raises(SystemExit, match="no reachable Treemap grounded in /breakdown"):
        treemap_run.verify_grounded_treemap(surface, normalized)


def test_live_proof_rejects_a_stray_unit_pointer_for_a_unitless_breakdown():
    surface, normalized = _unitless_proof_surface()
    surface["dataModel"]["breakdown_unit"] = "INR"
    with pytest.raises(SystemExit, match="dataModel does not match"):
        treemap_run.verify_grounded_treemap(surface, normalized)


def test_live_proof_accepts_the_expected_adversarial_results():
    cases = treemap_run.adversarial()
    assert [case["invariant"] for case in cases] == ["catalog", "data-not-code", "event"]
    assert all(case["refused"] for case in cases)


def test_live_proof_fails_if_an_adversarial_attack_is_accepted(monkeypatch):
    monkeypatch.setattr(
        treemap_run,
        "validate_surface",
        lambda surface: ValidationResult(accepted=surface["components"], rejections=[]),
    )
    with pytest.raises(SystemExit, match="catalog adversarial check failed"):
        treemap_run.adversarial()


@pytest.mark.parametrize(
    "rejection",
    [
        Rejection("tree", "type", Invariant.DATA_NOT_CODE, "unknown component type 'RawHtml'"),
        Rejection("other", "type", Invariant.CATALOG, "unknown component type 'RawHtml'"),
    ],
)
def test_live_proof_fails_on_the_wrong_adversarial_invariant_or_component(monkeypatch, rejection):
    monkeypatch.setattr(
        treemap_run,
        "validate_surface",
        lambda _surface: ValidationResult(
            accepted=[{"id": "root", "type": "Column", "children": ["tree"]}],
            rejections=[rejection],
        ),
    )
    with pytest.raises(SystemExit, match="catalog adversarial check failed"):
        treemap_run.adversarial()


def test_sanitized_live_proof_records_an_ordinary_grounded_treemap_run():
    proof = json.loads((_ROOT / "proofs" / "treemap_run.json").read_text())
    assert proof["schema_version"] == 2
    assert proof["request"]["respond_as"] == "ui"
    assert "treemap" not in proof["request"]["prompt"].casefold()
    assert "treemap" not in proof["composer_prompt"]["system"].casefold()
    assert "treemap" not in proof["composer_prompt"]["compose"].casefold()
    assert proof["composer_prompt"]["catalog_offered"] is True
    assert proof["normalized_breakdown"]["unit"] == "INR"
    assert proof["normalized_breakdown"]["total"] == 120000
    assert sum(item["value"] for item in proof["normalized_breakdown"]["items"]) == 120000
    assert proof["validator"]["rejected"] == 0
    assert proof["validator"]["ok"] is True
    assert "Treemap" in proof["component_types"]
    assert any(component["type"] == "Treemap" for component in proof["raw_surface"]["components"])
    assert any(component["type"] == "Treemap" for component in proof["accepted_surface"]["components"])
    treemap_run.verify_grounded_treemap(proof["accepted_surface"], proof["normalized_breakdown"])
    assert [case["invariant"] for case in proof["adversarial"]] == ["catalog", "data-not-code", "event"]
    assert all(case["refused"] for case in proof["adversarial"])
