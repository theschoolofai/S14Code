# S14Code

`S14Code` is the Session 14 runtime. It is the **entire Session 13 agent
runtime** — a live task graph, scoped and provenance-bearing memory, Rohan's
semantic chunking V2, and Agent2Agent interoperability — with the **Session 14
generative-UI layer folded in as one service**. There is no separate UI process:
the same FastAPI app that serves the agent API also serves the catalog,
validator, surface builder, AG-UI stream, and render client, reading the
runtime's graph **in-process**. It asks `glc_v3` for model completions over HTTP
and never owns provider credentials.

The load-bearing claim of Session 14, enforced by
[`s13code/ui/validator.py`](s13code/ui/validator.py):

> A surface is **declarative data**, checked against a catalog the client
> already trusts. Three invariants hold:
> - **catalog** — every component `type` is in the trusted catalog;
> - **data-not-code** — no property is ever evaluated as script, markup, or a URL;
> - **event** — the surface changes the world only by emitting a registered action.

The UI layer holds **no provider credentials**. It reads the graph the agent
already produced and calls no model directly; the generative path (the
`compose_surface` skill inside a live run) routes through the `glc_v3` gateway,
exactly as the rest of the runtime does.

## What runs where

Two services, not three. The Session 14 UI is part of the runtime on 8113.

| Service | Default address | Responsibility |
|---|---|---|
| `glc_v3` | `http://127.0.0.1:8111` | Models, keys, routing and channels (owns every credential) |
| `S14Code` HTTP | `http://127.0.0.1:8113` | Agent API (graph, memory, documents, JSON-RPC A2A) **and** the UI (catalog, validator, surface, AG-UI stream, render client) |
| `S14Code` gRPC | `127.0.0.1:8114` | Official A2A gRPC service |
| Ollama | `http://127.0.0.1:11434` | Phi-4 segmentation and Nomic embeddings |

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- A running `glc_v3` (for live runs and the generative UI loop)
- A running Ollama with `phi4` and `nomic-embed-text` (for live semantic chunking)

```bash
ollama pull phi4
ollama pull nomic-embed-text
ollama serve
```

The recorded proofs, invariant tests, and `/v1/harness/surface` need none of the
above — they replay real captured output.

## Install and run

```bash
uv sync

export GLC_BASE_URL=http://127.0.0.1:8111
export S13_GATEWAY_PROVIDER=gemini
export S13_SANDBOX_ROOT="$PWD/sandbox"
export S13_CHUNK_MODEL=phi4:latest
export S13_LIVE_SEMANTIC_CHUNKING=1

uv run s14code serve            # http://127.0.0.1:8113  (agent API + UI)
```

State is written under `~/.s13code` by default. Set `S13_DATA_DIR` to use
another directory.

Health, the trusted catalog, and the real harness-composed surface:

```bash
curl http://127.0.0.1:8113/healthz
curl http://127.0.0.1:8113/v1/catalog
open  http://127.0.0.1:8113/s/harness      # the render client, which executes nothing
```

## Run a prompt

```bash
curl -s http://127.0.0.1:8113/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_id": "course",
    "project_id": "s14",
    "user_id": "student-01",
    "agent_id": "assistant",
    "prompt": "Say hello."
  }'
```

The response contains the final answer, graph nodes and edges, ordered graph
events, and provider/agent assignments. Once a run exists, the UI routes render
it straight from the in-process graph:

```bash
curl http://127.0.0.1:8113/v1/agent/runs/<run-id>       # the raw journal
curl http://127.0.0.1:8113/v1/runs/<run-id>/surface     # validated A2UI surface
curl http://127.0.0.1:8113/v1/runs/<run-id>/dashboard   # the rich showcase dashboard
curl http://127.0.0.1:8113/v1/runs/<run-id>/events      # AG-UI events over SSE
open  http://127.0.0.1:8113/s/<run-id>                   # render it in a browser
```

## The UI routes

All served by the runtime on 8113, defined in
[`s13code/ui/routes.py`](s13code/ui/routes.py):

