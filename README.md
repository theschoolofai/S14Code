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
| `rating_proof.json` | `rating_proof.py` | a real live-graph run → Gemini composes the new `Rating` component unprompted |

```bash
uv run python proofs/run_surface_proof.py    # writes proof.json, prints the table
uv run pytest -q                             # S13 core + regression tests + the S14 invariant tests
```

## Evidence: `Rating` catalog component

Adds `Rating` (`label` / `value` / `max` / `onSelect`) as a 24th catalog
type, for a bounded 0–5 quality/confidence score shown as filled/empty stars
rather than a raw number. It lives in the three required places: a
`ComponentSpec` in [`s13code/ui/catalog.py`](s13code/ui/catalog.py); real
star-rating renderers in both render clients
([`index.html`](s13code/ui/client/index.html),
[`app.html`](s13code/ui/client/app.html)) — each star's fill state comes
only from a numeric threshold compare against a fixed colour pair, never
from bound text; and one captured live run where Gemini composes it into a
real interface.

**The prompt never names the component.** `compose_surface`'s instruction
(`s13code/runtime.py`) offers `Rating` to the model only through the catalog
manifest, plus a generic clause describing the `/ratings` data shape —
*"for `/ratings` (a bounded 0-5 quality/confidence score per item, not an
arbitrary number) render whichever catalog component best expresses a
bounded score visually rather than as a raw figure"* — the literal string
`"Rating"` never appears in the prompt (enforced by
`test_rating_prompt_never_names_rating_in_the_compose_instruction`). The
`/ratings` values are derived, not invented: `min(sources_count, 5)` per
research outcome, reusing the same `sources_count` every other metric/table
row already carries.

### Prompt

```
Compare the safety records of Tesla, Ford, and Toyota.
```

### Graph and event trace (`proofs/rating_proof.json`, run `run-b5dcef89732b`)

| Node | Skill | State | Agent | Provider / model |
|---|---|---|---|---|
| `search_1` | `researcher` | succeeded | `researcher` | `gemini_1` / `gemini-3.1-flash-lite` |
| `search_2` | `researcher` | succeeded | `researcher` | `gemini_1` / `gemini-3.1-flash-lite` |
| `search_3` | `researcher` | succeeded | `researcher` | `gemini_1` / `gemini-3.1-flash-lite` |
| `distill` | `distiller` | succeeded | `distiller` | `gemini_1` / `gemini-3.1-flash-lite` |
| `surface` | `compose_surface` | succeeded | `ui_composer` | `gemini_1` / `gemini-3.1-flash-lite` |

Edges: `search_1/2/3 → distill`, `search_1/2/3 → surface`, `distill → surface`.

```
1  run_started
2  graph_patched
3  task_started    search_1
4  task_started    search_2
5  task_started    search_3
6  task_succeeded   search_2
7  graph_patched
8  task_succeeded   search_3
9  graph_patched
10 task_succeeded   search_1
11 graph_patched
12 task_started    distill
13 task_succeeded   distill
14 graph_patched
15 task_started    surface
16 task_succeeded   surface
17 graph_patched
```

### Result

`compose_surface` proposed 16 components; the validator accepted all 16 and
rejected 0, using types `Card, Column, DataTable, ProgressBar, Rating, Row,
Tabs, Text` — Gemini chose `Rating` on its own, once per compared entity:

```json
{"id":"r0","type":"Rating","label":{"$bind":"/rating_0_label"},"value":{"$bind":"/rating_0_value"},"max":5}
{"id":"r1","type":"Rating","label":{"$bind":"/rating_1_label"},"value":{"$bind":"/rating_1_value"},"max":5}
{"id":"r2","type":"Rating","label":{"$bind":"/rating_2_label"},"value":{"$bind":"/rating_2_value"},"max":5}
```

### Adversarial: the injection wall holds for the new type too

Before this change `Rating` did not exist, so there was nothing to attack.
After adding it, the same wall guarding every other component was proven
against it (`tests/test_s14_ui.py`):

| Attack | Invariant broken | Result |
|---|---|---|
| `type: "RatingPro"` (unknown lookalike type) | catalog | rejected |
| `label: "<img src=x onerror=alert(1)>"` | data-not-code | rejected |
| `value: 4` (literal, not `{"$bind": ...}`) | data-not-code | rejected |
| `onSelect: {"action": "delete_everything"}` (unregistered) | event | rejected |

### Reproduce from a fresh checkout

```bash
uv sync
# terminal 1: glc_v3 on 8111 (needs at least one provider key, e.g. GEMINI_API_KEY)
# terminal 2:
export GLC_BASE_URL=http://127.0.0.1:8111
export S13_GATEWAY_PROVIDER=gemini
uv run s14code serve

uv run pytest -q                        # 118 passed, incl. 8 Rating-specific tests
uv run python proofs/rating_proof.py    # re-captures rating_proof.json live
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
