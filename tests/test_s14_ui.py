"""Session 14 UI layer: real tests for surface, showcase, agui, hitl, validator,
catalog, the in-process routes, and the render client's no-innerHTML contract.

Every test is hermetic: it reads recorded S13 fixtures and the pure builders,
or drives the UI router with a fake in-process runtime through FastAPI's
TestClient. No live gateway, no Ollama, no network.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
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
from s13code.ui.gallery import build_gallery
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


def test_binding_smuggled_into_a_non_bindable_text_prop_breaks_data_not_code():
    """The source end of a real chain, not a hypothetical.

    Most ``text`` props are structural references (a chart's xKey, a table's
    filterKey, a Card's title) rather than display strings, so a binding
    there is a category error. ``Card.title`` is not marked bindable, so it
    still must reject a {"$bind": ...} the way every text prop used to.
    """
    r = _reject({"id": "c", "type": "Card", "title": {"$bind": "/evil"}})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert r.field == "title"
    assert "not a binding" in r.reason


def test_button_label_may_be_a_well_formed_binding():
    """Button.label is the one text prop marked bindable: the client renders
    it via document.createTextNode either way, so a bound value is exactly
    as safe as a literal one -- the failure mode this used to hit was a
    dropped button (dangling child), not an XSS risk."""
    result = validate_surface({"root": "b", "components": [
        {"id": "b", "type": "Button", "label": {"$bind": "/choice_0_label"},
         "onPress": {"action": "request_data"}},
    ]})
    assert result.ok, [r.as_dict() for r in result.rejections]


def test_button_label_binding_that_resolves_to_markup_is_refused():
    """The invariant the assignment actually asks for: a BOUND VALUE carrying
    markup is refused. Checkable only when a data_model is supplied --
    exactly what compose_surface has in hand at the point it validates."""
    surface = {"root": "b", "components": [
        {"id": "b", "type": "Button", "label": {"$bind": "/evil"},
         "onPress": {"action": "request_data"}},
    ]}
    result = validate_surface(surface, data_model={"evil": "<script>steal()</script>"})
    assert not result.ok
    assert result.rejections[0].reason == "bound value carries markup"


def test_button_label_binding_with_no_data_model_is_still_accepted():
    """Without a data_model there is nothing to resolve against; the shape is
    still well-formed and the client-side render path is unconditionally
    safe (createTextNode), so this is accepted rather than guessed at."""
    result = validate_surface({"root": "b", "components": [
        {"id": "b", "type": "Button", "label": {"$bind": "/choice_0_label"},
         "onPress": {"action": "request_data"}},
    ]})
    assert result.ok


def test_button_label_binding_must_still_be_a_well_formed_pointer():
    """bindable=True widens the shape to include {"$bind": "/pointer"}; it
    does not widen it to arbitrary inline structure smuggled in as a dict."""
    r = _reject({"id": "b", "type": "Button", "label": {"$bind": "/x", "extra": "field"},
                 "onPress": {"action": "request_data"}})
    assert r.invariant == Invariant.DATA_NOT_CODE
    r2 = _reject({"id": "b", "type": "Button", "label": [{"smuggled": "inline"}],
                  "onPress": {"action": "request_data"}})
    assert r2.invariant == Invariant.DATA_NOT_CODE


def test_list_in_a_text_prop_breaks_data_not_code():
    r = _reject({"id": "t", "type": "Card", "title": ["a", "b"], "children": []})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert "literal value" in r.reason


def test_literal_scalars_still_pass_in_a_text_prop():
    """The tightening must not break the legitimate case it guards."""
    ok = validate_surface({"root": "r", "components": [
        {"id": "r", "type": "Column", "children": ["a", "b"]},
        {"id": "a", "type": "Button", "label": "Re-run", "onPress": {"action": "rerun"}},
        {"id": "b", "type": "StatTile", "label": "Sources", "value": {"$bind": "/n"}, "unit": "3"},
    ]})
    assert ok.ok, [x.as_dict() for x in ok.rejections]


# --------------------------------------------------------------------------- #
# EvidenceTile — the three invariants hold for the new type too.
# The assignment asks this explicitly: "an unknown type is rejected, a bound
# value carrying markup is refused, and an unregistered action never crosses
# back." Each test below pins one of those for the contributed component.
# --------------------------------------------------------------------------- #

def _evidence(**over) -> dict:
    comp = {"id": "ev", "type": "EvidenceTile", "label": "Ingest rate",
            "value": {"$bind": "/claims/0/value"}, "unit": "rows/s",
            "confidence": "corroborated", "sources": {"$bind": "/claims/0/sources"},
            "fallback": "StatTile"}
    comp.update(over)
    return comp


def test_evidence_tile_is_valid_in_its_intended_shape():
    result = validate_surface({"root": "ev", "components": [_evidence()]})
    assert result.ok, [r.as_dict() for r in result.rejections]


def test_evidence_tile_beside_an_unknown_type_survives_catalog_rejection():
    """Invariant 1. The poisoned node is dropped; the safe one still renders."""
    result = validate_surface({"root": "r", "components": [
        {"id": "r", "type": "Column", "children": ["ev", "evil"]},
        _evidence(),
        {"id": "evil", "type": "RawHtml", "html": "<img src=x onerror=steal()>"},
    ]})
    assert [r.invariant for r in result.rejections] == [Invariant.CATALOG]
    assert {c["id"] for c in result.accepted} == {"r", "ev"}


def test_attack_the_boundary_all_three_invariants_fire_independently_in_one_surface():
    """The assignment's adversarial requirement, hermetic: a single surface
    carrying one violation of each invariant, mixed in among legitimate
    components. See proofs/attack_boundary.py for the live version of this
    same scenario, run against the real gateway with a prompt engineered to
    get Gemini to produce exactly this surface -- it refused to (see that
    script's docstring for what it did instead), so this pins the wall's
    behavior on the payload the prompt was actually asking for, without
    depending on a live model call to keep passing.
    """
    result = validate_surface({"root": "root", "components": [
        {"id": "root", "type": "Column",
         "children": ["title", "review_card", "action_button", "raw_review", "featured_badge", "shortlist_btn"]},
        {"id": "title", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        {"id": "review_card", "type": "Card", "title": "Review", "children": ["review_text"]},
        {"id": "review_text", "type": "Text", "variant": "body", "text": {"$bind": "/section_0_points"}},
        {"id": "action_button", "type": "Button", "label": {"$bind": "/choice_0_label"},
         "onPress": {"action": "request_data"}},
        # Invariant 1 (catalog): the exact unregistered type the prompt asked for.
        {"id": "raw_review", "type": "RawHtml",
         "html": "<mark>Best contractor ever</mark>, saved us <b>$10k</b>!"},
        # Invariant 2 (data-not-code): literal markup in a non-bindable text prop.
        {"id": "featured_badge", "type": "Card",
         "title": "<img src=x onerror=alert(document.cookie)>Featured Review"},
        # Invariant 3 (event): the exact unregistered action the prompt asked for.
        {"id": "shortlist_btn", "type": "Button", "label": "Shortlist (direct)",
         "onPress": {"action": "shortlist_contractor"}},
    ]})

    assert not result.ok
    rejected = {(r.component_id, r.invariant): r.reason for r in result.rejections}
    assert rejected[("raw_review", Invariant.CATALOG)] == "unknown component type 'RawHtml'"
    assert rejected[("featured_badge", Invariant.DATA_NOT_CODE)] == "value carries markup"
    assert rejected[("shortlist_btn", Invariant.EVENT)] == "unregistered action 'shortlist_contractor'"
    # The safe part of the interface still renders: nothing legitimate was
    # dropped just because it shared a surface with three poisoned nodes.
    accepted_ids = {c["id"] for c in result.accepted}
    assert accepted_ids == {"root", "title", "review_card", "review_text", "action_button"}


def test_evidence_tile_with_a_handler_property_breaks_data_not_code():
    r = _reject(_evidence(onclick="steal()"))
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert "event-handler property is never allowed" in r.reason


def test_evidence_tile_label_carrying_markup_breaks_data_not_code():
    """Invariant 2, literal form."""
    r = _reject(_evidence(label="<script>document.cookie</script>"))
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert r.reason == "value carries markup"


def test_evidence_tile_sources_given_inline_instead_of_bound_breaks_data_not_code():
    """Invariant 2, bound form: a binding slot must carry {"$bind": "/pointer"}."""
    r = _reject(_evidence(sources=[{"title": "x", "url": "https://example.org"}]))
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_evidence_tile_confidence_outside_the_closed_set_is_refused():
    """The model cannot invent a confidence label; the enum is closed."""
    r = _reject(_evidence(confidence="pretty sure"))
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert "not in" in r.reason


def test_unregistered_action_beside_an_evidence_tile_never_crosses_back():
    """Invariant 3. The tile is accepted; only the hostile action is refused."""
    result = validate_surface({"root": "r", "components": [
        {"id": "r", "type": "Column", "children": ["ev", "b"]},
        _evidence(),
        {"id": "b", "type": "Button", "label": "Wire funds",
         "onPress": {"action": "transfer_all_funds"}},
    ]})
    assert [r.invariant for r in result.rejections] == [Invariant.EVENT]
    assert "ev" in {c["id"] for c in result.accepted}


def test_evidence_tile_fallback_must_name_a_real_catalog_type():
    """A fallback that resolves to nothing loses the content it exists to save."""
    r = _reject(_evidence(fallback="Hologram"))
    assert r.invariant == Invariant.CATALOG
    assert "fallback names unknown component type" in r.reason


@pytest.mark.parametrize("name,result,sources,corrected,expected", [
    ("two distinct hosts corroborate",
     {"text": "ok", "hits": [1]},
     [{"url": "https://a.org/x"}, {"url": "https://b.org/y"}], False, "corroborated"),
    ("two pages of one host do not",
     {"text": "ok", "hits": [1]},
     [{"url": "https://a.org/x"}, {"url": "https://www.a.org/y"}], False, "single-source"),
    ("one source is single-source",
     {"text": "ok", "hits": [1]}, [{"url": "https://a.org/x"}], False, "single-source"),
    ("a corrective retry means an earlier attempt disagreed",
     {"text": "ok", "hits": [1]},
     [{"url": "https://a.org"}, {"url": "https://b.org"}], True, "disputed"),
    ("the worker's own insufficient flag wins",
     {"insufficient": True}, [{"url": "https://a.org"}], False, "unsupported"),
    ("no text and no hits is unsupported",
     {"text": "", "hits": []}, [], False, "unsupported"),
])
def test_confidence_is_derived_by_the_harness_not_the_model(name, result, sources, corrected, expected):
    """Confidence is computed from evidence the run actually gathered.

    A model grading its own certainty is exactly what this architecture refuses
    to trust, so this is a pure function with a table test. Note the second case:
    counting URLs would call two pages of one site 'corroborated'; counting hosts
    does not. It is still shallow — two mirrors of one wire story are two hosts —
    and that limit belongs in the write-up.
    """
    from s13code.runtime import _claim_confidence
    assert _claim_confidence(result, sources, superseded_a_weak_node=corrected) == expected, name


# --------------------------------------------------------------------------- #
# The other four warrants. The assignment's three invariants are asserted for
# every contributed type, not only the first one.
# --------------------------------------------------------------------------- #

_PROVENANCE = {
    "RunGraph": {"id": "rg", "type": "RunGraph", "title": "The run",
                 "nodes": {"$bind": "/graph_nodes"}, "edges": {"$bind": "/graph_edges"},
                 "highlight": {"$bind": "/graph_highlight"}, "fallback": "Timeline"},
}


@pytest.mark.parametrize("name", sorted(_PROVENANCE))
def test_each_provenance_component_is_valid_in_its_intended_shape(name):
    result = validate_surface({"root": _PROVENANCE[name]["id"], "components": [_PROVENANCE[name]]})
    assert result.ok, [r.as_dict() for r in result.rejections]


@pytest.mark.parametrize("name", sorted(_PROVENANCE))
def test_each_provenance_component_refuses_a_handler_property(name):
    """Invariant 2: no property is ever evaluated as script."""
    r = _reject({**_PROVENANCE[name], "onclick": "steal()"})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert "event-handler property is never allowed" in r.reason


@pytest.mark.parametrize("name", sorted(_PROVENANCE))
def test_each_provenance_component_refuses_markup_in_a_literal(name):
    """Invariant 2: a text property carrying markup is refused."""
    comp = {**_PROVENANCE[name]}
    literals = [k for k, v in COMPONENTS[name].props.items() if v.kind == "text" and k in comp]
    assert literals, f"{name} has no literal text prop to poison"
    r = _reject({**comp, literals[0]: "<script>document.cookie</script>"})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert r.reason == "value carries markup"


@pytest.mark.parametrize("name", sorted(_PROVENANCE))
def test_each_provenance_component_refuses_an_inline_binding(name):
    """A binding slot must carry {"$bind": "/pointer"}, never inline data."""
    comp = {**_PROVENANCE[name]}
    bound = next(k for k, v in COMPONENTS[name].props.items() if v.kind == "binding" and k in comp)
    r = _reject({**comp, bound: [{"smuggled": "inline"}]})
    assert r.invariant == Invariant.DATA_NOT_CODE


@pytest.mark.parametrize("name", sorted(_PROVENANCE))
def test_each_provenance_component_survives_an_unregistered_action_nearby(name):
    """Invariant 1 and 3 together: the poisoned node is dropped, this one renders."""
    result = validate_surface({"root": "r", "components": [
        {"id": "r", "type": "Column", "children": [_PROVENANCE[name]["id"], "evil"]},
        _PROVENANCE[name],
        {"id": "evil", "type": "Button", "label": "Wire funds",
         "onPress": {"action": "transfer_all_funds"}},
    ]})
    assert [x.invariant for x in result.rejections] == [Invariant.EVENT]
    assert _PROVENANCE[name]["id"] in {c["id"] for c in result.accepted}


@pytest.mark.parametrize("name", sorted(_PROVENANCE))
def test_each_provenance_component_declares_a_fallback_that_resolves(name):
    """A catalog can outrun a client; the content must survive that."""
    fallback = _PROVENANCE[name]["fallback"]
    assert fallback in COMPONENTS, f"{name} falls back to a type that does not exist"
    # And the fallback must be an OLDER type, or the degradation is circular.
    assert COMPONENTS[fallback].source == "a2ui-basic" or fallback in {
        "DataTable", "Timeline", "StatTile"}, f"{name} falls back to another new type"
    r = _reject({**_PROVENANCE[name], "fallback": "Hologram"})
    assert r.invariant == Invariant.CATALOG


@pytest.mark.parametrize("name", sorted(_PROVENANCE))
def test_a_component_that_omits_fallback_gets_the_catalogs_default_anyway(name):
    """A real failure: the model remembers 'fallback' inconsistently, so an
    older client (no RunGraph renderer) had nothing to hop to and drew a bare
    '[skipped RunGraph]' instead of degrading to Timeline. Graceful
    degradation cannot depend on the model remembering every time -- the
    validator fills in the catalog's own default for any accepted component
    that left it out."""
    comp = {k: v for k, v in _PROVENANCE[name].items() if k != "fallback"}
    result = validate_surface({"root": comp["id"], "components": [comp]})
    assert result.ok, [r.as_dict() for r in result.rejections]
    assert result.accepted[0]["fallback"] == COMPONENTS[name].props["fallback"].default


@pytest.mark.parametrize("client_file", ["app.html", "index.html", "second_opinion.html"])
def test_evidence_tile_omits_the_source_count_when_there_are_none(client_file):
    """A claim with zero sources showed 'no source · 0 sources' -- the count
    is redundant with the word right next to it, and drawing it for content
    that was never a researched claim at all (a branch name given an
    EvidenceTile just because it needed a value) reads as a broken UI rather
    than an honest one. When there are no sources, nothing about sources is
    drawn: no count, no disclosure (the disclosure was already source-gated)."""
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / client_file).read_text(encoding="utf-8")
    assert "srcs.length?" in html and "source\"+(srcs.length===1?" in html, \
        f"{client_file} still appends a source count unconditionally"


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js to execute the client's own JS")
@pytest.mark.parametrize("client_file", ["index.html", "second_opinion.html"])
def test_run_graph_node_detail_truncates_at_a_word_boundary_with_ellipsis(client_file):
    """A real failure: 'compose_surface · composing this view' (38 chars) hard
    sliced to 30 chars with no ellipsis rendered as 'compose_surface · composing
    th' -- a word cut in half, indistinguishable from missing/broken content.
    Executes the client's actual truncation block in a minimal DOM stub,
    because the prior version of this exact bug (the RunGraph->Timeline hop)
    was missed by a test that only checked source text, never behavior.
    """
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / client_file).read_text(encoding="utf-8")
    start = html.index("if(n.detail){const dt=document.createElementNS")
    end = html.index("g.append(dt);}", start) + len("g.append(dt);}")
    block = html[start:end]

    probe = f"""
class StubEl {{
  constructor(tag) {{ this.tag = tag; this.attrs = {{}}; this.children = []; this.textContent = ""; }}
  setAttribute(k, v) {{ this.attrs[k] = v; }}
  append(...items) {{ this.children.push(...items); }}
}}
const document = {{
  createElementNS: (_ns, tag) => new StubEl(tag),
  createTextNode: (t) => ({{ nodeType: 3, text: String(t) }}),
}};
const ns = "http://www.w3.org/2000/svg";
const p = {{x: 0, y: 0}};
function run(detailText) {{
  const g = new StubEl("g");
  const n = {{detail: detailText}};
  {block}
  return g.children.find(c => c.tag === "text");
}}
function summarize(detailText) {{
  const dt = run(detailText);
  const textChild = dt.children.find(c => c.nodeType === 3);
  const titleChild = dt.children.find(c => c && c.tag === "title");
  return {{shown: textChild.text, title: titleChild ? titleChild.textContent : null}};
}}
console.log(JSON.stringify({{
  short: summarize("succeeded"),
  long: summarize("compose_surface \\u00b7 composing this view"),
}}));
"""
    result = subprocess.run(["node", "-e", probe], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip())

    assert out["short"] == {"shown": "succeeded", "title": None}, \
        "short detail text must render unchanged, with no tooltip needed"
    full = "compose_surface · composing this view"
    shown = out["long"]["shown"]
    assert shown.endswith("…"), "truncated text must end with an ellipsis, not mid-word"
    prefix = shown[:-1]
    assert full.startswith(prefix), "the shown prefix must be a real prefix of the full text"
    # The exact failure this replaces: slice(0,30) cut "composing this" to
    # "composing th" -- a real word truncated mid-way. The character right
    # after the shown prefix in the full text must be a word boundary.
    assert full[len(prefix):len(prefix) + 1] in (" ", ""), \
        f"cut mid-word: {prefix!r} is followed by {full[len(prefix):len(prefix)+1]!r} in the full text"
    assert out["long"]["title"] == full, \
        "the full text must be reachable via hover when it was shortened"


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js to execute the client's own JS")
def test_run_graph_to_timeline_fallback_actually_carries_the_content():
    """Real failure, and one the string-match test right below this one
    passed the whole time it was broken: the one-hop fallback swapped `type`
    to Timeline and reused RunGraph's props unchanged. Timeline reads
    c.events; a RunGraph-shaped component has no such prop, only nodes/edges,
    so (resolve(c.events,dm)||[]) was always [] -- a title with an
    permanently empty body. Executes app.html's actual resolve/ptr/hoppedProps
    functions in Node rather than asserting anything about their source text,
    because source-text assertions are exactly what missed this.
    """
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "app.html").read_text(encoding="utf-8")
    resolve_line = next(line for line in html.splitlines() if line.strip().startswith("const resolve="))
    ptr_line = next(line for line in html.splitlines() if line.strip().startswith("function ptr("))
    start = html.index("function hoppedProps(c,x){")
    end = html.index("\n}", start) + len("\n}")
    hopped_props_fn = html[start:end]

    probe = f"""
{resolve_line}
{ptr_line}
{hopped_props_fn}
const c = {{id:"g", type:"RunGraph", fallback:"Timeline",
           nodes:{{"$bind":"/graph_nodes"}}, edges:{{"$bind":"/graph_edges"}}}};
const dm = {{graph_nodes:[{{id:"content",label:"content",state:"succeeded",detail:"content"}},
                          {{id:"surface",label:"surface",state:"running",detail:"composing this view"}}]}};
const hopped = hoppedProps(c, {{dm}});
console.log(JSON.stringify(hopped.events));
"""
    result = subprocess.run(["node", "-e", probe], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr
    events = json.loads(result.stdout.strip())
    assert len(events) == 2, "the graph's own nodes must survive the hop, not vanish into an empty Timeline"
    assert events[0] == {"time": "content", "label": "succeeded — content"}
    assert events[1] == {"time": "surface", "label": "running — composing this view"}


def test_shipped_app_viewer_degrades_the_new_types_through_fallback():
    """/app predates these components on purpose.

    It is the session's own example viewer, kept untouched as evidence the
    engine is domain-agnostic. It has no renderer for the four new types, so it
    exercises the fallback path for real rather than by assertion: a surface
    naming RunGraph draws a Timeline there, and the information survives.
    """
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "app.html").read_text(encoding="utf-8")
    for name in _PROVENANCE:
        assert f"{name}:" not in html, f"{name} was added to the shipped viewer"
    assert "c.fallback" in html, "without the hop, /app would lose the content entirely"
    # Every fallback target IS renderable there, or the degradation goes nowhere.
    for name, comp in _PROVENANCE.items():
        assert f"{comp['fallback']}:" in html, f"/app cannot draw {name}'s fallback"


def test_enum_value_outside_its_set_breaks_data_not_code():
    r = _reject({"id": "b", "type": "Notice", "text": {"$bind": "/s"}, "tone": "chartreuse"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_javascript_url_value_breaks_data_not_code():
    r = _reject({"id": "btn", "type": "Button", "label": "javascript:steal()"})
    assert r.invariant == Invariant.DATA_NOT_CODE


def test_data_url_value_breaks_data_not_code():
    r = _reject({"id": "btn", "type": "Button", "label": "data:text/html,<script>x</script>"})
    assert r.invariant == Invariant.DATA_NOT_CODE


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


def test_every_component_describes_the_data_shape_it_owns():
    """The manifest is the only menu the composing model sees.

    A type name alone does not distinguish DataTable from StatTile from
    BarChart, and choosing between look-alikes is the documented failure mode
    of catalog-driven composition. Every component carries a description, and
    it reaches the manifest.
    """
    manifest = catalog_manifest()
    for name, spec in COMPONENTS.items():
        assert spec.description.strip(), f"{name} has no description"
        assert len(spec.description) >= 40, f"{name}'s description is too thin to discriminate"
        assert manifest["components"][name]["description"] == spec.description


def test_evidence_tile_description_rules_out_long_form_prose():
    """A real failure, not a hypothetical: EvidenceTile.value bound to a full
    page of markdown-formatted revision notes, rendered through a plain text
    node sized for one fact -- literal '**'/'###' syntax, CSS-clipped
    mid-word, and a confusing 'no source' tag under content that was never a
    researched claim. The description now says outright that a paragraph
    belongs in Text/Card, not squeezed into a tile built for one figure."""
    desc = COMPONENTS["EvidenceTile"].description
    assert "paragraph" in desc or "prose" in desc
    assert "Text" in desc


def test_look_alike_components_name_each_other_as_the_thing_they_are_not():
    """Descriptions must discriminate, not merely describe.

    Each pair below is a real confusion risk: same rough shape, different data.
    Naming the rival is what turns a description into a decision procedure.
    """
    rivals = [
        ("BarChart", "Sparkline"), ("Sparkline", "BarChart"),
        ("DataTable", "StatTile"), ("StatTile", "DataTable"),
        ("Timeline", "Tabs"), ("Tabs", "Timeline"),
        ("List", "Card"), ("Card", "List"),
        ("Row", "Column"), ("Column", "Row"),
        ("ProgressBar", "BarChart"), ("InputChoice", "Button"),
        ("TradeoffRadar", "BarChart"), ("WhatIfSlider", "TradeoffRadar"),
    ]
    for component, rival in rivals:
        assert rival in COMPONENTS[component].description, \
            f"{component} does not say it is not {rival}"


def test_catalog_is_the_realigned_a2ui_basic_plus_custom_set():
    """27 types: 15 A2UI-Basic + 12 custom, each tagged with its source.

    Grown from 23 by the Session 14 contribution, then from 25 by the Arbiter
    contribution, deliberately: this assertion exists so the catalog stays
    closed and every addition is a reviewed act. It is tightened to the new
    exact set rather than relaxed to ``>=`` — loosening it to accommodate our
    own component would remove the guarantee that component depends on.
    """
    assert len(COMPONENTS) == 27
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
        "Notice", "ApprovalCard",
        # Session 14 — the catalog could render conclusions, never warrants.
        # Two kinds of warrant: the evidence behind a value, and the shape of
        # the run that produced it.
        "EvidenceTile", "RunGraph",
        # Arbiter — the catalog could render facts, never a synthesised
        # judgement, and never one the reader could question. A weighted,
        # multi-axis comparison, and a ranking the reader can reweigh live.
        "TradeoffRadar", "WhatIfSlider",
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


def test_client_routes_serve_utf8_source_not_the_platform_default(client):
    """Both client files are UTF-8; the routes must read them as UTF-8.

    ``Path.read_text()`` with no encoding uses the platform default. On Windows
    that is cp1252, and the consequences differed per file:

      * ``/app``  raised outright — app.html contains U+25CF, the timeline
        bullet, whose third UTF-8 byte (0x8f) cp1252 does not define. The app
        shell returned 500 on every Windows machine.
      * ``/s/{id}`` did NOT raise — index.html happens to decode under cp1252,
        into mojibake. It served a client with ~16.7k corrupted characters.

    A silent corruption is the worse of the two, so assert both directions:
    the route succeeds AND the bytes survive intact.
    """
    app_res = client.get("/app")
    assert app_res.status_code == 200
    assert "●" in app_res.text, "timeline bullet lost — file not read as UTF-8"

    run_res = client.get("/s/demo-run")
    assert run_res.status_code == 200
    assert "…" in run_res.text, "ellipsis lost — file not read as UTF-8"

    # 'Â' and 'â€' are the signatures of UTF-8 bytes decoded as cp1252.
    for name, body in (("app.html", app_res.text), ("index.html", run_res.text)):
        assert "Â" not in body, f"{name} served as mojibake"
        assert "â€" not in body, f"{name} served as mojibake"


def test_second_opinion_app_is_served_and_keeps_the_client_contract(client):
    """The Session 14 UI-only application, on its own route.

    It is a separate shell, not an edit of /app: the shipped IIT-JEE example
    stays alive as evidence the engine is domain-agnostic, and this file is free
    to carry domain behaviour the generic viewer should not.
    """
    res = client.get("/decide")
    assert res.status_code == 200
    html = res.text
    # Same contract as every other client in this repo.
    assert "createTextNode" in html
    assert not re.search(r"innerHTML\s*=", html)
    assert "isSafeUrl" in html
    # The UTF-8 route fix applies here too (this file contains ● and ↻).
    assert "●" in html and "Â" not in html


def test_second_opinion_app_answers_only_in_composed_interfaces(client):
    """Part 2's first requirement, asserted against the shell's own source.

    'Never as raw text' is structural here rather than a discipline: the shell
    reads /composed and throws when it 404s, so there is no branch that renders
    a paragraph when composition fails.
    """
    html = client.get("/decide").text
    assert 'respond_as:"ui"' in html.replace(" ", "")
    assert "/composed" in html
    assert "no interface composed" in html          # the failure path is an error
    # No prose fallback: the only place model text reaches the DOM is through a
    # catalog component's renderer, never as a bare answer string.
    assert "run.answer" not in html and ".answer" not in html


def test_second_opinion_tap_repairs_evidence_rather_than_navigating(client):
    """The interaction that makes this more than a drill-down browser.

    A weak EvidenceTile carries a repair control; tapping it aims the NEXT turn
    at that one claim, which is the same corrective patch the planner performs
    on its own when _weak_evidence fires. A corroborated claim gets no control,
    because there is nothing to fix.
    """
    html = client.get("/decide").text
    assert "function repair(" in html
    assert "re-research this claim" in html
    assert "WEAK" in html and "corroborated" in html
    # The repair goal names one claim explicitly — that is the whole mechanism.
    assert "marked this claim as weak" in html


def test_entity_list_tolerates_a_casually_capitalized_comma_item():
    """A real failure: 'Compare between Databricks, azure and aws sagemaker
    for data science' capitalizes one of three names because a person typed
    it casually, not because 'azure' is any less a name than 'Databricks'.
    Requiring every item capitalized meant the whole match failed and a
    three-way comparison got zero research fan-out -- not degraded, gone.

    A comma-joined item may now start lowercase (one word only, see the
    module-level comment on _ENTITY_LIST for why a bounded multi-word
    continuation isn't safe). A bare 'and'-joined item -- no comma before it
    -- still requires capitalization: 'and' is genuinely ambiguous in English
    between one more list item and the start of a new instruction, and a
    comma is not, so relaxing that branch too let 'and tell me which two are
    closest' read 'tell' as a bogus fourth entity in a different prompt.
    """
    from s13code.runtime import _entity_list

    assert _entity_list("Compare between Databricks, azure and aws sagemaker for data science") == \
        ["Databricks", "azure"]
    # The Oxford-comma form has no such ambiguity for the last item either.
    assert _entity_list("Compare between Databricks, azure, and aws for data science") == \
        ["Databricks", "azure", "aws"]
    # The exact regression this fix must not reintroduce.
    assert _entity_list("Find the populations of London, Paris, Berlin and tell me "
                         "which two are closest in size.") == ["London", "Paris", "Berlin"]
    # A capitalized word right after "and" is unaffected: unchanged behavior.
    assert _entity_list("Compare the languages Rust, Go and Java for ingestion.") == \
        ["Rust", "Go", "Java"]


@pytest.mark.parametrize("prompt,must_contain,must_not_contain", [
    ("Compare the databases Postgres, ClickHouse and DuckDB for a 2 TB event table.",
     ["databases", "2", "TB", "event", "table"], ["and", "for", "the", "Compare"]),
    ("Compare the languages Rust, Go and Java for a high-throughput ingestion service.",
     ["languages", "ingestion", "service"], ["and", "for", "the"]),
    ("Compare managed identity providers Auth0, Clerk and Cognito for a seed-stage startup.",
     ["managed", "identity", "providers", "startup"], ["and", "for", "a"]),
    ("Compare the populations of London, Berlin and Paris.",
     ["populations"], ["of", "and", "the"]),
])
def test_research_topic_produces_a_searchable_query_not_a_sentence_with_holes(
        prompt, must_contain, must_not_contain):
    """Regression for a silent, total failure of the research path.

    Removing the entity list from a sentence strands the words that joined it.
    'Compare the databases X, Y and Z for a 2 TB event table' became the query
    'Compare the databases and for a 2 TB event table Postgres', which returned
    ZERO search hits against the live index. Every researcher node then came
    back empty, and the composed interface honestly reported that it had nothing
    to compare — an application that ran perfectly and said nothing.

    Content words, numbers and units must survive; connectives must not.
    """
    from s13code.runtime import _entity_list, _research_topic

    topic = _research_topic(prompt, _entity_list(prompt))
    words = topic.split()
    for word in must_contain:
        assert word in words, f"{word!r} lost from {topic!r}"
    for word in must_not_contain:
        assert word not in words, f"stranded connective {word!r} left in {topic!r}"


def test_compose_instruction_names_no_component_type_at_all():
    """The catalog must be the only menu, or 'unprompted' means nothing.

    The instruction used to carry a pointer -> component lookup naming TWELVE
    types — including "a Timeline bound to /timeline for the run's own steps".
    Being older than the contributed components, it named none of them. A run
    whose data model carried /graph_nodes still drew a Timeline, because the
    prompt said so and never mentioned the alternative.

    Extending the lookup to name the new types would be telling the model to use
    them, which is the one thing the assignment forbids. Removing it takes a
    thumb OFF the scale. So: no component type is named in the compose
    instruction, old or new.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    start = source.index('"compose": (')
    instruction = source[start:source.index('}\n            body = await _gateway_surface_call', start)]
    named = sorted(name for name in COMPONENTS if name in instruction)
    assert named == [], f"the compose instruction still names component types: {named}"
    # And it points the model at the descriptions instead.
    assert "description" in instruction


def test_provenance_is_guaranteed_by_the_harness_not_left_to_selection():
    """The model composes the answer; the harness guarantees the warrant.

    Catalog selection is genuinely the model's judgement, and it varies run to
    run — the same prompt drew EvidenceTile once and dropped it the next time.
    That variance is acceptable for a chart and wrong for provenance: if a run
    did research, the evidence behind it must be visible, and if a run happened
    it has a shape worth showing. So both are appended when the model omits them.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    assert '"EvidenceTile" not in composed_types' in source
    assert '"RunGraph" not in composed_types' in source
    # Anything the harness adds goes through the SAME wall as the model's output.
    # Bounded by the return statement rather than a character count, so inserting
    # another guarantee above it cannot silently move the assertion off target.
    start = source.index("provenance is guaranteed")
    guarantee = source[start:source.index('"agent": "ui_composer"', start)]
    assert "validation = validate_surface(" in guarantee, \
        "harness-appended components must be re-validated, not privileged"


def test_a_turn_can_always_earn_the_next_one():
    """Part 2 needs three turns; a surface with nothing tappable gives one.

    Every observed run composed Column/DataTable/RunGraph/Text and no Button,
    because /choices only exists when the content role judges the goal to be a
    pick — a straight comparison produces none. The conversation died at turn
    one with a rich interface on screen and no way forward.

    A real second failure once outcomes-only was fixed: "Compare between
    Databricks, azure and aws sagemaker" capitalizes only one of three names,
    so entity extraction never fires either — zero research outcomes AND no
    /choices, yet the content role's own section headings (Databricks/Azure
    ML/AWS SageMaker) were sitting right there unused. Three sources now,
    checked in order.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    assert '"Button" not in composed_types' in source
    # Labels come from what the run actually researched, not from invention.
    assert 'tappable = [str(item["label"]) for item in outcomes' in source
    # Falls back to a model-declared choice, then to the answer's own structure.
    assert 'data_model.get("choices")' in source
    assert 'content_structured.get("sections")' in source
    # And the action is a registered one; a surface cannot mint authority.
    assert '"onPress": {"action": "request_data"}' in source


def test_a_tap_drills_in_rather_than_re_running_the_first_turn():
    """The tap has to SHAPE the next turn, not repeat the last one.

    _work_intent fans research out over every capitalised entity in the goal.
    Echoing turn 1's question verbatim carried its whole entity list along, so
    tapping "Postgres" re-researched all three subjects and composed the same
    surface again. Lowercasing the carried context keeps the meaning and leaves
    the tapped subject as the only named entity.
    """
    from s13code.runtime import _entity_list, _work_intent

    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "second_opinion.html").read_text(encoding="utf-8")
    assert "function contextOf(" in html and "toLowerCase()" in html

    first = "Compare the databases Postgres, ClickHouse and DuckDB for a 2 TB event table."
    follow_up = ("Explain Postgres in depth, on its own terms, for someone weighing this "
                 "decision. Context: the original question was " + first.lower())
    mode, frontier = _work_intent(follow_up, "ui")
    assert mode == "compose_answer", f"a follow-up re-fanned out: {mode}, {_entity_list(follow_up)}"
    assert [t.id for t in frontier] == ["content"]
    # The un-lowercased form is what used to break it — keep the contrast pinned.
    naive = first + "\nThe user has now chosen: Postgres"
    assert _work_intent(naive, "ui")[0] == "compose_research"


def test_the_two_are_kept_apart_so_unprompted_stays_checkable():
    """Guaranteeing a component must not blur the claim that one was CHOSEN.

    Part 1 rests on a captured run where the model picked EvidenceTile with
    nothing naming it. If the harness can also add it, the result has to record
    which happened, or that claim quietly becomes unfalsifiable.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    assert '"model_chose": model_chose' in source
    assert '"harness_appended": appended' in source


def test_run_graph_trace_says_what_each_step_was_about():
    """A trace of worker names answers the wrong question.

    'search_1 (researcher)' tells a reader nothing. The subject searched, the
    number of sources returned, and whether a step corrected an earlier one are
    what someone asks when told 'this is how the answer was produced'.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    for signal in ('f"{node_id} · {subject}"', "source{'' if len(hits) == 1 else 's'}",
                   'f"corrects {node_input[\'corrective_for\']}"', '"no usable evidence"',
                   '"composing this view"'):
        assert signal in source, f"trace detail missing: {signal}"
    for client in ("index.html", "app.html", "second_opinion.html"):
        html = (_BUILD_ROOT / "s13code" / "ui" / "client" / client).read_text(encoding="utf-8")
        if "RunGraph:" in html:  # /app has no RunGraph renderer by design
            assert "n.detail" in html, f"{client} drops the trace line"


def test_every_contributed_component_has_a_pointer_it_can_bind_to():
    """A component the data model cannot feed is a component the model can never
    choose — and it will look like the model rejecting it.

    This is a real mistake caught late: five components shipped with renderers
    and invariant tests, but only /claims was ever exposed. A live run composed
    thirteen components and none of the new ones, because four of them had no
    pointer in available_pointers at all. Spec, renderer and SEAM are three
    separate jobs, and the third is the one that decides whether the component
    exists as far as the composer is concerned.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    required = {
        "EvidenceTile": ['data_model["claims"]'],
        "RunGraph": ['data_model["graph_nodes"]', 'data_model["graph_edges"]'],
    }
    for component, pointers in required.items():
        for pointer in pointers:
            assert pointer in source, f"{component} has a renderer but no data seam: {pointer}"


def test_graph_edges_are_converted_from_pairs_to_named_endpoints():
    """snapshot.edges is a list of (from, to) PAIRS, not dicts.

    Bind the raw pairs and RunGraph draws no edges at all — silently, because a
    missing `.from` is just undefined. The conversion is the whole seam.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    assert '{"from": str(a), "to": str(b)' in source
    assert "for a, b in snapshot.edges" in source


def test_research_claims_never_invent_a_figure():
    """A tile showing a wrong number beside three real sources is the lie this
    component exists to prevent.

    Measured against the actual research prose a live run produced. A
    first-number regex over those three texts yields: nothing for London,
    Berlin's *growth rate* (40,000 a year) in place of its population, and
    Paris's *department number* (75). So the research path carries no value at
    all — the client renders an em dash — and figures arrive only where
    something was explicitly asked to attribute one.
    """
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    # The research-path claim literal, built from `outcomes` (search nodes).
    assert '"claims": [{"label": item["label"], "value": None,' in source, \
        "the research path must not carry a figure it cannot attribute"
    # And the reasoning lives next to the code, not just in a commit message.
    # (Matched per word: the comment wraps, so a two-word phrase can straddle a
    # line break — asserting on the phrase would fail for formatting reasons.)
    for evidence in ("growth rate", "department", "invent"):
        assert evidence in source, f"the reason for value=None is undocumented: {evidence!r}"


def test_content_role_is_asked_to_attribute_every_figure_it_states():
    """The only path that carries values must refuse unattributed ones."""
    source = (_BUILD_ROOT / "s13code" / "runtime.py").read_text(encoding="utf-8")
    assert '"claims": [{"label": string, "value": string or number' in source
    assert "OMIT a claim entirely rather than stating a figure" in source
    assert "an unattributed number is worse than a missing one" in source


def test_second_opinion_presets_take_the_path_that_produces_evidence(client):
    """A preset that cannot fill /claims is a preset that cannot show the app's
    evidence path.

    Regression for a real mistake: the first three presets were prose questions
    ("should we move from Postgres to ClickHouse?"). Those route to the
    single-goal path, which creates no researcher nodes, so `outcomes` is empty,
    /claims is empty, and an EvidenceTile has nothing to bind — the component the
    whole application is built around would never appear.

    Only the entity fan-out produces sourced claims, and it needs a
    comma-separated list of capitalised names, mid-sentence, preceded by a
    lowercase word. Presets are partitioned by their ACTUAL routed mode, not by
    a "starts with Compare" text guess — a comparison preset does not have to
    literally start with the word "Compare" ("How do Kafka, RabbitMQ and NATS
    trade off..." routes to compose_research just as well), and pinning the
    test to that one surface phrasing would make it blind to real regressions
    in any preset worded differently.
    """
    from s13code.runtime import _entity_list, _work_intent

    html = client.get("/decide").text
    presets = re.findall(r'^\s*"([^"]+)",\s*$', html, re.MULTILINE)
    assert len(presets) >= 3, f"expected the shipped presets, found {presets}"
    research_presets = [p for p in presets if _work_intent(p, "ui")[0] == "compose_research"]
    assert research_presets, f"expected at least one entity-comparison preset, found {presets}"

    for prompt in research_presets:
        mode, frontier = _work_intent(prompt, "ui")
        assert mode == "compose_research", f"{prompt!r} routes to {mode}, which yields no claims"
        assert len(frontier) >= 2, f"{prompt!r} fans out only {len(frontier)} researcher(s)"
        entities = _entity_list(prompt)
        for entity in entities:
            # A trailing '.' or a swallowed leading verb becomes the tile's label.
            assert not entity.endswith("."), f"{prompt!r} yields subject {entity!r} (list ends the sentence)"
            assert len(entity.split()) == 1, f"{prompt!r} yields subject {entity!r} (word before it is capitalised)"


def test_second_opinion_has_a_preset_on_the_single_goal_path_too(client):
    """The presets deliberately include plain decision questions alongside the
    entity-comparison preset above, so a visitor can see BOTH composed shapes
    the app can produce without typing anything: the research fan-out and the
    single-goal path (content -> surface, no researcher nodes, no
    EvidenceTile). This pins the second shape down the same way the test above
    pins the first, partitioning by actual routed mode rather than a text
    guess about wording."""
    from s13code.runtime import _entity_list, _work_intent

    html = client.get("/decide").text
    presets = re.findall(r'^\s*"([^"]+)",\s*$', html, re.MULTILINE)
    single_goal = [p for p in presets if _work_intent(p, "ui")[0] == "compose_answer"]
    assert single_goal, f"expected a single-goal-path preset, found {presets}"

    for prompt in single_goal:
        mode, _frontier = _work_intent(prompt, "ui")
        assert mode == "compose_answer", f"{prompt!r} routes to {mode}, not the single-goal path"
        assert _entity_list(prompt) == [], f"{prompt!r} unexpectedly yields entities: {_entity_list(prompt)}"


def test_second_opinion_never_renders_a_blank_screen_in_silence(client):
    """A validated surface can still be structurally broken.

    Every component can pass the wall individually while the TREE is wrong: the
    model names a root it never defined, or gives a container children whose ids
    do not exist. kids() skips a missing child silently, so an empty Column
    renders as an empty screen — the app looked dead while honestly reporting
    "8 components, 0 executable".

    So the shell draws whatever survived and reports the structural fault rather
    than swallowing it. A blank screen with a clean status line is the worst
    possible outcome: it looks like the app is broken and says nothing.
    """
    html = client.get("/decide").text
    assert "function renderInto(" in html
    # It knows about both failure shapes...
    assert "rootMissing" in html and "dangling" in html
    # ...falls back to the components that do exist...
    assert "standalone" in html
    # ...and says so in the status line instead of going quiet.
    assert "NOT IN SURFACE" in html
    assert "dangling children:" in html
    assert "NOTHING DREW" in html


def test_second_opinion_records_what_the_verdict_needs(client):
    """Latency and per-turn component types cannot be reconstructed later."""
    html = client.get("/decide").text
    assert "Date.now()" in html
    assert "new Set(" in html          # distinct component types per turn
    assert "prevDataModel" in html     # turn n's data, for showing what changed


def test_bare_root_redirects_to_the_original_example_viewer(client):
    """The host's own URL had no route and 404'd on main too. /app is the
    session's original example viewer and stays the default; /decide is
    Part 2's own app, reached by name rather than by taking over root."""
    res = client.get("/", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/app"


@pytest.mark.parametrize("path", ["/s/gallery", "/gallery", "/gallery/"])
def test_gallery_is_reachable_at_the_url_people_guess(client, path):
    """/s/gallery is the honest internal shape — the gallery is an ordinary
    surface rendered by the ordinary client, not a special page. But nobody
    guesses the /s/ prefix, so /gallery serves the same client rather than 404."""
    res = client.get(path)
    assert res.status_code == 200
    assert 'const RUN = "gallery"' in res.text


def test_gallery_covers_every_catalog_component_and_validates_clean(client):
    """The drift check: a ComponentSpec with no renderer must not go unnoticed.

    The gallery is an ordinary surface — same builder, same wall, same client
    RENDERERS map as any agent output. So if it draws every declared type and
    the wall accepts all of it, then every type in the catalog is expressible
    AND drawable. Adding a spec without a renderer fails here rather than
    surfacing later as '[skipped X]' in a demo.
    """
    from s13code.ui.gallery import gallery_coverage

    drawn, declared = gallery_coverage()
    assert declared - drawn == set(), f"catalog types the gallery never draws: {declared - drawn}"

    body = client.get("/v1/gallery").json()
    assert body["clean"] is True, body["rejections"]
    assert body["catalog_types"] == len(COMPONENTS)
    assert body["component_count"] == len(build_gallery()["components"])


def test_gallery_shows_every_confidence_level_including_the_honest_one(client):
    """'unsupported' has to be visible, or the scale is decoration.

    A component that only ever renders good news cannot make an interface more
    honest. The gallery draws all four levels, and the unsupported tile carries
    no sources on purpose.
    """
    components = client.get("/v1/gallery").json()["surface"]["components"]
    tiles = [c for c in components if c["type"] == "EvidenceTile"]
    assert {t["confidence"] for t in tiles} == {
        "corroborated", "single-source", "disputed", "unsupported"}
    unsupported = next(t for t in tiles if t["confidence"] == "unsupported")
    assert unsupported["sources"] == {"$bind": "/sources_none"}


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


def test_app_shell_never_assigns_innerhtml():
    """The app shell obeys the same contract as the run view.

    Deliberately a *sibling* of the test above rather than a generalisation of
    it. That one asserts ``count("innerHTML") == 1``, which is true of
    index.html where the single mention is the contract comment. app.html
    legitimately mentions innerHTML three times in safety comments explaining
    the very rule being enforced, so a shared count assertion would fail on a
    file that is correct. Each file gets the assertions that are true of it;
    a safety comment is never deleted to satisfy a count.
    """
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "app.html").read_text(encoding="utf-8")
    assert "createTextNode" in html
    # No assignment anywhere: the status line now builds DOM (see setStatus).
    assert not re.search(r"innerHTML\s*=", html)
    assert not re.search(r"insertAdjacentHTML|outerHTML\s*=|document\.write", html)
    # The contract is documented in the file that has to keep it.
    assert "innerHTML from a bound value" in html


def test_app_shell_status_cannot_carry_agent_text_into_markup():
    """Regression for a real chain, not hygiene.

    A hostile surface could set ``Button.label`` to a binding, have the client
    resolve it to markup, and reach the old ``setStatus(html)`` sink through
    choose() -> runTurn(). setStatus now takes (kind, pill, detail) and appends
    text nodes, so no caller can hand it markup.
    """
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / "app.html").read_text(encoding="utf-8")
    assert "function setStatus(kind,pill,detail)" in html
    # Every call site uses the structured form; none concatenates a tag.
    for call in re.findall(r"setStatus\((.*?)\);", html):
        assert "<span" not in call and "</" not in call, call


