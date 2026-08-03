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
| `codeworks_turns.json` | `codeworks_turns.py` | 4 live turns of the CodeBlock app: underspecified ask → **tap** → translate → explain. Every turn records `goal_sent`, `driven_by`, `run_id`, `latency_s`, and the composed types. |
| `codeworks_attack.json` | `codeworks_attack.py` | Injection wall against a poisoned CodeBlock surface (inline source / handler prop / markup language) |
| `browser_demo.json` + `screens/turn[1-4].png`, `turn5_refused.png` | `browser_demo.py` | Headless-Chromium (Playwright) drives `/codeworks`, taps a Button on turn 2, screenshots each rendered surface. |

```bash
uv run python proofs/run_surface_proof.py    # writes proof.json, prints the table
uv run pytest -q                             # S13 core + regression tests + the S14 invariant tests
```

## Session 14 assignment — `CodeBlock` and the CodeWorks app

**Live hosted demo:** **<https://shwetha-sd78--s14code-codeworks-web.modal.run/codeworks>**

Deployed on Modal — one container serves both the model gateway (`glc_v3`, bound
to `127.0.0.1:8111` inside the container) and this runtime (public ASGI URL).
The Gemini key lives as a Modal secret; no key ever touches the image or git.

**BYOK.** The `/codeworks` page has a "Your Gemini key" input. Paste your own
free-tier key and every request in that browser session ships it as
`X-User-Gemini-Key`, which the gateway swaps in for that single request
(contextvar-scoped, never persisted). Blank input → falls back to the host
key. This keeps the demo alive if the host's free-tier quota runs out on
submission day, and lets reviewers verify the security path end to end. Get
a free key at <https://aistudio.google.com/app/apikey>.

Deploy script:
[`deploy/modal_app.py`](deploy/modal_app.py). Reproduce the deploy:

```bash
modal secret create s14-gemini-key GEMINI_API_KEY_1=<your-key>
modal deploy deploy/modal_app.py
```

**Part 1 — the `CodeBlock` component.** Added to the trusted catalog in
[`s13code/ui/catalog.py`](s13code/ui/catalog.py) with the schema
`{title: text, code: binding, language: text, onCopy: action}`. The renderer
in [`s13code/ui/client/index.html`](s13code/ui/client/index.html) is a
regex-grammar tokeniser (Prism-style — per-language rules with named token
classes, lookbehind for function/class names, greedy strings, hex/binary/
scientific/underscore numbers, decorators/annotations) that emits one
text-node `<span>` per token. It NEVER assigns `innerHTML`, NEVER evaluates
any bound value. Grammars for python, javascript, typescript, java, go,
rust, sql, shell, cpp, csharp, json, yaml, html, css, markdown ship; unknown
languages fall back to a text grammar that still highlights strings,
numbers, and comments. Aliases (`js`, `bash`, `c++`, `py`, `rs`, …) resolve
to their canonical grammar. The three invariants hold on the new type — see
the tests under `test_codeblock_*` in [`tests/test_s14_ui.py`](tests/test_s14_ui.py)
and the three new adversarial cases in
[`s13code/ui/fixtures/injections.json`](s13code/ui/fixtures/injections.json).

**Part 2 — the CodeWorks app.** A dedicated UI-only application at
[`s13code/ui/client/codeworks.html`](s13code/ui/client/codeworks.html)
(served on `GET /codeworks`). Dark IDE-inspired theme, starter prompts, a
resizable prompt textarea, a status pill for provider/component counts, a
crumb trail for the conversation, and an inline "validator refused N nodes"
panel so a hostile turn is visible instead of silent. Every reply is a
composed A2UI surface — never raw text.

The 4-turn arc — captured live in
[`proofs/codeworks_turns.json`](proofs/codeworks_turns.json) against
Google Gemini `gemini-flash-latest`, with each turn's exact prompt
(`goal_sent`), components rendered, latency and `run_id` committed to
the file:

| # | Driven by | What the user did | Composed types | CB language | Latency |
|---|---|---|---|---|---|
| 1 | typed | *"I'm writing a data-processing script and I need a helper to smooth noisy time-series values. Which approach fits best?"* | `Button`, `Column`, `ProgressBar`, `Text`, `Timeline` | — | 20.3 s |
| 2 | **tap** on a rendered Button | Clicked *"Moving Averages (SMA/EMA) — Fast, low complexity, good baseline"* | `CodeBlock`, `Card`, `Column`, `ProgressBar`, `Text`, `Timeline` | python | 32.6 s |
| 3 | typed | *"Now translate the current version to TypeScript with proper types."* | `CodeBlock`, `Card`, `Column`, `ProgressBar`, `Text` | typescript · 1 767 chars | 16.8 s |
| 4 | typed | *"Explain what happens inside the for-loop step by step using short bullet points. Do NOT rewrite the code."* | `Card`, `Column`, `Tabs`, `Text` | — (no new CodeBlock) | 17.1 s |

Turn 2 is the assignment's *"a tap in one interface shapes the next"*
property, executed literally: the button label from turn 1's composed
surface is fed back as turn 2's user input by `runTurn(label)` in
`codeworks.html`. No prompt engineering, no server-side state — the tap is
the input.

