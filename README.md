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

## The `NetworkGraph` component

The catalog carries **24** component types: 15 A2UI Basic + 9 custom extensions.
The ninth custom type is undirected `NetworkGraph`
([`s13code/ui/catalog.py`](s13code/ui/catalog.py)) — nodes and weighted edges for
relationship / similarity networks.

```python
"NetworkGraph": ComponentSpec("NetworkGraph", {
    "title":  PropSpec("text"),
    "nodes":  PropSpec("binding"),   # -> [{"id", "label"}]
    "edges":  PropSpec("binding"),   # -> [{"source", "target", "weight"?}]
    "layout": PropSpec("enum", ("circle",)),
}, source="custom"),
```

The renderers in [`client/index.html`](s13code/ui/client/index.html) and
[`client/app.html`](s13code/ui/client/app.html) draw SVG lines, circles, and
labels with `createElementNS` / `createTextNode` only — never `innerHTML`.

Nothing in the user prompt names `NetworkGraph`. Relational multi-entity runs
expose `/nodes` and `/edges` in the data model; `compose_surface` offers the
catalog and Gemini picks the type on its own.

### Evidence — unprompted live compose (`run-e7c7612e8e1e`)

Exact prompt (contains no `NetworkGraph` string):

```text
Compose a UI that shows how these software job roles relate by shared skills
as a network of connections: Backend Engineer, Frontend Engineer, Data Engineer,
ML Engineer, and DevOps Engineer. Prefer a relationship network of the roles
with weighted links for skill overlap.
```

API shape used by the proof harness (equivalent to `respond_as: "ui"`):

```bash
GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
  S13_EMBEDDER=deterministic S14_SURFACE_MAX_TOKENS=12000 \
  uv run python proofs/network_graph_compose.py
# -> proofs/network_graph_compose.json
```

Graph (skills / agents / providers / models):

| Node | Skill | Agent | Provider | Model | State |
|---|---|---|---|---|---|
| `search_1`…`search_5` | `researcher` | `researcher` | `gemini_1` | `gemini-2.5-flash` | succeeded |
| `distill` | `distiller` | `distiller` | `gemini_1` | `gemini-2.5-flash` | succeeded |
| `surface` | `compose_surface` | `ui_composer` | `gemini_1` | `gemini-2.5-flash` | succeeded |

Ordered event trace (abbreviated): `run_started` → five `task_started`/`task_succeeded`
on `search_*` → `distill` → `surface` → finish. Full journal is in
[`proofs/network_graph_compose.json`](proofs/network_graph_compose.json).

Final composed interface: validator accepted **3** components —
`Column`, `Text`, **`NetworkGraph`** — with nodes/edges bound into the data model.
`prompt_contains_NetworkGraph` is `false` in the captured proof.

### Evidence — adversarial wall (before vs after)

Before the declarative wall, the same payloads would have been executable HTML /
DOM handlers / unregistered actions. After `NetworkGraph` joined the catalog,
`validate_surface` still refuses every attack
([`proofs/adversarial_network_graph.json`](proofs/adversarial_network_graph.json)):

| Attack | Before (if unbound) | After (validator) |
|---|---|---|
| `RawHtml` + `onerror` image | script runs in the page | **catalog** — unknown type |
| `NetworkGraph` title with `<script>` | markup executes via `innerHTML` | **data-not-code** — markup refused |
| `NetworkGraph` + `onclick` | handler reaches the DOM | **data-not-code** — handler refused |
| Button `transfer_all_funds` beside a graph | action enters the graph | **event** — unregistered; safe `NetworkGraph` still accepted |

```bash
uv run python proofs/adversarial_network_graph.py
# -> proofs/adversarial_network_graph.json
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
| `network_graph_compose.json` | `network_graph_compose.py` | Gemini composes `NetworkGraph` without naming it |
| `adversarial_network_graph.json` | `adversarial_network_graph.py` | three invariants still hold around `NetworkGraph` |

Reproduce from a fresh checkout (gateway on 8111 with Gemini keys in `glc_v3/.env`,
never commit that file):

```bash
git clone https://github.com/Prerit-112/S14Code.git && cd S14Code
git checkout feat/network-graph
uv sync
uv run ruff check .
uv run pytest -q
uv run python proofs/adversarial_network_graph.py
# with glc_v3 serving on 8111:
GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
  S13_EMBEDDER=deterministic S14_SURFACE_MAX_TOKENS=12000 \
  uv run python proofs/network_graph_compose.py
uv run python proofs/run_surface_proof.py    # writes proof.json, prints the table
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
