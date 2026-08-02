"""Bounded readings in the generic data model, and the prompt that never names them.

A catalog entry alone does not make a component composable. `compose_surface`
builds a domain-neutral data model and offers the catalog beside it; if nothing
in that model is a bounded reading, a model can name `GaugeCluster` but has
nothing to bind it to, and would have to invent a scale to use it. So the model
gains a `/gauges` pointer for readings that carry a scale.

What the compose instruction must NOT do is say the word. The whole claim being
tested by the captured run is that the model reaches for the component on its
own, having seen it in the catalog and seen data shaped like its binding. An
instruction that says "for /gauges render a GaugeCluster" proves nothing at all.
"""
from __future__ import annotations

from s13code.runtime import compose_instruction, compose_system_prompt, merge_gauges


def test_readings_with_a_scale_become_bindable_gauges() -> None:
    model: dict = {}

    merge_gauges(model, {"gauges": [
        {"label": "CPU", "value": 72, "min": 0, "max": 100, "unit": "%"},
        {"label": "Disk", "value": 3.1, "min": 0, "max": 4, "unit": "TB"},
    ]})

    assert [g["label"] for g in model["gauges"]] == ["CPU", "Disk"]
    assert model["gauges"][0]["max"] == 100


def test_a_reading_with_no_scale_is_not_turned_into_a_gauge() -> None:
    """A gauge without bounds has to invent an axis to draw itself on, and an
    invented axis is a number the interface made up."""
    model: dict = {}

    merge_gauges(model, {"gauges": [{"label": "Errors", "value": 12}]})

    assert "gauges" not in model


def test_thresholds_and_the_failing_end_survive_into_the_model() -> None:
    """Severity comes from the limit that raises the real fault, and `invert`
    says which end that is. Dropping either leaves the renderer guessing from
    fraction-of-range, which is wrong for anything that fails low."""
    model: dict = {}

    merge_gauges(model, {"gauges": [
        {"label": "Charge", "value": 8, "min": 0, "max": 100, "unit": "%",
         "warn": 30, "alarm": 15, "invert": True},
    ]})

    gauge = model["gauges"][0]
    assert (gauge["warn"], gauge["alarm"], gauge["invert"]) == (30, 15, True)


def test_a_non_numeric_reading_is_dropped_rather_than_coerced() -> None:
    model: dict = {}

    merge_gauges(model, {"gauges": [
        {"label": "Status", "value": "green", "min": 0, "max": 1},
        {"label": "Load", "value": "0.6", "min": 0, "max": 1},
    ]})

    assert [g["label"] for g in model["gauges"]] == ["Load"]
    assert model["gauges"][0]["value"] == 0.6


def test_metrics_that_carry_a_scale_are_offered_as_gauges_too() -> None:
    """A metric with bounds already IS a bounded reading. Requiring a separate
    key would mean the same number is only gauge-able when it is described twice."""
    model: dict = {}

    merge_gauges(model, {"metrics": [
        {"label": "Memory", "value": 14, "min": 0, "max": 16, "unit": "GB"},
        {"label": "Requests", "value": 4021},
    ]})

    assert [g["label"] for g in model["gauges"]] == ["Memory"]


def test_nothing_bounded_means_no_pointer_at_all() -> None:
    """An empty pointer would invite a component bound to nothing."""
    model: dict = {}

    merge_gauges(model, {"metrics": [{"label": "Requests", "value": 4021}]})

    assert "gauges" not in model


# --------------------------------------------------------------------------- #
# the prompt offers the data and the catalog, and names no component for it
# --------------------------------------------------------------------------- #

def test_the_instruction_never_names_the_component_it_hopes_for() -> None:
    """The 20-point claim is that the model chooses it unprompted. If the prompt
    says the word, the captured run measures nothing but obedience."""
    instruction = compose_instruction("show me the rig", {"components": {}},
                                      {"title": "t", "gauges": [{"label": "CPU"}]})

    assert "GaugeCluster" not in str(instruction)
    assert "GaugeCluster" not in compose_system_prompt()


def test_the_instruction_still_points_at_the_data(  ) -> None:
    """Not naming the component is not the same as hiding the data. The pointer
    has to be listed, or the model is being asked to guess."""
    instruction = compose_instruction("show me the rig", {"components": {}},
                                      {"title": "t", "gauges": [{"label": "CPU"}]})

    assert "/gauges" in instruction["available_pointers"]


def test_the_catalog_carried_in_the_instruction_is_the_real_one() -> None:
    """The model learns the component exists from the catalog, which is the same
    object the validator enforces — so it cannot learn about a type that would
    then be rejected."""
    from s13code.ui.catalog import catalog_manifest

    instruction = compose_instruction("g", catalog_manifest(), {"title": "t"})

    assert "GaugeCluster" in instruction["catalog"]["components"]


# --------------------------------------------------------------------------- #
# repairing a surface once, upstream, rather than in every renderer
# --------------------------------------------------------------------------- #

from s13code.runtime import repair_surface


def test_a_missing_root_is_repaired_into_a_container() -> None:
    """Patching this in the render clients fixes it for browsers only. Every
    other consumer — the A2A parts reply, /composed, anything reading a stored
    run — still gets the broken tree. So it is repaired where the surface is
    produced, once."""
    components = [{"id": "a", "type": "Text", "text": {"$bind": "/x"}},
                  {"id": "b", "type": "Text", "text": {"$bind": "/y"}}]

    root, repaired = repair_surface("root", components)

    container = next(c for c in repaired if c["id"] == root)
    assert container["type"] == "Column"
    assert container["children"] == ["a", "b"]


