# Wayfarer — a UI-only trip planner (Assignment Part 2)

Record of building the second deliverable: "an application in a domain you
care about where the agent answers only by composing an interface, and
never with a paragraph of text."

## The ask

- Answer every turn as a composed, catalog-validated interface, never raw text.
- Use the rich component the situation calls for: a chart where there is a
  series, a table where there are rows, a timeline where there is a sequence.
- Carry a conversation across at least three turns, where a tap in one
  interface shapes the next.
- Run end to end against the real gateway.

The architecture already carries the whole application: `POST
/v1/agent/runs` with `respond_as: "ui"`, read `/v1/runs/{id}/composed`,
render it, turn a tap into the next turn. Fork `/app` or write a new shell.

## The domain: trip planning

Chosen because it naturally spans every rich shape the catalog offers: a
day-by-day itinerary is genuinely chronological (`Timeline`), comparing
hotels or transit options is genuinely tabular (`DataTable`), a budget
breakdown is genuinely numeric (`StatTile`/`BarChart`), and it supports
open-ended, real multi-turn exploration (a day, a comparison, a checklist,
a cost — the traveler can go in almost any direction, unlike a fixed
five-level lesson ladder).

Named it **Wayfarer**.

## What was forked vs. what's new

`client/trip.html` is a fork of `client/app.html`, split cleanly in two:

- **Forked verbatim** (proven, already-tested code, unchanged): the entire
  render engine — `$`/`T`/`resolve`/`rtext`/`ptr`, the safe-markdown parser,
  the full `R` component map including the `Stepper` one-step-at-a-time
  wizard, `resolveRoot`'s dangling-root fallback, `table`/`tabs`/`bars`/
  `spark`, and the run-chrome helpers (badges, graph path, process
  timeline). None of this is a rewrite — it's the same catalog-validated
  renderer every app on this runtime should reuse, not reinvent.
- **New**: the goal-building loop. `app.html`'s `buildGoal()` is a fixed
  "level N of `MAX_DEPTH`" lesson ladder. A trip isn't a ladder — it's an
  open exploration, so Wayfarer's `buildGoal()` instead accumulates a
  breadcrumb of what's been explored so far (`convo`) and asks for
  "whichever structure actually fits the content (a further day-by-day
  breakdown, a comparison table of options, a cost breakdown, a checklist,
  or whatever else fits)" — **never naming a UI component** — so
  `compose_surface` picks the richest one from the catalog on its own, the
  same way it already does for every other app.

## No backend changes

Confirmed by construction: the only backend edit for Part 2 was one new
route (`GET /trip` / `/trip/` in `s13code/ui/routes.py`) serving the static
`trip.html` file, mirroring `GET /app` exactly. `compose_surface`,
`catalog.py`, `validator.py`, and the planner are all untouched — the
generic pipeline genuinely does carry a brand-new domain with zero changes
to it, which is the whole architectural point being demonstrated.

## A real bug found while building it: the entity-list heuristic

The first live run of "5 days in Kyoto, Japan" produced a broken-looking
interface: zero itinerary sections, and garbage "metrics" like
`{"label": "Japan\n\nGive", "value": 0}`. Traced it to `runtime.py`'s
`_work_intent()`: a regex (`_ENTITY_LIST`) built to detect a genuine
"compare A, B and C" prompt and fan it out into real per-entity research
nodes. It has no notion that a comma can just be how a destination is
written — `"Kyoto, Japan"` parses exactly like "compare Kyoto and Japan" to
that regex, silently rerouting the run into the **multi-entity research
path** (`compose_research`, two live web searches with empty hits, an
outcomes-based data model) instead of the **single-goal content path**
(`compose_answer`) this app actually needs.

That's shared runtime infrastructure used by every app on this platform —
out of scope to change for a Part 2 UI-only app that's supposed to build
*on top of* the architecture, not patch it. Fixed client-side instead, in
`trip.html`'s `goalSafe()`:

```js
function goalSafe(text){ return String(text).replace(/,\s*/g, " in "); }
```

Applied everywhere the trip/breadcrumb/picked-label text is embedded into a
goal string. Purely cosmetic in meaning ("Kyoto, Japan" → "Kyoto in Japan")
and never touches what's displayed in the input box or the breadcrumb trail
— only what's sent as data. Re-tested after the fix: the same prompt
correctly produced 5 real day-by-day sections, real metrics (`Trip
Duration`, `Estimated Budget`, `Must-See Highlights`), real choices, and a
genuine `Timeline` component. (This same script (`generate_trip_gemini.py`)
mirrors the fix in Python for the captured proof, with the identical
comment explaining why.)

## Live verification (real browser, real gateway)

Three real turns, driven through an actual headless-Chromium session
against the live `glc_v3` gateway and a live `S14Code` server — not a mock,
not a fixture:

| Turn | Tapped | Composed |
|---|---|---|
| 1 | *(initial: "5 days in Kyoto, Japan")* | `Text` (heading+intro) → `StatTile`×3 (Days/Budget/Highlights) → **`Timeline`** (5-day itinerary, one dot per day) → 4 `Button`s |
| 2 | "Comparing accommodation types" | `Text` → **`DataTable`** (Ryokan/Machiya/Business Hotel/Capsule Hotel × Type/Vibe/Price Range/Best For) → `Card`s of considerations → 4 new `Button`s |
| 3 | "Navigating Kyoto" | `Text` → **`DataTable`** (Subway/Bus/Bicycle/Taxi × Mode/Best For/Speed/Cost) → `Card`s → 4 new `Button`s |

The breadcrumb (`#crumbs`) after turn 3 read exactly: `turn 3 of 6 · 5 days
in Kyoto, Japan › Comparing accommodation types › Navigating Kyoto` —
direct proof each tap became the next turn's context, not an isolated
request. Zero console errors (one benign favicon-style 404, unrelated).
Every turn showed `composed by gemini_1 inside the live graph · N
components · 0 executable`.

(A first pass of this same walkthrough, before deliberately steering which
button got tapped, landed on two turns in a row that were naturally
prose-shaped — a food guide and a temple's detail page — and correctly
rendered as `Text`/`Card`/`Button` with no chart or table, because that
content genuinely had no rows or series to show. That's not a failure of
the app; it's the model correctly declining to force a `DataTable` onto
content that isn't tabular. The walkthrough above deliberately taps
comparison-shaped choices specifically to *demonstrate* the table/timeline
capability, but the model choosing plain `Text` for plain content is the
system working as intended, not a gap.)

## Captured proof: `proofs/generate_trip_gemini.py`

A durable, reviewable artifact (same pattern as `generate_stepper_gemini.py`
from Part 1): constructs a real `S13Runtime`, drives **three real
sequential live-Gemini turns** through `respond_as="ui"`, with each turn's
goal built from an actual `Button` label chosen out of the *previous*
turn's real composed surface (not scripted labels) — mirroring `trip.html`'s
`goalSafe()`/`buildGoal()` in Python so the captured run matches what the
browser actually does.

```bash
GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
  uv run python proofs/generate_trip_gemini.py   # -> proofs/trip_gemini_run.json
```

Result:

```
turn 1: types=[Button, Column, Row, StatTile, Text, Timeline]           accepted=13 rejected=0  ok=True
  tapping: 'Comparing accommodation types'
turn 2: types=[Button, Card, Column, DataTable, List, Text]             accepted=15 rejected=0  ok=True
  tapping: 'Navigating Kyoto by bus vs train'
turn 3: types=[Button, Card, Column, DataTable, Row, StatTile, Text]    accepted=17 rejected=1  ok=False

component types seen: [Button, Card, Column, DataTable, List, Row, StatTile, Text, Timeline]
conversation: 5 days in Kyoto, Japan › Comparing accommodation types › Navigating Kyoto by bus vs train
```

### The one real rejection — the wall working on a genuine mistake, not an attack

Turn 3 had 1 rejection out of 18 proposed components:

```json
{
  "component_id": "choices_title",
  "field": "text",
  "invariant": "data-not-code",
  "reason": "binding must be {'$bind': '/pointer'}"
}
```

Gemini put a literal string directly where `Text.text` (a `binding`-kind
prop) requires `{"$bind": "/pointer"}` — an honest model mistake, not an
injection attempt, caught by the exact same wall that guards against
hostile input. `dangling_child_refs: ["choices_title"]` confirms the parent
component that referenced it just quietly has one fewer child — the render
client's `kids()` helper already skips missing children (`if(ch)e.append(...)`),
so this drops one label with zero visible breakage. 17 of 18 components
still rendered. This is the *safe-part-survives* invariant proven against
real, unscripted live output, not a hand-built test fixture — arguably a
stronger demonstration than the fixture-based invariant tests, precisely
because nobody engineered it to happen.

## Files touched

| File | Change |
|---|---|
| `s13code/ui/client/trip.html` | new — Wayfarer, forked render engine + new domain-specific goal-building loop |
| `s13code/ui/routes.py` | new `GET /trip` / `/trip/` route (mirrors `/app`); routes docstring updated to list both `/app` and `/trip` |
| `proofs/generate_trip_gemini.py` | new — captures a real 3-turn live conversation |
| `proofs/trip_gemini_run.json` | new — the captured proof artifact |
| `tests/test_s14_ui.py` | 2 new route smoke tests: `/app` and `/trip` both serve, use the real `/v1/agent/runs` + `respond_as:"ui"` contract, and read component values only through `createTextNode` |
| `README.md` | routes table updated; new "Part 2: Wayfarer" section; proofs table row |

Full suite: **124/124 pass** (122 baseline + 2 new route tests). Nothing in
`s13code/runtime.py`, `catalog.py`, or `validator.py` was touched for this
part — by design, proving the architecture really does carry a brand-new
domain-specific application with zero backend changes.
