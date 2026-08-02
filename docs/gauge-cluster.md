# GaugeCluster

A catalog component for **bounded measurements**: readings that have a scale and
a limit, where the question is not "what is the number" but "how close is it to
the edge". CPU temperature, disk pressure, tank level, battery charge, request
latency against an SLO.

It is the 24th component and the 9th custom extension — A2UI Basic has no gauge.

## The spec

`s13code/ui/catalog.py`:

```python
"GaugeCluster": ComponentSpec("GaugeCluster", {
    "title": PropSpec("text"), "gauges": PropSpec("binding"),
}, source="custom"),
```

Two props, and `gauges` is a **binding** — the component cannot carry values, only
a JSON Pointer to them. Each entry the pointer resolves to may carry:

| key | meaning |
|---|---|
| `label` | what the reading is |
| `value` | the reading |
| `min`, `max` | the scale it is drawn on; omitted means no scale is invented |
| `unit` | printed beside the value |
| `warn`, `alarm` | the thresholds that actually raise the fault |
| `invert` | the failing end is the **bottom** of the range, not the top |

## Why thresholds, and why `invert`

The obvious implementation colours a gauge by fraction-of-range: near the top is
bad. That is wrong twice.

A pump rated to 25 A that normally draws 1.2 A sits at 5% of its scale and is
perfectly healthy — fraction-of-range calls it a failure. And a reading whose
failure lives at the *bottom* (a level, a charge, a current that should be
flowing) is worst at zero, where fraction-of-range is calmest. So severity comes
from the thresholds the caller supplies, and `invert` says which end is the
failing one. Fraction-of-range is only the fallback when no threshold is given.

## Severity is not carried by length alone

Drawing severity as arc length has a failure mode that inverts the whole point:
the worse the fault, the less there is to draw. A signal in alarm *at zero*
sweeps nothing and disappears at the moment it matters most, indistinguishable
from "no data".

So a gauge in warn or alarm gets a floor sweep (`ALARM_MIN_SWEEP`), and the value
readout is toned as well — a channel whose visibility does not depend on the
magnitude of the fault. A healthy signal sitting low in its range is left alone:
the floor is for severity, not for every small number, and there is a test
pinning that so a small number is never inflated into looking like a fault.

## The renderer executes nothing

`s13code/ui/client/index.html` and `app.html` draw the cluster as SVG built from
`createElementNS` and text nodes. There is no `innerHTML` assignment anywhere in
either client and no string is ever evaluated, so a label carrying
`<img src=x onerror=...>` renders as the literal characters. The tests assert
this in a real DOM rather than by reading the source, because the client is the
second wall and a second wall is only worth having if someone checks it is there.

## The three invariants, for this component

- **catalog** — a surface naming a type the catalog does not define is rejected;
  `GaugeCluster` passes because the spec above declares it and its prop kinds.
- **data-not-code** — `gauges` is a `binding`, so the model can point at data but
  cannot inline markup; markup that arrives in a bound value stays text.
- **event** — a gauge names no action. Nothing about this component gives a model
  a new way to send an event back.

## Tests

| file | what it proves |
|---|---|
| `tests/test_gauge_cluster.py` | the spec is in the catalog and the validator accepts and rejects the right surfaces |
| `tests/test_gauge_cluster_renderer.py` | every shipped client draws it, assigns no `innerHTML`, evaluates no string, and floors the sweep in alarm |
| `tests/test_client_rendering_playwright.py` | what it actually draws in Chromium: sweep, tone, thresholds, `invert`, and injection staying inert |

## Composed unprompted

A catalog entry alone does not make a component composable. `compose_surface`
builds a domain-neutral data model and offers the catalog beside it — and until
this branch, nothing in that model was a *bounded* reading. A model could name
`GaugeCluster` but had nothing to bind it to, and would have had to invent a
scale to use it. So the data model gained a `/gauges` pointer: a value **with a
scale**, plus the thresholds and `invert` flag when the answer carries them. A
number without bounds stays a metric — giving it an invented axis would be the
interface making a number up.

The prompt does **not** say the word. `tests/test_compose_gauges.py` asserts that
neither `compose_system_prompt()` nor `compose_instruction()` contains
"GaugeCluster", because a captured run where the instruction named the component
would measure obedience rather than composition.

What the model chose, given the catalog and a data model containing bounded
readings, a series and rows — three different shapes, so picking the right
component for each is a real choice and not the only move available:

```
Text · Text · Row · StatTile ×4 · GaugeCluster · Sparkline · DataTable · ProgressBar
accepted 11 · rejected 0 · clean
"gauges": {"$bind": "/gauges"}
```

**Provenance, stated plainly:** produced against a local `gemma4` served by
Ollama, not Gemini. The mechanism under test is the same — `compose_surface`
reads the catalog and offers the component on its own — but the model is not the
one the assignment names, and a different model may well choose differently.

The capture harness is not in this repository. It is one machine's errand — a
specific goal, a specific local model, a specific endpoint — and a
general-purpose framework should not carry it. The evidence section of
[`README.md`](../README.md) carries the full run: the prompt sent, the raw
reply, the ordered event trace, and the validated surface.
What lives *here* is the part that makes the claim checkable —
`tests/test_compose_gauges.py` asserts that neither `compose_system_prompt()` nor
`compose_instruction()` contains the string "GaugeCluster".

## One interface that used it

The demo application composes panels of gauges from a machine telemetry source,
each signal drawn on the scale its database defines, with the thresholds that
raise the real fault. That application lives outside this repository — it is an
*application*, and this repository is the framework. Nothing automotive is
required to use `GaugeCluster`; it needs a number, a scale and a limit.
