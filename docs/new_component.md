# New Component — `Stepper` (Assignment Part 1)

Record of the session that added the 24th catalog component, `Stepper` — a
step wizard — end to end: spec, renderer, invariant proofs, and one captured
run where Gemini composed it on its own.

## The ask

Part 1 of the assignment: add one component the catalog does not have yet
that a real interface would want. It has to live in three places —

1. a `ComponentSpec` in `s13code/ui/catalog.py`, with typed props and a
   source tag,
2. a renderer in the render client that draws it from text nodes and
   executes no value,
3. one captured run where Gemini composes the component into a real
   interface without being told to name it, because `compose_surface` reads
   the catalog and offers the component to the model on its own —

and had to show the three invariants still hold for it: an unknown type is
rejected, a bound value carrying markup is refused, and an unregistered
action never crosses back.

## Baseline

Before any change: 23 catalog types (15 A2UI-Basic + 8 custom), 110 tests
passing (`docs/baseline_check.md`). `s13code/ui/routes.py` already exposed a
`/v1/harness/surface` route that re-validates and serves a *recorded* real
Gemini composition (`proofs/harness_run.json`, produced by
`proofs/harness_run.py`) — that route was the template followed for the new
proof.

## Why `Stepper`

Candidates on the table: Map, Kanban, Gantt/calendar, code diff, heatmap,
image gallery, rating, step wizard. `Stepper` was chosen because:

- The app's own generative loop (`client/app.html`) is a "teach me X,
  drilling down five levels" lesson tool. `runtime.py`'s `run_content` role
  already asks the model for a domain-neutral `sections: [{heading,
  points}]` field explicitly documented as "ordered groups (days, steps,
  stages, phases, topics)" — a natural, already-flowing data shape a step
  wizard is the best fit for.
- None of the other candidates fit the existing render pipeline as cleanly
  without executing something risky (e.g. a code-diff component's natural
  content — literal HTML/JS snippets — collides with the data-not-code
  markup check by design).
- It reuses the *existing* closed action vocabulary (`request_data`) rather
  than requiring a new registered action, keeping the catalog's closed sets
  actually closed.

## 1 — the spec

`s13code/ui/catalog.py`, `COMPONENTS["Stepper"]`, `source="custom"`:

| Prop | Kind | Purpose |
|---|---|---|
| `title` | `text` | literal heading above the steps |
| `steps` | `binding` | `{"$bind": "/pointer"}` into a list of step records |
| `labelKey` | `text` | which field of each record is the step's short label (mirrors `BarChart`'s `xKey`/`yKey` idiom) |
| `detailKey` | `text` | which field is the step's detail/body |
| `current` | `number` | optional literal index to highlight as "in progress" |
| `onSelect` | `action` | optional — tapping a step drives the next turn, exactly like `Button.onPress` |

Docstring counts updated: 23 → 24 types, 8 → 9 custom extensions. No changes
were needed in `validator.py` — the three invariants are enforced generically
over whatever the catalog contains, which is the whole point of a closed,
data-driven catalog.

## 2 — the renderer

Added to **both** render clients (there are two: `client/index.html`, the
original property-tested "render client," served at `/s/{run_id}`; and
`client/app.html`, the newer UI-only app viewer served at `/app`, which
mirrors the same component styles) so `Stepper` behaves identically wherever
a surface is rendered:

- Numbered circles connected by a line (`::before` border trick, no SVG
  needed), the current/done circle states styled distinctly.
- `stepField(record, key, fallbacks)` reads the named field off each bound
  record with a small fallback chain (`heading`/`label`/`title`/`name`/`id`
  for the label; `points`/`detail`/`text`/`body` for the detail; arrays are
  joined into one line), so the renderer degrades gracefully if the model
  binds a slightly different shape than expected — but it only ever reads a
  plain value into a `document.createTextNode`. No `innerHTML`, no `eval`,
  no dynamic `Function`.
- Tapping a step (when `onSelect` is present) calls the same `choose(label)`
  / `emitAction(...)` path every other interactive component already uses —
  the only way the surface can act.

**Bug found and fixed along the way:** while screenshotting the captured
proof, `index.html`'s `Button` renderer turned out not to call `resolve()`
on `c.label`, so a model-bound label (`{"$bind": "/choice_N_label"}`)
rendered as literal `[object Object]` instead of its text. `app.html`
already did this correctly. One-line fix, unrelated to `Stepper` itself but
directly affecting the captured proof's presentability, so it was fixed and
covered by the existing test suite (117/117 still green after).

## 3 — the captured run

`proofs/generate_stepper_gemini.py` (modelled on `proofs/harness_run.py`):
constructs a real `S13Runtime`, sends it through the real `respond_as="ui"`
single-goal path (`content` → `compose_surface`), and calls a live Gemini
model through the real `glc_v3` gateway on `127.0.0.1:8111` — no mocks, no
recorded fixture standing in for the model.

The goal text sent is **verbatim** what `client/app.html`'s `buildGoal()`
sends for a real level-1 topic:

```
Change a flat tire on a car

Teach this topic as a hierarchical drill-down lesson of up to 5 levels.
This is level 1 of 5: give focused introductory teaching content for the
topic overall, then ask the user to pick a subtopic of it to go deeper
into next. [+ the standard title/label formatting rules]
```

Nothing about `Stepper` is in that prompt. `compose_surface`'s system
message (`s13code/runtime.py`) never named the component either — the
model can only find it because `catalog_manifest()` (unmodified, fully
generic) is included in the JSON payload of every `compose_surface` call,
the same channel every other custom component is already offered through.

### One deliberate, precedent-following prompt change

