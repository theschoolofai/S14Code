"""UI-Only Interactive IIT-JEE & Tech Learning Tutor Application.

This application answers EVERY turn purely as a catalog-validated A2UI component tree.
It never outputs raw markdown or text blocks. Every interactive button tap emits a named,
validated action event that earns the next turn across 3+ interactive turns.
"""

from __future__ import annotations

from typing import Any, Dict
from s13code.ui.validator import validate_surface, ValidationResult


def build_tutor_surface_turn1(user_prompt: str) -> Dict[str, Any]:
    """Turn 1: Overview Dashboard with Subject StatTiles, Kanban Roadmap & Subject Selection Buttons."""
    surface = {
        "root": "c0",
        "components": [
            {
                "id": "c0",
                "type": "Column",
                "children": ["h1", "sub1", "tiles_row", "kanban_card", "subject_row"],
            },
            {
                "id": "h1",
                "type": "Text",
                "variant": "heading",
                "text": {"$bind": "/h1_text"},
            },
            {
                "id": "sub1",
                "type": "Text",
                "variant": "subtitle",
                "text": {"$bind": "/subtitle"},
            },
            {
                "id": "tiles_row",
                "type": "Row",
                "align": "center",
                "justify": "spaceBetween",
                "children": ["tile_phy", "tile_chem", "tile_math"],
            },
            {
                "id": "tile_phy",
                "type": "StatTile",
                "label": "Physics Mastery",
                "value": {"$bind": "/stats/physics"},
                "unit": "%",
                "delta": {"$bind": "/deltas/phy"},
                "tone": "good",
            },
            {
                "id": "tile_chem",
                "type": "StatTile",
                "label": "Chemistry Mastery",
                "value": {"$bind": "/stats/chemistry"},
                "unit": "%",
                "delta": {"$bind": "/deltas/chem"},
                "tone": "neutral",
            },
            {
                "id": "tile_math",
                "type": "StatTile",
                "label": "Mathematics Mastery",
                "value": {"$bind": "/stats/math"},
                "unit": "%",
                "delta": {"$bind": "/deltas/math"},
                "tone": "good",
            },
            {
                "id": "kanban_card",
                "type": "KanbanBoard",
                "title": "Preparation Roadmap & Tasks",
                "columns": "Todo,In Progress,Mastered",
                "cards": {"$bind": "/roadmap_cards"},
                "onSelect": {"action": "select_card"},
            },
            {
                "id": "subject_row",
                "type": "Card",
                "title": "Select a Subject to Begin Today's Lesson & Quiz",
                "children": ["btn_phy", "btn_chem", "btn_math"],
            },
            {
                "id": "btn_phy",
                "type": "Button",
                "label": "Start Physics (Mechanics)",
                "onPress": {"action": "rerun"},
            },
            {
                "id": "btn_chem",
                "type": "Button",
                "label": "Start Chemistry (Organic)",
                "onPress": {"action": "rerun"},
            },
            {
                "id": "btn_math",
                "type": "Button",
                "label": "Start Mathematics (Calculus)",
                "onPress": {"action": "rerun"},
            },
        ],
        "dataModel": {
            "h1_text": "IIT-JEE Interactive Learning Portal",
            "subtitle": f"Customized study plan generated for: '{user_prompt}'",
            "stats": {"physics": "88", "chemistry": "76", "math": "92"},
            "deltas": {"phy": "Target: 95%", "chem": "Target: 90%", "math": "Target: 98%"},
            "roadmap_cards": [
                {"id": "k1", "title": "Rotational Dynamics", "status": "In Progress", "tag": "Physics", "description": "Torque and Angular Momentum"},
                {"id": "k2", "title": "Chemical Bonding", "status": "Todo", "tag": "Chemistry", "description": "VSEPR & Hybridization"},
                {"id": "k3", "title": "Definite Integration", "status": "Mastered", "tag": "Math", "description": "Properties & Limits"},
            ],
        },
    }
    return surface


