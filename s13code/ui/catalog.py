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
kept as clearly labelled custom extensions (``source="custom"``). Twenty-seven
types in all; a student can read every one and the validator can prove coverage.

Property kinds:
  - ``text``   a string shown to the user as literal text, never as markup
  - ``binding``a ``/json/pointer`` into the data model (see surface.py)
  - ``enum``   one of a fixed set of strings
  - ``ref``    a list of component ids (children)
  - ``action`` a named action + bound args; the only way a surface acts
  - ``number`` a numeric literal
  - ``bool``   a boolean literal
  - ``type_ref`` the NAME of another catalog type (see ``fallback`` below)

Forward compatibility (``fallback``)
------------------------------------
A catalog can run ahead of a client: a surface validated here may name a type an
older render client has no renderer for. Without help the client drops the
component and the content with it. A component may therefore declare a
``fallback`` naming an OLDER catalog type to draw instead — the viewer loses the
richer widget, never the information. The client follows exactly one hop, so a
chain or a self-reference cannot recurse.

The catalog also registers the closed set of action names a surface may emit.
Anything outside these sets is rejected by validator.py before render.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PropSpec:
    kind: str  # text | binding | enum | ref | action | number | bool
    values: tuple[str, ...] = ()  # for enum
    # A "text" prop is normally literal-only: the client renders it via
    # document.createTextNode, so a bound value is exactly as safe as a
    # literal one, but most text props are structural references (a chart's
    # xKey, a table's filterKey, an image's src — checked separately for
    # safe-URL-ness) where "the model points at a data value" is a category
    # error, not a feature. bindable=True opts a specific display-label prop
    # into accepting {"$bind": "/pointer"} too; unset, behavior is exactly
    # what it always was.
    bindable: bool = False
    # For a "type_ref" prop (fallback): the older type to degrade to when the
    # model omits fallback, which it does often enough that "the model always
    # remembers" is not a plan. The validator fills this in on any accepted
    # component that has a default and left the field out, so degrade-gracefully
    # is a harness guarantee rather than a hope.
    default: str | None = None


@dataclass(frozen=True)
class ComponentSpec:
    type: str
    props: dict[str, PropSpec] = field(default_factory=dict)
    source: str = "a2ui-basic"  # "a2ui-basic" | "custom"
    # A one-line statement of the DATA SHAPE this component owns, and — where a
    # near neighbour exists — which one it is not. The manifest carries it to the
    # composing model, which otherwise chooses between look-alike types on their
    # names alone. Defaulted so every existing construction site keeps working.
    description: str = ""


_TONE = PropSpec("enum", ("neutral", "good", "warn", "bad"))

# How well a researched claim is supported. Ordinal and closed: the harness
# derives it from the evidence the run actually has (distinct source hosts, a
# corrective retry, a weak-evidence flag) and never asks the model to grade its
# own certainty.
_CONFIDENCE = PropSpec("enum", ("corroborated", "single-source", "disputed", "unsupported"))