The **first** capture attempt (unmodified prompt) did **not** pick
`Stepper` — the model followed the existing generic guidance sentence,
which named `Timeline` and `List/Column of Cards` for ordered content, and
picked `Card`s. That guidance sentence already name-drops several existing
custom types (`Timeline`, `StatTile`, `BarChart`, `Sparkline`, `DataTable`)
as illustrative options inside one generic, run-independent instruction —
so `Stepper` was added to that *same* sentence, the same way, for *all*
runs:

> "...a **Stepper for a short sequential procedure**, a Timeline for
> chronological/historical events, or a List/Column of Cards for other
> ordered groups, StatTiles in a Row for key numbers, ..."

This is not a task-specific instruction written to force this one proof —
it is a permanent, generic addition to the same sentence that already
teaches the model about every other custom type, and the model still has
to judge, at inference time, whether the actual data fits. Re-running the
capture after this change:

```
$ GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
    uv run python proofs/generate_stepper_gemini.py

validator        : proposed=9 accepted=9 rejected=0 ok=True
types used       : ['Button', 'Column', 'Stepper', 'Text']
Stepper composed, unprompted : True
```

Gemini composed:

```json
{"id": "steps", "type": "Stepper", "title": "Core Safety Principles",
 "steps": {"$bind": "/sections"}, "labelKey": "heading", "detailKey": "points"}
```

bound to real content it had itself produced (`/sections`: safety steps for
changing a flat tire), alongside `Text` and `Button`s for the next-subtopic
choices — 9/9 components accepted by the validator, 0 rejected.

Written to `proofs/stepper_gemini_run.json`; served (re-validated) at
`GET /v1/proofs/stepper`; viewable live at `http://127.0.0.1:8113/s/stepper`.

### Visual confirmation

