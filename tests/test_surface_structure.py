"""Is the surface a coherent tree — a separate question from whether it is safe.

`validate_surface` enforces the three invariants: known types, no markup or
handlers, no unregistered actions. It said nothing about whether the components
form a tree, and its own source carried the comment "children are refs;
validated by tree walk elsewhere" for a walk that did not exist anywhere.

That gap is not theoretical. A real model returned eleven components, every type
known and every binding sound — `clean: True`, zero rejections — and declared a
root id it never emitted. The renderer threw and the screen went blank on a
surface the wall had just called safe.

Structure is reported separately rather than as a fourth invariant. A missing
root is not an attack, and folding it into the security signal would make
"clean" mean two different things — a surface could then be refused as unsafe
for a mistake nobody made on purpose.
"""
from __future__ import annotations

from s13code.ui.validator import validate_surface

SAFE = {"id": "t", "type": "Text", "text": {"$bind": "/x"}}


def surface(root: str, components: list[dict]) -> dict:
    return {"root": root, "components": components, "dataModel": {"x": "hi"}}


# --------------------------------------------------------------------------- #
# the structural report
# --------------------------------------------------------------------------- #

def test_a_coherent_surface_reports_no_structural_problem() -> None:
    result = validate_surface(surface("c", [{"id": "c", "type": "Column", "children": ["t"]}, SAFE]))

    assert result.structure == []
    assert result.coherent is True


def test_a_declared_root_that_was_never_emitted_is_reported() -> None:
    """The exact failure a real model produced."""
    result = validate_surface(surface("root", [SAFE]))

    assert result.coherent is False
    assert any("root" in problem for problem in result.structure)


def test_a_child_reference_that_resolves_to_nothing_is_reported() -> None:
    result = validate_surface(surface("c", [{"id": "c", "type": "Column", "children": ["gone"]}]))

    assert result.coherent is False
    assert any("gone" in problem for problem in result.structure)


def test_a_child_dropped_by_the_wall_is_reported_as_dangling() -> None:
    """A component rejected for an invariant leaves a hole in its parent. The
    surface was coherent as sent and is not coherent as accepted, and the caller
    needs to know which it is holding."""
    hostile = {"id": "bad", "type": "Text", "onclick": "steal()"}
    result = validate_surface(surface("c", [{"id": "c", "type": "Column", "children": ["bad"]}, hostile]))

    assert result.rejections          # the wall did its job
    assert result.coherent is False   # and the tree has a hole where it acted


def test_structure_is_not_a_fourth_invariant() -> None:
    """Structural problems must not show up as rejections: `clean` means safe,
    and a surface that is merely incoherent has not attacked anything."""
    result = validate_surface(surface("root", [SAFE]))

    assert result.rejections == []
    assert result.ok is True
    assert result.coherent is False


def test_an_empty_surface_is_incoherent_rather_than_silently_fine() -> None:
    result = validate_surface({"root": "root", "components": []})

    assert result.coherent is False


# --------------------------------------------------------------------------- #
# an explicitly-null optional property is absent, not an attack
# --------------------------------------------------------------------------- #

def test_a_null_optional_property_does_not_cost_the_whole_component() -> None:
    """A real model wrote `"tone": null` on four StatTiles, meaning "no tone".
    The enum check compared None against the allowed values and dropped every
    one of them — four good components lost, and the Row that held them left
    with four dangling children. None is not markup, not a handler and not an
    unregistered action; it breaks no invariant. It means the prop was not set."""
    result = validate_surface(surface("t", [
        {"id": "t", "type": "StatTile", "label": "CPU", "value": {"$bind": "/x"}, "tone": None},
    ]))

    assert result.rejections == []
    assert result.accepted[0]["id"] == "t"


def test_a_null_property_is_stripped_rather_than_passed_on() -> None:
    """Downstream is a renderer that will do `c.tone || default`. Leaving an
    explicit null in place works by luck in JavaScript and not at all in Python."""
    result = validate_surface(surface("t", [
        {"id": "t", "type": "StatTile", "label": "CPU", "value": {"$bind": "/x"}, "tone": None},
    ]))

    assert "tone" not in result.accepted[0]


def test_a_genuinely_wrong_enum_value_is_still_refused() -> None:
    """Treating null as absent must not become treating anything as absent."""
    result = validate_surface(surface("t", [
        {"id": "t", "type": "StatTile", "label": "CPU", "value": {"$bind": "/x"}, "tone": "chartreuse"},
    ]))

    assert result.rejections


# --------------------------------------------------------------------------- #
# a binding that cannot resolve is reported, not silently drawn blank
# --------------------------------------------------------------------------- #

def test_a_pointer_that_resolves_to_nothing_is_reported() -> None:
    """Well-formed and pointing at nothing: it draws an empty widget that looks
    like missing data rather than like a broken binding. (Bracket notation is a
    different case — the wall refuses it as an expression, and compose repairs
    the spelling before the wall ever sees it.)"""
    result = validate_surface({
        "root": "t",
        "components": [{"id": "t", "type": "Text", "text": {"$bind": "/metrics/0/alarm"}}],
        "dataModel": {"metrics": []},
    })

    assert result.coherent is False
    assert any("metrics/0/alarm" in problem for problem in result.structure)


def test_a_pointer_that_does_resolve_is_not_reported() -> None:
    result = validate_surface({
        "root": "t",
        "components": [{"id": "t", "type": "Text", "text": {"$bind": "/a/b"}}],
        "dataModel": {"a": {"b": "here"}},
    })

    assert result.structure == []


def test_bindings_are_not_checked_when_no_data_model_was_given() -> None:
    """Callers validate bare component trees in places (the /v1/validate route,
    the adversarial tests). Reporting every binding as unresolvable there would
    be noise, not a finding."""
    result = validate_surface({"root": "t", "components": [
        {"id": "t", "type": "Text", "text": {"$bind": "/anything"}}]})

    assert result.structure == []


# --------------------------------------------------------------------------- #
# a binding is a pointer, not a little expression language
# --------------------------------------------------------------------------- #

def test_a_binding_carrying_a_filter_expression_is_refused() -> None:
    """A real model bound `/readings[0].value|toFixed(1)`. Nothing evaluates it,
    so nothing executed — but it is an attempt to get computation to happen
    inside a value, and the pointer rule was loose enough to wave it through.
    Data-not-code is the invariant that says a value is read, never run."""
    result = validate_surface({
        "root": "t",
        "components": [{"id": "t", "type": "Text", "text": {"$bind": "/a|toFixed(1)"}}],
    })

    assert result.rejections
    assert result.rejections[0].invariant == "data-not-code"


def test_pointers_with_call_syntax_are_refused() -> None:
    for pointer in ("/a(1)", "/a${b}", "/a`b`", "/a+b", "/a?b:c"):
        result = validate_surface({
            "root": "t",
            "components": [{"id": "t", "type": "Text", "text": {"$bind": pointer}}],
        })

        assert result.rejections, pointer


def test_ordinary_pointers_still_pass() -> None:
    """Including the ones the repair step produces, and escaped tokens."""
    for pointer in ("/gauges", "/gauges/0/label", "/a~1b", "/metric_0_value", ""):
        result = validate_surface({
            "root": "t",
            "components": [{"id": "t", "type": "Text", "text": {"$bind": pointer or "/x"}}],
        })

        assert result.rejections == [], pointer
