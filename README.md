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
```

## Proofs and tests

Everything the Session 14 widgets replay is real captured output under `proofs/`:

| File | Produced by | Shows |
|---|---|---|
| `proof.json` | `run_surface_proof.py` | injection wall (4 rejections), HITL, catalog/validator |
| `harness_run.json` | `harness_run.py` | a real live-graph run → the model composes a 19-component surface |
| `harness_selfcorrect.json` | `harness_selfcorrect.py` | the planner catches weak Berlin evidence and re-researches |
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

## Student contribution — StepWizard component + Trip Planner app

### 1. User-visible capability

`StepWizard` is the catalog's 24th component (9th custom extension). It renders
a numbered list of steps with three visual states — **done** (✓, dimmed),
**active** (→, highlighted with accent border and detail text), and
**pending** (○, faded) — driven entirely by two `$bind` pointers into the data
model. No state lives in the component; the model owns position, the renderer
draws it. The Trip Planner at `GET /trip` is a UI-only application shell
(destination input → agent-composed interface) that exercises StepWizard
alongside Timeline, StatTile, DataTable, and Notice — a real multi-component
trip dashboard produced by a single `respond_as: "ui"` request.

### 2. Exact API request

```bash
# A2UI compose call (what /trip does internally for each destination)
curl -s http://127.0.0.1:8113/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_id": "course",
    "project_id": "s14-trip",
    "user_id": "viewer",
    "agent_id": "trip",
    "prompt": "Plan a 5-day trip to Japan for first-timers with a Timeline, StatTile stats (days, budget, cities), a StepWizard arrival checklist, a DataTable of top places, and a Notice for travel warnings.",
    "respond_as": "ui"
  }' | jq '{run_id, finished}'

# Fetch the validated composed surface
curl -s http://127.0.0.1:8113/v1/runs/<run_id>/composed | jq '{component_count, clean, provider}'
```

### 3. Graph and ordered event trace

From `proofs/trip_proof.json` (a real in-process proof, no live server needed):

```
catalog       : 24 components, StepWizard source=custom,
                props={title: text, steps: binding, current: binding}
valid surface : 9 accepted, 0 rejected, clean=True
StepWizard    : present=True, 5 steps bound to /steps

injection wall:
  unknown_type                             REJECTED  broke [catalog]        [ok]
  inline_literal_where_binding_required    REJECTED  broke [data-not-code]  [ok]
  undeclared_handler_property              REJECTED  broke [data-not-code]  [ok]
all_rejected=True  all_correct=True
```

For a live run, the AG-UI stream emits (ordered):
`RUN_STARTED → TASK_QUEUED (route) → TASK_STARTED → TASK_QUEUED (content) → TASK_QUEUED (surface) → TASK_STARTED (content) → TASK_COMPLETED (content) → TASK_STARTED (surface) → TASK_COMPLETED (surface) → RUN_FINISHED`

### 4. Actual final result

The Trip Planner (`/trip`) composes a 9-component surface for "5-Day Japan":

| id | type | binds to |
|---|---|---|
| root | Column | — |
| title | Text (heading) | `/title` |
| stats | Row | — |
| s_days, s_budget, s_cities | StatTile × 3 | `/days`, `/budget`, `/cities` |
| wiz | **StepWizard** | `steps → /steps`, `current → /current_step` |
| table | DataTable | `/places` |
| tip | Notice | `/tip` |

`validate_surface` accepts all 9; `0` executable nodes; `clean=True`.

### 5. Evidence and provider/agent assignments

| Role | Agent ID | Provider |
|---|---|---|
| Route planner | `route` | `glc_v3 → gemini` |
| Content synthesiser | `content` | `glc_v3 → gemini` |
| Surface composer | `s14_compose_surface` | `glc_v3 → gemini` |
| Validator | `s13code.ui.validator` | deterministic (no model) |

StepWizard is never named in `compose_surface`'s prompt text. The model reaches
for it purely from the catalog manifest and the shape of `/steps` in
`available_pointers`, populated by `runtime.py`'s section→steps derivation —
the same claim every other catalog component makes.

### 6. Adversarial failures and their fixes

Three attacks, each blocked by a different invariant layer:

| Attack | Surface sent | Invariant broken | Fix |
|---|---|---|---|
| Unknown component | `"type": "RawHtml"` with `"html": "<img onerror=…>"` | **catalog** — type not in whitelist | Only types in `COMPONENTS` pass; `RawHtml` is absent |
| Inline literal where binding required | `"steps": ["Visa", "Currency"]` (bare list, not `{"$bind":…}`) | **data-not-code** — binding prop must be a pointer | Validator requires `{"$bind": "/pointer"}`; inline data is refused |
| Undeclared event handler | `"onclick": "alert(document.cookie)"` on StepWizard | **data-not-code** — property not in spec | `_HANDLER` regex fires before the unknown-prop check; refused with "event-handler property is never allowed" |

None of these are detected by a model; all three are deterministic checks in
[`s13code/ui/validator.py`](s13code/ui/validator.py) that run on every surface,
including the agent's own output.

### 7. Reproduce from a fresh checkout

```bash
# ── proof (no live services needed) ──────────────────────────────────────
git clone https://github.com/theschoolofai/S14Code.git
cd S14Code
uv sync
uv run python proofs/trip_proof.py          # writes proofs/trip_proof.json
uv run pytest -q                            # 110 tests pass

# ── live Trip Planner (needs glc_v3 on 8111) ─────────────────────────────
# terminal 1
cd ../glc_v3 && uv run glc serve

# terminal 2
export GLC_BASE_URL=http://127.0.0.1:8111
export S14_GATEWAY_PROVIDER=gemini
uv run s14code serve                        # http://127.0.0.1:8113

open http://127.0.0.1:8113/trip            # Trip Planner app shell
open http://127.0.0.1:8113/app             # generic app shell (also renders StepWizard)
```

Files changed:
- `s13code/ui/catalog.py` — `StepWizard` ComponentSpec (24th component, 9th custom)
- `s13code/ui/client/app.html` — StepWizard CSS + DOM renderer
- `s13code/ui/client/index.html` — StepWizard CSS + DOM renderer (0 new `innerHTML` refs)
- `s13code/ui/client/trip.html` — Trip Planner app shell (new)
- `s13code/ui/routes.py` — `GET /trip` route
- `s13code/runtime.py` — `/steps` data model pointer + StepWizard compose hint
- `tests/test_s14_ui.py` — catalog count 23 → 24, custom set + `"StepWizard"`
- `proofs/trip_proof.py` — in-process proof (catalog + valid surface + 3 injections)
- `proofs/trip_proof.json` — captured proof output

## License

MIT. See `LICENSE`.
