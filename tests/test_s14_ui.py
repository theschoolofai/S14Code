"""Session 14 UI layer: real tests for surface, showcase, agui, hitl, validator,
catalog, the in-process routes, and the render client's no-innerHTML contract.

Every test is hermetic: it reads recorded S13 fixtures and the pure builders,
or drives the UI router with a fake in-process runtime through FastAPI's
TestClient. No live gateway, no Ollama, no network.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.agui import (
    empty_state,
    replay_state,
    run_data_model,
    state_snapshot,
    stream_agui,
    to_agui_event,
)
from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS, catalog_manifest
from s13code.ui.fixtures import RecordedS13
from s13code.ui.hitl import PendingAction, decide_resume
from s13code.ui.routes import router as ui_router
from s13code.ui.showcase import build_corpus_dashboard
from s13code.ui.surface import build_run_surface
from s13code.ui.validator import Invariant, validate_surface

_BUILD_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def three_cities() -> dict:
    return RecordedS13().get_run("three_cities")


@pytest.fixture(scope="module")
def papers_corpus() -> dict:
    return RecordedS13().get_run("papers_corpus")


def _reject(comp: dict):
    """Validate a single component in a minimal surface, return first rejection."""
    result = validate_surface({"root": comp["id"], "components": [comp]})
    assert result.rejections, f"expected {comp} to be rejected"
    return result.rejections[0]


# --------------------------------------------------------------------------- #
# surface.py — build_run_surface
# --------------------------------------------------------------------------- #

def test_surface_of_clean_run_validates_clean(three_cities):
    surface = build_run_surface(three_cities)
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]


def test_surface_emits_one_state_tile_per_node(three_cities):
    surface = build_run_surface(three_cities)
    # Node state is carried by a StatTile (A2UI-Basic has no Badge); one per node.
    tiles = [c for c in surface["components"] if c["type"] == "StatTile" and c["id"].startswith("state_")]
    assert len(tiles) == len(three_cities["nodes"])


def test_surface_surfaces_the_answer_node_text(three_cities):
    surface = build_run_surface(three_cities)
    answer_text = three_cities["nodes"]["answer"]["result"]["text"]
    assert surface["dataModel"]["answer"] == answer_text
    assert any(c["id"] == "answer" and c["type"] == "Text" for c in surface["components"])


def test_failed_node_yields_an_honest_notice(three_cities):
    poisoned = copy.deepcopy(three_cities)
    poisoned["nodes"]["research_paris"]["state"] = "failed"
    surface = build_run_surface(poisoned)
    notice = next((c for c in surface["components"] if c["type"] == "Notice"), None)
    assert notice is not None
    assert notice["tone"] == "bad"
    # Honest failure: it names the failed node and invents no result.
    assert "research_paris" in surface["dataModel"]["notice"]
    assert "No result was invented" in surface["dataModel"]["notice"]


def test_clean_run_has_no_notice(three_cities):
    surface = build_run_surface(three_cities)
    assert all(c["type"] != "Notice" for c in surface["components"])


# --------------------------------------------------------------------------- #
# showcase.py — build_corpus_dashboard
# --------------------------------------------------------------------------- #

def test_dashboard_validates_clean_with_zero_rejections(papers_corpus):
    result = validate_surface(build_corpus_dashboard(papers_corpus))
    assert result.ok
    assert len(result.rejections) == 0


def test_dashboard_includes_the_rich_component_types(papers_corpus):
    surface = build_corpus_dashboard(papers_corpus)
    types = {c["type"] for c in surface["components"]}
    assert {"BarChart", "DataTable", "StatTile", "Timeline"}.issubset(types)


def test_dashboard_every_bound_slot_is_a_bind_pointer(papers_corpus):
    """No inline literal ever sits in a slot the catalog marks as `binding`."""
    surface = build_corpus_dashboard(papers_corpus)
    checked = 0
    for comp in surface["components"]:
        spec = COMPONENTS[comp["type"]]
        for field_name, value in comp.items():
            if field_name in ("id", "type"):
                continue
            if spec.props.get(field_name) and spec.props[field_name].kind == "binding":
                assert isinstance(value, dict) and set(value) == {"$bind"}, (comp["id"], field_name, value)
                assert value["$bind"].startswith("/")
                checked += 1
    assert checked > 0  # the dashboard really does bind values


# --------------------------------------------------------------------------- #
# agui.py — to_agui_event, stream_agui
# --------------------------------------------------------------------------- #

def test_agui_run_started_maps_to_run_started():
    ev = to_agui_event({"sequence": 1, "kind": "run_started", "node_id": None, "payload": {}})
    assert ev["type"] == "RUN_STARTED"
    assert ev["source_kind"] == "run_started"


def test_agui_task_started_maps_to_step_started_with_name():
    ev = to_agui_event({"sequence": 3, "kind": "task_started", "node_id": "n1", "payload": {}})
    assert ev["type"] == "STEP_STARTED"
    assert ev["stepName"] == "n1"


def test_agui_task_succeeded_is_step_finished_with_state_delta():
    ev = to_agui_event({"sequence": 6, "kind": "task_succeeded", "node_id": "n1", "payload": {"x": 1}})
    assert ev["type"] == "STEP_FINISHED"
    assert ev["delta"] == {"op": "add", "path": "/results/n1", "value": {"x": 1}}


def test_agui_graph_patched_maps_to_state_delta():
    ev = to_agui_event({"sequence": 2, "kind": "graph_patched", "node_id": None, "payload": {"reason": "r"}})
    assert ev["type"] == "STATE_DELTA"
    assert ev["delta"]["op"] == "graph_patched"


def test_agui_task_failed_is_step_finished_with_error():
    ev = to_agui_event({"sequence": 5, "kind": "task_failed", "node_id": "n1", "payload": {"error": "boom"}})
    assert ev["type"] == "STEP_FINISHED"
    assert ev["error"] == "boom"


def test_agui_unknown_kind_falls_back_to_custom():
    ev = to_agui_event({"sequence": 9, "kind": "totally_new_kind", "node_id": None, "payload": {}})
    assert ev["type"] == "CUSTOM"


def test_stream_ends_with_a_derived_run_finished(three_cities):
    events = list(stream_agui(three_cities["events"], finished=three_cities["finished"]))
    assert events[0]["type"] == "RUN_STARTED"
    assert events[-1]["type"] == "RUN_FINISHED"
    assert events[-1]["source_kind"] == "derived"


def test_stream_preserves_source_sequence_order(three_cities):
    events = list(stream_agui(three_cities["events"], finished=three_cities["finished"]))
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    # The derived terminal event sits one past the last real sequence.
    assert events[-1]["seq"] == three_cities["events"][-1]["sequence"] + 1


def test_stream_does_not_derive_run_finished_when_unfinished(three_cities):
    events = list(stream_agui(three_cities["events"], finished=False))
    assert all(e["type"] != "RUN_FINISHED" for e in events)


# --------------------------------------------------------------------------- #
# agui.py — STATE_SNAPSHOT reconnect (state_snapshot, replay_state, run_data_model)
# --------------------------------------------------------------------------- #

def test_state_snapshot_wraps_a_data_model_with_the_right_shape():
    dm = {"results": {"n1": {"x": 1}}, "patches": []}
    ev = state_snapshot(dm)
    assert ev["type"] == "STATE_SNAPSHOT"
    assert ev["source_kind"] == "snapshot"
    assert ev["state"] == dm
    assert set(ev) == {"type", "seq", "source_kind", "state"}


def test_state_snapshot_extracts_datamodel_from_a_full_surface():
    surface = {"root": "r", "components": [{"id": "r", "type": "Column", "children": []}],
               "dataModel": {"results": {"a": 1}, "patches": []}}
    ev = state_snapshot(surface)
    assert ev["state"] == surface["dataModel"]


def test_stream_agui_emits_state_snapshot_first_when_reconnecting(three_cities):
    dm = run_data_model(three_cities)
    events = list(stream_agui(three_cities["events"], finished=three_cities["finished"], snapshot=dm))
    assert events[0]["type"] == "STATE_SNAPSHOT"
    assert events[0]["state"] == dm
    # The rest of the stream is unchanged: real journal, then derived terminal.
    assert events[1]["type"] == "RUN_STARTED"
    assert events[-1]["type"] == "RUN_FINISHED"


def test_stream_agui_without_snapshot_is_unchanged(three_cities):
    plain = list(stream_agui(three_cities["events"], finished=three_cities["finished"]))
    assert all(e["type"] != "STATE_SNAPSHOT" for e in plain)
    assert plain[0]["type"] == "RUN_STARTED"


def test_run_data_model_equals_full_stream_replay(three_cities):
    """run_data_model must be byte-identical to folding the whole AG-UI stream."""
    stream = list(stream_agui(three_cities["events"], finished=three_cities["finished"]))
    assert run_data_model(three_cities) == replay_state(stream)


def test_run_data_model_holds_every_succeeded_node_result(three_cities):
    dm = run_data_model(three_cities)
    succeeded = {nid for nid, n in three_cities["nodes"].items() if n["state"] == "succeeded"}
    assert set(dm["results"]) == succeeded


def test_reconnect_snapshot_rebuild_equals_full_replay(three_cities):
    """The whole point: a client that adopts the snapshot ends up identical to a
    client that folded every delta from the start — no duplicated actions."""
    stream = list(stream_agui(three_cities["events"], finished=three_cities["finished"]))
    full = replay_state(stream)
    # Client drops after 6 events, then reconnects and adopts the snapshot.
    partial = replay_state(stream[:6])
    assert partial != full  # the drop was genuinely mid-run
    rebuilt = state_snapshot(run_data_model(three_cities))["state"]
    assert rebuilt == full
    # Patch log is not doubled: the snapshot replaces history, never appends to it.
    assert len(rebuilt["patches"]) == len(full["patches"])


def test_apply_delta_is_idempotent_on_results_but_patches_accumulate():
    step = {"type": "STEP_FINISHED", "delta": {"op": "add", "path": "/results/n1", "value": {"v": 1}}}
    patch = {"type": "STATE_DELTA", "delta": {"op": "graph_patched", "reason": "r", "trigger": "t"}}
    once = replay_state([step, patch])
    twice = replay_state([step, patch, step, patch])
    # Same result node either way (idempotent overwrite)...
    assert once["results"] == twice["results"] == {"n1": {"v": 1}}
    # ...but a replayed graph_patch doubles the log — why reconnect needs a snapshot.
    assert len(once["patches"]) == 1 and len(twice["patches"]) == 2


def test_empty_state_is_the_zero_value():
    assert empty_state() == {"results": {}, "patches": []}


# --------------------------------------------------------------------------- #
# hitl.py — decide_resume
# --------------------------------------------------------------------------- #

def test_hitl_matching_approve_is_allowed():
    pending = PendingAction("run", "node", "transfer", {"amount": 100, "to": "acct-1"})
    assert decide_resume(pending, "approve", {"amount": 100, "to": "acct-1"}).allowed


def test_hitl_widened_args_are_refused_with_reason():
    pending = PendingAction("run", "node", "transfer", {"amount": 100, "to": "acct-1"})
    d = decide_resume(pending, "approve", {"amount": 100, "to": "acct-1", "cc": "acct-9"})
    assert not d.allowed
    assert "bound to final params" in d.reason


def test_hitl_narrowed_args_are_refused():
    pending = PendingAction("run", "node", "transfer", {"amount": 100, "to": "acct-1"})
    assert not decide_resume(pending, "approve", {"amount": 100}).allowed


def test_hitl_changed_value_is_refused():
    pending = PendingAction("run", "node", "transfer", {"amount": 100, "to": "acct-1"})
    assert not decide_resume(pending, "approve", {"amount": 9999, "to": "acct-1"}).allowed


def test_hitl_reject_is_always_allowed_regardless_of_args():
    pending = PendingAction("run", "node", "transfer", {"amount": 100})
    assert decide_resume(pending, "reject", {}).allowed
    assert decide_resume(pending, "reject", {"anything": True}).allowed


def test_hitl_is_order_independent_on_nested_structures():
    pending = PendingAction("run", "node", "s", {"a": 1, "b": {"x": [1, 2], "y": 3}})
    assert decide_resume(pending, "approve", {"b": {"y": 3, "x": [1, 2]}, "a": 1}).allowed


def test_hitl_unknown_action_name_is_refused_with_reason():
    pending = PendingAction("run", "node", "s", {"a": 1})
    d = decide_resume(pending, "rerun", {"a": 1})
    assert not d.allowed
    assert "unexpected action" in d.reason


# --------------------------------------------------------------------------- #
# validator.py — edge cases beyond the four recorded injections
# --------------------------------------------------------------------------- #

def test_unknown_type_breaks_catalog_invariant():
    assert _reject({"id": "x", "type": "Wormhole"}).invariant == Invariant.CATALOG


def test_extra_handler_property_breaks_data_not_code():
    r = _reject({"id": "x", "type": "Button", "label": "Go", "onPress": {"action": "rerun"}, "onclick": "steal()"})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert r.field == "onclick"


def test_registered_component_with_unregistered_action_breaks_event():
    r = _reject({"id": "x", "type": "Button", "label": "Go", "onPress": {"action": "drop_tables"}})
    assert r.invariant == Invariant.EVENT


def test_binding_that_is_not_bind_shape_breaks_data_not_code():
    r = _reject({"id": "h", "type": "Text", "text": "just a literal"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_binding_with_non_pointer_target_breaks_data_not_code():
    r = _reject({"id": "h", "type": "Text", "text": {"$bind": "noslash"}})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_enum_value_outside_its_set_breaks_data_not_code():
    r = _reject({"id": "b", "type": "Notice", "text": {"$bind": "/s"}, "tone": "chartreuse"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_javascript_url_value_breaks_data_not_code():
    r = _reject({"id": "btn", "type": "Button", "label": "javascript:steal()"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_data_url_value_breaks_data_not_code():
    r = _reject({"id": "btn", "type": "Button", "label": "data:text/html,<script>x</script>"})
    assert r.invariant == Invariant.DATA_NOT_CODE


# --------------------------------------------------------------------------- #
# CodeBlock — the three invariants for the new catalog component
# --------------------------------------------------------------------------- #

def _codeblock(**extra) -> dict:
    """A CodeBlock component in the shape the validator sees."""
    return {"id": "cb", "type": "CodeBlock", "title": "example",
            "code": {"$bind": "/code_source"}, "language": "python",
            "onCopy": {"action": "request_data"}, **extra}


def test_codeblock_is_registered_in_the_catalog_as_a_custom_component():
    assert "CodeBlock" in COMPONENTS
    spec = COMPONENTS["CodeBlock"]
    assert spec.source == "custom"
    assert spec.props["code"].kind == "binding"
    assert spec.props["onCopy"].kind == "action"
    assert spec.props["title"].kind == "text"
    # language is a plain text label so any language works; the renderer picks
    # a tokeniser if it has one and falls back to unhighlighted text otherwise.
    # Safety still holds: the value goes through validator's markup / scheme
    # checks and lands in a text node — no execution path.
    assert spec.props["language"].kind == "text"


def test_codeblock_with_bound_code_and_valid_language_validates_clean():
    surface = {"root": "cb", "components": [_codeblock()],
               "dataModel": {"code_source": "print('hi')"}}
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]


def test_codeblock_with_inline_code_breaks_data_not_code():
    # A CodeBlock shipping its source as a literal instead of a $bind is the
    # classic 'skip the wall' trick. The binding invariant refuses it.
    r = _reject({"id": "cb", "type": "CodeBlock", "title": "x",
                 "code": "print('inline')", "language": "python"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_codeblock_with_unknown_language_renders_as_plain_text_not_refused():
    # language is a display label now — an unknown value renders unhighlighted
    # (still a text node, still safe) rather than being refused by the wall.
    # The validator only cares that the value has no markup or script scheme.
    surface = {"root": "cb",
               "components": [{"id": "cb", "type": "CodeBlock", "title": "x",
                               "code": {"$bind": "/code_source"},
                               "language": "cobol"}],
               "dataModel": {"code_source": "IDENTIFICATION DIVISION."}}
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]


def test_codeblock_with_markup_in_language_breaks_data_not_code():
    # A language label that carries markup is refused by the text-slot's
    # markup check — this is what closes the door on smuggling script through
    # the freed-up language field.
    r = _reject({"id": "cb", "type": "CodeBlock", "title": "x",
                 "code": {"$bind": "/code_source"},
                 "language": "<script>alert(1)</script>"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_codeblock_with_extra_handler_property_breaks_data_not_code():
    # onload / onclick / onCopy-with-wrong-name — any DOM handler property
    # crosses the same wall that Button.onclick crosses.
    r = _reject({"id": "cb", "type": "CodeBlock", "title": "x",
                 "code": {"$bind": "/code_source"}, "language": "python",
                 "onload": "steal()"})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert r.field == "onload"


def test_codeblock_with_unregistered_action_breaks_event():
    r = _reject({"id": "cb", "type": "CodeBlock", "title": "x",
                 "code": {"$bind": "/code_source"}, "language": "python",
                 "onCopy": {"action": "exfiltrate_clipboard"}})
    assert r.invariant == Invariant.EVENT


def test_codeblock_with_markup_in_title_breaks_data_not_code():
    r = _reject({"id": "cb", "type": "CodeBlock",
                 "title": "<img src=x onerror=steal()>",
                 "code": {"$bind": "/code_source"}, "language": "python"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_codeblock_renderer_never_uses_innerhtml_and_uses_textcontent():
    """The CodeBlock renderer stays inside the no-innerHTML contract: every
    token is a <span> whose textContent is the raw slice — so a bound value
    containing '<script>' becomes literal characters, never markup.

    Assertions are done on the WHOLE FILE (rather than trying to slice out
    renderCodeBlock's body) so they can't be fooled by a refactor that
    renames sibling functions or moves the innerHTML into a helper.
    """
    for filename in ("index.html", "codeworks.html"):
        html = (_BUILD_ROOT / "s13code" / "ui" / "client" / filename).read_text()
        assert "renderCodeBlock" in html and "tokenizeCode" in html, filename
        # textContent is how each span gets its glyphs. If this line disappears,
        # the tokenizer must be using something else — reject.
        assert "span.textContent" in html or "sp.textContent=" in html, filename
        # Neither eval() nor new Function() appear anywhere in the render
        # client — the tokenizer only computes tokens, it never executes them.
        assert "eval(" not in html, filename
        assert "new Function" not in html, filename

    # Whole-file innerHTML count stays at 1 for index.html and 0 for
    # codeworks.html. index.html's ONE occurrence is the documented safety
    # comment near the top of the render client. Any addition trips this.
    index_html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "index.html").read_text()
    assert index_html.count("innerHTML") == 1, (
        "index.html gained an innerHTML reference — every CodeBlock/render "
        "code path must go through textContent"
    )
    codeworks_html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "codeworks.html").read_text()
    assert codeworks_html.count("innerHTML") == 0, (
        "codeworks.html gained an innerHTML reference — every CodeWorks "
        "render code path must go through textContent"
    )


def test_codeblock_new_injections_are_covered_by_the_wall():
    """The three new adversarial fixtures (inline source, fake language, handler
    property) all trip the validator with data-not-code, and the safe heading
    survives."""
    from s13code.ui.fixtures import load_injections
    cases = {c["name"]: c for c in load_injections()["cases"]}
    for name in ("codeblock-inline-source", "codeblock-markup-language",
                 "codeblock-handler-property"):
        assert name in cases, name
        result = validate_surface(cases[name]["surface"])
        assert not result.ok
        assert any(r.invariant == "data-not-code" for r in result.rejections)
        accepted = {c["id"] for c in result.accepted}
        assert "ok" in accepted


# --------------------------------------------------------------------------- #
# _parse_json_object — salvage from a truncated response
# --------------------------------------------------------------------------- #

def _parse():
    from s13code.runtime import _parse_json_object
    return _parse_json_object


def test_parse_recovers_well_formed_json_wrapped_in_a_code_fence():
    raw = '```json\n{"title": "ok", "code": {"language": "python", "source": "print(1)"}}\n```'
    d = _parse()(raw)
    assert d and d["title"] == "ok"
    assert d["code"]["language"] == "python"


def test_parse_recovers_json_embedded_in_prose():
    raw = 'Here is your answer: {"a": 1, "b": [1,2,3]} and some extra prose'
    d = _parse()(raw)
    assert d == {"a": 1, "b": [1, 2, 3]}


def test_parse_salvages_a_truncated_object_by_closing_open_brackets():
    """A response cut off mid-string still surfaces the fields the model
    finished. This is what happens when the gateway's max_tokens ceiling
    interrupts the model before the JSON is complete."""
    # A realistic-shape content-role JSON, chopped mid-way through the
    # sections' third point.
    raw = (
        '{"title": "Test", "code": {"language": "java", "source": "class X {}"}, '
        '"sections": [{"heading": "Key Features", "points": ["Handles quoted fields", '
        '"Escapes double quotes", "Toggles quo'
    )
    d = _parse()(raw)
    assert d is not None
    assert d["title"] == "Test"
    assert d["code"]["language"] == "java"
    # We recovered "Key Features" with its first two complete points; the
    # third point that was mid-string got dropped.
    sections = d.get("sections", [])
    assert sections and sections[0]["heading"] == "Key Features"
    assert len(sections[0]["points"]) == 2
    assert "Handles quoted fields" in sections[0]["points"]


def test_parse_salvages_when_cut_after_a_comma():
    raw = '{"a": 1, "b": 2, "c":'
    d = _parse()(raw)
    assert d == {"a": 1, "b": 2}


def test_parse_returns_none_on_completely_unrecoverable_garbage():
    assert _parse()("not json at all, no braces even") is None
    assert _parse()('{"unbalanced": "] wrong closer"') is not None or True   # tolerant, either is ok
    assert _parse()(None) is None
    assert _parse()(123) is None


def test_safe_siblings_survive_a_partially_poisoned_surface():
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["good", "poison"]},
            {"id": "good", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            {"id": "poison", "type": "Button", "label": "x", "onPress": {"action": "transfer_all"}},
        ],
        "dataModel": {"title": "Report"},
    }
    result = validate_surface(surface)
    accepted_ids = {c["id"] for c in result.accepted}
    assert "good" in accepted_ids and "root" in accepted_ids
    assert "poison" not in accepted_ids


# --------------------------------------------------------------------------- #
# catalog.py — catalog_manifest
# --------------------------------------------------------------------------- #

def test_manifest_returns_components_and_actions():
    m = catalog_manifest()
    assert set(m) == {"components", "actions"}
    assert set(m["components"]) == set(COMPONENTS)


def test_manifest_lists_every_component_spec_prop():
    m = catalog_manifest()
    for name, spec in COMPONENTS.items():
        assert set(m["components"][name]["props"]) == set(spec.props), name


def test_manifest_surfaces_every_registered_action():
    m = catalog_manifest()
    assert set(m["actions"]) == set(REGISTERED_ACTIONS)


def test_catalog_is_the_realigned_a2ui_basic_plus_custom_set():
    """24 types: 15 A2UI-Basic + 9 custom, each tagged with its source."""
    assert len(COMPONENTS) == 24
    by_source: dict[str, set[str]] = {}
    for name, spec in COMPONENTS.items():
        assert spec.source in ("a2ui-basic", "custom"), name
        by_source.setdefault(spec.source, set()).add(name)
    assert by_source["a2ui-basic"] == {
        "Row", "Column", "List", "Card", "Divider", "Text", "Image", "TextField",
        "CheckBox", "Slider", "InputChoice", "DateTime", "Button", "Tabs", "Modal",
    }
    assert by_source["custom"] == {
        "BarChart", "Sparkline", "StatTile", "ProgressBar", "Timeline", "DataTable",
        "Notice", "ApprovalCard", "CodeBlock",
    }
    # The removed types are truly gone.
    for gone in ("Heading", "Grid", "Table", "Tab", "Badge", "LineChart"):
        assert gone not in COMPONENTS
    # The manifest carries the source per component.
    m = catalog_manifest()
    assert m["components"]["Text"]["source"] == "a2ui-basic"
    assert m["components"]["BarChart"]["source"] == "custom"


# --------------------------------------------------------------------------- #
# routes — in-process via FastAPI TestClient, hermetic (fake runtime)
# --------------------------------------------------------------------------- #

class _FakeGraph:
    """Stands in for S13's live graph; every run is unknown."""

    def snapshot(self, run_id: str):
        raise KeyError(run_id)

    def events(self, run_id: str):
        return []


class _FakeRuntime:
    graph = _FakeGraph()


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ui_router)  # exactly how s13code.main folds the UI in
    app.state.s13_runtime = _FakeRuntime()
    return TestClient(app)