def test_a_component_already_claimed_as_a_child_is_not_hoisted() -> None:
    """The synthesised container holds what nothing else holds. Adding a claimed
    child would draw it twice, in two places, at two sizes."""
    components = [{"id": "row", "type": "Row", "children": ["a"]},
                  {"id": "a", "type": "Text", "text": {"$bind": "/x"}}]

    root, repaired = repair_surface("root", components)

    assert next(c for c in repaired if c["id"] == root)["children"] == ["row"]


def test_a_surface_that_already_has_its_root_is_left_alone() -> None:
    """Repair is for the broken case. Rewriting a sound tree would mean the
    interface the model composed is not the interface that ships."""
    components = [{"id": "root", "type": "Column", "children": ["a"]},
                  {"id": "a", "type": "Text", "text": {"$bind": "/x"}}]

    root, repaired = repair_surface("root", components)

    assert root == "root"
    assert repaired == components


def test_the_synthesised_root_never_collides_with_an_existing_id() -> None:
    components = [{"id": "root", "type": "Text", "text": {"$bind": "/x"}}]

    root, repaired = repair_surface("missing", components)

    assert root != "root"
    assert len({c["id"] for c in repaired}) == len(repaired)


def test_the_repaired_surface_passes_the_structural_check() -> None:
    from s13code.ui.validator import validate_surface

    components = [{"id": "a", "type": "Text", "text": {"$bind": "/x"}}]
    root, repaired = repair_surface("root", components)

    result = validate_surface({"root": root, "components": repaired})

    assert result.coherent is True
    assert result.ok is True


def test_nothing_to_repair_when_there_is_nothing_at_all() -> None:
    _, repaired = repair_surface("root", [])

    assert repaired == []


def test_a_reference_to_a_component_the_wall_removed_is_pruned() -> None:
    """The wall drops a poisoned component; whatever named it as a child is left
    pointing at a hole and renders an empty container. A real run hit exactly
    this: four StatTiles dropped, and the Row that held them survived with four
    dead references and nothing to show."""
    components = [{"id": "row", "type": "Row", "children": ["a", "gone", "b"]},
                  {"id": "a", "type": "Text", "text": {"$bind": "/x"}},
                  {"id": "b", "type": "Text", "text": {"$bind": "/y"}}]

    _, repaired = repair_surface("row", components)

    assert next(c for c in repaired if c["id"] == "row")["children"] == ["a", "b"]


def test_a_container_left_with_no_children_at_all_is_dropped() -> None:
    """An empty Row is a blank band across the interface that says nothing about
    why it is there."""
    components = [{"id": "row", "type": "Row", "children": ["gone"]},
                  {"id": "keep", "type": "Text", "text": {"$bind": "/x"}}]

    _, repaired = repair_surface("keep", components)

    assert [c["id"] for c in repaired] == ["keep"]


def test_pruning_does_not_touch_a_sound_tree() -> None:
    components = [{"id": "row", "type": "Row", "children": ["a"]},
                  {"id": "a", "type": "Text", "text": {"$bind": "/x"}}]

    _, repaired = repair_surface("row", components)

    assert repaired == components


# --------------------------------------------------------------------------- #
# pointers a model wrote in JavaScript, repaired only when the fix resolves
# --------------------------------------------------------------------------- #

def test_bracket_notation_is_rewritten_into_a_json_pointer() -> None:
    """Every turn a real model composed wrote `/gauges[0].label`. It passes the
    syntax check, resolves to nothing, and renders as an empty label — the
    interface looks like it has missing data rather than a broken binding."""
    components = [{"id": "g", "type": "Text", "text": {"$bind": "/gauges[0].label"}}]
    data_model = {"gauges": [{"label": "CoreTemp"}]}

    _, repaired = repair_surface("g", components, data_model)

    assert repaired[0]["text"] == {"$bind": "/gauges/0/label"}


def test_dotted_notation_is_rewritten_too() -> None:
    components = [{"id": "g", "type": "Text", "text": {"$bind": "/gauges.0.label"}}]
    data_model = {"gauges": [{"label": "CoreTemp"}]}

    _, repaired = repair_surface("g", components, data_model)

    assert repaired[0]["text"] == {"$bind": "/gauges/0/label"}


def test_a_pointer_is_only_rewritten_when_the_rewrite_actually_resolves() -> None:
    """The repair fixes notation, it does not go looking for a value the model
    might have meant. A pointer at data that is simply not there stays exactly as
    written, so the structural report still names it."""
    components = [{"id": "g", "type": "Text", "text": {"$bind": "/absent[0].label"}}]
    data_model = {"gauges": [{"label": "CoreTemp"}]}

    _, repaired = repair_surface("g", components, data_model)

    assert repaired[0]["text"] == {"$bind": "/absent[0].label"}


def test_a_pointer_that_already_resolves_is_untouched() -> None:
    components = [{"id": "g", "type": "Text", "text": {"$bind": "/a/b"}}]

    _, repaired = repair_surface("g", components, {"a": {"b": 1}})

    assert repaired[0]["text"] == {"$bind": "/a/b"}


def test_pointers_are_left_alone_without_a_data_model() -> None:
    """Nothing to check a rewrite against means no rewrite."""
    components = [{"id": "g", "type": "Text", "text": {"$bind": "/gauges[0].label"}}]

    _, repaired = repair_surface("g", components)

    assert repaired[0]["text"] == {"$bind": "/gauges[0].label"}
