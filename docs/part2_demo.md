# Part 2 — Getting-Started Assistant (a real app, answering only in UI)

## What it is

A small onboarding/FAQ assistant: you ask it about getting started with something,
and it never writes prose back — it always answers by **composing an A2UI
interface** from the shared catalog (`s13code/ui/catalog.py`), validated by the
same wall that guards injection (`s13code/ui/validator.py`), and rendered by the
same DOM-only render client every other student's component draws through. It
reuses the app scaffold that already ships in this repo (`GET /app`,
[app.html](../s13code/ui/client/app.html)) instead of hand-building screens — the
protocol does the work.

Tapping a `Button` in the composed interface becomes the *next* prompt to the
agent (see `choose()` → `runTurn()` in `app.html`), so a multi-turn conversation
is really just a chain of independent `compose_answer` runs, each one composing
a fresh, validated interface.

## Why it counts as "real"

- It runs against the **real, unmodified** `compose_surface` pipeline in
  [runtime.py](../s13code/runtime.py) — same `content` role, same
  `catalog_manifest()`, same `validate_surface()`.
- It talks to a **real Gemini model** (`gemini-2.5-flash`) through a **real
  glc_v3 gateway** on `127.0.0.1:8111` — not a stub, not a canned response.
- Every interface below is the model's own JSON, validated live, with the
  accept/reject counts to prove it. Nothing was hand-authored.

## How it reuses Part 1's Accordion

The assistant's FAQ-style answers are exactly the shape `Accordion` was built
for: an ordered set of `{heading, points}` sections a user opens one at a time.
`compose_surface`'s per-pointer guidance for `/sections` now names three valid
layouts — Timeline, Cards, or Accordion — so the model is genuinely free to
choose; in both captured turns below it chose `Accordion` on its own.

## Running it yourself

```bash
# 1. Start glc_v3 (owns the real Gemini key)
cd glc_v3 && uv run glc serve            # http://127.0.0.1:8111

# 2. Start the real S14Code app. proofs/patched_app.py runs the UNCHANGED
#    s13code.main:app; the only thing it does differently is swap the memory
#    embedder from OllamaNomicEmbedder to the repo's own DeterministicEmbedder
#    (s13code/core/memory/embeddings.py — already built for "offline demos"),
#    for machines without a local Ollama install. No production file is edited.
cd S14Code
S13_DATA_DIR=/tmp/s14-demo GLC_BASE_URL=http://127.0.0.1:8111 \
  S13_GATEWAY_PROVIDER=gemini S13_A2A_GRPC_ENABLED=0 \
  uv run python proofs/patched_app.py      # http://127.0.0.1:8113

# 3. Open the app
open http://127.0.0.1:8113/app
```

(If your machine already has Ollama running, just use the standard
`uv run uvicorn s13code.main:app --port 8113` instead — `patched_app.py` exists
purely as a no-Ollama convenience for this demo.)

## Captured transcript (real run, saved in full at `proofs/part2_demo_run.json`)

**Turn 1** — user asks the opening question:

> "I want to start contributing to open source. Answer these frequently asked
> questions so I can open one at a time: why should I contribute, what are the
> common early challenges, and what are my first steps. Then ask me which of
> those three topics I want to go deeper on."

`run-ba99aa433798` → `gemini_1` / `gemini-2.5-flash` → **10 components, 0
rejected, clean=true**:

```
Column
├─ Text (heading)      → /title
├─ Text (body)         → /summary
├─ Accordion            title="Frequently Asked Questions", sections → /sections
├─ Column (choices)
│  ├─ Button → /choice_0_label  onPress: request_data
│  ├─ Button → /choice_1_label  onPress: request_data
│  └─ Button → /choice_2_label  onPress: request_data
├─ ProgressBar → /progress_value, /progress_max
└─ Timeline    → /timeline
```

The Accordion's three sections (bound, not inlined) were the model's own real
answers — "Why should I contribute", "What are common early challenges",
"What are my first steps" — each with 6 real bullet points.

**Turn 2** — the user taps the **"What are my first steps?"** button. `app.html`
folds that into the next prompt exactly as it does for any run (`"So far the
user then picked: What are my first steps?. Respond with the next interface for
that."`) and starts a fresh run:

`run-00cbc80dba57` → `gemini_1` / `gemini-2.5-flash` → **9 components, 0
rejected, clean=true**:

```
Column
├─ Text (heading)      → /title ("Your First Steps in Open Source")
├─ Text (body)         → /summary
├─ Accordion            title="Your First Steps", sections → /sections (5 steps, drilled deeper)
├─ Divider
└─ Column (choices)
   ├─ Button → "Choosing the Right Project"
   ├─ Button → "Making Your First Pull Request"
   └─ Button → "Back to Main Topics"
```

The model didn't just repeat the first answer's "first steps" bullets — it
expanded that single topic into five new, more detailed steps, and offered new
follow-up choices, including a "Back to Main Topics" escape hatch it invented
on its own.

## The three invariants, live (not just unit tests)

Both turns above validated with **zero rejections** against real, unfiltered
model output — the same `validate_surface()` unit tests exercise in
[test_s14_ui.py](../tests/test_s14_ui.py). No component here was hand-approved;
every accepted component in both surfaces passed the catalog / data-not-code /
event checks the same way a hostile surface would be checked and rejected.

## A real edge case the demo actually caught

A third live run (a machine-learning-roadmap FAQ, not saved to the transcript
above) hit content generation's shared 700-token cap before finishing its JSON,
so `content`'s structured answer fell back to raw text in `/summary` — but
`compose_surface` still bound `Accordion.sections` to that string pointer.
`validate_surface` correctly still passed it (a `{"$bind": "/summary"}` value
*is* a structurally valid binding; the validator proves the surface can't
smuggle code, not that every pointer's *runtime shape* matches what the
component expects — that's a real, honest limit of a schema-only wall, not a
bug in it). Client-side, `Accordion` would have called `.forEach` on a string
and thrown, blanking the whole surface for one bad component.

Fixed in `renderAccordion()` (both [index.html](../s13code/ui/client/index.html)
and [app.html](../s13code/ui/client/app.html)): the sections binding is now
guarded with `Array.isArray(...)` before iterating, so a malformed bind
degrades to an empty Accordion instead of crashing the page — matching how
`renderComponent`'s unknown-type fallback already avoids blanking the screen
for one bad node. Covered by
`test_render_client_accordion_guards_against_a_non_array_binding` in
[test_s14_ui.py](../tests/test_s14_ui.py). The shared 700-token content cap
itself (`GatewayClient.complete`, [gateway.py](../s13code/gateway.py)) is out
of scope here — it affects every skill in the graph, not just this component.
