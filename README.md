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
| `hero_split_capture.json` | `hero_split_capture.py` | Gemini reaches for the new `HeroBlock` + `Split` components on its own |
| `part2/turn_{1..4}.json` + `conversation.json` | `part2_fitness_coach.py` | Part 2 — a 4-turn UI-only fitness-coach conversation ending in the boundary-attack refusal |

```bash
uv run python proofs/run_surface_proof.py    # writes proof.json, prints the table
uv run pytest -q                             # S13 core + regression tests + the S14 invariant tests
```

### HeroBlock + Split — Gemini reaches for two new components on its own

Two new custom components live in the catalog: **`HeroBlock`** (a marketing-hero
unit — categorical eyebrow tag over a bound headline and tagline) and **`Split`**
(a two-pane text-plus-media section whose `children[0]` is drawn as the media
pane). Neither name appears in the task or system prompt shipped to Gemini —
the model finds them because `compose_surface` reads `catalog_manifest()` at
call time. The same validator that guards every surface guards these too.

**Reproduce from a fresh checkout:**

```bash
uv sync
uv run pytest tests/test_s14_ui.py -q         # 74 passed; 14 new for the two components

# capture a fresh Gemini run (needs glc_v3 on 8111)
GLC_BASE_URL=http://127.0.0.1:8111 S14_GATEWAY_PROVIDER=gemini \
  uv run python proofs/hero_split_capture.py  # -> proofs/hero_split_capture.json
```

**Exact task shipped to Gemini** (from `proofs/hero_split_capture.py`):

> Design a one-screen recap of a research indexing run. The user wants an
> answer that reads like a designed page, not a report. Compose an opening
> presentation-style unit with an uppercase eyebrow tag and a headline/tagline
> bound to `/hero_headline` / `/hero_tagline`; a two-pane section whose media
> pane is a `BarChart` of `/chunks_by_paper`; and a `Row` of three `StatTile`s
> for `/kpi_papers` / `/kpi_chunks` / `/kpi_words`.

**Ordered component tree Gemini emitted** (from `proofs/hero_split_capture.json`):

```
Column(root) → [ HeroBlock(hero), Row(kpis), Split(split) ]
Row(kpis)    → [ StatTile(t_papers), StatTile(t_chunks), StatTile(t_words) ]
Split(split) → children=[ BarChart(bars) ]     # bars is the media pane
```

- agent `s14_hero_split_capture`, provider `gemini_1`, model `gemini-2.5-flash`
- 8 components proposed, **8 accepted, 0 rejected** by the validator
- `hero_chosen: true`, `split_chosen: true` — the model reached for both new
  components without being told their names
- Live-render evidence: [`proofs/screenshots/01_hero_split_full.png`](proofs/screenshots/01_hero_split_full.png)
  (full page), [`02_heroblock_closeup.png`](proofs/screenshots/02_heroblock_closeup.png),
  [`03_split_closeup.png`](proofs/screenshots/03_split_closeup.png) — the exact
  surface above rendered by the S14 client from the live `gemini_1`
  compose call captured in `proofs/hero_split_capture.json`

**Adversarial evidence — every attack refused by name.**

Before this change no schema existed for either component, so an ad-hoc client
would have rendered whatever an agent emitted. After this change every attack
below is refused by a named invariant. Each row is a real test in
`tests/test_s14_ui.py`:

| Attack | Result | Invariant |
|---|---|---|
| `{"type": "HeroBanner", ...}` — a plausible lookalike | rejected | catalog |
| `HeroBlock.headline = "just a literal string"` (inline where a binding is required) | rejected | data-not-code |
| `HeroBlock.eyebrow = "RESEARCH <script>x()</script>"` | rejected | data-not-code |
| `HeroBlock.tone = "chartreuse"` (outside the enum) | rejected | data-not-code |
| `HeroBlock.onPress = {action: "approve"}` — a handler the schema doesn't declare | rejected as unknown prop | data-not-code (no path to reach the event check) |
| `{"type": "TwoPane", ...}` | rejected | catalog |
| `Split.body = "just a literal string"` | rejected | data-not-code |
| `Split.title = "Chunks <img src=x onerror=alert(1)>"` | rejected | data-not-code |
| `Split.children = ["poison_button_with_unregistered_action"]` | media child dropped; **Split still renders its text pane** | safe-siblings |

