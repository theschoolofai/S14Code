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
        "Notice", "ApprovalCard", "RouteMap",
    }
    # The removed types are truly gone.
    for gone in ("Heading", "Grid", "Table", "Tab", "Badge", "LineChart"):
        assert gone not in COMPONENTS
    # The manifest carries the source per component.
    m = catalog_manifest()
    assert m["components"]["Text"]["source"] == "a2ui-basic"
    assert m["components"]["BarChart"]["source"] == "custom"


# --------------------------------------------------------------------------- #
# RouteMap — the contributed component, held to the same three invariants
# --------------------------------------------------------------------------- #

_GOOD_MAP = {
    "id": "map", "type": "RouteMap", "title": "Day 1",
    "points": {"$bind": "/places"}, "mode": "route", "tone": "good",
}


def test_routemap_is_a_custom_catalog_component_with_typed_props():
    spec = COMPONENTS["RouteMap"]
    assert spec.source == "custom"
    assert {p: s.kind for p, s in spec.props.items()} == {
        "title": "text", "points": "binding", "mode": "enum", "tone": "enum",
    }
    # It offers no way to reach the network: no src, no url, no image property.
    assert not {"src", "url", "tileUrl", "href"} & set(spec.props)
    # And no way to act: a map cannot emit an action at all.
    assert not any(s.kind == "action" for s in spec.props.values())


def test_routemap_clean_surface_validates_with_zero_rejections():
    result = validate_surface({"root": "map", "components": [_GOOD_MAP]})
    assert result.ok and len(result.accepted) == 1


def test_routemap_catalog_invariant_rejects_an_unknown_map_type():
    """A hostile surface cannot name a map type the catalog never declared."""
    r = _reject({**_GOOD_MAP, "type": "LeafletMap"})
    assert r.invariant == Invariant.CATALOG and "LeafletMap" in r.reason


def test_routemap_data_not_code_refuses_markup_in_a_shown_value():
    r = _reject({**_GOOD_MAP, "title": "<script>fetch('//evil')</script>Day 1"})
    assert r.invariant == Invariant.DATA_NOT_CODE and r.reason == "value carries markup"


def test_routemap_data_not_code_refuses_inline_points_instead_of_a_binding():
    """Points must arrive as {'$bind': '/pointer'}; inline data is how markup sneaks in."""
    r = _reject({**_GOOD_MAP, "points": [{"label": "<img onerror=x>", "lat": 1, "lon": 2}]})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert r.reason == "binding must be {'$bind': '/pointer'}"


def test_routemap_data_not_code_refuses_a_smuggled_tile_url():
    r = _reject({**_GOOD_MAP, "tileUrl": "https://tiles.example/{z}/{x}/{y}.png"})
    assert r.invariant == Invariant.DATA_NOT_CODE and "unknown property 'tileUrl'" in r.reason


def test_routemap_data_not_code_refuses_a_javascript_url():
    r = _reject({**_GOOD_MAP, "title": "javascript:alert(1)"})
    assert r.invariant == Invariant.DATA_NOT_CODE and r.reason == "value is a script/data URL"


def test_routemap_data_not_code_refuses_an_event_handler_property():
    r = _reject({**_GOOD_MAP, "onclick": "steal()"})
    assert r.invariant == Invariant.DATA_NOT_CODE
    assert r.reason == "event-handler property is never allowed"


def test_routemap_enum_invariant_refuses_a_mode_outside_its_set():
    r = _reject({**_GOOD_MAP, "mode": "satellite"})
    assert r.invariant == Invariant.DATA_NOT_CODE and "'satellite' not in" in r.reason


def test_routemap_event_invariant_unregistered_action_never_crosses_back():
    """An unregistered action beside a map is dropped; the map still renders."""
    surface = {"root": "root", "components": [
        {"id": "root", "type": "Column", "children": ["map", "exfil"]},
        _GOOD_MAP,
        {"id": "exfil", "type": "Button", "label": "Export",
         "onPress": {"action": "post_to_webhook"}},
    ]}
    result = validate_surface(surface)
    assert [r.invariant for r in result.rejections] == [Invariant.EVENT]
    assert result.rejections[0].reason == "unregistered action 'post_to_webhook'"
    # The safe part of the interface survives: root and the map still render.
    assert {c["id"] for c in result.accepted} == {"root", "map"}