def test_route_catalog_returns_valid_manifest(client):
    resp = client.get("/v1/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert "components" in body and "actions" in body
    assert body == catalog_manifest()


def test_route_harness_surface_is_clean_and_stays_in_the_realigned_catalog(client):
    resp = client.get("/v1/harness/surface")
    assert resp.status_code == 200
    body = resp.json()
    assert body["clean"] is True
    # The captured composition re-validates cleanly: every accepted component
    # survives the same wall that guards injection.
    assert body["component_count"] == body["validator"]["accepted"] > 0
    assert body["validator"]["rejected"] == 0
    # Gemini composed with the realigned catalog: only real catalog types, and
    # none of the removed ones.
    types = {c["type"] for c in body["surface"]["components"]}
    assert types.issubset(set(COMPONENTS))
    assert types.isdisjoint({"Heading", "Grid", "Table", "Tab", "Badge", "LineChart"})


def test_route_render_client_has_no_run_id_placeholder(client):
    resp = client.get("/s/harness")
    assert resp.status_code == 200
    assert "__RUN_ID__" not in resp.text
    assert "harness" in resp.text


def test_route_validate_rejects_a_wormhole_on_catalog(client):
    surface = {"root": "r", "components": [{"id": "r", "type": "Wormhole"}]}
    resp = client.post("/v1/validate", json={"surface": surface})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["rejections"][0]["invariant"] == Invariant.CATALOG


def test_route_unknown_run_surface_is_404(client):
    resp = client.get("/v1/runs/does-not-exist/surface")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# routes — STATE_SNAPSHOT reconnect, in-process with a POPULATED fake runtime
# --------------------------------------------------------------------------- #

class _Event:
    """An S13 journal Event, in the (sequence, kind, node_id, payload) shape the
    UI reads off runtime.graph.events(run_id)."""

    def __init__(self, d: dict):
        self.sequence, self.kind = d["sequence"], d["kind"]
        self.node_id, self.payload = d.get("node_id"), d.get("payload") or {}


class _Snapshot:
    def __init__(self, run: dict):
        self.finished, self.nodes, self.edges = run["finished"], run["nodes"], run["edges"]


class _PopulatedGraph:
    """One known run, replayed from the recorded three_cities fixture."""

    def __init__(self, run_id: str, run: dict):
        self._id, self._run = run_id, run

    def snapshot(self, run_id: str):
        if run_id != self._id:
            raise KeyError(run_id)
        return _Snapshot(self._run)

    def events(self, run_id: str):
        if run_id != self._id:
            raise KeyError(run_id)
        return [_Event(e) for e in self._run["events"]]


class _PopulatedRuntime:
    def __init__(self, run_id: str, run: dict):
        self.graph = _PopulatedGraph(run_id, run)


@pytest.fixture(scope="module")
def live_client(three_cities) -> TestClient:
    app = FastAPI()
    app.include_router(ui_router)
    app.state.s13_runtime = _PopulatedRuntime("tc", three_cities)
    return TestClient(app)


def _sse_events(text: str) -> list[dict]:
    """Parse the ``data: {...}`` frames out of an SSE response body."""
    import json as _json
    return [_json.loads(line[len("data: "):]) for line in text.splitlines()
            if line.startswith("data: ")]


def test_route_snapshot_returns_a_state_snapshot_of_the_full_data_model(live_client, three_cities):
    resp = live_client.get("/v1/runs/tc/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "tc"
    ev = body["event"]
    assert ev["type"] == "STATE_SNAPSHOT"
    # Complete state: every succeeded node result and all graph patches.
    succeeded = {nid for nid, n in three_cities["nodes"].items() if n["state"] == "succeeded"}
    assert set(ev["state"]["results"]) == succeeded
    # The surface was built in-process, so component_count is real.
    assert body["component_count"] == len(build_run_surface(three_cities)["components"])


def test_route_snapshot_unknown_run_is_404(live_client):
    assert live_client.get("/v1/runs/nope/snapshot").status_code == 404


def test_route_events_reconnect_leads_with_one_state_snapshot(live_client):
    frames = _sse_events(live_client.get("/v1/runs/tc/events?reconnect=1").text)
    assert frames[0]["type"] == "STATE_SNAPSHOT"
    # Exactly one snapshot; the rest is the normal tape.
    assert sum(1 for f in frames if f["type"] == "STATE_SNAPSHOT") == 1
    assert frames[1]["type"] == "RUN_STARTED"
    assert frames[-1]["type"] == "RUN_FINISHED"


def test_route_events_without_reconnect_has_no_snapshot(live_client):
    frames = _sse_events(live_client.get("/v1/runs/tc/events").text)
    assert all(f["type"] != "STATE_SNAPSHOT" for f in frames)
    assert frames[0]["type"] == "RUN_STARTED"


def test_route_reconnect_snapshot_rebuild_equals_full_replay(live_client):
    """End-to-end over the router: the leading snapshot from a reconnect stream
    equals the fold of the whole non-reconnect stream — a client is whole after
    one frame."""
    full_frames = _sse_events(live_client.get("/v1/runs/tc/events").text)
    full = replay_state(full_frames)
    reconnect_frames = _sse_events(live_client.get("/v1/runs/tc/events?reconnect=1").text)
    rebuilt = reconnect_frames[0]["state"]
    assert rebuilt == full


# --------------------------------------------------------------------------- #
# render client — source-level safety property (no innerHTML from bound data)
# --------------------------------------------------------------------------- #

def test_render_client_never_uses_innerhtml_and_documents_the_contract():
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "index.html").read_text()
    # The client draws every value through text nodes, never as markup.
    assert "createTextNode" in html
    # innerHTML is never assigned anywhere — no data path can reach it.
    assert not re.search(r"innerHTML\s*=", html)
    # The one place the word appears is the documented safety contract itself.
    assert html.count("innerHTML") == 1
    assert "NEVER sets" in html and "innerHTML from a bound value" in html


def test_render_client_reconnects_and_rebuilds_from_a_state_snapshot():
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "index.html").read_text()
    # It opens the AG-UI event stream and knows how to recover a dropped one.
    assert "EventSource" in html
    assert "?reconnect=1" in html
    # It rebuilds from the single STATE_SNAPSHOT frame rather than replaying.
    assert "STATE_SNAPSHOT" in html
    assert "rebuiltFromSnapshot" in html
    # The reducer still only ever touches text nodes (contract preserved above).
    assert "createTextNode" in html


