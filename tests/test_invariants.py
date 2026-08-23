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


def test_radarchart_and_heatmap_pass_validation():
    surface = {
        "root": "r",
        "components": [
            {
                "id": "r",
                "type": "Column",
                "children": ["radar", "heatmap"],
            },
            {
                "id": "radar",
                "type": "RadarChart",
                "title": "Actuator Performance Radar",
                "axes": {"$bind": "/axes"},
                "series": {"$bind": "/series"},
            },
            {
                "id": "heatmap",
                "type": "Heatmap",
                "title": "Joint Requirement Heatmap",
                "xLabels": {"$bind": "/x"},
                "yLabels": {"$bind": "/y"},
                "data": {"$bind": "/grid"},
                "caption": "Joint torque demand",
            },
        ],
        "dataModel": {
            "/axes": ["Torque Density", "Backdrivability", "Thermal", "Bandwidth", "Cost"],
            "/series": [{"name": "T-Motor AK10-9", "values": [90, 85, 80, 90, 75]}],
            "/x": ["Hip", "Knee", "Ankle"],
            "/y": ["Torque (Nm)", "Velocity (RPM)"],
            "/grid": [[150, 180, 90], [120, 200, 150]],
        },
    }
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]
    assert len(result.accepted) == 3


def test_rating_and_stepwizard_pass_validation():
    surface = {
        "root": "r",
        "components": [
            {
                "id": "r",
                "type": "Column",
                "children": ["wizard", "rating"],
            },
            {
                "id": "wizard",
                "type": "StepWizard",
                "title": "Resume Builder Progress",
                "steps": {"$bind": "/steps"},
                "currentStep": 2,
                "onStepPress": {"action": "approve"},
            },
            {
                "id": "rating",
                "type": "Rating",
                "label": "Python Mastery",
                "value": 5,
                "max": 5,
                "tone": "good",
            },
        ],
        "dataModel": {
            "/steps": ["1. Profile", "2. Experience", "3. Skills", "4. Export"],
        },
    }
    result = validate_surface(surface)
    assert result.ok, [r.as_dict() for r in result.rejections]
    assert len(result.accepted) == 3