def test_routemap_survives_a_poisoned_sibling_map():
    """One poisoned map cannot blank a screen that holds a clean one."""
    surface = {"root": "root", "components": [
        {"id": "root", "type": "Column", "children": ["map", "bad"]},
        _GOOD_MAP,
        {"id": "bad", "type": "RouteMap", "title": "<b>x</b>", "points": {"$bind": "/places"}},
    ]}
    result = validate_surface(surface)
    assert {c["id"] for c in result.accepted} == {"root", "map"}
    assert [r.component_id for r in result.rejections] == ["bad"]


def _routemap_renderer(filename: str) -> str:
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / filename).read_text()
    match = re.search(r"function routeMap\w*\(.*?\n\}", html, re.DOTALL)
    assert match, f"{filename} has no RouteMap renderer"
    return match.group(0)


@pytest.mark.parametrize("filename", ["index.html", "app.html"])
def test_routemap_renderer_draws_it_and_executes_nothing(filename):
    body = _routemap_renderer(filename)
    # It builds SVG nodes and writes every label as text, never as markup.
    assert "createElementNS" in body and "textContent" in body
    assert "innerHTML" not in body
    # No outbound channel: no tile server, no image, no fetch of any kind.
    for forbidden in ("fetch(", "XMLHttpRequest", "<img", 'createElement("img")', "src"):
        assert forbidden not in body, f"{filename}: RouteMap must not use {forbidden}"
    # The one URL in the renderer is the SVG XML namespace, which is a constant
    # the DOM requires and never a resource the browser retrieves.
    assert re.findall(r"https?://\S*?[\"'`]", body) == ['http://www.w3.org/2000/svg"']
    # No string is ever evaluated.
    for forbidden in ("eval(", "new Function", "setTimeout("):
        assert forbidden not in body, f"{filename}: RouteMap must not use {forbidden}"


@pytest.mark.parametrize("filename", ["index.html", "app.html"])
def test_routemap_is_wired_into_the_client_renderer_table(filename):
    html = (_BUILD_ROOT / "s13code" / "ui" / "client" / filename).read_text()
    assert re.search(r"\bRouteMap\s*:", html), f"{filename} does not dispatch RouteMap"


# --------------------------------------------------------------------------- #
# Waypoint — the UI-only trip-planner shell served at /trip
# --------------------------------------------------------------------------- #

def _trip_html() -> str:
    return (_BUILD_ROOT / "s13code" / "ui" / "client" / "trip.html").read_text()


def test_trip_shell_can_draw_every_type_the_agent_may_compose():
    """The shell must cover the whole catalog.

    compose_surface offers the model all 24 types, so a shell that implements
    only some of them would silently degrade a legitimate interface into
    "skipped unknown type" boxes and blame the agent for it.
    """
    html = _trip_html()
    missing = [name for name in COMPONENTS if not re.search(rf"\n  {name}\s*:", html)]
    assert not missing, f"/trip cannot draw: {missing}"


def test_trip_shell_never_assigns_innerhtml():
    html = _trip_html()
    assert not re.search(r"innerHTML\s*=", html)
    # The word appears once, in the contract comment that explains the rule.
    assert html.count("innerHTML") == 1
    assert "NEVER assigns innerHTML" in html


def test_trip_shell_evaluates_no_string_and_builds_text_nodes():
    html = _trip_html()
    assert "createTextNode" in html
    for forbidden in ("eval(", "new Function", "document.write", "insertAdjacentHTML", "outerHTML"):
        assert forbidden not in html, f"/trip must not use {forbidden}"


def test_trip_shell_asks_for_a_composed_interface_and_reads_it_back():
    html = _trip_html()
    # It requests a UI answer, then reads the interface the agent composed.
    assert 'respond_as:"ui"' in html
    assert "/v1/agent/runs" in html and "/composed" in html
    # A tap becomes the next turn: the label is fed back into the conversation.
    assert "runTurn(lab)" in html


def test_trip_shell_uses_a_synthetic_identity():
    html = _trip_html()
    assert 'user_id:"traveller-01"' in html
    for real in ("@", "bindroo", "tomtom"):
        assert real not in html.lower(), "the shell must carry no real identity"