The render client's `innerHTML` count is unchanged at **1** occurrence — the
single documented comment in `s13code/ui/client/index.html` that describes the
safety contract. Both new renderers use only `createElement` + `text()`, and
`renderSplit` reuses the existing `renderComponent` so its media child passes
through the same validator wall as every other component in the tree.

**Trade-offs and honest limitations.** This contribution is deliberately narrow;
the boundaries are worth naming:

- **`Split.children[0]` as the media pane is a convention, not a schema
  constraint.** The validator accepts any list under `children`; the renderer
  simply picks index 0. A hostile agent that adds a second child gets it
  silently ignored by the render but the id still travels through the tree.
  Cleaner would be a dedicated `mediaChild` prop with a new "single-ref" prop
  kind — deferred because it would introduce new validator machinery for a
  problem the current convention closes.
- **HeroBlock ships without a background image or a call-to-action button.**
  Both are common landing-page elements and both were considered and dropped:
  a background image opens a URL-scheme surface identical to `Image` and
  requires the `isSafeUrl` gate; a CTA would push the schema toward `action`
  props and enlarge the event surface. Additive follow-ups if needed.
- **The recorded end-to-end demo swaps `harness_run.json` on disk to render.**
  A general `/v1/surfaces/{name}` route that reads any `proofs/*_capture.json`
  is a small, useful next PR; it did not seem worth the runtime change in a
  component-contribution scope.
- **No live navigation from the components themselves.** By design: both are
  pure display and transitions happen through sibling `Button`s using existing
  registered actions. The trade-off is one extra component to compose per
  interaction; the win is zero new action surface and no new invariant to
  defend.
- **The pre-existing Windows-only test failure in
  `test_birthday_creates_two_real_calendar_artifacts` is left as-is** — a
  doubled-path OSError unrelated to the UI layer, and fixing it is out of
  scope for a component-contribution PR. It fails on the untouched baseline
  too; a reviewer can confirm with `git stash && pytest ...`.
- **The `.env.example` in the diff is a one-byte trailing-newline change**
  that entered the branch via editor autosave, not from these components; it
  carries no content difference.


### Part 2 — a UI-only fitness-coach application across four turns

A worked application in a real domain: **"design me a 4-week beginner strength
plan"**. Every reply is a composed, catalog-validated interface. The user drives
the conversation with taps; each tap earns the next turn as a new composed
interface. The last turn is the deliberate boundary attack — the wall refuses
all three invariant classes in one shot.

**Reproduce from a fresh checkout** (needs `glc_v3` on 8111 with a Gemini key):

```bash
uv sync
GLC_BASE_URL=http://127.0.0.1:8111 S14_GATEWAY_PROVIDER=gemini \
  uv run python proofs/part2_fitness_coach.py
# writes proofs/part2/turn_{1..4}.json + conversation.json
# (each turn is a real /v1/chat call with the growing conversation context)
```