def build_tutor_surface_turn2(subject: str = "Physics") -> Dict[str, Any]:
    """Turn 2: Detailed Topic Table & Interactive Quiz Card."""
    surface = {
        "root": "c0",
        "components": [
            {
                "id": "c0",
                "type": "Column",
                "children": ["h1", "table_card", "quiz_card"],
            },
            {
                "id": "h1",
                "type": "Text",
                "variant": "heading",
                "text": {"$bind": "/h1_text"},
            },
            {
                "id": "table_card",
                "type": "Card",
                "title": "Topic Syllabus & Weightage",
                "children": ["topic_table"],
            },
            {
                "id": "topic_table",
                "type": "DataTable",
                "columns": "Topic, Weightage, Difficulty, Status",
                "rows": {"$bind": "/topics"},
                "sortable": True,
                "filterKey": "Topic",
            },
            {
                "id": "quiz_card",
                "type": "Card",
                "title": "Interactive Quiz: Rotational Motion (Kinematics)",
                "children": ["q_text", "opt_a", "opt_b", "opt_c"],
            },
            {
                "id": "q_text",
                "type": "Text",
                "variant": "body",
                "text": {"$bind": "/question_text"},
            },
            {
                "id": "opt_a",
                "type": "Button",
                "label": "Option A: π/2",
                "onPress": {"action": "approve"},
            },
            {
                "id": "opt_b",
                "type": "Button",
                "label": "Option B: π (Correct)",
                "onPress": {"action": "approve"},
            },
            {
                "id": "opt_c",
                "type": "Button",
                "label": "Option C: 2/π",
                "onPress": {"action": "approve"},
            },
        ],
        "dataModel": {
            "h1_text": f"{subject}: Lesson Breakdown & Topics",
            "topics": [
                {"Topic": "Kinematics & Circular Motion", "Weightage": "12%", "Difficulty": "Medium", "Status": "Active"},
                {"Topic": "Work, Energy & Power", "Weightage": "10%", "Difficulty": "Easy", "Status": "Completed"},
                {"Topic": "Rigid Body Dynamics", "Weightage": "15%", "Difficulty": "Hard", "Status": "Pending"},
            ],
            "question_text": "A particle moves along a semicircle of radius R. What is the ratio of distance traveled to displacement?",
        },
    }
    return surface


def build_tutor_surface_turn3(user_answer: str = "Option B: π") -> Dict[str, Any]:
    """Turn 3: Performance Score BarChart, Recommended Revision Timeline & Approval Card."""
    surface = {
        "root": "c0",
        "components": [
            {
                "id": "c0",
                "type": "Column",
                "children": ["h1", "score_tile", "chart_card", "timeline_card", "approval_node"],
            },
            {
                "id": "h1",
                "type": "Text",
                "variant": "heading",
                "text": {"$bind": "/h1_text"},
            },
            {
                "id": "score_tile",
                "type": "StatTile",
                "label": "Quiz Performance",
                "value": {"$bind": "/score"},
                "unit": " Marks",
                "delta": {"$bind": "/delta_text"},
                "tone": "good",
            },
            {
                "id": "chart_card",
                "type": "BarChart",
                "title": "Topic Accuracy Breakdown across Physics Modules",
                "data": {"$bind": "/module_scores"},
                "xKey": "module",
                "yKey": "score",
            },
            {
                "id": "timeline_card",
                "type": "Timeline",
                "title": "Recommended Revision Step Sequence",
                "events": {"$bind": "/revision_steps"},
            },
            {
                "id": "approval_node",
                "type": "ApprovalCard",
                "summary": {"$bind": "/approval_summary"},
                "params": {"$bind": "/approval_params"},
                "confirm": {"action": "approve"},
                "reject": {"action": "reject"},
            },
        ],
        "dataModel": {
            "h1_text": "Assessment Summary & Action Plan",
            "score": "100",
            "delta_text": f"Submitted: {user_answer} — Correct!",
            "module_scores": [
                {"module": "Kinematics", "score": "95"},
                {"module": "Dynamics", "score": "88"},
                {"module": "Rotation", "score": "92"},
                {"module": "Fluids", "score": "78"},
            ],
            "revision_steps": [
                {"seq": 1, "kind": "Review", "node": "Rotational Inertia Formulas"},
                {"seq": 2, "kind": "Practice", "node": "JEE Advanced 2024 PYQs"},
                {"seq": 3, "kind": "Mock", "node": "Full-length Mechanics Test"},
            ],
            "approval_summary": "Schedule Intensive Mock Test for Rotational Motion on Sunday at 10:00 AM?",
            "approval_params": {"test_name": "JEE_Advanced_Mechanics_Mock", "duration": "180 mins", "total_questions": 30},
        },
    }
    return surface


def get_tutor_turn(turn_number: int, user_input: str = "") -> Dict[str, Any]:
    """Return catalog-validated surface for requested turn."""
    if turn_number == 1:
        raw_surface = build_tutor_surface_turn1(user_input or "IIT JEE Preparation")
    elif turn_number == 2:
        raw_surface = build_tutor_surface_turn2(user_input or "Physics")
    else:
        raw_surface = build_tutor_surface_turn3(user_input or "Option B")

    validation: ValidationResult = validate_surface(raw_surface)
    return {
        "turn": turn_number,
        "respond_as": "ui",
        "valid": validation.ok,
        "surface": raw_surface,
        "validation_result": {
            "accepted_count": len(validation.accepted),
            "rejections": [r.as_dict() for r in validation.rejections],
        },
    }
