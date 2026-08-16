"""Hermetic test suite for the Generative UI Health App (/app/health).

Tests API routes, component catalog validation, surface generation,
and Human-In-The-Loop action decisions for the wellbeing coach.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.catalog import catalog_manifest
from s13code.ui.hitl import PendingAction, decide_resume
from s13code.ui.routes import router as ui_router
from s13code.ui.validator import validate_surface


@pytest.fixture
def api_client():
    app = FastAPI()
    app.include_router(ui_router)
    return TestClient(app)


def test_health_app_routes(api_client):
    """Verify /app/health and /health return HTTP 200 with HTML shell."""
    for path in ["/app/health", "/app/health/", "/health", "/health/"]:
        res = api_client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Vitality" in res.text
        assert "1% Health Coach" in res.text


def test_health_surface_validation():
    """Verify that a complex health dashboard surface validates cleanly."""
    health_surface = {
        "root": "col_root",
        "components": [
            {
                "id": "col_root",
                "type": "Column",
                "children": ["title_text", "row_tiles", "chart_activity", "card_approval"]
            },
            {
                "id": "title_text",
                "type": "Text",
                "text": {"$bind": "/title"},
                "variant": "heading"
            },
            {
                "id": "row_tiles",
                "type": "Row",
                "children": ["tile_food", "tile_mind"]
            },
            {
                "id": "tile_food",
                "type": "StatTile",
                "label": "Food Score",
                "value": {"$bind": "/food_score"},
                "unit": "/10",
                "tone": "good"
            },
            {
                "id": "tile_mind",
                "type": "StatTile",
                "label": "Mental Wellbeing",
                "value": {"$bind": "/mind_score"},
                "unit": "/10",
                "tone": "good"
            },
            {
                "id": "chart_activity",
                "type": "BarChart",
                "title": "Weekly Steps",
                "data": {"$bind": "/steps"},
                "xKey": "day",
                "yKey": "count"
            },
            {
                "id": "card_approval",
                "type": "ApprovalCard",
                "summary": {"$bind": "/tweak_summary"},
                "confirm": {"action": "approve", "args": {"target": "commit_tweak"}},
                "reject": {"action": "reject", "args": {"target": "commit_tweak"}}
            }
        ],
        "dataModel": {
            "title": "Daily Health Review",
            "food_score": "8",
            "mind_score": "7",
            "steps": [
                {"day": "Mon", "count": 8000},
                {"day": "Tue", "count": 10500},
                {"day": "Wed", "count": 9200}
            ],
            "tweak_summary": "Commit to drinking 1 extra glass of water tomorrow morning."
        }
    }

    result = validate_surface(health_surface)
    assert result.ok, f"Expected clean validation, got rejections: {[r.as_dict() for r in result.rejections]}"
    assert len(result.accepted) == 7
    assert len(result.rejections) == 0


def test_health_hitl_action_decision():
    """Verify that health action decisions (approve / reject) execute safely."""
    pending = PendingAction(
        run_id="run-health-101",
        node_id="card_approval",
        summary="Commit to 1% tweak",
        params={"target": "commit_tweak"}
    )

    # Approve action matching pending params
    decision_approve = decide_resume(pending, "approve", {"target": "commit_tweak"})
    assert decision_approve.allowed is True
    assert "approved" in decision_approve.reason.lower()

    # Reject action matching pending params
    decision_reject = decide_resume(pending, "reject", {"target": "commit_tweak"})
    assert decision_reject.allowed is True
    assert "rejected" in decision_reject.reason.lower()

    # Unregistered action attempt must be refused
    decision_invalid = decide_resume(pending, "unregistered_action", {})
    assert decision_invalid.allowed is False


def test_catalog_manifest_includes_all_health_components():
    """Verify catalog manifest includes custom types used in health dashboards."""
    manifest = catalog_manifest()
    components = manifest["components"]
    for expected in ["StatTile", "BarChart", "Sparkline", "DataTable", "ProgressBar", "CodeDiff", "ApprovalCard"]:
        assert expected in components
    assert "approve" in manifest["actions"]
    assert "reject" in manifest["actions"]
