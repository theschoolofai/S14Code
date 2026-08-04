# Catalog contribution — `Map`, `Calendar`, `Rating`

This document covers **only** what was added to the component catalog and what had to change around
it. The base runtime is unchanged and documented in [`README.md`](README.md); the full assignment
write-up, including the application and the honest verdict, is in [`SUBMISSION.md`](SUBMISSION.md).

The catalog goes from **23 types to 26**: 15 A2UI-Basic + 8 custom + **3 `student-extension`**.
`s13code/ui/validator.py` is **not touched**. That is the point of the exercise — a component added
to the catalog inherits the existing wall rather than softening it.

---

## 1. Why these three

Each one carries a data shape the previous 23 types flattened or dropped.

| Type | The gap it fills |
|---|---|
| `Map` | Nothing in the catalog could show *where* something is. Coordinates were previously stringified into a `DataTable` cell or a `Text` blob. |
| `Calendar` | `Timeline` shows a *sequence*. Only a month grid shows *which dates are taken and which are still free* — the question a planner is actually asked. |
| `Rating` | A score out of a maximum was previously squeezed into a `StatTile` ("4.5") or buried in prose, losing both the scale and the sample size. |

---

## 2. The `ComponentSpec`s

[`s13code/ui/catalog.py`](s13code/ui/catalog.py). No new `PropSpec` **kind** was invented: the closed
property vocabulary the validator already understands (`text`, `binding`, `enum`, `ref`, `action`,
`number`, `bool`) is what makes an unknown property refusable, so widening it would weaken the wall.

```python
"Map": ComponentSpec("Map", {
    "title": PropSpec("text"),
    "points": PropSpec("binding"),        # [{label, lat, lon}]
    "labelKey": PropSpec("text"),
    "latKey": PropSpec("text"),
    "lonKey": PropSpec("text"),
    "zoom": PropSpec("number"),
}, source="student-extension"),

"Calendar": ComponentSpec("Calendar", {
    "title": PropSpec("text"),
    "events": PropSpec("binding"),        # [{date: "2026-09-21", label}]
    "month": PropSpec("binding"),         # "2026-09" — which month to draw
    "onSelect": PropSpec("action"),       # tapping a day earns the next turn
}, source="student-extension"),

"Rating": ComponentSpec("Rating", {
    "label": PropSpec("text"),
    "value": PropSpec("binding"),         # 4.5
    "max": PropSpec("number"),            # out of how many
    "count": PropSpec("binding"),         # "1,204 reviews"
    "tone": _TONE,                        # reuses the existing neutral/good/warn/bad enum
    "onRate": PropSpec("action"),
}, source="student-extension"),
```

### The `source` tag

The existing tags are `a2ui-basic` and `custom`. A third value, **`student-extension`**, keeps the two
original buckets exactly as the test suite describes them and makes the new types attributable at a
glance — including over the wire, since `catalog_manifest()` already serves `source` per component:

```bash
curl -s http://127.0.0.1:8113/v1/catalog | python -c "import json,sys; c=json.load(sys.stdin); \
  print({k:v['source'] for k,v in c['components'].items() if v['source']=='student-extension'})"
# {'Map': 'student-extension', 'Calendar': 'student-extension', 'Rating': 'student-extension'}
```

### Two new registered actions

```python
REGISTERED_ACTIONS = frozenset(
    {"approve", "reject", "rerun", "request_data", "select_day", "rate"}
)
```

`select_day` and `rate` are what `Calendar.onSelect` and `Rating.onRate` are allowed to emit. The set
stays **closed** around them — that is the whole event invariant, and adding a component is not a
licence to widen it further.

---

## 3. The renderers

`Map`, `Calendar` and `Rating` are drawn in all three client pages, so no page degrades to
`[skipped unknown type]`:

| File | Renderer table | Role |
|---|---|---|
| [`s13code/ui/client/index.html`](s13code/ui/client/index.html) | `RENDERERS` → `renderMap` / `renderCalendar` / `renderRating` | the render client the assignment names |
| [`s13code/ui/client/app.html`](s13code/ui/client/app.html) | `R` | the bare-minimal `/app` shell |
| [`s13code/ui/client/trip.html`](s13code/ui/client/trip.html) | `R` | the UI-only application at `/trip` (new) |

Every one of them obeys the same rules as the 23 that came before:

- Built with `document.createElement` / `createElementNS` and `document.createTextNode`. **No
  `innerHTML`, no `eval`, no string-to-code path anywhere.** `tests/test_s14_ui.py` asserts that
  `innerHTML` never appears on the left of an assignment in any client.
- **`Map` carries coordinates, not a tile URL.** The renderer projects lat/lon equirectangularly into
  an inline SVG viewBox framed on the points themselves, draws one circle and one `<text>` label per
  point, and dashes a route line through them in order. There is **no tile fetch, no `<iframe>` and no
  `src`** — an external tile URL would hand the model a network channel the catalog never approved,
  which is precisely what the session forbids. A test asserts the `Map` renderer contains no `src`, no
  `fetch(`, and no URL other than the SVG namespace.
- **`Calendar` draws a real month grid** as a `<table>` from `month` + `events`: Monday-first weekday
  header, correct leading pad cells, a label on each day that has an entry. A day with an entry is
  tappable only when `onSelect` is present, and the tap goes through the same `emitAction` door a
  `Button` uses.
- **`Rating`** draws `★`/`☆` glyphs as text nodes plus the numeric value and `count`, toned by the
  existing `--green`/`--amber`/`--red` variables.
- **Missing data degrades quietly.** No coordinates renders "no coordinates available — nothing
  drawn"; no dated entries renders the equivalent. A renderer that throws would blank the screen,
  which would break the "the safe part still renders" promise from the other direction.

Verified under a DOM harness: a bound value containing `<script>steal()</script>` ends up as a single
literal **text node** reading `"<script>steal()</script>"`, never as markup.

---

## 4. Giving the model something to bind, without naming the components

`compose_surface` already sends the model the whole catalog manifest, so the new types are offered
automatically. What was missing was *data of the right shape*. Two additive edits in
[`s13code/runtime.py`](s13code/runtime.py):

1. **The content role's schema** gained three optional, domain-neutral fields, described only by
   shape:
   ```
   "places":   [{"label": string, "lat": number, "lon": number}]
   "schedule": [{"date": "YYYY-MM-DD", "label": string}]
   "ratings":  [{"label": string, "value": number, "max": number, "count": string}]
   ```
   with an explicit instruction never to invent coordinates, dates or scores it does not have — omit
   the field instead. A generated interface can lie in a way a paragraph cannot, and a map with
   invented pins is exactly that lie.

2. **The compose data model** exposes what survived validation as `/map_points`, `/calendar_events`,
   `/calendar_month` (derived from the earliest entry), `/ratings`, and per-index
   `/rating_N_value` / `/rating_N_count`, mirroring the existing `metric_N_value` pattern.
   Coordinates outside ±90 / ±180 and dates that are not `YYYY-MM-DD` are dropped rather than drawn.

The compose **instruction** gained exactly one sentence, and it names no component type:

> "Any OTHER pointer in available_pointers that carries structured data must ALSO be rendered: read
> the catalog and choose the component whose declared props best fit that data's shape (match the prop
> names and kinds), rather than dropping the data or flattening it into a Text."

There is deliberately **no** `"for /map_points render a Map"` rule. Gemini has to read
`Map.points`, `Calendar.events` and `Rating.value` out of the manifest and make the match itself.

---

## 5. Gemini composed all three unprompted

[`proofs/harness_custom_components.py`](proofs/harness_custom_components.py) runs a real live-graph
task through the real gateway with a prompt that describes a *situation*, never an interface. The
words "Map", "Calendar" and "Rating" appear nowhere in the prompt, nowhere in the compose system
prompt and nowhere in the compose instruction — the proof file records that check as
`prompt_names_no_component`.

