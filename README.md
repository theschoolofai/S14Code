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
| `GET /v1/proofs/checklist` | the captured run where Gemini composed `Checklist` unprompted (re-validated on serve) |
| `GET /v1/runs/{id}/proof` | goal + raw model reply + validator verdict for **any** run's composed interface |
| `POST /v1/validate` | run any surface through the injection wall |
| `POST /v1/action` | a validated user action (approve/reject), bound to final params |
| `GET /s/{id}` | the render client, pointed at a run |
| `GET /proof/{id}` | a human-readable proof page for one run's composed interface |
| `GET /app` | the generic "teach me X" UI-only app viewer |
| `GET /checkpoint` | Checkpoint, a UI-only readiness-planner app (see below) |

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

## Checklist — a new catalog component, and Checkpoint

A 24th catalog type, added on top of the 23 above (`s13code/ui/catalog.py`):
a checkable task list — `title`, an `items` binding, `labelKey`/`doneKey`,
and an optional `onToggle` action. It's the one interface shape none of the
other 23 types cover: `List`/`Card` render a flat ordered group, `Timeline`
renders chronological events, but nothing renders "here's what's left to do,
and here's what's already done." It's drawn by all three render clients
(`client/index.html`, `client/app.html`, `client/checkpoint.html`,
`client/proof.html`), from text nodes only — the same no-innerHTML,
no-`eval` contract every other component follows.

**Checkpoint** (`GET /checkpoint`, `s13code/ui/client/checkpoint.html`) is a
UI-only readiness planner built on the exact same generic runtime Wayfarer/`
/app` use — zero backend changes beyond the one route and a small tweak to
`compose_surface`'s own instruction text (see below). Domain: getting ready
for a real deadline — moving apartments, a first race, a website launch.
Turn 1 composes an overview plus a prep list (a `Checklist` when the tasks
are flat and checkable, a `Timeline` when they read as scheduled) plus
readiness `StatTile`s plus next-step `Button`s; every following turn takes
whichever choice was tapped and composes whichever structure actually fits
that facet — `DataTable`, `BarChart`, another `Checklist` — never naming a
component in the prompt.

**Unprompted composition, and what it actually took to get there.**
`compose_surface`'s system prompt never contains the string `"Checklist"` —
only the catalog manifest handed to the model as data does — and Gemini
reaches for it on its own (`proofs/generate_checklist_gemini.py` →
`proofs/checklist_gemini_run.json`, replayed live at `/v1/proofs/checklist`).
That took one real fix, not just prompt luck: the existing `compose`
instruction hard-coded only two options — `Timeline` or a `List`/`Column` of
`Card`s — for `/sections`-shaped data, the one path a flat task list
naturally produces. Without a change, `Checklist` was structurally
*unreachable* through that path no matter how a goal was phrased. Adding it
as a third *eligible* (not forced) option — the same technique this
codebase's Stepper contribution used — is the one line changed in
`s13code/runtime.py` outside of the new files.

**A real adversarial prompt, refused.** `proofs/attack_boundary_checklist.py`
sends one goal with three embedded instructions (an unregistered `RawHtml`
type, a literal `<script>` string where a binding is required, an
unregistered `onPress` action) straight through the live graph. Gemini
complied with all three; the validator caught all three — one per invariant
— while still rendering the 12 legitimate components alongside them. Ground
truth, checked in the script itself: neither `RawHtml` nor the injected
action name ever entered `COMPONENTS` / `REGISTERED_ACTIONS`.

**A proof link on every turn, not just a captured fixture.**
`GET /v1/runs/{id}/proof` re-validates *any* run's composed interface on
serve and returns its goal, raw (unedited) model reply, and
proposed/accepted/rejected verdict; `GET /proof/{id}` renders that as a page
— goal, a validator panel, the interface itself redrawn read-only. Every
turn in Checkpoint (and `/app`) links "view proof ↗" to its own run's page,
so the three invariants aren't only demonstrated once in a canned capture —
they're inspectable for every single composition a user actually triggers.

**The honest gaps**, in full in [`PR_DESCRIPTION_CHECKLIST.md`](PR_DESCRIPTION_CHECKLIST.md):
component choice isn't fully deterministic even at `temperature: 0` (the
same goal shape produced `Timeline` once, `Checklist` another time, `List`/
`Card`s a third); the harness's generic `/sections` binding groups a flat
task list as one section with an array-valued `points` field, which needed a
defensive array-join fix in the renderer (mirroring `Stepper`'s existing
`stepField` pattern) to avoid an `[object Object]`-shaped row; and latency is
~5–8s per turn, two sequential live model calls with no progress mid-flight
beyond an elapsed-time pill.

```bash
uv run pytest -q                                    # 122 tests, hermetic

# live captures (need glc_v3 + s14code serve running, see above)
uv run python proofs/generate_checklist_gemini.py    # unprompted Checklist composition
uv run python proofs/attack_boundary_checklist.py     # adversarial prompt + validator refusal

open http://127.0.0.1:8113/checkpoint                 # the app
open http://127.0.0.1:8113/v1/proofs/checklist         # the captured proof, re-validated on serve
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
| `checklist_gemini_run.json` | `generate_checklist_gemini.py` | Gemini composes the new `Checklist` type, unprompted |
| `attack_boundary_checklist_run.json` | `attack_boundary_checklist.py` | a live adversarial prompt, refused (all 3 invariants) |

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