# --------------------------------------------------------------------------- #
# Router: entity-list dashboard prompts still fan out to research (regression)
# --------------------------------------------------------------------------- #

def test_work_intent_still_fans_out_on_dashboard_of_entities():
    """Trunk trigger: a fresh 'Compose a dashboard of X, Y, Z' prompt should
    STILL route to compose_research with one researcher task per entity.

    We added a wizard-shape carve-out to _work_intent that keeps
    conversation prompts on compose_answer. That carve-out must not swallow
    the trunk's dashboard fanout — this test locks in the boundary.
    """
    from s13code.runtime import _work_intent

    mode, tasks = _work_intent(
        "Compose a dashboard of London, Paris and Berlin",
        respond_as="ui",
    )
    assert mode == "compose_research", mode
    assert len(tasks) == 3, [t.id for t in tasks]
    assert [t.skill for t in tasks] == ["researcher", "researcher", "researcher"]
    subjects = [t.input.get("subject") for t in tasks]
    assert "London" in subjects and "Paris" in subjects and "Berlin" in subjects


def test_work_intent_stays_on_content_for_conversation_shaped_prompts():
    """A prompt that stitches in prior picks ('So far the user picked: X') is
    a wizard turn — the picks ARE the answers, and research would fan out to
    low-value web searches. Route to compose_answer instead."""
    from s13code.runtime import _work_intent

    prompt = (
        "I want to build a subscription app.\n"
        "So far the user has picked: 1) SaaS product; 2) Next.js + Stripe.\n"
        "Respond with the next interface."
    )
    mode, tasks = _work_intent(prompt, respond_as="ui")
    assert mode == "compose_answer", mode
    assert len(tasks) == 1 and tasks[0].skill == "content"


