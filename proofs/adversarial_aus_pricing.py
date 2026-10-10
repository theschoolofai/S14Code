"""Adversarial security proof for Australian Insurance Pricing application.

Tests engineered hostile prompts attempting to inject raw HTML (<script>, <iframe>),
DOM event handlers (onclick=, onerror=), and unregistered actions into the surface.
Asserts that validator.py identifies and rejects bad nodes while rendering safe components.
"""

from __future__ import annotations

import json
from s13code.ui.catalog import COMPONENTS
from s13code.ui.validator import Invariant, validate_surface


def test_adversarial_markup_injection_refused():
    """Hostile prompt attempting script injection in property valuation field."""
    poisoned_surface = {
        "root": "col1",
        "components": [
            {"id": "col1", "type": "Column", "children": ["title1", "card1"]},
            {"id": "title1", "type": "Text", "variant": "heading", "text": "Australian Insurance Valuation"},
            {
                "id": "card1",
                "type": "Notice",
                "text": "<script>alert('Exfiltrating APRA Reserve Data');</script>",
                "tone": "bad",
            },
        ],
        "dataModel": {},
    }
    result = validate_surface(poisoned_surface)
    assert not result.ok
    assert len(result.rejections) == 1
    assert result.rejections[0].invariant == Invariant.DATA_NOT_CODE
    assert result.rejections[0].field == "text"
    # Safe component still passes
    assert len(result.accepted) == 2
    assert {c["id"] for c in result.accepted} == {"col1", "title1"}


def test_adversarial_unregistered_action_refused():
    """Hostile prompt attempting to trigger unregistered server action."""
    poisoned_surface = {
        "root": "btn1",
        "components": [
            {
                "id": "btn1",
                "type": "Button",
                "label": "Override Premium Rates",
                "onPress": {"action": "unregistered_override_admin"},
            }
        ],
    }
    result = validate_surface(poisoned_surface)
    assert not result.ok
    assert len(result.rejections) == 1
    assert result.rejections[0].invariant == Invariant.EVENT
    assert result.rejections[0].field == "onPress"


def test_adversarial_unknown_type_refused():
    """Hostile prompt attempting to inject raw HTML frame node."""
    poisoned_surface = {
        "root": "bad1",
        "components": [
            {
                "id": "bad1",
                "type": "RawHtmlFrame",
                "html": "<iframe src='http://attacker.com'></iframe>",
            }
        ],
    }
    result = validate_surface(poisoned_surface)
    assert not result.ok
    assert len(result.rejections) == 1
    assert result.rejections[0].invariant == Invariant.CATALOG


if __name__ == "__main__":
    test_adversarial_markup_injection_refused()
    test_adversarial_unregistered_action_refused()
    test_adversarial_unknown_type_refused()
    print("All Australian Insurance Pricing adversarial security tests passed!")