| Route | Serves |
|---|---|
| `GET /v1/catalog` | the trusted component catalog |
| `GET /v1/runs/{id}/surface` | a validated declarative surface built from the in-process graph |
| `GET /v1/runs/{id}/dashboard` | the rich showcase dashboard, validated |
| `GET /v1/runs/{id}/events` | the S13 journal mapped to AG-UI events over SSE |
| `GET /v1/harness/surface` | the real surface a recorded S13 harness run composed (re-validated on serve) |
| `POST /v1/validate` | run any surface through the injection wall |
| `POST /v1/action` | a validated user action (approve/reject), bound to final params |
| `GET /s/{id}` | the render client, pointed at a run |

## The generative loop (UI composed by the harness)

The surface is composed by a **skill node inside a real live-graph run**, not by
a standalone prompt. The `compose_surface` skill lives in
[`s13code/runtime.py`](s13code/runtime.py) (grep `# --- S14 additive` and
`# --- S14 outcome-aware`) and imports the catalog and validator from
`s13code.ui`. A real run researches, distills, then composes the A2UI surface via
the gateway; the validator checks the model's own output.

```bash
# gateway on 8111 (provider=gemini); Ollama with nomic-embed-text for episode embedding
S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
  uv run python proofs/harness_run.py          # -> proofs/harness_run.json

# the outcome-aware planner: weak evidence earns a corrective node before compose
S14_SELFCORRECT_CITY=Berlin GLC_BASE_URL=http://127.0.0.1:8111 \
  uv run python proofs/harness_selfcorrect.py  # -> proofs/harness_selfcorrect.json

# HeatMap: never named in the prompt or in compose_surface's own instructions —
# only reachable through the catalog manifest, same as every other component
S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
  uv run python proofs/heatmap_run.py          # -> proofs/heatmap_run.json
```

## The HeatMap component (Session 14 catalog contribution)

`HeatMap` is the catalog's 24th component (9th custom extension) —
[`s13code/ui/catalog.py`](s13code/ui/catalog.py) — for rendering a matrix of
comparable numbers: row labels, column labels and a numeric `cells` grid, all
three as bindings into the harness-owned data model. Nothing in
`compose_surface`'s prompt (`s13code/runtime.py`) names it; the model reaches
for it, if at all, purely from the catalog manifest and the shape of
`available_pointers` — the same claim the rest of the catalog makes for every
other component. [`proofs/heatmap_run.py`](proofs/heatmap_run.py) proves this
against a real Gemini call: `proofs/heatmap_run.json` captures Gemini composing
a "Performance Matrix" / "Profit/Loss Matrix" `HeatMap` unprompted, `0`
validator rejections, correctly bound to `/matrix_rows` `/matrix_columns`
`/matrix_cells` — derived mechanically in `_matrix_from_table()` from whichever
real table the run's `content` role happened to produce.

Adding a component means it joins the vocabulary the *whole* catalog composes
with, so the same three invariants the top of this README quotes have to hold
for `HeatMap` specifically, not just in the abstract — each one demonstrated
by a test in [`tests/test_s14_ui.py`](tests/test_s14_ui.py), not asserted by
prose:

- **catalog** — `test_heatmap_catalog_invariant_accepts_the_real_type_and_rejects_a_near_miss`
  puts a real `HeatMap` and a wrong-cased `Heatmap` in the *same* surface: the
  real one is accepted, the near-miss is rejected under `Invariant.CATALOG` —
  proving the check discriminates for this component, not just for an
  unrelated placeholder like `"Wormhole"`.
- **data-not-code** — the most heavily tested of the three:
  `test_heatmap_rejects_an_inline_literal_where_a_binding_belongs` (an inline
  literal where `rows`/`columns`/`cells` must be a `{"$bind": ...}`),
  `test_heatmap_rejects_markup_in_its_literal_title` (an `<img onerror>` in
  `title`), and `test_heatmap_rejects_a_handler_shaped_property_it_never_declared`
  (a bare `onclick`) all fail the same way `HeatMap` fails everywhere else in
  the catalog.