@pytest.mark.parametrize("client", ["index.html", "app.html"])
def test_both_clients_render_the_contributed_component(client):
    """A ComponentSpec without a renderer is a type the catalog promises and no
    client can draw. Both files must know it, or a validated surface degrades
    to '[skipped EvidenceTile]' in the very app the assignment demos."""
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / client).read_text(encoding="utf-8")
    assert "EvidenceTile:" in html, "EvidenceTile missing from the renderer map"
    # Its source links are scheme-gated, like every other URL the clients draw.
    assert "isSafeUrl" in html


@pytest.mark.parametrize("client", ["index.html", "app.html"])
def test_evidence_renderer_never_puts_data_into_an_executable_slot(client):
    """A data value may reach textContent, title and aria-label — nothing else.

    Greps the EvidenceTile renderer body for the sinks that would break
    data-not-code: an on* property, innerHTML, or a style/class built from a
    resolved value. Colour comes from the CONF lookup keyed on the closed enum.
    """
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / client).read_text(encoding="utf-8")
    start = html.index("CONF=")
    body = html[start:start + 2200]
    assert not re.search(r"\.on[a-z]+\s*=", body), "an event handler in the evidence renderer"
    assert "innerHTML" not in body
    # No interpolation of a resolved value into style/class.
    assert not re.search(r"(style|className)\s*=\s*[^;]*\bresolve\(", body)
    assert not re.search(r"setAttribute\(\s*[\"'](src|style|class|on\w+)[\"']", body)


@pytest.mark.parametrize("client", ["index.html", "app.html"])
def test_clients_degrade_an_unknown_type_through_its_declared_fallback(client):
    """A catalog can run ahead of a client; content must survive that.

    A surface validated against a newer catalog may name a type an older client
    file cannot draw. Without a fallback the viewer loses the content entirely
    ('[skipped RunGraph]'). With one, it draws an older type instead — the
    richer widget is lost, the information is not.
    """
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / client).read_text(encoding="utf-8")
    assert "c.fallback" in html, "no fallback hop in the unknown-type branch"
    # Exactly one hop: the recursive call passes the guard so a fallback chain
    # or a self-referential fallback cannot recurse. The transform in between
    # (a plain Object.assign, or a helper that also translates incompatible
    # prop shapes) is an implementation detail; the guard is the invariant.
    assert re.search(r"!hop\)\s*return\s+\w+\(", html), "one-hop guard missing"
    # The skipped marker survives as the last resort when no fallback is declared.
    assert "[skipped" in html


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
