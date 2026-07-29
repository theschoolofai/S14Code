# UI enhancement — conversation log

## User request

> enhance the app ui to show functionality as shown in the image -

*(image: a "Session 14 hero" screenshot — "The model composes the surface; the
client renders it" — showing two toggle pills ("Harness-composed surface" /
"Model draws HTML"), a badge row ("composed by gemini_3 inside the live graph
· 16 components · 0 executable", "composed by gemini-3.1-flash-lite · 0
model-authored code", "run run-cc3b2834e1c1"), a live graph breadcrumb
("graph › search_1/2/3 (gemini) › distill (gemini) › compose_surface
(gemini)"), a population-comparison dashboard (stat tiles for cities/sources/
research nodes, a bar chart, a trend sparkline, a filterable/sortable data
table, city selector pills, an answer paragraph, a progress bar), and a dark
"Process Timeline" console of run events.)*

## Investigation

- `s13code/ui/client/app.html` — the bare-minimal "app" viewer (drill-down
  lesson demo). Had uncommitted in-progress changes for a 5-level teaching
  drill-down feature (unrelated to this request).
- `s13code/ui/client/index.html` — the fuller render client, already
  supporting `StatTile`, `BarChart`, `Sparkline`, filterable/sortable
  `DataTable`, `Tabs`, `ProgressBar`, and a dark `.tl` timeline console — the
  visual language the screenshot draws on.
- `docs/s14architecture.md` (pre-existing verification doc) explicitly flags
  that the screenshot's "Model draws HTML vs. Declarative surface" toggle
  demo is **lesson narrative that isn't implemented anywhere in this repo** —
  the render client here never executes model-authored markup, by design
  (no `innerHTML` from any bound value).
- `s13code/runtime.py` confirmed the breadcrumb's node path
  (`search_1/2/3` → `distill` → `compose_surface`) is real, existing live-graph
  behavior (`compose_research` mode: parallel `researcher` nodes → a
  `distiller` node → a terminal `compose_surface` node), not something to
  invent.
- `s13code/ui/routes.py` confirmed the data needed already exists via
  `GET /v1/agent/runs/{id}` (nodes, edges, events) and
  `GET /v1/runs/{id}/composed` (provider, model, component_count) — no new
  backend endpoints were needed.

## Clarification asked

Because the screenshot's two toggle pills map to a demo the architecture doc
says was never built — and building the "Model draws HTML" side for real
would mean adding an actual `innerHTML`-execution path for model output,
contradicting the app's entire security thesis — a scope question was asked
before writing code:

1. **Safe chrome only (chosen)** — enhance `app.html`'s header/breadcrumb/
   timeline with real live-graph data, drop the unsafe toggle.
2. Full toggle including an intentionally unsafe demo path.
3. Static visual styling only, no real data wiring.

**User chose option 1.**

## What was implemented

All in `s13code/ui/client/app.html`, reading only existing endpoints
(`POST /v1/agent/runs`, `GET /v1/runs/{id}/composed`,
`GET /v1/agent/runs/{id}`) — no backend changes, no new execution paths:

- **Badges bar** — green pill `composed by <provider> inside the live graph ·
  N components · 0 executable`, a muted `composed by <model> · 0
  model-authored code` line, and the run id.
- **Live graph breadcrumb** — e.g. `graph › search_1/2/3 (gemini) › distiller
  (gemini) › compose_surface (gemini)`, built from the run's real nodes/
  events: parallel sibling nodes (same skill, `prefix_N` ids) collapse into
  one id-range chip; singleton nodes are labeled by skill (more descriptive
  than a bare id like `surface`); each chip is tagged with the provider that
  actually answered that node.
- **Process Timeline console** — dark monospace log of the run's real event
  tape (sequence, kind, node id), styled after `index.html`'s existing `.tl`
  console.

The existing 5-level drill-down lesson behavior and the render engine's
no-innerHTML guarantee were both left untouched.

## Verification performed

- Extracted and syntax-checked the embedded `<script>` with `node --check`.
- Ran the full `tests/test_s14_ui.py` suite (58 tests) before and after —
  unchanged, all passing.
- Drove a real run through `TestClient(app)` with a multi-entity prompt
  ("Compare the population of London, Berlin and Paris"), faking only the
  LLM calls (not the graph/runtime logic), and confirmed the runtime really
  produces `search_1/2/3 → distill → surface` nodes with `gemini_N`-style
  provider tags and a `gemini_3` / `gemini-3.1-flash-lite` provider/model
  pair on the composed surface — matching the screenshot's data shape.
- Fed that real JSON output through the actual breadcrumb/badge-building JS
  (extracted and run under Node) and confirmed it renders:
  `graph › search_1/2/3 (gemini) › distiller (gemini) › compose_surface (gemini)`
  `composed by gemini_3 inside the live graph · 4 components · 0 executable`
  `composed by gemini-3.1-flash-lite · 0 model-authored code`