# The 23 component types the render client knows how to draw. The first 15 are
# A2UI Basic's own names; the last 8 are custom extensions A2UI Basic lacks.
COMPONENTS: dict[str, ComponentSpec] = {
    # --- A2UI Basic: layout / text / media / inputs / containers (15) --------
    "Row": ComponentSpec("Row", {
        "children": PropSpec("ref"),
        "align": PropSpec("enum", ("start", "center", "end", "stretch", "baseline")),
        "justify": PropSpec("enum", ("start", "center", "end", "spaceBetween", "spaceAround")),
    }, source="a2ui-basic",
        description="Lays its children out left to right on one band, with align and justify. "
                    "Use for a row of peers such as key figures. Not for stacking (see Column)."),
    "Column": ComponentSpec("Column", {"children": PropSpec("ref")}, source="a2ui-basic",
        description="Stacks its children top to bottom. The default container for a screen or "
                    "a section. Not for a side-by-side band (see Row)."),
    "List": ComponentSpec("List", {"children": PropSpec("ref")}, source="a2ui-basic",
        description="A vertical run of children with even spacing and no container chrome. Use "
                    "for repeated items of one kind. Not a titled box (see Card)."),
    "Card": ComponentSpec("Card", {"title": PropSpec("text"), "children": PropSpec("ref")},
        source="a2ui-basic",
        description="A titled, bordered box grouping related children. Use to separate one "
                    "subject from its neighbours. Not for a bare vertical run (see List)."),
    "Divider": ComponentSpec("Divider", {}, source="a2ui-basic",
        description="A hairline rule between sections. Carries no content."),
    "Text": ComponentSpec("Text", {
        "text": PropSpec("binding"),
        "variant": PropSpec("enum", ("heading", "subtitle", "body", "caption")),
    }, source="a2ui-basic",
        description="A bound run of prose; variant sets heading, subtitle, body or caption. Use "
                    "for narrative and for titles. Not for a single key figure (see StatTile)."),
    "Image": ComponentSpec("Image", {"src": PropSpec("text"), "alt": PropSpec("text")},
        source="a2ui-basic",
        description="A picture with alt text. The client drops javascript:, data: and vbscript: "
                    "sources, so an unvetted scheme renders nothing."),
    "TextField": ComponentSpec("TextField", {
        "label": PropSpec("text"), "value": PropSpec("binding"), "placeholder": PropSpec("text"),
    }, source="a2ui-basic",
        description="A single-line text input bound two-way into the local data model. Edits "
                    "stay local until the user commits an action."),
    "CheckBox": ComponentSpec("CheckBox", {
        "label": PropSpec("text"), "checked": PropSpec("binding"),
    }, source="a2ui-basic",
        description="A boolean toggle bound to the data model. Use for one on/off choice."),
    "Slider": ComponentSpec("Slider", {
        "label": PropSpec("text"), "value": PropSpec("binding"),
        "min": PropSpec("number"), "max": PropSpec("number"),
    }, source="a2ui-basic",
        description="A numeric input constrained between min and max. Use when any value in a "
                    "range is valid. Not for picking from a known list (see InputChoice)."),
    "InputChoice": ComponentSpec("InputChoice", {
        "label": PropSpec("text"), "options": PropSpec("binding"), "value": PropSpec("binding"),
    }, source="a2ui-basic",
        description="A single-select over bound options. Use when one value must be picked from "
                    "a known list. Not for tappable navigation (see Button)."),
    "DateTime": ComponentSpec("DateTime", {
        "label": PropSpec("text"), "value": PropSpec("binding"),
    }, source="a2ui-basic",
        description="A local date-and-time picker bound to the data model."),
    "Button": ComponentSpec("Button", {
        "label": PropSpec("text", bindable=True), "onPress": PropSpec("action"),
    }, source="a2ui-basic",
        description="A tappable control emitting exactly one registered action. The only way a "
                    "surface changes anything. Use for choices the user makes."),
    "Tabs": ComponentSpec("Tabs", {"labels": PropSpec("text"), "children": PropSpec("ref")},
        source="a2ui-basic",
        description="A tab strip; each child is one panel, named by the matching entry in "
                    "labels. Use for alternative views of one subject. Not for a sequence meant "
                    "to be read in order (see Timeline)."),
    "Modal": ComponentSpec("Modal", {
        "title": PropSpec("text"), "children": PropSpec("ref"), "open": PropSpec("binding"),
    }, source="a2ui-basic",
        description="A titled panel raised above the surface; open decides preview or open "
                    "state. Use to interrupt. Not for inline grouping (see Card)."),
    # --- Custom extensions: what A2UI Basic does not define (8) ---------------
    "BarChart": ComponentSpec("BarChart", {
        "title": PropSpec("text"), "data": PropSpec("binding"),
        "xKey": PropSpec("text"), "yKey": PropSpec("text"),
    }, source="custom",
        description="Vertical bars over bound rows keyed by xKey and yKey. Use to compare a "
                    "labelled numeric series across categories. Not for a bare trend line (see "
                    "Sparkline) and not for rows of records (see DataTable)."),
    "Sparkline": ComponentSpec("Sparkline", {
        "data": PropSpec("binding"), "tone": _TONE,
    }, source="custom",
        description="A compact inline trend line over a bound list of numbers. Use where the "
                    "shape of a movement matters but axes and labels do not. Not for labelled "
                    "comparison across categories (see BarChart)."),
    "StatTile": ComponentSpec("StatTile", {
        "label": PropSpec("text"), "value": PropSpec("binding"),
        "unit": PropSpec("text"), "delta": PropSpec("binding"), "tone": _TONE,
    }, source="custom",
        description="One key figure: a literal label with a bound value, optional unit and "
                    "delta. Use for a headline number. Not for many numbers at once (see "
                    "DataTable)."),
    "ProgressBar": ComponentSpec("ProgressBar", {
        "value": PropSpec("binding"), "max": PropSpec("number"), "tone": _TONE,
    }, source="custom",
        description="A filled bar showing a bound value against max. Use for completion or "
                    "capacity. Not for comparing independent quantities (see BarChart)."),
    "Timeline": ComponentSpec("Timeline", {
        "title": PropSpec("text"), "events": PropSpec("binding"),
    }, source="custom",
        description="An ordered list of bound events, each with a time and a label. Use for a "
                    "sequence that happened, in order. Not for unordered alternative panels "
                    "(see Tabs)."),
    "DataTable": ComponentSpec("DataTable", {
        "columns": PropSpec("text"), "rows": PropSpec("binding"),
        "sortable": PropSpec("bool"), "filterKey": PropSpec("text"),
    }, source="custom",
        description="Rows of records sharing the same fields, optionally sortable and "
                    "filterable. Use when every row has the same columns. Not for a single "
                    "figure (see StatTile) and not for one labelled series (see BarChart). Not "
                    "for a comparison of 2+ named options across 2+ shared dimensions where you "
                    "are supplying the comparative numbers yourself as part of your own answer "
                    "(see TradeoffRadar for a visual read of the same numbers, or WhatIfSlider if "
                    "the reader — not you — should decide how much each dimension matters)."),
    "Notice": ComponentSpec("Notice", {
        "text": PropSpec("binding"), "tone": _TONE,
    }, source="custom",
        description="A short callout with a coloured left edge set by tone. Use to state a "
                    "caveat, a failure, or that data the interface would need does not exist. "
                    "Never use it to present a result (see Text)."),
    "ApprovalCard": ComponentSpec("ApprovalCard", {
        "summary": PropSpec("binding"), "params": PropSpec("binding"),
        "confirm": PropSpec("action"), "reject": PropSpec("action"),
    }, source="custom",
        description="Human-in-the-loop: a bound summary and the exact parameters an action will "
                    "run, with confirm and reject. Use when a high-impact action must be "
                    "approved before it proceeds. Not for an ordinary choice (see Button)."),
    # --- Session 14 contribution: provenance (1) ------------------------------
    # The catalog could render CONCLUSIONS but never WARRANTS. The runtime already
    # collects the source URLs behind every researched claim and drops them on the
    # floor (runtime.py: node_data is written and never read) because no component
    # could draw them. Every one of the 23 types above renders a claim with the
    # same visual authority: "3.78M" from one weak source looks exactly like
    # "9.14M" from three that agree. EvidenceTile is the missing primitive.
    "EvidenceTile": ComponentSpec("EvidenceTile", {
        "label": PropSpec("text"),          # what is being claimed
        "value": PropSpec("binding"),       # the claim itself
        "unit": PropSpec("text"),
        # Coarse and closed, never a percentage and never a binding: the agent
        # picks from a fixed set, so it cannot invent a confidence label, and
        # research finds users act faster on "not sure" than on "73% confident".
        "confidence": _CONFIDENCE,
        "sources": PropSpec("binding"),     # [{"title": str, "url": str}]
        "dissent": PropSpec("binding"),     # {"value": ..., "source": ...} | None
        "fallback": PropSpec("type_ref", default="StatTile"),   # older clients draw this instead
    }, source="custom",
        description="One SHORT claim shown together with the evidence behind it: a figure, a name, "
                    "or a one-line finding, plus how well corroborated it is, the sources that "
                    "support it, and any conflicting figure. The value is a tile-sized fragment, "
                    "not a passage: a number, a short phrase, at most one sentence. Use whenever "
                    "a displayed value came from research rather than from the user. Not for a "
                    "bare number with no provenance (see StatTile). Not for a paragraph, a list of "
                    "points, or any multi-sentence explanation, however factual — that is prose, "
                    "and prose belongs in Text or a Card wrapping Text, not squeezed into a tile "
                    "built to hold one fact."),
    "RunGraph": ComponentSpec("RunGraph", {
        "title": PropSpec("text"),
        "nodes": PropSpec("binding"),       # [{"id": str, "label": str, "state": str}]
        "edges": PropSpec("binding"),       # [{"from": str, "to": str, "reason": str}]
        "highlight": PropSpec("binding"),   # one node id to ring
        "fallback": PropSpec("type_ref", default="Timeline"),
    }, source="custom",
        description="The run's own shape: every step taken, which step fed which, and the state "
                    "each ended in. EVERY answer was produced by a run, so this is available on "
                    "every turn and is always relevant to how the answer came about — it is the "
                    "process-level counterpart to showing which sources back a value. Include it "
                    "whenever /graph_nodes is present and the reader may reasonably ask how the "
                    "answer was reached. Not an ordered list of events (see Timeline): a Timeline "
                    "shows what happened in sequence and cannot show that one step earned another."),
    # --- Arbiter contribution: synthesis, not just facts (2) -------------------
    # Every type above shows what IS: a figure, a series, a table of rows. None of
    # them shows a JUDGEMENT across several things at once against several axes,
    # and none of them lets the reader question the judgement rather than just
    # read it. A decision desk that only ever displays facts still leaves the
    # actual deciding to the reader's own head. These two close that gap.
    "TradeoffRadar": ComponentSpec("TradeoffRadar", {
        "title": PropSpec("text"),
        "axes": PropSpec("binding"),       # [str], in the order every series' values follow
        "series": PropSpec("binding"),     # [{"name": str, "values": [number, ...]}]
        "fallback": PropSpec("type_ref", default="DataTable"),
    }, source="custom",
        description="Plots 2+ named options across the SAME 2+ axes as one shape per option, so "
                    "a reader sees who wins where in a single glance instead of scanning a table "
                    "cell by cell. SELF-CHECK before reaching for DataTable: are 2 or more named "
                    "options being compared here at all, on 2 or more shared dimensions (latency, "
                    "durability, ops burden, cost, ...)? If yes, use this instead — ALWAYS, not "
                    "only when the prompt explicitly asks for a chart or a visual. NOT exclusive "
                    "with EvidenceTile: keep an EvidenceTile per subject for its headline sourced "
                    "fact, and ADD this beneath to show how the subjects stack up against each "
                    "other — 'what did we learn about X' and 'how do X, Y, Z compare' are two "
                    "different questions and a decision desk answers both. Example: comparing "
                    "Kafka, RabbitMQ and NATS on throughput, durability and ops simplicity is a "
                    "TradeoffRadar, not a DataTable — assign each option a 1-10 score per axis from "
                    "what the evidence suggests. That score is a synthesised judgement, the same "
                    "kind EvidenceTile's own confidence rating already makes about a single claim, "
                    "not an invented research figure. Not for one labelled series across "
                    "categories (see BarChart) and not for plain rows of records with no shared "
                    "axes to plot (see DataTable)."),
    "WhatIfSlider": ComponentSpec("WhatIfSlider", {
        "title": PropSpec("text"),
        "criteria": PropSpec("binding"),   # [{"key": str, "label": str, "weight": number 0-100}]
        "options": PropSpec("binding"),    # [{"name": str, "scores": {criterionKey: number}}]
        "fallback": PropSpec("type_ref", default="DataTable"),
    }, source="custom",
        description="One slider per criterion, reranking a list of named options live as a weight "
                    "moves — entirely client-side, no round trip. SELF-CHECK before reaching for "
                    "DataTable or a plain ranked List: are 2 or more named options being weighed "
                    "against 2 or more criteria here, with no single fixed weighting stated? If "
                    "yes, use this instead — ALWAYS, not only when the prompt asks to 'adjust' or "
                    "'explore' priorities. Example: prioritising 'reduce p99 latency' vs 'cut cloud "
                    "spend' vs 'improve on-call load' this quarter is a WhatIfSlider, not a "
                    "DataTable or Timeline — score each option 1-10 per criterion from what you "
                    "already know about it, and let the reader set the weights, because THEY hold "
                    "the priorities, not you. Only fall back to DataTable/List when the prompt "
                    "itself fixes the weighting or asks for one settled answer. Not for a fixed "
                    "judgement the reader cannot reweigh (see TradeoffRadar) and not for an input "
                    "the user must submit before anything happens (see Slider)."),
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
                # The composing model picks from this manifest alone. Without a
                # description it discriminates look-alike types (DataTable vs
                # StatTile vs BarChart) on their names, which is guessing.
                "description": comp.description,
                "props": {
                    prop: {"kind": spec.kind, **({"values": list(spec.values)} if spec.values else {})}
                    for prop, spec in comp.props.items()
                },
            }
            for name, comp in COMPONENTS.items()
        },
        "actions": sorted(REGISTERED_ACTIONS),
    }