**`proofs/custom_component_run_calendar.json`** — run `run-439b80171bb3`,
`gemini-3.1-flash-lite-preview`, **10 proposed / 10 accepted / 0 rejected**, types
`Calendar, Column, List, Map, Rating, Tabs, Text`. What the model wrote:

```json
{"id":"map","type":"Map","title":"Key Locations","points":{"$bind":"/map_points"},
 "labelKey":"label","latKey":"lat","lonKey":"lon","zoom":12}

{"id":"calendar","type":"Calendar","title":"Trip Schedule","events":{"$bind":"/calendar_events"},
 "month":{"$bind":"/calendar_month"},"onSelect":{"action":"request_data"}}

{"id":"r0","type":"Rating","label":"Hotel Nikko Osaka (Shinsaibashi)",
 "value":{"$bind":"/rating_0_value"},"max":5,"count":{"$bind":"/rating_0_count"}}
```

Every data value is a `$bind` pointer into the harness-owned data model; only labels and key names
are literal UI strings, exactly as the catalog allows.

**`proofs/custom_component_run.json`** — a second capture (`run-3483bab0e2a4`, 15/15/0) where the same
prompt shape produced `Map` + `Rating` and the model chose `Tabs` over `Calendar` for three days. That
is a defensible choice and it is why the date-centric capture exists: `Calendar` gets picked when
individual dates are load-bearing, not merely present.

```bash
# the capture, from a fresh checkout (gateway on 8111)
S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
  uv run python proofs/harness_custom_components.py

# the date-centric variant that draws all three at once
S14_OUT=custom_component_run_calendar.json \
S14_TASK="I land in Osaka on 21 September 2026 and fly home on 30 September 2026. Tell me what I should be doing on each individual date in that window, and how well reviewed each place I would stay is." \
  uv run python proofs/harness_custom_components.py
```

The script exits `0` only when the surface succeeded **and** at least one `student-extension` type was
composed; `4` means the model composed cleanly but reached for none of them.

---

## 6. The three invariants still hold for the new types

Adding a component must not soften the wall, so each new type is attacked in
[`tests/test_s14_ui.py`](tests/test_s14_ui.py) and in the shared fixture
[`s13code/ui/fixtures/injections.json`](s13code/ui/fixtures/injections.json) (now **seven** cases —
four against the base catalog, three aimed at the new types, all picked up automatically by
`tests/test_invariants.py`).

| Invariant | What is refused |
|---|---|
| **catalog** | The plausible neighbours an attacker reaches for next: `MapView`, `GoogleMap`, `Calendar3D`, `StarRating`, `Leaflet`. A new type widens the vocabulary by one name, not by a family. |
| **data-not-code** | Markup in `Map.points`, `Calendar.events`, `Rating.count`; a tile URL in a `src` prop `Map` never declared; a `javascript:` value in `Calendar.title`; a literal where the schema demands `{"$bind": "/pointer"}`; `Rating.tone: "chartreuse"`; an `onclick` smuggled in beside a legitimate `onSelect`. |
| **event** | `Calendar.onSelect: {"action": "exfiltrate"}`, `Rating.onRate: {"action": "drop_tables"}` and `{"action": "charge_card"}`. `select_day` and `rate` are accepted, so a real tap can still earn the next turn. |

Two further properties are asserted directly:

- **No new type exposes a fetchable or executable property.** No prop on `Map`, `Calendar` or `Rating`
  is named `src`, `href`, `url`, `html`, `style`, `script`, or matches `^on[a-z]` (a lowercase DOM
  handler shape) — only the camelCase `onSelect` / `onRate` action props the schema declares.
- **A poisoned new component does not take the interface down with it.** A hostile `Map` is dropped
  while the `Calendar` beside it and the heading above it still render, with exactly one rejection
  raised.

