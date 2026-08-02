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

## Evidence — `GaugeCluster`, and the wall that guards it

This branch adds one catalog component, `GaugeCluster` (design notes:
[`docs/gauge-cluster.md`](docs/gauge-cluster.md)), plus the structural checks and
repairs that keep a model-composed surface renderable. Everything below is a
real run, transcribed. The provider is a local `gemma4:latest` served by Ollama
behind the `glc_v3` HTTP contract — **not** Gemini; see *Honest verdict*.

### The request

```bash
curl -s http://127.0.0.1:8113/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"telltale-demo","user_id":"bench-operator",
       "respond_as":"ui",
       "prompt":"A technician is standing at a test bench looking at a vehicle. Summarise the state of the vehicle so they can decide what to look at first, using ONLY the readings below.\n\nReadings from the bench bus (JSON):\n{ ...six readings, each with label/value/min/max/unit/warn/alarm/invert... }\n\nReport every reading you use as a metric carrying its own label, value, unit, min, max and the warn/alarm limits given here, so the numbers keep their scale. Do not invent readings that are not listed."}'
# -> {"run_id": "run-23b9222c1829"}
```

**The prompt never says `GaugeCluster`.** `tests/test_compose_gauges.py` asserts
that neither `compose_system_prompt()` nor `compose_instruction()` contains the
string, because a run whose instruction named the component would measure
obedience rather than composition.

### The graph, and the ordered event trace

```
nodes:  content  (skill=content,         agent=content)
        surface  (skill=compose_surface, agent=ui_composer)
edges:  content -> surface

205  run_started
206  graph_patched     add=[content]   "first frontier selected for compose_answer"
207  task_started      content         skill=content        agent=content
208  task_succeeded    content          -> structured {title, intro, sections, metrics×6}
209  graph_patched     add=[surface]   "content produced; compose a validated A2UI surface"
210  task_started      surface         skill=compose_surface agent=ui_composer
211  task_succeeded    surface         provider=ollama model=gemma4:latest
212  graph_patched     "composed a surface the S14 validator accepted"
```

**Provider and agent assignment, per node:** `content` → agent `content`,
provider `ollama`, model `gemma4:latest`. `surface` → agent `ui_composer`,
provider `ollama`, model `gemma4:latest`. No node holds a credential; both reach
the model through `GLC_BASE_URL` alone.

### The result

The model's raw reply, unedited:

```json
{"root":"root","components":[
  {"id":"t1","type":"Text","variant":"heading","text":{"$bind":"/title"}},
  {"id":"n1","type":"Notice","text":{"$bind":"/summary"},"tone":"bad"},
  {"id":"card0","type":"Card","title":"Critical Faults & Status","children":["t2"]},
  {"id":"t2","type":"Text","variant":"body","text":{"$bind":"/section_0_points"}},
  {"id":"gauge_cluster","type":"GaugeCluster","gauges":{"$bind":"/gauges"}},
  {"id":"card1","type":"Card","title":"System Readings","children":["t3"]},
  {"id":"t3","type":"Text","variant":"body","text":{"$bind":"/section_1_points"}}
]}
```

Offered a data model containing bounded readings, a series and rows — three
different shapes, so choosing per shape is a real choice — it reached for
`GaugeCluster` and bound it to `/gauges`. The validator's verdict:

```json
{"proposed": 7, "accepted": 7, "rejected": 0, "ok": true,
 "component_types": ["Card", "GaugeCluster", "Notice", "Text"],
 "component_count": 8,
 "structure": ["root 'root' is not among the components"], "root_repaired": true}
```

Note the last two fields. The model declared `"root":"root"` and then **never
emitted a component with that id** — the client would have thrown on the first
lookup. That is not an attack, so refusing it would be the wrong answer; it is
incoherence, and it is repaired. Hence `ValidationResult` grows a second, separate
property: `ok` means *safe*, `coherent` means *renderable*. Different questions,
opposite responses. `repair_surface` synthesises the missing container, and the
count goes 7 → 8.

### Three turns, each shaped by the tap before it

| turn | tapped | composed | verdict |
|---|---|---|---|
| 1 overview | — | `Text · Notice · Card ×2 · GaugeCluster` (8) | clean, coherent, first attempt |
| 2 domain | `Lighting` | `Column · Text` (2) | clean, coherent — **but prose only, after 3 attempts** |
| 3 fault | `C0040` | `Text · Card · GaugeCluster` (8) | clean, **not coherent** |

Turn 2 answered in text while bounded readings sat in the data model, twice, and
the third attempt composed nothing at all. Turn 3 bound a gauge title to
`/gauges.title`, which resolves to nothing, and the structural check said so
rather than shipping a blank heading. Both are recorded because a table showing
only turn 1 would be a different, false claim.

