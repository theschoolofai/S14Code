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
| `GET /v1/runs/{id}/composed` | the interface the agent COMPOSED, re-validated, with what the wall refused |
| `GET /app` | the bare-minimal UI-only app shell |
| `GET /academy` | Trading Systems Academy — the UI-only application (see below) |

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
```

## Session 14 assignment: the `Heatmap` component and the Academy app

### Part 1 — `Heatmap`, contributed to the shared catalog

The catalog is now **24** types: 15 A2UI Basic + 9 custom. The new one is
`Heatmap`, the one shape none of the others could carry — `BarChart` and
`Sparkline` are one-dimensional and `DataTable` shows cells but not magnitude.
A heatmap is a rows × columns grid where the *number* in each cell is the
message: mastery per topic per week, latency per venue per hour, coverage per
module per suite.

It lives in three places, as the assignment requires:

| Where | What |
|---|---|
| [`s13code/ui/catalog.py`](s13code/ui/catalog.py) | the `ComponentSpec` — `title`, `rows`, `columns`, `values`, `unit`, `tone`, tagged `source="custom"` |
| [`s13code/ui/client/index.html`](s13code/ui/client/index.html) | `renderHeatmap` — draws from text nodes and executes no value (also in `app.html` and `academy.html`) |
| [`proofs/academy_turns.json`](proofs/academy_turns.json) | a real run where Gemini composed it **without being told its name** |

Nothing names `Heatmap` to the model. `compose_surface` hands over
`catalog_manifest()`, the run's data model exposes a generic `/matrix_*` pointer
set, and the compose instruction deliberately gives **no** mapping for it —
only a component-neutral line saying that pointers without a listed mapping
should be served by reading the catalog and matching prop shapes. The model
found it on its own:

```json
{ "id": "effort_heatmap", "type": "Heatmap",
  "title":   {"$bind": "/matrix_title"},
  "rows":    {"$bind": "/matrix_rows"},
  "columns": {"$bind": "/matrix_columns"},
  "values":  {"$bind": "/matrix_values"},
  "tone": "neutral" }
```

The safety property, enforced in the renderer: the **only** thing a bound value
may influence is an intensity the client computes itself — `Number(v)`,
normalised and clamped to `0..1`. The colour channel is a fixed lookup keyed by
the catalog's validated `tone` enum, so no string the agent wrote ever reaches
CSS. A non-numeric cell tints nothing and prints as literal text.

`_matrix_pointers` in [`s13code/runtime.py`](s13code/runtime.py) exposes a grid
only when it is fully labelled, rectangular and numeric. A ragged grid is not
evidence, so it is never exposed and never drawn — the same honesty discipline
that makes the runtime emit a `Notice` instead of an invented chart.

### Part 2 — Trading Systems Academy, a UI-only application

`GET /academy` ([`s13code/ui/client/academy.html`](s13code/ui/client/academy.html))
is a tutor for exchange and trading *infrastructure* — matching engines, market
data, FIX, risk gates, latency. It never answers in prose. Every turn is a
composed, catalog-validated interface, and a tap on a rendered `Button` becomes
the next turn.

The app adds one standing requirement of its own (`KEEP_GOING`): always finish by
offering 3–5 concrete next topics. That is the *application's* need — it can only
be driven by tapping — and it names no component, so which one carries the
choices is still the composer's call.

The strip above the screen reports the live verdict on every turn: model,
component count, `0 executable`, and how many components the wall refused. When
anything is refused, the panel below names each one and the invariant it broke.

### Reproducing all of it from a fresh checkout

```bash
# terminal 1 — the gateway (owns every credential)
cd glc_v3 && uv sync && uv run glc serve

# terminal 2 — this runtime
cd S14Code && uv sync
export GLC_BASE_URL=http://127.0.0.1:8111
export S13_GATEWAY_PROVIDER=gemini
export S13_MAX_TOKENS=6000            # see note below
export S14_SURFACE_MAX_TOKENS=20000
uv run s14code serve

# the invariants, hermetically (no gateway, no Ollama, no network)
uv run pytest -q

# the live captures
uv run python proofs/academy_turns.py    # 3 prompts -> 3 interfaces, + a 3-turn thread
uv run python proofs/academy_attack.py   # the injection wall, deterministic + live

open http://127.0.0.1:8113/academy
```

> **Token budgets.** `max_tokens` is a budget for everything the provider
> generates, and on `gemini-2.5-flash` the reasoning tokens are drawn from it
> first. Asking for `"reasoning": "off"` does not change that — the gateway just
> omits `thinkingConfig`, which leaves Gemini on its default *dynamic* thinking
> budget. At the old hardcoded 700 the model spent nearly all of it thinking and
> returned ~120 characters, so the content role's JSON came back truncated and
> unparseable and every interface collapsed to a single `Text`. The ceiling is
> now `S13_MAX_TOKENS` (default 4000).

> **Free-tier quota.** Each turn spends several large model calls. On free-tier
> Gemini keys the per-key request budget is the binding constraint, and the
> gateway answers `502` once the pool is burned. Both proof scripts pace
> themselves (`S14_PACE_SECONDS`, default 30) and retry, and `academy_turns.py`
> reuses turns it has already captured so a quota stall never discards good ones.

## Proofs and tests

Everything the Session 14 widgets replay is real captured output under `proofs/`:

| File | Produced by | Shows |
|---|---|---|
| `proof.json` | `run_surface_proof.py` | injection wall (4 rejections), HITL, catalog/validator |
| `harness_run.json` | `harness_run.py` | a real live-graph run → the model composes a 19-component surface |
| `harness_selfcorrect.json` | `harness_selfcorrect.py` | the planner catches weak Berlin evidence and re-researches |
| `generated_surface.json` | `generate_live.py` | a local model's output caught by the validator |
| `gemini_surface.json` | `generate_gemini.py` | Gemini's raw output via the gateway |
| `academy_turns.json` | `academy_turns.py` | 3 prompts → 3 interfaces, a 3-turn tap-driven thread, `Heatmap` chosen unprompted |
| `academy_attack.json` | `academy_attack.py` | the four attack forms refused, plus two live hostile prompts |

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
