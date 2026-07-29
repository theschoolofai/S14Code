"""Session 14 assignment: the contributed ``Heatmap`` component and the
Trading Systems Academy UI-only application.

Three things are proved here, all hermetically — no gateway, no Ollama, no
network:

  1. ``Heatmap`` is a real catalog citizen: typed props, tagged source, and
     present in the manifest that ``compose_surface`` hands the model (which is
     the whole reason the model can choose it without being told its name).
  2. The three invariants still hold *for the new component*. An unknown type is
     rejected, a bound value carrying markup is refused, a smuggled handler is
     refused, and an unregistered action never crosses back — while the safe
     part of a partly-poisoned surface still renders.
  3. The renderer executes nothing. Neither client assigns ``innerHTML``, and
     the only thing a Heatmap value may influence is an intensity the client
     computes itself; the colour channel comes from a fixed lookup keyed by the
     catalog's ``tone`` enum, so no string the agent wrote reaches CSS.

``_matrix_pointers`` — the pure helper that turns a content-role matrix into
data-model pointers — is tested directly, because a ragged or unlabelled grid
must never be exposed: a heatmap drawn over data the system does not have is
exactly the kind of confident lie Session 14 refuses to draw.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.runtime import _coerce_number, _matrix_pointers, _sequence_pointers  # noqa: E402
from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS, catalog_manifest  # noqa: E402
from s13code.ui.routes import router as ui_router  # noqa: E402
from s13code.ui.validator import Invariant, validate_surface  # noqa: E402

_BUILD_ROOT = Path(__file__).resolve().parent.parent
_CLIENT_DIR = _BUILD_ROOT / "s13code" / "ui" / "client"


def _first_rejection(component: dict):
    """Validate one component alone; return its first rejection."""
    result = validate_surface({"root": component["id"], "components": [component]})
    assert result.rejections, f"expected {component} to be rejected"
    return result.rejections[0]


def _heatmap(**overrides) -> dict:
    """A clean, catalog-legal Heatmap; override one field to poison it."""
    component = {
        "id": "hm",
        "type": "Heatmap",
        "title": "Study effort",
        "rows": {"$bind": "/matrix_rows"},
        "columns": {"$bind": "/matrix_columns"},
        "values": {"$bind": "/matrix_values"},
        "unit": "%",
        "tone": "good",
    }
    component.update(overrides)
    return component


# --------------------------------------------------------------------------- #
# 1. Heatmap is a real catalog citizen
# --------------------------------------------------------------------------- #

def test_heatmap_is_a_custom_catalog_component():
    assert "Heatmap" in COMPONENTS
    assert COMPONENTS["Heatmap"].source == "custom"


def test_heatmap_props_are_typed_the_way_the_renderer_reads_them():
    props = COMPONENTS["Heatmap"].props
    assert {name: spec.kind for name, spec in props.items()} == {
        "title": "text", "rows": "binding", "columns": "binding",
        "values": "binding", "unit": "text", "tone": "enum",
    }
    assert props["tone"].values == ("neutral", "good", "warn", "bad")


def test_heatmap_declares_no_property_a_client_would_ever_execute():
    """The load-bearing property: nothing here is a handler, a URL or markup."""
    for name, spec in COMPONENTS["Heatmap"].props.items():
        assert not re.match(r"^on[a-z]+$", name, re.I), name
        assert spec.kind in ("text", "binding", "enum")


def test_manifest_offers_heatmap_to_the_model():
    """compose_surface hands this manifest to the model verbatim. Heatmap being
    in it is the entire mechanism by which the model can pick it unprompted."""
    manifest = catalog_manifest()
    assert manifest["components"]["Heatmap"]["source"] == "custom"
    assert set(manifest["components"]["Heatmap"]["props"]) == set(COMPONENTS["Heatmap"].props)
    assert manifest["components"]["Heatmap"]["props"]["tone"]["values"] == \
        ["neutral", "good", "warn", "bad"]


def test_a_clean_heatmap_surface_validates_clean():
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "Column", "children": ["hm"]}, _heatmap()],
        "dataModel": {"matrix_rows": ["W1"], "matrix_columns": ["FIX"], "matrix_values": [[3]]},
    }
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]


# --------------------------------------------------------------------------- #
# 2. The three invariants, applied to the new component
# --------------------------------------------------------------------------- #

def test_catalog_invariant_rejects_a_near_miss_of_the_new_type():
    """`HeatMap` is not `Heatmap`. A closed catalog means close does not count."""
    assert _first_rejection({"id": "x", "type": "HeatMap"}).invariant == Invariant.CATALOG


def test_catalog_invariant_still_rejects_rawhtml_now_that_the_catalog_grew():
    assert _first_rejection({"id": "x", "type": "RawHtml"}).invariant == Invariant.CATALOG


def test_data_not_code_refuses_a_handler_smuggled_onto_a_heatmap():
    rejection = _first_rejection(_heatmap(onclick="steal()"))
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert rejection.field == "onclick"
    assert "event-handler" in rejection.reason


def test_data_not_code_refuses_markup_in_a_heatmap_text_prop():
    rejection = _first_rejection(_heatmap(title="<script>alert(1)</script>"))
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert rejection.reason == "value carries markup"


def test_data_not_code_refuses_a_script_url_in_a_heatmap_text_prop():
    rejection = _first_rejection(_heatmap(unit="javascript:steal()"))
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert "script/data URL" in rejection.reason


def test_data_not_code_refuses_inline_values_where_a_binding_belongs():
    """Handing the grid over inline is how markup sneaks into a data slot."""
    rejection = _first_rejection(_heatmap(values=[[1, 2], [3, 4]]))
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert "binding must be" in rejection.reason


def test_data_not_code_refuses_a_binding_that_is_not_a_json_pointer():
    rejection = _first_rejection(_heatmap(rows={"$bind": "matrix_rows"}))
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert "invalid JSON Pointer" in rejection.reason


def test_data_not_code_refuses_a_tone_outside_the_enum():
    rejection = _first_rejection(_heatmap(tone="chartreuse"))
    assert rejection.invariant == Invariant.DATA_NOT_CODE


def test_data_not_code_refuses_an_undeclared_property_on_a_heatmap():
    rejection = _first_rejection(_heatmap(cellColour="rgba(0,0,0,1)"))
    assert rejection.invariant == Invariant.DATA_NOT_CODE
    assert rejection.field == "cellColour"


def test_event_invariant_refuses_an_unregistered_action_beside_a_heatmap():
    rejection = _first_rejection(
        {"id": "b", "type": "Button", "label": "Drill in", "onPress": {"action": "exfiltrate_memory"}}
    )
    assert rejection.invariant == Invariant.EVENT
    assert "exfiltrate_memory" in rejection.reason
    assert "exfiltrate_memory" not in REGISTERED_ACTIONS


def test_a_poisoned_sibling_never_blanks_the_heatmap():
    """The safe part of a partly-poisoned surface still renders."""
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["hm", "poison", "raw"]},
            _heatmap(),
            {"id": "poison", "type": "Button", "label": "Go", "onPress": {"action": "exfiltrate_memory"}},
            {"id": "raw", "type": "RawHtml", "html": "<img src=x onerror=alert(1)>"},
        ],
        "dataModel": {"matrix_rows": ["W1"], "matrix_columns": ["FIX"], "matrix_values": [[3]]},
    }
    result = validate_surface(surface)
    accepted = {component["id"] for component in result.accepted}
    assert accepted == {"root", "hm"}
    assert {rejection.invariant for rejection in result.rejections} == \
        {Invariant.EVENT, Invariant.CATALOG}


# --------------------------------------------------------------------------- #
# 3. _matrix_pointers — a grid is exposed only when it is real
# --------------------------------------------------------------------------- #

def test_matrix_pointers_expose_a_rectangular_labelled_grid():
    pointers = _matrix_pointers({
        "title": "Effort by topic and week", "unit": "%",
        "rows": ["Order book", "Matching"], "columns": ["W1", "W2", "W3"],
        "values": [[40, 30, 10], [20, 35, 25]],
    })
    assert pointers["matrix_rows"] == ["Order book", "Matching"]
    assert pointers["matrix_columns"] == ["W1", "W2", "W3"]
    assert pointers["matrix_values"] == [[40.0, 30.0, 10.0], [20.0, 35.0, 25.0]]
    assert pointers["matrix_title"] == "Effort by topic and week"
    assert pointers["matrix_unit"] == "%"


def test_matrix_pointers_coerce_numeric_strings():
    pointers = _matrix_pointers({"rows": ["a"], "columns": ["x", "y"], "values": [["1,200", "3"]]})
    assert pointers["matrix_values"] == [[1200.0, 3.0]]


def test_matrix_pointers_default_the_title_and_unit():
    pointers = _matrix_pointers({"rows": ["a"], "columns": ["x"], "values": [[1]]})
    assert pointers["matrix_title"] == "matrix"
    assert pointers["matrix_unit"] == ""


@pytest.mark.parametrize("matrix", [
    None,
    "not a dict",
    {},
    {"rows": [], "columns": ["x"], "values": [[1]]},                 # no row labels
    {"rows": ["a"], "columns": [], "values": [[1]]},                 # no column labels
    {"rows": ["a", "b"], "columns": ["x"], "values": [[1]]},         # fewer rows than labels
    {"rows": ["a"], "columns": ["x", "y"], "values": [[1]]},         # ragged row
    {"rows": ["a"], "columns": ["x"], "values": [["n/a"]]},          # a cell that is not a number
    {"rows": ["a"], "columns": ["x"], "values": [[True]]},           # a bool is not a magnitude
    {"rows": ["a"], "columns": ["x"], "values": ["oops"]},           # a row that is not a list
])
def test_matrix_pointers_refuse_anything_that_is_not_a_real_grid(matrix):
    """A heatmap over data the system does not have is a confident lie. If the
    grid is not fully labelled, rectangular and numeric, no pointer is exposed,
    so the model has nothing to draw and draws nothing."""
    assert _matrix_pointers(matrix) == {}


def test_coerce_number_rejects_bools_and_junk_but_accepts_numeric_text():
    assert _coerce_number(3) == 3.0
    assert _coerce_number("  1,024 ") == 1024.0
    assert _coerce_number(True) is None
    assert _coerce_number("n/a") is None
    assert _coerce_number(None) is None


# --------------------------------------------------------------------------- #
# 3b. SequenceDiagram — the second contributed component
# --------------------------------------------------------------------------- #

def _sequence(**overrides) -> dict:
    """A clean, catalog-legal SequenceDiagram; override one field to poison it."""
    component = {
        "id": "sq",
        "type": "SequenceDiagram",
        "title": "FIX session handshake",
        "actors": {"$bind": "/sequence_actors"},
        "messages": {"$bind": "/sequence_messages"},
        "tone": "neutral",
    }
    component.update(overrides)
    return component


def test_sequencediagram_is_a_custom_catalog_component():
    assert COMPONENTS["SequenceDiagram"].source == "custom"


def test_sequencediagram_props_are_typed_the_way_the_renderer_reads_them():
    props = COMPONENTS["SequenceDiagram"].props
    assert {name: spec.kind for name, spec in props.items()} == {
        "title": "text", "actors": "binding", "messages": "binding", "tone": "enum",
    }


def test_sequencediagram_declares_no_property_a_client_would_ever_execute():
    for name, spec in COMPONENTS["SequenceDiagram"].props.items():
        assert not re.match(r"^on[a-z]+$", name, re.I), name
        assert spec.kind in ("text", "binding", "enum")


def test_manifest_offers_sequencediagram_to_the_model():
    manifest = catalog_manifest()
    assert manifest["components"]["SequenceDiagram"]["source"] == "custom"
    assert set(manifest["components"]["SequenceDiagram"]["props"]) == \
        set(COMPONENTS["SequenceDiagram"].props)


def test_a_clean_sequencediagram_surface_validates_clean():
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "Column", "children": ["sq"]}, _sequence()],
        "dataModel": {"sequence_actors": ["Client", "Engine"],
                      "sequence_messages": [{"from": "Client", "to": "Engine", "label": "NewOrderSingle"}]},
    }
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]


@pytest.mark.parametrize("poison,invariant,field", [
    ({"type": "Sequencediagram"}, Invariant.CATALOG, "type"),        # close does not count
    ({"onclick": "steal()"}, Invariant.DATA_NOT_CODE, "onclick"),
    ({"title": "<img src=x onerror=alert(1)>"}, Invariant.DATA_NOT_CODE, "title"),
    ({"title": "javascript:steal()"}, Invariant.DATA_NOT_CODE, "title"),
    ({"actors": ["Client", "Engine"]}, Invariant.DATA_NOT_CODE, "actors"),   # inline, not bound
    ({"messages": {"$bind": "sequence_messages"}}, Invariant.DATA_NOT_CODE, "messages"),
    ({"tone": "chartreuse"}, Invariant.DATA_NOT_CODE, "tone"),
    ({"lifelineColour": "red"}, Invariant.DATA_NOT_CODE, "lifelineColour"),
])
def test_the_three_invariants_hold_for_sequencediagram(poison, invariant, field):
    rejection = _first_rejection(_sequence(**poison))
    assert rejection.invariant == invariant
    assert rejection.field == field


def test_sequencediagram_declares_no_action_so_it_cannot_cross_back():
    """The event invariant holds vacuously: the component has no action-kind prop,
    so there is no path from this widget to the graph at all."""
    assert not any(spec.kind == "action" for spec in COMPONENTS["SequenceDiagram"].props.values())


def test_sequence_pointers_expose_a_declared_interaction():
    pointers = _sequence_pointers({
        "title": "Order lifecycle", "actors": ["Client", "Gateway", "Engine"],
        "messages": [{"from": "Client", "to": "Gateway", "label": "NewOrderSingle", "note": "tag 35=D"},
                     {"from": "Gateway", "to": "Engine", "label": "Validate"}],
    })
    assert pointers["sequence_actors"] == ["Client", "Gateway", "Engine"]
    assert pointers["sequence_title"] == "Order lifecycle"
    assert pointers["sequence_messages"][0]["note"] == "tag 35=D"
    assert "note" not in pointers["sequence_messages"][1]


def test_sequence_pointers_default_the_title():
    pointers = _sequence_pointers({"actors": ["A", "B"],
                                   "messages": [{"from": "A", "to": "B", "label": "ping"}]})
    assert pointers["sequence_title"] == "interaction"


@pytest.mark.parametrize("sequence", [
    None,
    "not a dict",
    {},
    {"actors": ["Only one"], "messages": [{"from": "Only one", "to": "Only one", "label": "x"}]},
    {"actors": ["A", "B"], "messages": []},                                   # nothing happens
    {"actors": ["A", "B"], "messages": [{"from": "A", "to": "C", "label": "x"}]},   # undeclared actor
    {"actors": ["A", "B"], "messages": [{"from": "A", "to": "B"}]},           # no label
    {"actors": ["A", "B"], "messages": ["A talks to B"]},                     # not a message object
])
def test_sequence_pointers_refuse_an_interaction_that_is_not_fully_declared(sequence):
    """An exchange whose participants are unknown is not evidence. Nothing is
    exposed, so the model has nothing to draw and draws nothing."""
    assert _sequence_pointers(sequence) == {}


# --------------------------------------------------------------------------- #
# 4. The renderers execute nothing
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("filename", ["index.html", "academy.html", "app.html"])
@pytest.mark.parametrize("component", ["Heatmap", "SequenceDiagram"])
def test_every_client_registers_the_contributed_renderers(filename, component):
    html = (_CLIENT_DIR / filename).read_text(encoding="utf-8")
    assert f"{component}:" in html, f"{filename} would skip {component}"


@pytest.mark.parametrize("filename", ["index.html", "academy.html", "app.html"])
def test_sequence_lane_spans_are_computed_from_the_actor_list_not_from_data(filename):
    """A message decides only WHICH COLUMN a cell starts in and how far it spans —
    integers derived from the actor list here, never a value the agent supplied."""
    html = (_CLIENT_DIR / filename).read_text(encoding="utf-8")
    assert "Math.min(" in html and "Math.max(" in html
    assert "findIndex" in html          # actor names resolve to indices, not to markup
    assert "colSpan" in html


@pytest.mark.parametrize("filename", ["index.html", "academy.html"])
def test_heatmap_colour_comes_from_a_fixed_tone_lookup_not_a_model_string(filename):
    """The only value-driven CSS is an alpha the client computes. The colour
    channel is a constant keyed by the validated `tone` enum, so a string the
    agent wrote can never reach a style property."""
    html = (_CLIENT_DIR / filename).read_text(encoding="utf-8")
    assert "const HEAT_RGB=" in html
    # backgroundColor is assembled from the fixed rgb triple plus a clamped number.
    assert 'backgroundColor="rgba("+rgb+","' in html
    assert "Math.max(0,Math.min(1," in html          # the alpha is clamped to 0..1
    assert "Number.isFinite" in html                 # non-numeric cells tint nothing


def test_academy_app_never_assigns_innerhtml_and_documents_the_contract():
    html = (_CLIENT_DIR / "academy.html").read_text(encoding="utf-8")
    assert "createTextNode" in html
    assert not re.search(r"innerHTML\s*=", html)
    # The single mention is the documented safety contract itself.
    assert html.count("innerHTML") == 1
    assert "NEVER assigns" in html


@pytest.mark.parametrize("filename", ["index.html", "academy.html", "app.html"])
def test_every_catalog_type_has_a_renderer_so_nothing_silently_skips(filename):
    """A catalog the client cannot draw is a catalog that shows "[skipped]". Every
    type the agent may legally compose must map to a widget in every client."""
    html = (_CLIENT_DIR / filename).read_text(encoding="utf-8")
    missing = [name for name in COMPONENTS if f"{name}:" not in html]
    assert not missing, f"{filename} has no renderer for {missing}"


@pytest.mark.parametrize("filename", ["index.html", "academy.html", "app.html"])
def test_no_client_terminates_its_own_script_block(filename):
    """A literal closing script tag inside an inline script — in a string OR in a
    comment — ends the block early and silently kills the whole page. The
    adversarial seed in academy.html has to talk about one, so it escapes it.
    Only the real closing tag may appear unescaped."""
    html = (_CLIENT_DIR / filename).read_text(encoding="utf-8")
    assert html.count("</script>") == 1, (
        f"{filename} contains an unescaped closing script tag before its own end; "
        r"write it as <\/script>"
    )


def test_academy_app_skips_unknown_types_instead_of_executing_them():
    html = (_CLIENT_DIR / "academy.html").read_text(encoding="utf-8")
    assert "[skipped unknown type: " in html


def test_academy_app_carries_the_adversarial_seed():
    """The app ships the hostile prompt it must survive, so the wall can be
    watched refusing a real composition rather than asserted about."""
    html = (_CLIENT_DIR / "academy.html").read_text(encoding="utf-8")
    assert "RawHtml" in html and "onclick" in html and "exfiltrate_memory" in html


# --------------------------------------------------------------------------- #
# 5. Routes — hermetic, driven through the UI router
# --------------------------------------------------------------------------- #

class _Snapshot:
    def __init__(self, run: dict):
        self.finished, self.nodes, self.edges = run["finished"], run["nodes"], run["edges"]


class _Graph:
    def __init__(self, run_id: str, run: dict):
        self._id, self._run = run_id, run

    def snapshot(self, run_id: str):
        if run_id != self._id:
            raise KeyError(run_id)
        return _Snapshot(self._run)

    def events(self, run_id: str):
        if run_id != self._id:
            raise KeyError(run_id)
        return []


class _Runtime:
    def __init__(self, run_id: str, run: dict):
        self.graph = _Graph(run_id, run)


# A recorded compose_surface node in the exact shape the live skill returns: the
# model proposed a Heatmap plus two hostile nodes, and the wall kept only the
# Heatmap. ``surface`` therefore holds the accepted tree; ``validator`` holds
# what was refused.
_COMPOSED_RUN = {
    "finished": True,
    "edges": [],
    "nodes": {
        "surface": {
            "skill": "compose_surface",
            "state": "succeeded",
            "input": {},
            "result": {
                "provider": "gemini_1",
                "model": "gemini-2.5-flash",
                "surface": {
                    "root": "root",
                    "components": [
                        {"id": "root", "type": "Column", "children": ["hm"]},
                        _heatmap(),
                    ],
                },
                "data_model": {"matrix_rows": ["W1"], "matrix_columns": ["FIX"],
                               "matrix_values": [[3]]},
                "validator": {
                    "proposed": 4, "accepted": 2, "rejected": 2, "ok": False,
                    "component_types": ["Column", "Heatmap"],
                    "rejections": [
                        {"component_id": "raw", "field": "type", "invariant": "catalog",
                         "reason": "unknown component type 'RawHtml'"},
                        {"component_id": "btn", "field": "onPress", "invariant": "event",
                         "reason": "unregistered action 'exfiltrate_memory'"},
                    ],
                },
            },
        },
    },
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ui_router)
    app.state.s13_runtime = _Runtime("rid", _COMPOSED_RUN)
    return TestClient(app)


def test_route_academy_serves_the_application(client):
    response = client.get("/academy")
    assert response.status_code == 200
    assert "Trading Systems Academy" in response.text
    assert "renderHeatmap" in response.text


def test_route_composed_returns_the_accepted_heatmap(client):
    body = client.get("/v1/runs/rid/composed").json()
    assert body["component_count"] == 2
    assert {component["type"] for component in body["surface"]["components"]} == {"Column", "Heatmap"}
    assert body["model"] == "gemini-2.5-flash"


def test_route_composed_surfaces_what_the_wall_refused(client):
    """The app must be able to SHOW the refusal, not merely claim it."""
    validator = client.get("/v1/runs/rid/composed").json()["validator"]
    assert validator["proposed"] == 4
    assert validator["rejected"] == 2
    assert [rejection["invariant"] for rejection in validator["rejections"]] == ["catalog", "event"]
    # Re-validating the accepted tree is a second, independent pass: it is clean,
    # which is what lets the safe part of a poisoned surface still render.
    assert validator["revalidated_rejections"] == []


def test_route_composed_is_404_for_a_run_with_no_composed_interface(client):
    assert client.get("/v1/runs/unknown/composed").status_code == 404
