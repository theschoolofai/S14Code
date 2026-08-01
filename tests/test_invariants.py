"""The three invariants, proven against real catalog and fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.agui import stream_agui
from s13code.ui.hitl import PendingAction, decide_resume
from s13code.ui.fixtures import RecordedS13, load_injections
from s13code.ui.surface import build_run_surface
from s13code.ui.validator import Invariant, validate_surface


def test_builder_surface_is_clean():
    run = RecordedS13().get_run("three_cities")
    result = validate_surface(build_run_surface(run))
    assert result.ok, [r.as_dict() for r in result.rejections]


def test_each_injection_is_rejected_by_the_right_invariant():
    for case in load_injections()["cases"]:
        result = validate_surface(case["surface"])
        assert not result.ok, f"{case['name']} was not rejected"
        broke = {r.invariant for r in result.rejections}
        assert case["expect_invariant"] in broke, (case["name"], broke)


def test_safe_part_of_a_poisoned_surface_still_renders():
    case = next(c for c in load_injections()["cases"] if c["name"] == "raw-html-type")
    result = validate_surface(case["surface"])
    # The Text heading survives; only the RawHtml node is dropped.
    assert any(c.get("type") == "Text" for c in result.accepted)
    assert all(c.get("type") != "RawHtml" for c in result.accepted)


def test_catalog_invariant_names_unknown_type():
    surface = {"root": "r", "components": [{"id": "r", "type": "Wormhole"}]}
    result = validate_surface(surface)
    assert result.rejections[0].invariant == Invariant.CATALOG


def test_domain_adversarial_attacks_rejected_and_safe_part_renders():
    """The four due-diligence attacks: each is refused by the right invariant
    and the safe heading still renders."""
    cases = {
        "deck-as-raw-html": Invariant.CATALOG,
        "fetched-description-onerror": Invariant.DATA_NOT_CODE,
        "approval-disguised-transfer": Invariant.EVENT,
        "unregistered-component-type": Invariant.CATALOG,
    }
    by_name = {c["name"]: c for c in load_injections()["cases"]}
    for name, expected in cases.items():
        result = validate_surface(by_name[name]["surface"])
        assert not result.ok, f"{name} was not rejected"
        assert expected in {r.invariant for r in result.rejections}, (name, result.rejections)
        # The safe Text heading survives; only the offending node is dropped.
        assert any(c.get("type") == "Text" for c in result.accepted), name
        assert all(c.get("type") != "RawHtml" and c.get("type") != "WebView" for c in result.accepted), name


def test_event_invariant_blocks_unregistered_action():
    surface = {
        "root": "r",
        "components": [{"id": "r", "type": "Button", "label": "x", "onPress": {"action": "drop_tables"}}],
    }
    result = validate_surface(surface)
    assert result.rejections[0].invariant == Invariant.EVENT


def test_agui_maps_journal_to_events_and_derives_run_finished():
    run = RecordedS13().get_run("three_cities")
    events = list(stream_agui(run["events"], finished=run["finished"]))
    types = [e["type"] for e in events]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert "STEP_STARTED" in types and "STEP_FINISHED" in types


def test_hitl_matching_approve_allowed_widened_refused():
    pending = PendingAction("run", "node", "transfer", {"amount": 100, "to": "acct-1"})
    assert decide_resume(pending, "approve", {"amount": 100, "to": "acct-1"}).allowed
    assert not decide_resume(pending, "approve", {"amount": 9999, "to": "acct-1"}).allowed
    assert decide_resume(pending, "reject", {}).allowed


def test_hitl_is_order_independent_on_params():
    pending = PendingAction("run", "node", "s", {"a": 1, "b": [1, 2]})
    assert decide_resume(pending, "approve", {"b": [1, 2], "a": 1}).allowed