**`CodeBlock` was chosen unprompted.** The word never appears in any user
prompt in the captured conversation; the model picked it out of the catalog
by shape. Verify straight from the committed proof:

```bash
python3 -c "import json; \
  p = json.load(open('proofs/codeworks_turns.json'))['turns'][0]['goal_sent']; \
  print('turn 1 prompt mentions CodeBlock:', 'codeblock' in p.lower() or 'code block' in p.lower())"
# → turn 1 prompt mentions CodeBlock: False
```

Every turn is a distinct type signature — 4 turns, 4 different component
sets, and the variety check (`Button`-only → `CodeBlock`-python →
`CodeBlock`-typescript → prose) verifies the app doesn't reach for
`CodeBlock` reflexively.

**Screenshots per turn — tap-driven arc on the hosted Modal deploy** —
[`proofs/screens/turn1.png`](proofs/screens/turn1.png) (typed ask →
DataTable + 5 Buttons + BYOK panel), [`turn2.png`](proofs/screens/turn2.png)
(tapped *"Moving Average (SMA / EMA)"* → Python CodeBlock with SMA + EMA
implementations, 3 stat tiles, method-comparison card),
[`turn3.png`](proofs/screens/turn3.png) (tapped *"Explore Other Options"*
→ 5 alternative-technique cards + 5 follow-up Buttons, 3-entry crumb trail),
and [`turn4_refused.png`](proofs/screens/turn4_refused.png) (adversarial
prompt asking for an onload handler + markup-in-language → model refused
at generation time; wall reports 0 rejections because the surface arrived
clean). All four captured by a headless Chromium in
[`proofs/browser_demo.py`](proofs/browser_demo.py) against the live Modal
URL, all pills say `gemini_1 · N components · 0 executable`.

Every turn in the browser is driven by either typing (Ask button, which
by the shared-code convention resets the crumb trail — see
`app.html:522`) or **tapping a Button in the composed surface** (which
calls `choose(label)` → `runTurn(label)`, extending the crumb trail).
The three-turn arc above uses one typed + two taps; the crumb trail at
the bottom of turn 3's screenshot proves the state persisted:
*"I'm writing... › Simple / Exponential Moving Average (SMA / EMA) ›
Explore Other Options"*.

Reproduce hermetically (no live gateway required):

```bash
uv run pytest tests/test_codeworks_app.py -v    # 6 end-to-end tests
```

Reproduce against a live gateway (`glc_v3` on 8111):

```bash
uv run s14code serve &
S14CODE_BASE=http://127.0.0.1:8113 \
  uv run python proofs/codeworks_turns.py   # 4 live turns → proofs/codeworks_turns.json
S14CODE_BASE=http://127.0.0.1:8113 \
  uv run python proofs/codeworks_attack.py  # wall vs poisoned CodeBlock surface

# Re-capture screenshots (needs Playwright — optional dep)
uv sync --group demo && uv run playwright install chromium
S14CODE_BASE=http://127.0.0.1:8113 \
  uv run python proofs/browser_demo.py      # → proofs/screens/turn[1-5].png
```

**Adversarial coverage.** Three attacks are proven refused:

1. `CodeBlock` with an inline `code` literal (not a `$bind`) → refused with
   *data-not-code: binding must be `{"$bind": "/pointer"}`*.
2. `CodeBlock` with an `onload` handler property → refused with
   *data-not-code: event-handler property is never allowed*.
3. `CodeBlock` whose `language` label carries `<script>...</script>` →
   refused with *data-not-code: value carries markup*.

The safe siblings in the same surface still render. Additionally, the
adversarial proof script runs a live prompt-injection turn against the
actual model; the model refused to comply and composed a clean surface. Two
independent defences: the model AND the wall.

**Honest verdict — where it succeeds and where it falls short:**

- The 4-turn arc works. The model chose `CodeBlock` unprompted for every
  code-shaped ask, correctly switched languages when asked to translate,
  and correctly avoided a CodeBlock for the explanation turn. Every
  composed surface re-validated clean.
- The tokeniser handles the top ~12 languages at roughly the quality of
  Prism.js — function-name recognition via lookbehind (`def foo`, `class
  Foo`, `fn bar`), distinct classes for builtins vs keywords, proper
  numeric literal shapes (hex `0xff`, binary `0b101`, scientific `1e10`,
  underscore separators `1_000_000`), decorators/annotations, greedy
  strings, template literals, Java text blocks, Python f-strings and
  triple-quoted docstrings.
- Falls short on: f-string interpolation isn't recursively tokenised (the
  entire f-string renders as one string token, including the `{expr}`);
  HTML/CSS grammars are the simplest of the set and lose semantic
  distinctions like tag-name vs attribute-name; the fallback grammar for
  exotic languages (Kotlin, Elixir, Zig, Haskell) only recognises
  strings/numbers/comments, not language-specific keywords — those
  snippets render as monospace with subtle color hints rather than full
  highlighting. This is the deliberate cost of not shipping a JavaScript
  parsing library.

Nothing is invisible to the user: the language they typed shows in the
header exactly as the model chose it, regardless of whether we have a
grammar for it. The safety story is identical for every language —
`textContent` per span, no `innerHTML` anywhere in the CodeBlock code path.

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