def test_route_trip_planner_serves_the_shell(client):
    r = client.get("/trip")
    assert r.status_code == 200
    assert "Waypoint" in r.text
    # It is served whole, with the renderer intact.
    assert "RouteMap:" in r.text


def test_the_capture_script_chains_turns_exactly_like_the_shell():
    """proofs/waypoint_turns.py claims to drive the same loop /trip drives.

    If the two prompts drift the capture stops being evidence about the running
    application, so the shared sentences are compared rather than trusted.
    """
    shell = _trip_html()
    script = (_BUILD_ROOT / "proofs" / "waypoint_turns.py").read_text()
    for sentence in (
        "The user has since tapped, in order: ",
        "Produce the content for that next step of the plan. Go one level deeper than the",
        " previous step rather than repeating it, and include real locations with coordinates",
        " whenever the step involves places.",
        "\\nAlways finish by offering 3 to 5 short, concrete choices the user could tap",
        " to go one level deeper. Keep each choice label under about eight words.",
    ):
        assert sentence in shell, f"/trip lost: {sentence!r}"
        assert sentence in script, f"waypoint_turns.py lost: {sentence!r}"


def test_a_prose_tap_label_does_not_become_a_web_search_fanout():
    """A conversational turn is prose, and prose is full of proper nouns.

    The entity-list heuristic exists for "compare London, Berlin and Paris". A
    tapped choice label like "Kanto (Tokyo, Hakone, Nikko): explore ..." trips
    it on proper nouns alone, and the resulting three-way research fan-out then
    stalls the whole turn on its distill node. A UI turn only fans out when the
    goal also asks for a lookup.
    """
    from s13code.runtime import _work_intent

    tap = ("Plan a 5-day trip to Japan.\nThe user has since tapped, in order: "
           "Kanto (Tokyo, Hakone, Nikko): Explore the vibrant metropolis of Tokyo, "
           "historical sites like Nikko, and the natural beauty of Hakone.")
    mode, frontier = _work_intent(tap, respond_as="ui")
    assert mode == "compose_answer"
    assert [t.skill for t in frontier] == ["content"]


def test_a_ui_goal_that_really_asks_for_a_lookup_still_fans_out():
    """The guard must not disable the multi-entity research path it narrows."""
    from s13code.runtime import _work_intent

    mode, frontier = _work_intent(
        "Compare London, Berlin and Paris, then compose a dashboard.", respond_as="ui")
    assert mode == "compose_research"
    assert [t.skill for t in frontier] == ["researcher"] * 3


def test_the_adversarial_payloads_are_each_refused_by_their_own_invariant():
    """The security property the /trip demo rests on, proven without a model.

    proofs/waypoint_adversarial.py sends these three payloads at a live gateway.
    The refusal itself is deterministic, so it is pinned here: a hostile prompt
    that gets all three into a surface still cannot reach the DOM, and the safe
    interface around them survives intact.
    """
    from proofs.waypoint_adversarial import PAYLOADS

    safe = [
        {"id": "root", "type": "Column", "children": ["h", "map"]},
        {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        _GOOD_MAP,
    ]
    result = validate_surface({
        "root": "root", "dataModel": {"title": "Lisbon", "places": []},
        "components": safe + [comp for _, comp in PAYLOADS],
    })
    by_id = {r.component_id: r for r in result.rejections}
    for expected_invariant, comp in PAYLOADS:
        rejection = by_id.get(comp["id"])
        assert rejection is not None, f"{comp['id']} was not refused"
        assert rejection.invariant == expected_invariant, comp["id"]
    # Every safe component still renders — one poisoned node cannot blank a screen.
    assert {c["id"] for c in result.accepted} == {"root", "h", "map"}


def test_compose_step_never_names_the_contributed_component():
    """The proof that the agent chose RouteMap on its own.

    ``compose_surface`` hands the model the catalog manifest and the list of
    available pointers, and nothing else. If the runtime mentioned the component
    by name the composition would be instruction-following, not selection.
    """
    runtime_src = (_BUILD_ROOT / "s13code" / "runtime.py").read_text()
    assert "RouteMap" not in runtime_src


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
