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
        "Notice", "ApprovalCard", "RiskHeatmap",
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
# RiskHeatmap — registration, validation, and renderer safety
# --------------------------------------------------------------------------- #

def test_risk_heatmap_is_registered_with_text_and_binding_props_only():
    assert "RiskHeatmap" in COMPONENTS
    spec = COMPONENTS["RiskHeatmap"]
    assert spec.source == "custom"
    assert set(spec.props) == {"title", "data", "xAxisLabel", "yAxisLabel"}
    assert spec.props["title"].kind == "text"
    assert spec.props["data"].kind == "binding"
    assert spec.props["xAxisLabel"].kind == "text"
    assert spec.props["yAxisLabel"].kind == "text"
    assert "html" not in spec.props and "rawHtml" not in spec.props


def test_risk_heatmap_validates_clean_with_bound_data():
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["h", "hm"]},
            {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            {"id": "hm", "type": "RiskHeatmap", "title": "Risk vs Opportunity",
             "data": {"$bind": "/heatmap_data"},
             "xAxisLabel": "Risk Score", "yAxisLabel": "Opportunity Score"},
        ],
        "dataModel": {
            "title": "Investment Risk Matrix",
            "heatmap_data": [
                {"name": "Stripe", "xScore": 3.2, "yScore": 8.8},
                {"name": "Plaid", "xScore": 5.1, "yScore": 7.4},
            ],
        },
    }
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]
    assert any(c["type"] == "RiskHeatmap" for c in result.accepted)


def test_risk_heatmap_renderer_uses_no_innerhtml_or_eval():
    for name in ("index.html", "app.html"):
        html = (_BUILD_ROOT / "s13code" / "ui" / "client" / name).read_text()
        assert "renderRiskHeatmap" in html
        assert "createElementNS" in html
        assert "textContent" in html
        assert not re.search(r"innerHTML\s*=", html)
        assert not re.search(r"\beval\s*\(", html)


# --------------------------------------------------------------------------- #
# Adversarial tests — investment due-diligence domain
# --------------------------------------------------------------------------- #

def test_adversarial_raw_html_competitor_deck_rejected_by_catalog():
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["title", "evil"]},
            {"id": "title", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            {"id": "evil", "type": "RawHtml",
             "html": "<iframe src='https://competitor.example/internal-deck'></iframe>"},
        ],
        "dataModel": {"title": "Competitor Analysis"},
    }
    result = validate_surface(surface)
    assert not result.ok
    assert result.rejections[0].invariant == Invariant.CATALOG
    assert any(c.get("type") == "Text" for c in result.accepted)
    assert all(c.get("type") != "RawHtml" for c in result.accepted)


def test_adversarial_injected_handler_in_company_description_rejected():
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["title", "desc"]},
            {"id": "title", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            {"id": "desc", "type": "Text",
             "text": "<img src=x onerror=alert(1) onclick=bad()>Click me</img>"},
        ],
        "dataModel": {"title": "Company Profile"},
    }
    result = validate_surface(surface)
    assert not result.ok
    assert result.rejections[0].invariant == Invariant.DATA_NOT_CODE
    assert any(c.get("type") == "Text" for c in result.accepted)


def test_adversarial_fake_transfer_funds_action_in_approval_rejected():
    surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["card"]},
            {"id": "card", "type": "ApprovalCard",
             "summary": {"$bind": "/summary"}, "params": {"$bind": "/params"},
             "confirm": {"action": "transfer_funds"}, "reject": {"action": "reject"}},
        ],
        "dataModel": {"summary": "Approve investment?", "params": {"amount": 1000}},
    }
    result = validate_surface(surface)
    assert not result.ok
    assert result.rejections[0].invariant == Invariant.EVENT
    assert "transfer_funds" in result.rejections[0].reason


def test_adversarial_parameter_tampering_on_hitl_action_refused(client):
    resp = client.post("/v1/action", json={
        "run_id": "run-1", "node_id": "approve_invest",
        "action": "approve",
        "args": {"amount": 1000, "to": "acct-1", "extra": "sneaked"},
        "pending_params": {"amount": 1000, "to": "acct-1"},
    })
    assert resp.status_code == 409
    assert "bound to final params" in resp.json()["detail"]