### Adversarial: one attack that used to get through

The rule that admits a binding was `^/[^\s]*$` — it reads like a JSON Pointer
check and is really a *no whitespace* check. So this passes it:

```json
{"id":"g0","type":"GaugeCluster","gauges":{"$bind":"/readings[0].value|toFixed(1)"}}
```

A member access, an index, and a filter call — an expression, in the one place
the design says only data may travel. **Before** (the validator at `main`, loaded
out of git and executed, not paraphrased):

```json
{"accepted": ["root", "g0"], "rejections": [], "clean": true}
```

It reaches the browser. **After** (this branch, same payload, same catalog):

```json
{"accepted": ["root"], "clean": false,
 "rejections": [{"component_id": "g0", "field": "gauges", "invariant": "data-not-code",
                 "reason": "invalid JSON Pointer '/readings[0].value|toFixed(1)'"}]}
```

The fix is one line — `_POINTER = re.compile(r"^/[A-Za-z0-9_\-./~]*$")` — an
allow-list of what a pointer may contain instead of a deny-list of what it may
not. The container survives; only the hostile node is dropped, because a wall
that answered an attack by discarding the whole surface would hand the attacker a
denial of service.

The other three invariants, each given the surface a complying model would emit:

| attack | refused by | verdict |
|---|---|---|
| `{"type":"RawHtml","html":"<script>alert(document.cookie)</script>"}` | catalog | `unknown component type 'RawHtml'` |
| `Button.label = "<img src=x onerror=…>"`, `Image.src = "javascript:alert(1)"` | data-not-code | `value carries markup`, `value is a script/data URL` |
| `onPress.action = "exfiltrate_memory"` / `"delete_all_runs"` | event | `unregistered action` ×2 |

In each case every hostile component is removed and the safe remainder still
renders.

### Honest verdict

**The model is not the one the assignment names.** These runs are `gemma4:latest`
on a local Ollama, reached through the same `glc_v3` contract Gemini uses. The
mechanism under test is identical; the composition quality is not, and a
different model would likely choose differently.

**Composition is unreliable, and the fix is upstream of the renderers.** Across
runs the same prompt produced a rich interface, a prose-only answer, and nothing
at all. That is why this branch adds structural repair rather than only a
component: a missing root, a dangling child reference and a misspelled pointer
each arrived from a real model, and each is repaired once — in `compose_surface`,
the narrowest point every consumer passes through — instead of in each renderer.

**Sending hostile prompts through the live model proved less than expected.**
`gemma4` declined all three: it composed an interface *about* the refusal instead
of the requested payload, and substituted a registered action for the invented
one. Encouraging, but not evidence about the wall — a model that happens to
behave says nothing about the next one. So the invariant table above is the
constructed surface handed straight to the validator, and it is labelled as such.
One incidental finding from those runs: the attack text travelled into the data
model and was rendered as characters, which is data-not-code working as intended
and is pinned by `test_markup_in_a_bound_value_renders_as_literal_text`.

**Also worth stating:** an attack payload containing a URL never reached the
composer at all. The planner saw the URL, routed the run to `fetch_url`, and the
run died on DNS. It cost six runs that looked like model flakiness.

### Reproduce from a fresh checkout

No model and no network — this is the whole adversarial claim, checkable in
seconds:

```bash
git clone <this-fork> && cd S14Code && git checkout pitlane-generative-ui
uv sync --dev
uv run pytest -q                       # 198 passed
uv run pytest -q tests/test_surface_structure.py tests/test_gauge_cluster.py
```

The browser tests need one extra download and skip cleanly without it:

```bash
uv run playwright install chromium
uv run pytest -q tests/test_client_rendering_playwright.py
```

The wall, over HTTP, on a running server:

```bash
uv run s14code serve &
curl -s http://127.0.0.1:8113/v1/validate -H 'Content-Type: application/json' \
  -d '{"surface":{"root":"root","components":[
        {"id":"root","type":"Column","children":["x"]},
        {"id":"x","type":"RawHtml","html":"<script>alert(document.cookie)</script>"}],
      "dataModel":{}}}'
# {"ok":false,"accepted":["root"],
#  "rejections":[{"component_id":"x","field":"type","invariant":"catalog",
#                 "reason":"unknown component type 'RawHtml'"}]}
```

Reproducing the *live* runs needs a gateway speaking `POST {GLC_BASE_URL}/v1/chat`
and returning `{text, provider, model}`. The one used here is an operational
shim for a local model; it is not in this repository, because a framework should
not carry a second gateway for a model the assignment does not name.

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