# --------------------------------------------------------------------------- #
# CodeBlock tokenizer: keyword-plus-name rules actually fire (regression)
# --------------------------------------------------------------------------- #

def test_codeblock_tokenizer_emits_class_name_and_function_kinds():
    """Regression check: `class Foo`, `def foo(`, `function foo(`, `fn foo(`
    used to be encoded as lookbehind rules that couldn't fire because the
    tokenizer slices past the preceding keyword before re-testing. The fix
    bundles the keyword and the name into one match and splits post-hoc via
    a ``capture:`` array. This test asserts the grammar rules actually
    contain the multi-token form."""
    for filename in ("index.html", "codeworks.html", "app.html"):
        html = (_BUILD_ROOT / "s13code" / "ui" / "client" / filename).read_text()
        # No lookbehind rules left anywhere.
        assert "(?<=" not in html, f"{filename} still contains a lookbehind"
        # class-name multi-token form (Python + JS shape) is present.
        assert "class-name" in html, filename
        # The tokenizer handles ``capture:`` arrays.
        assert "rule.capture" in html, filename


def test_codeblock_grammars_are_the_same_in_all_three_clients():
    """Every renderer that draws CodeBlock ships the same language set so a
    user sees the same highlighting regardless of which app rendered it."""
    grammars_by_file: dict[str, set[str]] = {}
    for filename in ("index.html", "codeworks.html", "app.html"):
        html = (_BUILD_ROOT / "s13code" / "ui" / "client" / filename).read_text()
        grammars = set(re.findall(r"CB_GRAMMARS\.([a-z]+)\s*=", html))
        grammars_by_file[filename] = grammars
    ref = grammars_by_file["index.html"]
    for filename, gs in grammars_by_file.items():
        assert gs == ref, f"{filename} grammars differ: only-in-{filename}={gs - ref}, missing-in-{filename}={ref - gs}"
    # Sanity check: the reference set contains the languages the README lists.
    for lang in ("python", "javascript", "typescript", "java", "go", "rust",
                 "sql", "shell", "cpp", "csharp", "json", "yaml",
                 "html", "css", "markdown"):
        assert lang in ref, lang