```bash
uv run pytest -q                             # the invariant tests, hermetic — no gateway needed
uv run python proofs/run_surface_proof.py    # prints all seven injection cases and the invariant each broke
```

Result from the wall proof:

```
injection wall:
  raw-html-type              REJECTED  broke ['catalog']        [ok]
  smuggled-handler           REJECTED  broke ['data-not-code']  [ok]
  markup-in-binding          REJECTED  broke ['data-not-code']  [ok]
  unregistered-action        REJECTED  broke ['event']          [ok]
  map-near-miss-type         REJECTED  broke ['catalog']        [ok]
  markup-in-calendar-binding REJECTED  broke ['data-not-code']  [ok]
  rating-unregistered-action REJECTED  broke ['event']          [ok]
  all_rejected=True all_correct=True
```

---

## 7. Every file the component addition touched

| File | Change |
|---|---|
| `s13code/ui/catalog.py` | 3 `ComponentSpec`s under `source="student-extension"`, 2 new registered actions, docstring 23 → 26 |
| `s13code/ui/client/index.html` | `renderMap` / `renderCalendar` / `renderRating` + their CSS |
| `s13code/ui/client/app.html` | the same three in the `R` table + their CSS |
| `s13code/ui/client/trip.html` | **new** — the UI-only application, which renders all 26 types |
| `s13code/runtime.py` | 3 optional content-schema fields; the data-model merge for them; one non-naming compose clause; derived next-step choices so an interface can always earn a turn |
| `s13code/ui/fixtures/injections.json` | 3 new hostile cases aimed at the new types |
| `tests/test_s14_ui.py` | catalog-shape test updated to 26/3-source; new invariant tests per new type; renderer and trip-shell contract tests |
| `s13code/ui/routes.py` | `GET /trip`; client files now read as UTF-8 (the `★`/`●` glyphs cannot be decoded by the Windows default codepage) |
| `proofs/harness_custom_components.py` | **new** — the captured unprompted composition |
| `proofs/run_surface_proof.py` | docstring: the injection count is no longer fixed at four |

Not touched: **`s13code/ui/validator.py`**.

---

## 8. Reusing them

Bind real data and let the model choose, or hand-build:

```json
{"id": "m", "type": "Map", "title": "Route",
 "points": {"$bind": "/map_points"}, "labelKey": "label", "latKey": "lat", "lonKey": "lon"}

{"id": "k", "type": "Calendar", "title": "Itinerary",
 "events": {"$bind": "/calendar_events"}, "month": {"$bind": "/calendar_month"},
 "onSelect": {"action": "select_day"}}

{"id": "r", "type": "Rating", "label": "Ryokan Yachiyo",
 "value": {"$bind": "/rating_0_value"}, "max": 5,
 "count": {"$bind": "/rating_0_count"}, "tone": "good", "onRate": {"action": "rate"}}
```

with a data model shaped like:

```json
{
  "map_points": [{"label": "Kyoto", "lat": 35.01, "lon": 135.77}],
  "calendar_events": [{"date": "2026-09-21", "label": "Higashiyama"}],
  "calendar_month": "2026-09",
  "rating_0_value": 4.6,
  "rating_0_count": "1,204 reviews"
}
```

`labelKey` / `latKey` / `lonKey` default to `label` / `lat` / `lon`, so they can be omitted when the
points already use those names. `Calendar.month` can be omitted too — the renderer falls back to the
month of the earliest event. `Rating.max` defaults to 5 and is clamped to 10.

Push any surface through the wall before trusting it, the same way the runtime does:

```bash
curl -s http://127.0.0.1:8113/v1/validate -H 'Content-Type: application/json' \
  -d '{"surface": {"root": "r", "components": [{"id": "r", "type": "MapView"}]}}'
# {"ok": false, "accepted": [], "rejections": [{"component_id":"r","field":"type",
#   "invariant":"catalog","reason":"unknown component type 'MapView'"}]}
```