- **event** — `HeatMap` declares **no `action`-kind prop at all**
  (`catalog.py`), a deliberate choice: it is read-only, no click, no drill-in.
  `test_heatmap_has_no_action_surface_so_the_event_invariant_holds_vacuously`
  proves this is real, not assumed — it injects `onPress` carrying a genuinely
  *registered* action and confirms the wall never even reaches the
  action-registration check: an undeclared prop is refused one step earlier,
  under data-not-code, the same as any other prop `HeatMap` never declared.

Hardening applied after the first working version, each caught by actually
executing the render client's JS during development rather than trusting it by
inspection:

| Fix | Problem it closes |
|---|---|
| Per-column colour normalization | A single global min/max silently washed out a low-variance column (e.g. a 1–10 rating) sharing a grid with a high-variance one (e.g. a dollar figure) |
| `null` → not-available, not `0` | `Number(null) === 0` is truthy-finite in JS; an unguarded missing cell rendered as a real, coloured zero instead of "—" |
| Symmetric diverging scale | Signed data (profit/loss) had no way to show "this is bad" vs "this is good" — a single-hue scale only reads as "more intense = more"; verified against a real Gemini-composed profit/loss matrix carrying genuine negative values |
| Vertical size cap | No ceiling on grid height, unlike the sibling `Timeline` component |
| Locale-pinned numeric formatting | An unpinned `toLocaleString()` silently followed the *server's* locale — on this machine that produced Indian-style lakh/crore digit grouping instead of the thousands grouping every other string in the catalog assumes |

Deliberately not done, and not glossed over: no outlier-robust scaling (one
extreme value still compresses the rest of its column's colour range), no
row/column sort (unlike the sibling `DataTable`), `tone` still applies to a
whole non-diverging column rather than per cell, and the colour-math itself
(`heatFill`, `heatFillDiverging`, `colStats`, `cellNum`, `fmtNum`) has no
*automated* test — every check above was run by hand against Node during
development, not wired into `pytest` or CI.

## Proofs and tests

Everything the Session 14 widgets replay is real captured output under `proofs/`:

| File | Produced by | Shows |
|---|---|---|
| `proof.json` | `run_surface_proof.py` | injection wall (4 rejections), HITL, catalog/validator |
| `harness_run.json` | `harness_run.py` | a real live-graph run → the model composes a 19-component surface |
| `harness_selfcorrect.json` | `harness_selfcorrect.py` | the planner catches weak Berlin evidence and re-researches |
| `heatmap_run.json` | `heatmap_run.py` | a real live-graph run → Gemini composes a `HeatMap` from the catalog manifest alone, never told its name |
| `generated_surface.json` | `generate_live.py` | a local model's output caught by the validator |
| `gemini_surface.json` | `generate_gemini.py` | Gemini's raw output via the gateway |

```bash
uv run python proofs/run_surface_proof.py    # writes proof.json, prints the table
uv run pytest -q                             # S13 core + regression tests + the S14 invariant tests
```

## Architecture

- `s13code/core/live_graph/`: durable graph state, patches, event replay and bounded parallel execution
- `s13code/core/memory/`: scope checks, provenance, contradiction history, semantic chunking and FAISS retrieval
- `s13code/core/a2a_adapter/`: Agent Cards, JSON-RPC, SSE/push, official gRPC and trust checks
- `s13code/gateway.py`: the only `S14Code → glc_v3` seam
- `s13code/runtime.py`: joins graph, memory, tools and model calls into an inspectable run; hosts the `compose_surface` skill
- `s13code/ui/`: the Session 14 layer — `catalog`, `validator`, `surface`, `showcase`, `agui`, `hitl`, `routes`, recorded `fixtures/`, and the `client/` render page
- `tests/`: executable invariants and regression cases

## Sharing / security

- Contains no secrets. The UI layer never reads `.env` and holds no credentials.
- `.venv/`, `__pycache__/`, any `.env`, and generated databases are git-ignored.
- Use synthetic identities in every proof.

## License

MIT. See `LICENSE`.