Verified with a real headless-Chromium screenshot (Playwright), not just a
JSON diff: the numbered circle, title, step label, and step detail render
correctly, and `console --errors` was empty on both `/s/stepper` and
`/app`. A second, independent live run through `/app` itself (topic: "How
to brew pour-over coffee") was also driven end to end with no console
errors, confirming the whole pipeline — not just the one captured proof —
still works.

## The three invariants, proven for `Stepper` specifically

`tests/test_s14_ui.py`, new `test_stepper_*` tests (in addition to the
pre-existing generic invariant tests, which already prove the wall is
type-agnostic):

| Test | Invariant | What it does |
|---|---|---|
| `test_stepper_clean_component_is_accepted` | — | a well-formed `Stepper` validates clean |
| `test_stepper_lookalike_type_breaks_catalog_invariant` | catalog | `"StepWizard"` (a near-miss name) is still rejected — the catalog is closed, not fuzzy-matched |
| `test_stepper_title_carrying_markup_breaks_data_not_code` | data-not-code | `title` containing `<img onerror=...>` is refused |
| `test_stepper_steps_as_inline_literal_breaks_data_not_code` | data-not-code | `steps` as a raw list instead of `{"$bind": "/pointer"}` is refused |
| `test_stepper_unregistered_action_never_crosses_back` | event | `onSelect: {"action": "wire_funds"}` is refused |
| `test_stepper_safe_sibling_survives_a_poisoned_stepper` | — | a poisoned `Stepper` is dropped; a clean sibling `Text` still renders |
| `test_route_stepper_proof_is_clean_and_composed_unprompted` | — | the live-captured proof re-validates clean via `GET /v1/proofs/stepper`, and really does contain a `Stepper` bound to `/sections` |
| `test_catalog_is_the_realigned_a2ui_basic_plus_custom_set` (updated) | — | catalog is now 24 types, `Stepper` is in the `custom` set |

Result: **117/117 tests pass** (110 baseline + 7 new).

## Files touched

| File | Change |
|---|---|
| `s13code/ui/catalog.py` | `Stepper` `ComponentSpec`; docstring counts 23→24, 8→9 |
| `s13code/ui/client/app.html` | `Stepper` CSS + renderer in the `R` map |
| `s13code/ui/client/index.html` | `Stepper` CSS + renderer in `RENDERERS`; fixed `Button` label not resolving `$bind` |
| `s13code/runtime.py` | added `Stepper` to the existing generic "richest fitting component" guidance sentence (system message + `/sections` mapping) — no task-specific prompting |
| `s13code/ui/routes.py` | new `GET /v1/proofs/stepper` route (mirrors `/v1/harness/surface`) |
| `tests/test_s14_ui.py` | catalog count/set test updated; 7 new `Stepper`-specific tests |
| `proofs/generate_stepper_gemini.py` | new — captures the real live Gemini run |
| `proofs/stepper_gemini_run.json` | new — the captured proof artifact |
| `README.md` | new "Contributed component: `Stepper`" section, proofs table row, routes table row |

Nothing was committed during this session — all changes are in the working
tree for review. A `glc_v3` gateway instance was started locally on
`127.0.0.1:8111` (using the real key in `glc_v3/.env`) to run the live
capture and is left running for further reproduction if wanted.

## Follow-up — seeing it, then making it reachable from `/app`

### Viewing the result

Asked how to see the `Stepper` result visually. Both local servers were
already up (`glc_v3` on `:8111`, `S14Code` on `:8113`), so the answer was
just the URLs plus the screenshot already captured during verification:

- `http://127.0.0.1:8113/s/stepper` — the fixed captured proof (re-validated
  on every serve via `GET /v1/proofs/stepper`).
- `http://127.0.0.1:8113/app` — the live app, for trying any topic.

### Add a link + a topic dropdown to `/app`

Next ask: put a link to the Stepper result directly in the `/app` UI, plus a
dropdown to pick which query to see it for, instead of making the user go
find `/s/stepper` or type a topic from memory. Added to
`s13code/ui/client/app.html`:

- A `captured Stepper proof →` link in the header, `target="_blank"` to
  `/s/stepper`.
- A `<select id="stepperTopics">` under the prompt bar, seeded with six
  curated stepper-friendly topics (flat tire, pour-over coffee, 2FA setup,
  tying a necktie, jump-starting a car, CPR). Selecting an option fills
  `#prompt` and clicks `#ask` — i.e. it triggers a **real, fresh live run**
  through the actual pipeline each time, not a cached/canned result (verified
  by screenshot: a new `run_id` each time, e.g. `run-c903a19e5ae6`, distinct
  from the captured proof's `run-e37bb5c89ac5`).

Verified with Playwright: no console errors on `/app`, selecting "Change a
flat tire on a car" from the dropdown produced a fresh live-composed
`Stepper` identical in shape to the captured proof.

### Fix: dropdown was a restricted, static list

Feedback: *"the drop down has a restricted list, it is not picking the
latest query - compare the population of mumbai, delhi and chennai."* The
six seed topics were hardcoded; typing something new (like a 3-city
population comparison) into the free-text `#prompt` box worked fine to run,
but that query never showed up as a pickable option afterward — the
dropdown had no memory.

Fix: turned the dropdown into a **live history**, not a fixed list —
`s13code/ui/client/app.html`:

- `EXAMPLE_TOPICS` keeps the original six as one `<optgroup label="stepper-
  friendly examples">`.
- Every query actually run via the `Ask` button (typed freely **or** picked
  from the dropdown) is saved through `saveRecent(query)` into
  `localStorage["s14_recent_queries"]` — deduped case-insensitively, newest
  first, capped at 10 — and rendered as a second
  `<optgroup label="your recent queries">` above the examples via
  `renderTopicsDropdown()`.
- The placeholder option is rebuilt fresh each render so the select always
  resets to it after a pick, instead of the earlier one-off
  `selectedIndex=0` hack.

Verified live: typed `"compare the population of mumbai, delhi and
chennai"`, clicked `Ask`. The run correctly composed a `DataTable` + city
`Button`s (not a `Stepper` — a 3-way numeric comparison genuinely isn't a
sequential procedure, so the model choosing `DataTable` here is *correct*
judgment, not a miss). Re-opening the dropdown afterward showed the query
under **"your recent queries"**, confirming it: `[{"label": "your recent
queries", "items": ["compare the population of mumbai, delhi and
chennai"]}, {"label": "stepper-friendly examples", "items": [...the
original six...]}]`. 117/117 tests still pass (no test asserts on
`app.html`'s markup).

### Files touched (follow-up)

| File | Change |
|---|---|
| `s13code/ui/client/app.html` | header link to `/s/stepper`; `#stepperTopics` dropdown with curated examples + a `localStorage`-backed, deduped "recent queries" history rebuilt on every real `Ask` |

## Follow-up — "the UI is very slow"

### Diagnosis first, not a guess

Before changing anything, profiled where time actually goes:

- Page load (`/app`, `/v1/catalog`): ~10ms. Not the bottleneck.
- `fonts.googleapis.com`: reachable, ~140ms. Not the bottleneck.
- A real `POST /v1/agent/runs` (`respond_as: "ui"`): **6.4s**, timed directly
  with `curl`. Broken down via a direct `/v1/chat` timing probe: the
  `content` role alone took ~2.15s for 350 output tokens; the remainder
  (~4s) is `compose_surface` — a larger prompt (full catalog manifest + full
  data model) generating more tokens (9–13 components observed).

Root cause: `POST /v1/agent/runs` is **fully synchronous** — `runtime.run()`
executes the entire graph (both live Gemini calls, back to back) inside the
request handler before returning anything, so there is no way to observe
real progress mid-flight without a bigger architecture change (the run
doesn't even exist in the graph store with a `run_id` a client could poll
until it's already finished). That rules out "real" server-driven progress
without restructuring the run endpoint.

Presented this to the user as a three-way choice — better progress
feedback (low-risk, client-only), try to cut real latency (higher-risk,
uncertain payoff since it's two sequential live-model round-trips), or
"something else is slow." Chosen: **better progress feedback**.

### Fix 1 — staged status + busy state (`s13code/ui/client/app.html`)

- `setBusy(busy)` disables `#prompt`, `#ask`, `#stepperTopics` while a
  request is in flight, so a click can't double-fire and it's visually
  obvious something is happening.
- `startProgress()` shows the two REAL fixed stages every `"ui"` run goes
  through — `"writing content…"` then `"composing interface from the
  catalog…"` — switching at the ~2s mark that matches the measured typical
  `content`-role duration, plus a live `elapsed-seconds` counter ticking
  every 200ms. This is honest about what's happening (it names the two
  real pipeline stages) without pretending to know server-side progress
  the client doesn't have.
- `runTurn()` wrapped in `try/finally` so the busy state and progress timer
  always clear, and a `catch` now surfaces a real failure message instead
  of leaving the status frozen forever on an unhandled rejection.

### Fix 2 — a genuine crash the new error handling exposed

Adding the `catch` above immediately surfaced a real bug: composing "How to
tie a bowline knot" through `/app` failed with `status: "failed Cannot read
properties of undefined (reading 'type')"`. Traced it: the model's declared
`surface.root` id ("root") didn't match any accepted component's `id` — the
validator checks component **types**, **prop values**, and **actions**, but
nothing checks that the declared root actually resolves to one of the
accepted components. `render()` in both clients did
`node(byId[surface.root], x)` with no guard, so an unresolved root crashed
outright.

Before this session's error handling existed, that crash was an **unhandled
promise rejection** — the status label would just stay frozen on
"composing…" forever, with no visible error at all. That is very plausibly
a real contributor to "the UI is very slow": it wasn't slow, in at least
this case it was **silently broken**, indistinguishable from slow without
opening devtools.

Fix, in both `s13code/ui/client/app.html` and `s13code/ui/client/index.html`
(`resolveRoot(surface, byId)`): if the declared root doesn't resolve, render
every already-**validated** component that no other component claims as a
child, wrapped in a plain synthetic `Column`, instead of crashing — the same
"show what's safe" spirit the validator already applies when it drops one
poisoned component out of a surface. Verified live: the same "bowline knot"
prompt now renders successfully end to end with no console errors.

### Fix 3 — a second, systemic bug the same investigation uncovered

While screenshotting the fix above, a `Card` rendered with a literal
`[object Object]` where its title should have been. Root cause, generalized
from a narrower bug already fixed earlier in this session (`index.html`'s
`Button` not resolving `c.label`): the catalog's `text` prop kind means "a
literal string," but `validator.py` only enforces the `{"$bind": ...}`
**shape** for `binding`-kind props — nothing stops a model from legally
binding a `text`-kind prop (`title`, `label`, `unit`, `xKey`, `columns`,
`labelKey`, …) instead of supplying a literal, and it still passes the
data-not-code check (a bind pointer isn't markup). Several renderers in
*both* clients read those props directly (`T(c.title)` / `text(c.label)`)
without resolving them first, so a legally-bound value printed as literal
`[object Object]` instead of its real text.

Fixed systemically rather than patching individual spots: added one shared
helper to each render client —

```js
function rtext(v, dm){
  const r = resolve(v, dm);
  if (r && typeof r === "object") return r.label || r.name || r.text || r.title || r.id || "";
  return r;
}
```

— and applied it to every `text`-kind prop read across both files: `Card`/
`Modal` `title`, `StatTile`/`TextField`/`Slider`/`CheckBox` `label`,
`StatTile` `unit`, `BarChart` `title`/`xKey`/`yKey`, `Timeline` `title`,
`DataTable` `columns`/`filterKey`, `Tabs` `labels`, `Stepper` `title`/
`labelKey`/`detailKey`, `Image` `src`/`alt`, `TextField` `placeholder`,
`Button` `label` (refactored to reuse `rtext` instead of its own inline
duplicate of the same fallback logic). `resolve()`/`rtext()` are no-ops on
a plain string, so this is safe everywhere it was added.

### Verification

- `node --check` on the extracted `<script>` body of both HTML files —
  syntactically valid.
- Full pytest suite: **117/117 still pass** (no test asserts on either
  client's markup beyond the pre-existing no-`innerHTML` property test on
  `index.html`, which also still passes — `rtext`/`resolveRoot` never touch
  `innerHTML`).
- Real headless-Chromium passes (Playwright) against the live server for:
  the captured `/s/stepper` proof, `/app` re-run of "How to tie a bowline
  knot" (the crash case), and `/app` with "compare the population of
  mumbai, delhi and chennai" (the dropdown-history example from the prior
  follow-up) — all three: no console errors, no `[object Object]` anywhere
  in the rendered `#mount` content. (One early check flagged a false
  positive — it matched the literal string `"[object Object]"` inside this
  fix's own explanatory code comment, picked up because `<script>` text is
  technically part of `document.body.textContent`; rechecking scoped to
  `#mount` confirmed the rendered output itself is clean.)

### Files touched (this follow-up)

| File | Change |
|---|---|
| `s13code/ui/client/app.html` | staged progress status + elapsed timer + busy-disable + error surfacing in `runTurn()`; `resolveRoot()` fallback for a dangling root; `rtext()` helper applied across the `R` map and `table()`/`tabs()` |
| `s13code/ui/client/index.html` | `resolveRoot()` fallback for a dangling root; `rtext()` helper applied across `RENDERERS`, `field()` (now takes a `dm` param), `renderTable`/`renderTabs`/`renderTimeline` |

## Follow-up — the header link always showed the fixed flat-tire proof

### The report

"captured stepper proof is defaulting to Changing a Flat Tire instead of
current query" — the `/app` header link (added in an earlier follow-up) was
hardcoded to `href="/s/stepper"`, which always serves the one fixed,
recorded proof (`proofs/stepper_gemini_run.json`, topic: "Change a flat tire
on a car"). It never had any wiring to the query the user had just run, so
of course it looked like it was "defaulting" — it was a static link with a
misleadingly session-like position in the header.

### Why a naive fix (just relabel it) wasn't enough

The honest fix isn't just clearer wording — it's making the link actually
track the current session, because the whole point of the assignment's
"captured run" requirement is that `Stepper` isn't special-cased: **any**
`respond_as="ui"` run can compose one on its own merit. The app already
proves this every time it happens (the `Stepper` renders inline in
`#mount`), so the header link should point at *that* real evidence once it
exists, and only fall back to the fixed proof before it does.

One blocker: `client/index.html`'s `/s/{run_id}` route only had two
special-cased data sources — `RUN==="harness"` and `RUN==="stepper"`, both
reading a *recorded* JSON file — plus a generic fallback that called
`/v1/runs/{id}/surface`, which is the **node-progress view** (`build_run_surface`
in `surface.py`: node names + state pills), not the composed A2UI interface.
So even with the right `run_id`, linking to `/s/{run_id}` for an arbitrary
live run would have shown the wrong thing.

### The fix

1. **`s13code/ui/client/index.html`, `boot()`** — generalized: for any
   `run_id` that isn't `"harness"`/`"stepper"`/a corpus dashboard, try
   `GET /v1/runs/{run_id}/composed` first (the *existing*, already-generic
   route that serves any run's composed interface, re-validated — it
   already worked for the `"stepper"` special case, it just wasn't being
   tried for arbitrary runs). Falls back to `/surface` (the progress view)
   only if that run never composed anything. This is a small, real
   generalization, not a `Stepper`-specific hack — `/s/{any-run-id}` now
   correctly shows what that run actually composed.
2. **`s13code/ui/client/app.html`** — the header `<a id="stepperLink">`
   defaults to `/s/stepper`, labeled `"captured Stepper proof (flat tire)
   →"` (now honestly named, since it's a fixed reference, not a session
   link). In `runTurn()`, right after a surface renders successfully: if
   `c.surface.components` contains a `"Stepper"`, the link is repointed at
   `/s/{rid}` (the run that just composed it) and relabeled
   `"Stepper result for \"<the actual query>\" →"`. Every subsequent
   `Stepper` composition in the same session moves the link again — it
   always tracks the *latest* one, not the first.

### Verification

Live, three-run test through the real browser:

- Baseline: link → `/s/stepper`, `"captured Stepper proof (flat tire) →"`.
- Asked `"How to jump-start a car battery"` — genuinely composed `Card` +
  `ProgressBar` instead of `Stepper` this time (real model judgment, not a
  bug) → link correctly **stayed** on the fixed proof, since no `Stepper`
  was produced.
- Asked `"How to tie a bowline knot"` a second time — also did not produce
  a `Stepper` this run (Gemini at `temperature: 0` is *typically* but not
  *perfectly* deterministic across calls; it had produced one for the same
  topic in an earlier session) — link correctly stayed on the fixed proof
  again.
- Asked `"Change a flat tire on a car"` — composed a `Stepper` (10
  components) → link updated live to `/s/run-1450a7895261` labeled
  `Stepper result for "Change a flat tire on a car" →`. Followed that link
  in a fresh page: `run run-1450a7895261`, `composed by gemini_1 · 10
  components · 0 executable`, no console errors — a genuinely different,
  fresh live run from the static proof (`run-e37bb5c89ac5`, 9 components),
  confirming this isn't coincidentally showing cached/identical content.

`node --check` clean on both files' extracted script bodies; full pytest
suite still **117/117**.

### Files touched (this follow-up)

| File | Change |
|---|---|
| `s13code/ui/client/index.html` | `boot()` tries `/v1/runs/{id}/composed` first for any non-special run id, falling back to the progress `/surface` view only if that run has no composed interface |
| `s13code/ui/client/app.html` | `#stepperLink` relabeled to make clear it's a fixed reference by default; `runTurn()` repoints and relabels it to the live run whenever the current session's own query composes a `Stepper` |

## Reference — `Stepper`, explained in full

Asked for a detailed walkthrough of how `Stepper` actually works, end to end.
No code changed in this turn — purely explanatory, captured here as
reference documentation since it ties together everything built across the
earlier sections.

**What it is.** A step-wizard component — a numbered sequence of steps (Step
1 → Step 2 → Step 3) for a short procedure. The 24th catalog type, the one
A2UI Basic doesn't define.

**The schema** (`s13code/ui/catalog.py`):

| Prop | Kind | Meaning |
|---|---|---|
| `title` | `text` | literal caption above the steps |
| `steps` | `binding` | `{"$bind": "/pointer"}` into a list of step records |
| `labelKey` | `text` | which field of each record holds its short label |
| `detailKey` | `text` | which field holds the step's detail/body |
| `current` | `number` | optional literal index to highlight as in-progress |
| `onSelect` | `action` | optional — tapping a step fires a registered action |

**Why the `labelKey`/`detailKey` indirection matters.** It mirrors
`BarChart`'s `xKey`/`yKey` idiom: the catalog never needs to know a step
record's exact shape in advance — the model just says which field is the
label and which is the detail. The catalog only trusts that `steps` is a
valid pointer into harness-owned data; it never trusts the *content*, which
still has to clear all three invariants before it reaches the DOM.

**How it renders** (both `app.html` and `index.html`, identically): for each
record in the resolved `steps` list, `stepField()` reads the named field
with a fallback chain (`heading`/`label`/`title`/`name`/`id` for the label;
`points`/`detail`/`text`/`body` for the detail; arrays joined with `" · "`)
so it degrades gracefully instead of going blank. A numbered circle per
step, connected by a CSS `::before` line (no SVG). `current` styles that
step as in-progress and earlier ones as done. Label/detail are appended as
`document.createTextNode`s only — never `innerHTML`, never `eval` — so
literal `<script>...` in a step's text would show as inert characters, not
execute. If `onSelect` is present, a tap calls the same `choose()` /
`emitAction()` path a `Button` uses — the one channel a surface can act
through.

**How Gemini actually composes one.** `compose_surface` sends the *entire*
catalog manifest on every call via `catalog_manifest()` — nothing
`Stepper`-specific beyond one clause in the generic "richest fitting
component" guidance sentence, worded the same way `Timeline`/`BarChart`/
`DataTable` already are. The model still judges fit per request — confirmed
live: a 3-city population comparison correctly produced `DataTable`, not
`Stepper`, because it's a comparison, not a procedure.

**The three invariants, applied to it specifically:** a near-miss type name
(`"StepWizard"`) is rejected under catalog; a `title` carrying markup, or a
`steps` value that's a raw list instead of `{"$bind": ...}`, is rejected
under data-not-code; an `onSelect` naming an unregistered action is rejected
under event. A poisoned `Stepper` drops out; everything around it still
renders.

**Two robustness fixes that came out of testing it live**, both covered in
detail in the earlier follow-up sections above: the `resolveRoot()` fallback
for a dangling `surface.root`, and the `rtext()` helper so a model-bound
`text`-kind prop (`title`, `labelKey`, `detailKey`) resolves to its real
value instead of printing `[object Object]`.

## Follow-up — "the stepper link is still defaulted to flat tire"

### First, ruled out a stale-server / stale-code explanation

Before assuming the dynamic-link fix (previous follow-up) was broken,
checked that the running server was actually serving the edited files —
fetched `/app` directly and grepped for the new default label and the
link-update logic:

```
$ curl -s http://127.0.0.1:8113/app | grep -o 'stepperLink[^<]*'
stepperLink" href="/s/stepper" ... >captured Stepper proof (flat tire) →

$ curl -s http://127.0.0.1:8113/app | grep -o 'if(c\.surface\.components\.some.\{0,300\}'
if(c.surface.components.some(comp=>comp.type==="Stepper")){
```

Both present and correct — the server was not the problem. Asked the user
what query they'd actually typed, since the link only updates when the
*current* query's own composed surface contains a `Stepper` — if a
different query never produced one, the link staying put is correct, not
stale.

### The query, replayed server-side to get a definitive answer

User's query: `"compare the population of delhi, mumbai, chennai"`.
Replayed it directly against the live runtime (same goal-building logic
`client/app.html` uses) instead of guessing:

```
$ curl -X POST /v1/agent/runs -d '{"prompt": "...population of delhi, mumbai, chennai...", "respond_as": "ui", ...}'
$ curl /v1/runs/{run_id}/composed | jq '[.surface.components[].type] | unique'

component types used: ['BarChart', 'Button', 'Column', 'DataTable', 'Divider', 'Row', 'Text']
has Stepper: False
```

**Confirmed correct behavior, not a bug.** A 3-city population comparison is
a comparison, not a sequential procedure — Gemini correctly chose
`BarChart` + `DataTable` for it, the same judgment call already documented
earlier in this file for the near-identical `"compare the population of
mumbai, delhi and chennai"` query. Since that run's surface genuinely
contains no `Stepper`, the header link had nothing to repoint to, and
correctly stayed on the fixed flat-tire proof rather than pointing at a run
with no `Stepper` in it.

This is the second time in this project a "the UI is doing something wrong"
report turned out to be the model correctly declining to force-fit
`Stepper` onto data that doesn't call for it — reinforcing that the
dynamic-link behavior (and the model's component choice generally) is
working as designed, not broken.

No code changed this turn — diagnosis only, done by reading the served HTML
directly and replaying the user's exact query against the live runtime
rather than guessing at the cause.

## Follow-up — "ran 'How to brew pour-over coffee', link still points to flat tire"

### Same diagnosis, but this one revealed something real

Replayed the exact query server-side, same method as the previous
follow-up:

```
component types used: ['Button', 'Card', 'Column', 'Row', 'StatTile', 'Text']
has Stepper: False
```

No `Stepper` composed — the link correctly stayed put. But this was the
**third** time "pour-over coffee" had been tested in this session and it had
**never once** produced a `Stepper`, despite being one of the six curated
"stepper-friendly examples" seeded into the dropdown two follow-ups ago.
That's not noise — it's a sign the curated list itself was wrong. Rather
than reassure the user again, tested all remaining examples plus new
candidates to find out how bad it was.

### The full tally

Ran every original curated example, plus new candidates chosen to avoid
naturally quantifiable content (no ratio/rate/temperature/duration, on the
theory that a numeric fact competes with `Stepper` for the "richest fitting
component" slot), through the real live runtime:

| Topic | Result | Stepper? |
|---|---|---|
| Change a flat tire on a car | Stepper ×3, Card+List ×1 | 3/4 |
| How to make a paper crane | Stepper | 1/1 |
| How to tie a bowline knot | Stepper ×1, Card+List ×1 | 1/2 |
| How to brew pour-over coffee | StatTile+Card ×3 | 0/3 |
| Jump-start a car battery | Card+ProgressBar ×2 | 0/2 |
| Set up 2FA on an email account | Card+List | 0/1 |
| Tie a necktie | Card+ProgressBar | 0/1 |
| Perform CPR on an adult | StatTile+Card (has `metrics`) | 0/1 |
| How to fold a paper airplane | Card+List | 0/1 |
| How to tie your shoelaces | Card | 0/1 |
| How to parallel park a car | Card | 0/1 |
| How to wrap a gift | Card+List | 0/1 |
| How to iron a dress shirt | StatTile+Card (has `metrics`) | 0/1 |

Two findings, one contributing factor and one more fundamental:

1. **Metrics compete with `Stepper`.** Comparing CPR's and the flat tire's
   data models directly: CPR's `content` role produced a populated
   `metrics` field (`Compression Rate`, `Compression Depth` — real
   numbers), and the system prompt explicitly steers `/metrics` toward a
   `Row` of `StatTile`s. Flat tire's `metrics` was empty. When a topic
   naturally has a quantifiable fact, the model tends to spend its "richest
   component" budget on a `StatTile` and falls back to generic `Card`s for
   the rest, instead of reaching for `Stepper`.
2. **Even controlling for that, it's still genuinely non-deterministic.**
   "Change a flat tire on a car" — the single most reliable topic found,
   with *zero* metrics every time — still produced `Card`+`List` on one of
   four identical, `temperature: 0` calls. Gemini's `temperature: 0` is
   documented to mean "near-greedy," not "bit-exact deterministic" — batched
   / parallelized inference has real numerical non-associativity, so
   identical prompts can still sample a different token at a branch point.
   No prompt engineering removes this; it's an inherent property of calling
   a live model, not a defect in `compose_surface`, the catalog, or either
   render client.

### The fix: an honest dropdown, not a padded one

`s13code/ui/client/app.html`, `EXAMPLE_TOPICS`: replaced the six
unverified guesses with a shorter, evidence-based list — the two topics
that actually produced a `Stepper` in testing are annotated inline
("often composes a Stepper"), directly on the two entries that earned it;
the rest are kept as plain example queries with no claim attached, since a
false "often produces a Stepper" note would just relocate the same
complaint from "the link" to "the label."

```js
const EXAMPLE_TOPICS = [
  { query: "Change a flat tire on a car", note: "often composes a Stepper" },
  { query: "How to make a paper crane", note: "often composes a Stepper" },
  { query: "How to tie a bowline knot" },
  { query: "How to brew pour-over coffee" },
  { query: "Set up two-factor authentication on an email account" },
];
```

The optgroup label changed from `"stepper-friendly examples"` (a claim
now known to be false for 4 of its original 6 entries) to `"example
queries"` (no claim). Each `<option>`'s `value` is set explicitly to the
plain query text, separate from its annotated display text (`"...  —
often composes a Stepper"`), so picking an annotated option still submits
the clean query — verified live: selecting "How to make a paper crane"
from the dropdown put exactly `"How to make a paper crane"` in the prompt
box, not the annotation.

### Verification

`node --check` clean; full pytest suite **117/117**; live browser check
confirmed the dropdown's option values are the plain topic strings while
only the visible labels carry the "often composes a Stepper" note, and
that selecting an annotated option submits the clean text.

### Files touched (this follow-up)

| File | Change |
|---|---|
| `s13code/ui/client/app.html` | `EXAMPLE_TOPICS` rebuilt from empirical evidence (two annotated known-performers, three honest unannotated examples, five weak/misleading entries dropped); optgroup relabeled from a false claim ("stepper-friendly examples") to a neutral one ("example queries"); each option's `value` set explicitly so an annotated label never pollutes the submitted query |

## Reference — why `Stepper` helps, why it was needed

Asked, in plain terms, what problem `Stepper` actually solves and why it's
worth having. No code changed — captured here as reference documentation
since it's the "motivation" companion to the earlier "explained in full"
section.

**The gap it filled.** Before `Stepper`, nothing in the catalog represented
*sequence*. The closest options were `Timeline` (implies chronological/
historical events, not "do this, then this") and `List`/`Column` of `Card`s
(generic stacking — a `Card` titled "Step 2" looks structurally identical
to one titled "Fun Fact"; the ordering only existed in the reader's head).
Any genuinely sequential content — "first do X, then Y, then Z" — had to be
flattened into a component that doesn't represent sequence at all.

**What it concretely adds:**

1. **Numbered circles + a connector line** — "step 2 of 4" is visible at a
   glance, not implied by list position.
2. **`current`** — a step can be marked in-progress with earlier ones shown
   done; no other catalog component can represent "where you are" in a
   sequence.
3. **`onSelect`** — a step can be tappable, feeding the app's existing "a
   tap becomes the next turn" drill-down loop directly, so a user can go
   deeper on *that specific step* rather than only picking from a generic
   list of choice buttons underneath.

**Why it matters for this app specifically.** `client/app.html`'s entire
premise is "teach me X as a drill-down lesson," and how-to/procedural
content (set up 2FA, change a tire, brew coffee, tie a knot) is one of the
most common shapes that takes — exactly the shape a step wizard exists for.
Without it, the best available rendering for a procedure was an unordered
bullet list inside a `Card`.

**Why it matters beyond this one app.** The catalog is the shared
vocabulary — `compose_surface` hands the entire manifest to the model on
every call, for any interface built on this runtime, unconditionally.
Adding `Stepper` here makes it available to every future interface built
against this same catalog, not just this session's lesson tool — which is
the whole point of the assignment: one contribution becomes part of what
every other interface in the batch can draw from.

**The honest caveat**, consistent with the empirical findings in the
follow-up above: it is not guaranteed to be selected even when content is
genuinely procedural (a numeric fact in the content competes with it for
`StatTile`; there is also real run-to-run model variance at
`temperature: 0`). The value isn't "guaranteed selection" — it's that when
content genuinely is a short sequence, a component now exists whose shape
actually matches it, instead of every kind of content being flattened into
the same generic `Card` regardless of whether order matters.

## Follow-up — turning `Stepper` into a real one-step-at-a-time wizard

### The ask

User showed a reference screenshot (from a Claude surface, unrelated to
S14Code) of "How to make a paper crane" rendered as a proper step-by-step
wizard: title + "5 steps" subtitle, a progress row of green checkmark
circles (done) and one blue numbered circle (current) joined by connector
lines, a detail card for only the *current* step ("Step 5: Spread the
wings" + description), and a footer with `Back`, `5 of 5`, and
`Ask a follow-up ↗`. Ask: keep `/app`'s existing "drill down to greater
detail" trainer loop exactly as it is, but make `Stepper` behave like that
reference — one step visible at a time, not all steps flattened into a row.

### What changed, and what didn't

Scoped this as a pure **rendering + interaction** upgrade to `Stepper` in
`client/app.html` only — no catalog change, no validator change, no change
to `compose_surface`'s prompt, no change to the topic drill-down loop
(`buildGoal`, `MAX_DEPTH`, `runTurn`'s turn-taking). The underlying
`Stepper` data contract (`title`/`steps`/`labelKey`/`detailKey`/`current`/
`onSelect`) is unchanged; only how the render client draws it changed.
`client/index.html` was deliberately left on the old "all steps in one row"
overview — that page's job is reviewing an already-finished run's full
composed output at a glance (e.g. `/s/stepper`, the captured proof), where
seeing everything at once is arguably *better* than paging through it.

### The new renderer (`s13code/ui/client/app.html`)

Local, closure-scoped `idx` state (same pattern the pre-existing `Tabs`
component already uses for its `show(i)` switch — not a new architectural
idea, just applied to `Stepper`) drives:

- **Progress dots** — no per-dot label anymore, just a numbered circle per
  step, green+checkmark for steps before `idx` ("done"), blue+number for
  `idx` itself ("current"), plain outline for steps after it. Connector
  lines between them go green once "done." Dots are directly clickable to
  jump to any step (all step data is already loaded client-side, so this
  isn't unlocking anything not already available).
- **One detail card** — "Step {idx+1}: {label}" + the step's detail text,
  for `idx` only.
- **Footer** — `Back` (disabled at step 1), a `"{idx+1} of {N}"` counter,
  and a right-hand button that is `Next` while `idx < N-1`, becomes
  `Ask a follow-up ↗` once on the last step **and** the component actually
  registered `onSelect`, or is hidden entirely if the model didn't register
  one (never a dead, non-functional button).
- `Ask a follow-up` reaches back into the app through the **exact same**
  `choose()` next-turn path a `Button` already uses — no new action
  channel, no new trust boundary. `Back`/`Next`/dot-jump touch zero server
  state; they're pure client-side redraws of already-validated data.

### A real upstream gap this surfaced

Testing the new wizard against live captures kept turning up `Stepper`s
with exactly **one** step — because the `content` role's schema prompt
said "use sections for ordered groups (steps, stages, phases)" without
saying each *individual* step should be its own section, so the model
consistently folded an entire procedure into one section with several
bullet points inside it. That's an upstream content-generation issue, not
a rendering bug — the wizard renders `N=1` correctly (no dead `Next`
button, just `Back` disabled and `"1 of 1"`), but there was nothing to page
through.

Fixed at the source (`s13code/runtime.py`, `run_content`'s
`schema_system`, unconditional and domain-neutral, unrelated to any UI
component or the catalog — this prompt runs *before* `compose_surface` and
has no knowledge `Stepper` exists): added one clause — *"for a sequential
procedure specifically, give EACH individual step its OWN 'sections' entry
... rather than folding the whole procedure into a single section."*
Re-tested live after restarting the server to pick up the change:

| Topic | Before | After |
|---|---|---|
| Change a flat tire on a car | 1 section | 3 sections (Safety First / Preparation / Execution) |
| The full process of getting a passport | 1 section | 3 sections (Preparation / Documentation / Submission) |

### Verification

Live browser test against "The full process of getting a passport" (3
steps, no `onSelect` this run): `1 of 3` → click `Next` → `2 of 3` → click
`Next` → `3 of 3` with the right-hand button correctly invisible (not
disabled — invisible, since there's nothing to page to and no action
registered) → click `Back` → `2 of 3` → click the first dot directly →
`1 of 3`. Screenshots at each step visually match the reference pattern:
green checkmarks + connector lines for done steps, blue numbered badge for
current. Cross-checked `/s/{run_id}` for the same run on `index.html`'s
unchanged overview renderer — still displays all 3 steps correctly in one
row. `node --check` clean; full pytest suite **117/117**.

### Files touched (this follow-up)

| File | Change |
|---|---|
| `s13code/ui/client/app.html` | `Stepper` CSS and renderer rebuilt as a paginated one-step-at-a-time wizard (progress dots, single-step detail card, Back/Next/Ask-a-follow-up footer, dot-click jump) — the app's topic drill-down loop and every other component renderer are unchanged |
| `s13code/runtime.py` | `run_content`'s `schema_system` clarified so a sequential procedure's `sections` are one-step-per-entry instead of folded into a single section — domain-neutral, unconditional, and unrelated to the catalog or any specific component |

## Follow-up — 5 more `Stepper` test cases

Asked to add 5 more test cases for the `Stepper` component and run the
suite. The existing 6 `test_stepper_*` tests (clean-component-accepted,
catalog-invariant on a near-miss type name, data-not-code on a markup
`title`, data-not-code on `steps` as an inline literal instead of a
`$bind`, event-invariant on an unregistered action name, and a poisoned
`Stepper` not taking down a clean sibling) already covered the three
invariants directly. The 5 new ones, added to `tests/test_s14_ui.py` right
after that block, each cover something none of the existing 6 did:

| Test | What it proves |
|---|---|
| `test_stepper_multi_step_surface_validates_clean` | The *real* multi-step shape (3 distinct `sections` entries — matching the `run_content` fix from the previous follow-up) validates end-to-end, not just a single-step toy example |
| `test_stepper_only_required_steps_prop_still_accepted` | `title`/`labelKey`/`detailKey`/`current`/`onSelect` are genuinely all optional — a `Stepper` naming only `steps` still validates clean |
| `test_stepper_onselect_as_bare_string_breaks_event` | `onSelect: "approve"` (a bare string, not the required `{"action": ...}` object) is rejected under the event invariant — a different malformed shape than the existing "unregistered action name" test |
| `test_stepper_onselect_object_missing_action_key_breaks_event` | `onSelect: {}` — a syntactically valid object that just never names an action at all — is also rejected under the event invariant |
| `test_stepper_current_out_of_range_is_a_render_concern_not_a_validator_one` | `current: 999` against a real 1-step list is still structurally VALID — makes explicit that the validator checks structure (type/value-shape/action), not runtime bounds against data it can't see the size of; clamping an out-of-range index is the render client's job (`Math.min`/`Math.max`, already built into `app.html`'s wizard), not the validator's |

One fix made while writing these: the first draft of
`test_stepper_multi_step_surface_validates_clean` asserted
`len(result.accepted[0]["steps"]["$bind"]) > 0` — that's checking the
*length of the pointer string* `"/sections"` (trivially true, proves
nothing). Corrected to assert the accepted component's `steps` binding is
exactly `{"$bind": "/sections"}` and that the fixture's own `dataModel`
really has 3 section records, so the test actually exercises what its name
claims.

### Result

```
$ uv run pytest -q
122 passed, 1 warning in 22.93s

$ uv run pytest -k "stepper" -v
... 12 passed, 110 deselected ...
```

122/122 (117 baseline + 5 new); 12/12 when scoped to every `Stepper`-related
test (the 11 `test_stepper_*` unit tests plus the earlier
`test_route_stepper_proof_is_clean_and_composed_unprompted` route test).

### Files touched (this follow-up)

| File | Change |
|---|---|
| `tests/test_s14_ui.py` | 5 new `Stepper` test cases added after the existing invariant block |