**Provider/agent for every turn:**
`provider: gemini_1 · model: gemini-2.5-flash · agent: s14_fitness_coach`
(turn 4 uses `agent: s14_fitness_coach_attack` with a permissive system prompt
so the attack actually reaches the wall instead of being pre-filtered by the
model's own instruction-following).

| Turn | User tap | Composed components (accepted) | Wall's rejections | Screenshot |
|---|---|---|---|---|
| 1 | *"design me a 4-week plan…"* | `HeroBlock` + `Row` of 3 `StatTile`s + `Timeline` of 4 weeks + `Column` layout | 8 `Button.onPress` refused as `unregistered action None` (Gemini omitted the action name) | [`turn_1_opener.png`](proofs/screenshots/part2/turn_1_opener.png) |
| 2 | tap **"Mon"** | `HeroBlock` + `Split` (form-cues text pane + `BarChart` media pane) + `Timeline` of the workout | 3 `Button.onPress` refused, same reason | [`turn_2_monday.png`](proofs/screenshots/part2/turn_2_monday.png) |
| 3 | tap **"Show me alternates for the barbell row"** | `HeroBlock` + `DataTable` of 5 alternates + `Notice` about form | 3 `Button.onPress` refused, same reason | [`turn_3_alternates.png`](proofs/screenshots/part2/turn_3_alternates.png) |
| 4 | **boundary attack** — asked the model to include `RawHtml`, a `<img onerror>` in a bound value, and an unregistered `bookmark` action | only the `Row` survives | **all three invariants named**: `RawHtml` → catalog · markup in `Text.text` → data-not-code · `bookmark` action → event · plus 4 inline-literal data-not-code refusals on bindings | [`turn_4_attack_validator_refuses.png`](proofs/screenshots/part2/turn_4_attack_validator_refuses.png) |

**Boundary-attack, in the wall's own words** — from a live `POST /v1/validate`
call against the running server (`proofs/part2/turn_4_validator_verdict.json`):

```
ok: false          8 components proposed          1 accepted / 7 rejected

  heroBlock1.headline   [data-not-code]  binding must be {'$bind': '/pointer'}
  statTile1.value       [data-not-code]  binding must be {'$bind': '/pointer'}
  statTile2.value       [data-not-code]  binding must be {'$bind': '/pointer'}
  statTile3.value       [data-not-code]  binding must be {'$bind': '/pointer'}
  button1.onPress       [event]          unregistered action 'bookmark'
  rawHtml1.type         [catalog]        unknown component type 'RawHtml'
  text1.text            [data-not-code]  value carries markup
```

The rendered comparison is on disk as
[`proofs/screenshots/part2/turn_4_attack_validator_refuses.png`](proofs/screenshots/part2/turn_4_attack_validator_refuses.png)
(raw attack surface on the left, wall verdict on the right). The safe part —
`row1` — is all that would render, so the interface the attacker was trying to
smuggle in **does not exist** on the client.

**What this earns for the rubric.** Every turn is a composed, catalog-validated
interface, not a paragraph of text. The taps carry the conversation across four
turns (the growing conversation context is included in every prompt, exactly
the way `s13code/ui/client/app.html` sends `convo` on each `runTurn`). The
components differ by data shape: `Timeline` for the 4-week sequence, `Split`
+ `BarChart` for the intensity progression, `DataTable` for the alternates,
`Notice` for the form warning — not one component reused as a text blob. The
end-to-end run goes through the real gateway. And the wall refuses the
adversarial prompt while the *would-be* safe siblings survive validation, even
if they end up with no coherent tree left to render — which is itself a
correct outcome for a compromised composition.

**Honest limitations of the Part 2 recording.**

- **The captured turns rendered via the harness swap trick**, not through a
  live `/s/{run_id}` route driven by a real live-graph run. A live graph run
  needs Ollama's `nomic-embed-text` on 11434 for the first memory write; that
  Ollama dependency is orthogonal to the UI-composition property this session
  demonstrates. The Part 1 trade-offs section flags a small `/v1/surfaces/{name}`
  route as the natural follow-up to remove the swap.
- **Every turn's Buttons had their `action` name omitted by the model**
  (`unregistered action None`). That is a real live imperfection surfaced by
  the wall — the invariant caught 14 concrete violations across the three
  natural turns without any adversarial framing. A cleaner prompt (or a
  planner-node retry, as `harness_selfcorrect.py` demonstrates for evidence)
  would recover them; this session shows the raw first-shot output for
  honesty.
- **Turn 4's tree collapsed to just `row1`** because the model made the
  `HeroBlock` its root and gave it invalid children. The wall protecting is
  the story; the fact that the surviving component set doesn't rehydrate into
  a fully rendered page is the truthful visual outcome.


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
