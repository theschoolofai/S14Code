"""The trusted component catalog.

A surface an agent produces may reference only the component *types* named
here, and each component may carry only the *properties* its schema allows.
The catalog is closed on purpose. There is no ``RawHtml`` type and no
free-form property, because a type or property that does not exist cannot be
named by a hostile agent.

The catalog is aligned to A2UI's Basic component set: the 15 layout / text /
input / container types A2UI Basic already defines are adopted under their real
A2UI names (``source="a2ui-basic"``). Only the components A2UI Basic genuinely
lacks — charts, tiles, tables, timelines, notices, and the approval card — are
kept as clearly labelled custom extensions (``source="custom"``). Twenty-three
types in all; a student can read every one and the validator can prove coverage.

Property kinds:
  - ``text``   a string shown to the user as literal text, never as markup
  - ``binding``a ``/json/pointer`` into the data model (see surface.py)
  - ``enum``   one of a fixed set of strings
  - ``ref``    a list of component ids (children)
  - ``action`` a named action + bound args; the only way a surface acts
  - ``number`` a numeric literal
  - ``bool``   a boolean literal

The catalog also registers the closed set of action names a surface may emit.
Anything outside these sets is rejected by validator.py before render.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PropSpec:
    kind: str  # text | binding | enum | ref | action | number | bool
    values: tuple[str, ...] = ()  # for enum


@dataclass(frozen=True)
class ComponentSpec:
    type: str
    props: dict[str, PropSpec] = field(default_factory=dict)
    source: str = "a2ui-basic"  # "a2ui-basic" | "custom"


_TONE = PropSpec("enum", ("neutral", "good", "warn", "bad"))


# The 23 component types the render client knows how to draw. The first 15 are
# A2UI Basic's own names; the last 8 are custom extensions A2UI Basic lacks.
COMPONENTS: dict[str, ComponentSpec] = {
    # --- A2UI Basic: layout / text / media / inputs / containers (15) --------
    "Row": ComponentSpec("Row", {
        "children": PropSpec("ref"),
        "align": PropSpec("enum", ("start", "center", "end", "stretch", "baseline")),
        "justify": PropSpec("enum", ("start", "center", "end", "spaceBetween", "spaceAround")),
    }, source="a2ui-basic"),
    "Column": ComponentSpec("Column", {"children": PropSpec("ref")}, source="a2ui-basic"),
    "List": ComponentSpec("List", {"children": PropSpec("ref")}, source="a2ui-basic"),
    "Card": ComponentSpec("Card", {"title": PropSpec("text"), "children": PropSpec("ref")}, source="a2ui-basic"),
    "Divider": ComponentSpec("Divider", {}, source="a2ui-basic"),
    "Text": ComponentSpec("Text", {
        "text": PropSpec("binding"),
        "variant": PropSpec("enum", ("heading", "subtitle", "body", "caption")),
    }, source="a2ui-basic"),
    "Image": ComponentSpec("Image", {"src": PropSpec("text"), "alt": PropSpec("text")}, source="a2ui-basic"),
    "TextField": ComponentSpec("TextField", {
        "label": PropSpec("text"), "value": PropSpec("binding"), "placeholder": PropSpec("text"),
    }, source="a2ui-basic"),
    "CheckBox": ComponentSpec("CheckBox", {
        "label": PropSpec("text"), "checked": PropSpec("binding"),
    }, source="a2ui-basic"),
    "Slider": ComponentSpec("Slider", {
        "label": PropSpec("text"), "value": PropSpec("binding"),
        "min": PropSpec("number"), "max": PropSpec("number"),
    }, source="a2ui-basic"),
    "InputChoice": ComponentSpec("InputChoice", {
        "label": PropSpec("text"), "options": PropSpec("binding"), "value": PropSpec("binding"),
    }, source="a2ui-basic"),
    "DateTime": ComponentSpec("DateTime", {
        "label": PropSpec("text"), "value": PropSpec("binding"),
    }, source="a2ui-basic"),
    "Button": ComponentSpec("Button", {
        "label": PropSpec("text"), "onPress": PropSpec("action"),
    }, source="a2ui-basic"),
    "Tabs": ComponentSpec("Tabs", {"labels": PropSpec("text"), "children": PropSpec("ref")}, source="a2ui-basic"),
    "Modal": ComponentSpec("Modal", {
        "title": PropSpec("text"), "children": PropSpec("ref"), "open": PropSpec("binding"),
    }, source="a2ui-basic"),
    # --- Custom extensions: what A2UI Basic does not define (8) ---------------
    "BarChart": ComponentSpec("BarChart", {
        "title": PropSpec("text"), "data": PropSpec("binding"),
        "xKey": PropSpec("text"), "yKey": PropSpec("text"),
    }, source="custom"),
    "Sparkline": ComponentSpec("Sparkline", {
        "data": PropSpec("binding"), "tone": _TONE,
    }, source="custom"),
    "StatTile": ComponentSpec("StatTile", {
        "label": PropSpec("text"), "value": PropSpec("binding"),
        "unit": PropSpec("text"), "delta": PropSpec("binding"), "tone": _TONE,
    }, source="custom"),
    "ProgressBar": ComponentSpec("ProgressBar", {
        "value": PropSpec("binding"), "max": PropSpec("number"), "tone": _TONE,
    }, source="custom"),
    "Timeline": ComponentSpec("Timeline", {
        "title": PropSpec("text"), "events": PropSpec("binding"),
    }, source="custom"),
    "DataTable": ComponentSpec("DataTable", {
        "columns": PropSpec("text"), "rows": PropSpec("binding"),
        "sortable": PropSpec("bool"), "filterKey": PropSpec("text"),
    }, source="custom"),
    "Heatmap": ComponentSpec("Heatmap", {
        "title": PropSpec("text"),
        "data": PropSpec("binding"),
        "columns": PropSpec("number"),
    }, source="custom"),
    "Notice": ComponentSpec("Notice", {
        "text": PropSpec("binding"), "tone": _TONE,
    }, source="custom"),
    "ApprovalCard": ComponentSpec("ApprovalCard", {
        "summary": PropSpec("binding"), "params": PropSpec("binding"),
        "confirm": PropSpec("action"), "reject": PropSpec("action"),
    }, source="custom"),
}

# The closed set of action names a surface may emit. An action the agent did
# not register cannot cross back into the graph.
REGISTERED_ACTIONS: frozenset[str] = frozenset({"approve", "reject", "rerun", "request_data"})


def catalog_manifest() -> dict:
    """A JSON view of the catalog, served at /v1/catalog for the client."""
    return {
        "components": {
            name: {
                "source": comp.source,
                "props": {
                    prop: {"kind": spec.kind, **({"values": list(spec.values)} if spec.values else {})}
                    for prop, spec in comp.props.items()
                },
            }
            for name, comp in COMPONENTS.items()
        },
        "actions": sorted(REGISTERED_ACTIONS),
    }
