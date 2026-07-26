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
| `annotated_image_surface.json` | `generate_annotated_image_proof.py` | Gemini picks the new `AnnotatedImage` component **unprompted** |

```bash
uv run python proofs/run_surface_proof.py    # writes proof.json, prints the table
uv run pytest -q                             # S13 core + regression tests + the S14 invariant tests
```

### Evidence: `AnnotatedImage` (Part 1)

**Capability.** A new catalog component, `AnnotatedImage` (`s13code/ui/catalog.py`,
source `"custom"`), draws pre-computed detection boxes as data-bound overlays on
top of an image (`src`, `alt`: literal text; `boxes`: a binding to
`[{x,y,w,h,label,confidence}, ...]`; `caption`: literal text). Its renderer lives
in `s13code/ui/client/index.html` (`renderAnnotatedImage`), built entirely with
`createElement`/`textContent` — no `innerHTML`. No changes to `runtime.py`,
`validator.py`, or any other component were needed: `compose_surface` reads
`COMPONENTS` from the catalog and offers every registered type to the model
automatically.

**Exact API request** (`proofs/generate_annotated_image_proof.py`, live against
the running `glc_v3` gateway, `provider=gemini`):

```
POST http://127.0.0.1:8111/v1/chat
{
  "messages": [{"role": "user", "content": "<CATALOG json>\n\n<DATA MODEL json>\n\nTASK: ..."}],
  "system": "<SYSTEM prompt from generate_live.py>",
  "max_tokens": 1500, "temperature": 0, "reasoning": "off",
  "agent": "s14_surface", "provider": "gemini"
}
```

The task instruction (verbatim, `TASK` in the script) never names a component
type — it only describes the data: *"...the frame with its detections visibly
marked on top of the image itself (not listed separately in a table)... Pick
whichever catalog component types best fit each piece of data."* The word
`AnnotatedImage` appears only inside the embedded catalog manifest (the model
has to know it exists to choose it) — never in the instruction.

**Agent / provider assignment.** `provider=gemini_1`, `model=gemini-2.5-flash`,
called through the same `glc_v3` gateway seam `compose_surface` itself uses
internally (`_gateway_surface_call` in `runtime.py`) — same endpoint, same
validator, invoked directly rather than from inside a live graph run.

**Why no graph/event trace here.** This capability is a catalog + renderer
addition, not a graph change, so there's no new node/skill to trace. The real
graph's `compose_surface` node (`harness_run.py` / `harness_run.json`, unchanged
by this PR) *does* now offer `AnnotatedImage` as one of 24 available types with
zero code changes — verified live below — but that node's data model only ever
carries the generic `content` role's fixed schema (`title`/`sections`/`metrics`/
`series`/`table`/`choices`; see `run_content` in `runtime.py`), which has no
field for an image URL or a box list. Getting a real photo + boxes in front of
the model therefore has to go around that schema, via the same direct-gateway
path `compose_surface` itself uses — which is what this proof does. Wiring
domain-specific data into the graph's generic content schema is explicitly
Part 2 scope (CCTV Incident Investigator, kept out of this repo per the
instructor's "PR is only for the catalog").

```bash
# 24 types now offered to compose_surface, unaffected trace, zero runtime.py changes:
S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
  uv run python proofs/harness_run.py
```

**Actual final result.** Gemini composed a `Column` of a `Text` heading, two
`Card`s (one wrapping a `Text` summary, one wrapping the `AnnotatedImage`,
bound `src`→`/frame_url`, `boxes`→`/boxes`), and a third `Card` wrapping a
`DataTable` of cross-camera matches — 8 proposed, 8 accepted, 0 rejected. Full
request/response, data model, and validator verdict:
`proofs/annotated_image_surface.json`.

`frame_url` is a real stock photo (picsum.photos id 342 — a person carrying a
cream backpack in a street scene), standing in for staged CCTV footage per
§2.1's documented limitation; the box coordinates were placed by visually
inspecting that exact photo, not by running a real detector — §2.3's
documented fallback, named explicitly here rather than left implicit. An
earlier version of this proof used a *different* stock photo (picsum id 1084,
which turned out to be walruses, not a person) with box coordinates that were
never checked against what the image actually showed; a reviewer caught the
mismatch, which is why this note — and the requirement to verify an image's
actual content before hand-authoring boxes for it — is now spelled out rather
than assumed.

**Adversarial failure, live against a running server** (`uv run s14code serve`,
then `POST /v1/validate`) — three attacks, the same three invariants §1.5 names,
run directly against `AnnotatedImage`:

| Attack | Request (surface fragment) | Result |
|---|---|---|
| Event-handler prop | `AnnotatedImage` with `"onClick":"doSomething()"` | `{"ok":false,...,"reason":"event-handler property is never allowed"}` — catalog invariant |
| Unregistered action (adjacent `Button`) | `Button` with `onPress:{"action":"drop_tables"}` next to a clean `AnnotatedImage` | `AnnotatedImage` **accepted**, only the `Button` rejected (`"unregistered action 'drop_tables'"`) — event invariant, safe part still renders |
| Markup inside the *bound* `boxes` array | a `label` containing `<img src=x onerror=alert(1)>` inside the array the `boxes` binding resolves to | `{"ok":true,...}` — **not caught by `validate_surface`** (§1.5's documented nuance: the markup check only inspects top-level prop values, and `boxes` at the top level is `{"$bind":"/boxes"}`, a dict, not a string). Protection here is the renderer: `renderAnnotatedImage` places `label` only in a `createTextNode`, never `innerHTML`, so the payload renders as inert visible text, never executes. |

Reproduce all three:

```bash
uv run s14code serve   # separate terminal, needs GLC_BASE_URL pointed at glc_v3

curl -s -X POST http://127.0.0.1:8113/v1/validate -H "Content-Type: application/json" -d '{
  "surface": {"root":"img1","components":[
    {"id":"img1","type":"AnnotatedImage","src":"https://example.com/frame.jpg","boxes":{"$bind":"/boxes"},"onClick":"doSomething()"}
  ]}}'

curl -s -X POST http://127.0.0.1:8113/v1/validate -H "Content-Type: application/json" -d '{
  "surface": {"root":"col","components":[
    {"id":"col","type":"Column","children":["img1","btn"]},
    {"id":"img1","type":"AnnotatedImage","src":"https://example.com/frame.jpg","boxes":{"$bind":"/boxes"}},
    {"id":"btn","type":"Button","label":"Wipe","onPress":{"action":"drop_tables"}}
  ]}}'

curl -s -X POST http://127.0.0.1:8113/v1/validate -H "Content-Type: application/json" -d '{
  "surface": {"root":"img1","components":[
    {"id":"img1","type":"AnnotatedImage","src":"https://example.com/frame.jpg","boxes":{"$bind":"/boxes"}}
  ]}}'
```

**Full reproduction from a fresh checkout:**

```bash
uv sync
uv run pytest -q tests/test_annotated_image.py tests/test_s14_ui.py   # unit-level invariants

GLC_BASE_URL=http://127.0.0.1:8111 \
  uv run python proofs/generate_annotated_image_proof.py              # live Gemini proof
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
