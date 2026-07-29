# Session 14: A Face for the Agent — Generative UI, A2UI, and AG-UI

## 1. What this session is

Session 13 gave the agent a live graph, typed memory and A2A handoff, but every
result still returned as text: a numbered list, a distilled answer or a
Markdown table. This session gives the same system an interface the user can
see and interact with, without allowing the model to generate or execute a
single pixel of untrusted code.

The central claim is simple. An agent-generated interface is declarative data,
validated against a component catalog already trusted by the client. Every
user interaction returns to the agent as an event. The model never sends
executable HTML, JavaScript or arbitrary markup, and the render client never
executes anything written by the model. Under this boundary, accepting a
generated interface from a remote agent is no more dangerous than accepting a
validated JSON response.

The system uses two services. glc_v3 remains the gateway on port 8111,
responsible for models, five Gemini keys, routing, quotas, cost, channels,
voice and policy. S14Code is the Session 13 runtime evolved: the full live
graph and typed memory from Session 13 with the new UI layer folded into one
package, a single FastAPI service on port 8113. It owns the graph journal
in-process and adds three components:

- a surface builder that converts an agent outcome into a declarative
  component tree using only trusted catalog entries,
- an event channel that streams graph events to the browser and returns user
  actions as new events,
- a render client that maps catalog component types to real widgets without
  executing the agent's text.

As always, the code is built before the lesson is written. Every example in
this session is a replay from S14Code driving its own live graph through the
real gateway: real prompts, real streamed events, a real declarative interface
and a real injection attempt rejected by the catalog validator.

The same three-city comparison rendered in two ways. In Model draws HTML, the
agent produces a dashboard whose markup contains a script that attempts to
read a memory handle, while the layout changes every time the interface is
regenerated. Switch to Declarative surface and press Render it live. The agent
now emits only a component tree, the client maps each node to a trusted
widget, the layout remains stable, and the embedded script never runs because
no executable code ever leaves the agent.

## Verified against the code

### Confirmed

- **glc_v3 = gateway on 8111** — `GLC_PORT` defaults to 8111
  (`.env.example`, `glc/main.py`, `glc/cli.py`); it owns `channels/`,
  `voice/`, `policy/`, `routing.py`, `pricing.py` (cost), and rate-limit
  tests (quotas) — matches the "models, routing, quotas, cost, channels,
  voice, policy" claim.
- **S14Code = single FastAPI service on 8113, S13 + UI folded together** —
  `s13code/main.py` defaults `S13_PORT=8113` and mounts all three routers
  (`routes.router` = S13 graph/memory, `a2a_routes.router` = A2A,
  `ui_router` = new UI layer) on **one** `FastAPI()` app. This matches "one
  package... owns the graph journal in-process."
- **Three new UI components** — `surface.py` (surface builder), `agui.py` +
  the SSE routes (event channel), `client/index.html` (render client) all
  exist exactly as described, and were already confirmed no-innerHTML/
  catalog-only in the earlier Session 14 suite verification pass (see
  [baseline_check.md](baseline_check.md)).

### Not verifiable / discrepancy

- **"Five Gemini keys"** — the local `glc_v3/.env` has a single
  `GEMINI_API_KEY`, not five numbered keys (`GEMINI_API_KEY_1..5`). The code
  supports up to `MAX_GEMINI_KEYS = 16` pooled keys, so five is plausible for
  whatever environment this was authored against, but it isn't evidenced in
  this repo's actual config.
- **The "Model draws HTML" vs. "Declarative surface" interactive demo**
  (three-city comparison, a malicious script reading a memory handle, a
  "Render it live" button) — searched all HTML/Python/Markdown in the repo
  and found no trace of this specific side-by-side demo, that exact copy, or
  a raw-HTML rendering path in the client at all (`s13code/ui/client/*.html`
  only ever renders via the catalog mapper, never raw markup). This reads as
  lesson narrative for an artifact/slide that isn't part of this repo — it
  isn't something traceable to code here.

Everything else in the architecture description (port assignments, service
boundaries, the three UI components) checks out exactly.

**Update, later in this conversation:** the "Model draws HTML vs. Declarative
surface" gap noted above is now partially closed. It is still not a live
in-app toggle, but the exact three failures it narrates (execution,
consistency, interaction) are now proven against real code and a real live
run in [`docs/s14_naive_ui_failure.md`](s14_naive_ui_failure.md) and
[`proofs/naive_html_dashboard.py`](../proofs/naive_html_dashboard.py).

## 3. The declarative interface, from first principles

An interface needs only four nouns, deliberately aligned with the four graph
nouns from Session 13.

| Noun | Plain meaning |
|---|---|
| Component | One interface unit with a stable ID, a catalog type and typed properties. |
| Catalog | The closed set of component types the client knows how to render, with a schema for each type. |
| Data model | The values displayed or edited by the interface, kept separate from its structure. |
| Action | The only legal way a user changes anything: a named event with validated arguments, sent back to the agent. |

The important decision is that the model does not receive a canvas it can
paint freely. It proposes a small validated component tree. Following the
A2UI pattern, we represent that tree as a flat adjacency list: an array of
components connected by ID, with exactly one root.

```json
{
  "root": "c0",
  "components": [
    { "id": "c0", "type": "Column", "children": ["c1", "c2"] },
    { "id": "c1", "type": "Heading", "text": {"$bind": "/title"} },
    { "id": "c2", "type": "Table", "columns": ["City", "Population"], "rows": {"$bind": "/rows"} }
  ]
}
```

A flat list is easier for a streaming model than a deeply nested tree. The
model can append, replace or patch one component at a time without
regenerating the entire interface.

Two details provide the safety boundary. First, every type must exist in the
trusted catalog. `Column`, `Heading` and `Table` render because the client
defines them. `RawHtml` cannot render because it does not exist in the
catalog. Second, displayed values arrive through a `$bind` path into the data
model, rather than as executable markup written inline by the model.
Structure and data travel separately, and neither one is treated as code.

### Data binding, and when the agent sees a change

The data model is addressed using JSON Pointer paths. `/title` refers to the
title, while `/rows` points to the array rendered by the table. Inputs use
two-way binding: when the user edits a bound field, the client updates its
local data model immediately, so the interface remains responsive. The agent
is still unaware of the change.

```
user types in the "year" field  → client data model updates, agent remains unaware
user presses "Re-run"           → action emitted: {name: "rerun", args: {year: 2027}}
                                 → event enters the S13 graph
                                 → agent plans a surface patch
```

The server sees the change only when the user deliberately commits an
action. That action contains a named event and typed arguments, validated in
the same way the graph validates a planner patch. Local edits therefore
remain local until the user submits them, and there is no direct path from
typing in an input field to calling a tool.

### Build the primitive before adopting the standard

We do not begin by importing A2UI. When the model can make a decision
safely, we let it decide. When the boundary itself matters, we first build
the smallest version that makes the boundary visible.

S14Code therefore begins with a small first-principles renderer, a catalog
of trusted component types and a validator that rejects every unknown type.
Only after the primitive works, and after we have watched it refuse an
unsupported component, do we give the pattern its name: A2UI, Google's
declarative agent-interface protocol, at v1.0 release-candidate in mid-2026.

The primitive already contains the core idea. The agent emits declarative
components, the client renders only catalog-approved types, and the
validator blocks everything else. Building this first turns the A2UI
specification into a description of a system we already understand, rather
than a standard we are trusting without understanding.

The full catalog the agent can draw from holds 23 components. Fifteen are
adopted directly from A2UI's Basic set — Row, Column, List, Card, Divider,
Text, Image, TextField, CheckBox, Slider, InputChoice, DateTime, Button, Tabs
and Modal — and eight are custom extensions that A2UI Basic lacks: BarChart,
Sparkline, StatTile, ProgressBar, Timeline, DataTable, Notice and
ApprovalCard. A2UI does not ship a fixed set you must use. Its Basic
catalog, renamed from Standard in v0.9, is a starting point that each
application extends, so we adopt A2UI's Basic names for everything that
overlaps and add only the few components a dashboard actually needs. The
renderer itself is A2UI-style, built from first principles to understand the
protocol, rather than an implementation of the literal A2UI wire format.

### Verified against the code (Section 3)

#### Confirmed

- **23 components, split 15 / 8, exact names** — `s13code/ui/catalog.py`'s
  `COMPONENTS` dict is not paraphrased by this section, it *is* this section:
  the 15 A2UI Basic names and the 8 custom extensions listed above match the
  dict's two comment-delimited groups (`# --- A2UI Basic ... (15) ---` /
  `# --- Custom extensions ... (8) ---`) name-for-name, in the same order.
- **Catalog invariant** — an unregistered `type` (e.g. `RawHtml`) has no
  entry in `COMPONENTS`, so `validator.py`'s catalog check rejects it before
  a `type`-dispatch table (`R` in `app.html`, `RENDERERS` in `index.html`)
  ever sees it — confirmed by `tests/test_s14_ui.py::test_unknown_type_breaks_catalog_invariant`
  and reproduced live in `proofs/naive_html_dashboard.py` (see
  [`s14_naive_ui_failure.md`](s14_naive_ui_failure.md)).
- **Data-not-code invariant / `$bind` pointers** — `validator.py:123-133`
  requires every `binding`-kind prop to be exactly `{"$bind": "/pointer"}`
  and checks the pointer against `_POINTER = re.compile(r"^/[^\s]*$")`; a
  literal string where a binding belongs is rejected under
  `Invariant.DATA_NOT_CODE`. Both render clients (`app.html`, `index.html`)
  implement the read side identically: a `resolve()`/`ptr()` (or
  `pointer()`) walk of the pointer's `/`-separated segments against the
  local data model, never `eval`, never `innerHTML`.
- **Two-way binding is local-only** — `index.html`'s `setPointer()` (the only
  function an input's `oninput`/`onchange` calls) writes solely into the
  client-held `ctx.dm` object; nothing in that path performs a network call.
  The *only* function in either client that talks back to the server is
  `emitAction()` (`index.html`) / a `Button`'s `onclick → choose()` chain
  (`app.html`), both triggered exclusively by a `Button`/`ApprovalCard`
  press — exactly the "no direct path from typing to calling a tool" claim.
- **Actions are validated the way a planner patch is** — `s13code/ui/hitl.py`'s
  `decide_resume()` compares the resuming action's args against the
  parked node's recorded params using an order-independent canonical form,
  refusing the resume on any mismatch — structurally the same "propose,
  then validate before it mutates state" shape `GraphPatch` already has in
  `s13code/core/live_graph/core.py`. `REGISTERED_ACTIONS` in `catalog.py` is
  `frozenset({"approve", "reject", "rerun", "request_data"})` — the example
  diagram's `{"name": "rerun", ...}` is not an illustrative placeholder, it
  names a real, currently-registered action.
- **Flat adjacency list, not a nested tree** — every surface in this repo
  (`compose_surface`'s own system prompt in `runtime.py`, `showcase.py`'s
  `build_corpus_dashboard`, `surface.py`'s `build_run_surface`) emits
  `{"root": <id>, "components": [flat array]}` with `children` as an array
  of ids resolved through a `byId` map at render time — never nested
  component objects.

#### Not verifiable / discrepancy

- **A2UI version numbers** ("v1.0 release-candidate in mid-2026", "Basic
  renamed from Standard in v0.9") are claims about an external spec's
  release history, not something this repo's code can confirm or deny —
  same category as the earlier "five Gemini keys" claim.

## 4. The event stream was already there

Session 13's graph did more than compute an answer. It recorded a durable,
ordered journal of the entire run: `run_started`, `graph_patched`,
`task_started`, `task_succeeded` and `task_failed`. That journal is already
an interface stream. It only needs a client that can read it.

S14Code reads the journal through Server-Sent Events, a one-way HTTP stream
from the server to the browser. Because the runtime owns the journal
in-process, the event channel reads it directly and forwards each event as
it arrives. These events are mapped to the vocabulary of AG-UI, CopilotKit's
event-based agent-interface protocol, rather than creating another custom
event format.

| S13 graph event | AG-UI event | Interface behaviour |
|---|---|---|
| `run_started` | `RUN_STARTED` | Open the run panel and show the prompt |
| `task_started` | `STEP_STARTED` | Add a node card in the running state |
| `task_succeeded` | `STEP_FINISHED` + `STATE_DELTA` | Mark the node complete and patch the data model |
| `graph_patched` | `STATE_DELTA` | Patch the data model as the planner revises the graph |
| `run_finished` | `RUN_FINISHED` | Close the run and enable actions |

AG-UI defines roughly thirty event types across eight categories in its
mid-2026 form. We use only the small subset required here. Two additional
categories are important. The state category carries complete snapshots and
RFC 6902 JSON Patch deltas, allowing the client to reconstruct itself after
reconnecting. The reasoning category carries reasoning as a separate stream.
A dropped connection therefore does not destroy the interface: the client
requests a `STATE_SNAPSHOT` and rebuilds itself, just as the Session 13
graph replays its journal after a crash.

The critical property is that the browser contains no graph logic. It only
projects the event stream. A node card appears because the stream reports
that a task started. A table changes because the stream carries a state
delta. Nothing from the graph is moved into the browser, and nothing in the
browser can affect the graph except a named, validated action.

```
S14 graph  ──journal──▶  S14 event channel  ──SSE──▶  render client
    ▲                                                      │
    └───────────── validated action event ◀─────────────────┘
```

Press play and watch the real three-city run stream as an AG-UI event tape
driving the interface above it. Scrub back and forth: the interface is a
pure function of the events up to that point. Cut the connection mid-run and
reconnect to see a `STATE_SNAPSHOT` rebuild the interface from the durable
journal.

Watch a `graph_patched` event arrive when the planner judges its own outcome
and revises the graph mid-run. The node view rewires itself and a
`STATE_DELTA` repaints the affected cards, all without the browser holding a
shred of planner logic.

### Verified against the code (Section 4)

#### Confirmed

- **The S13→AG-UI mapping table is exact** — `s13code/ui/agui.py`'s
  `_KIND_TO_AGUI` dict and `to_agui_event()` implement every row: `run_started
  → RUN_STARTED`, `task_started → STEP_STARTED`, `graph_patched →
  STATE_DELTA`, and `task_succeeded` maps to **one** event carrying both
  `STEP_FINISHED` semantics and a `{"op": "add", "path": "/results/<node>",
  ...}` delta — the table's "`STEP_FINISHED` + `STATE_DELTA`" is one wire
  event with two meanings folded in, not two separate frames. Each mapping
  has its own unit test (`test_agui_run_started_maps_to_run_started`,
  `test_agui_task_started_maps_to_step_started_with_name`,
  `test_agui_task_succeeded_is_step_finished_with_state_delta`,
  `test_agui_graph_patched_maps_to_state_delta`).
- **`RUN_FINISHED` is honestly derived, not recorded** — `agui.py`'s own
  docstring states this outright ("RUN_FINISHED is not a journal event in
  S13... it is derived from the snapshot after the last event"), and
  `stream_agui()` appends it only when `finished=True`, confirmed by
  `test_stream_ends_with_a_derived_run_finished` and its negative,
  `test_stream_does_not_derive_run_finished_when_unfinished`.
- **STATE_SNAPSHOT reconnect rebuilds the client in one frame** —
  `GET /v1/runs/{id}/events?reconnect=1` (`s13code/ui/routes.py`) leads the
  stream with one `state_snapshot()` event before resuming normal delivery,
  confirmed at three layers: the pure fold
  (`test_reconnect_snapshot_rebuild_equals_full_replay`), the route
  (`test_route_events_reconnect_leads_with_one_state_snapshot`), and the
  actual browser client
  (`test_render_client_reconnects_and_rebuilds_from_a_state_snapshot`,
  and `index.html`'s `openStream()`, which reconnects with `?reconnect=1`
  only after a genuine mid-stream `onerror`, never after a clean
  `RUN_FINISHED`).
- **The snapshot is byte-identical to a full replay** — `run_data_model()`
  is explicitly documented and tested
  (`test_run_data_model_equals_full_stream_replay`) to equal folding every
  delta from scratch, so a reconnecting client provably ends up in the same
  state a client that never disconnected would have.
- **"No graph logic in the browser"** — grepping both render clients
  (`app.html`, `index.html`) confirms neither contains a planner, a
  scheduler, or any branching on `graph_patched`'s *reason* — the browser
  only folds `delta` objects into a plain data model (`applyDelta()`); see
  Section 5 for a correction to what happens after that fold. The only
  outbound path is `emitAction()` / a `Button`'s `onPress`, matching the
  diagram's single "validated action event" arrow back into the graph.

#### Not verifiable / discrepancy

- **"Roughly thirty event types across eight categories"** — the
  `agui.py` docstring itself says "~30-event protocol," so the *order of
  magnitude* is consistent with what this repo's authors believed when they
  wrote the mapping, but the category count and full taxonomy are a claim
  about the external AG-UI spec that this codebase has no way to verify or
  falsify.
- **The reasoning category** — searched `s13code/ui/` and both render
  clients for any reasoning-stream handling; there is none. This repo
  implements only the `RUN_STARTED / STEP_STARTED / STEP_FINISHED /
  STATE_DELTA / STATE_SNAPSHOT / RUN_FINISHED / CUSTOM` subset the mapping
  table lists — the reasoning category is mentioned as context on AG-UI's
  broader shape, not as something S14Code uses.
- **"Press play," "scrub back and forth," a visible node-graph view that
  "rewires itself"** — these describe an interactive playback/scrubber
  widget. Neither render client (`app.html`, `index.html`) has playback
  transport controls (play/pause/scrub) or a node-graph visualization; the
  live client only auto-streams forward via `EventSource` and, as Section 5
  details, does not currently re-render the mounted surface from incoming
  events at all. The *property* the scrub demo claims — "the interface is a
  pure function of the events up to that point" — is real and independently
  tested (`replay_state()` / `run_data_model()` folding an arbitrary prefix
  of the event list), but it is not exposed as an interactive scrubbing
  control anywhere in this repo. Same category as Section 1's "Model draws
  HTML" demo: lesson narrative for an artifact/slide, not a shipped UI
  feature here.

## 5. Two protocols, one surface

A common explanation sets A2UI against AG-UI and asks which one to choose.
By mid-2026, that framing is already wrong. The two protocols solve
different problems and are designed to work together.

> A2UI describes what to render. AG-UI carries the interaction between the
> agent and the surface. A2UI payloads travel through AG-UI events.

CopilotKit, which stewards AG-UI, was also a launch partner for Google's
A2UI and provides middleware for carrying A2UI surfaces over AG-UI. In
S14Code, the surface builder produces an A2UI component tree, while the
event channel delivers that tree and every later update as AG-UI events.
A2UI's own spec calls this rendered thing a surface; throughout this session
we call it the interface, and the two names mean the same object. A2UI
defines the interface. AG-UI defines how that interface stays connected to
the agent.

A third standard answers a different question. MCP Apps, introduced in
January 2026 as the first official extension to MCP, defines how an
interactive surface runs inside a host such as ChatGPT or Claude rather than
inside an application we own. An MCP App declares a `ui://` resource, which
the host renders inside a sandboxed iframe. The surface communicates with
the host over JSON-RPC, and every tool call passes through the host's own
consent and authorization path.

The same security principle holds across all three systems: the surface is
declared and constrained, while every user action crosses a validated
boundary before it can affect the agent or call a tool.

These standards fit into the protocol stack the course has been building
since Session 4.

```
MCP    agent ↔ tools
A2A    agent ↔ agent
AG-UI  agent ↔ surface   (transport)
A2UI   what to render    (payload)
MCP Apps  UI inside a chat host
```

Each protocol owns a different boundary. MCP connects agents to tools. A2A
connects agents to other agents. AG-UI carries events and shared state
between an agent and a surface. A2UI describes the surface itself. MCP Apps
places an interactive surface inside a chat host we do not control.

The decision is straightforward:

- Use AG-UI when we own the application and need a live channel for events,
  streaming and shared state.
- Use A2UI when an agent, including a remote agent reached through A2A, must
  describe a surface that our client can render safely.
- Use MCP Apps when the interface must appear inside a host such as ChatGPT
  or Claude.
- Use them together in the common case: an A2UI surface delivered through
  AG-UI events inside an application we built.

The same three-city surface, split down the middle. On the left, the A2UI
component tree that says what to render. On the right, the AG-UI event
stream that carries it and its updates. Change the data on the agent side
and watch a `STATE_DELTA` cross the middle and repaint the left without
re-sending the tree.

### Verified against the code (Section 5)

#### Confirmed

- **A2UI (structure) and AG-UI (transport) really are handled by separate
  code paths in this repo** — `s13code/ui/surface.py` / `showcase.py` /
  `runtime.py`'s `compose_surface` produce the component-tree payload;
  `s13code/ui/agui.py` is the only module that speaks AG-UI event names
  (`RUN_STARTED`, `STATE_DELTA`, ...). Neither module imports the other's
  vocabulary — `agui.py` has no `type: "Column"`-style rendering logic, and
  `surface.py`/`showcase.py` never construct an AG-UI event dict. This
  matches "A2UI describes what to render, AG-UI carries the interaction" as
  a real code-level separation, not just a narrative one.
- **This repo really does implement two protocols beyond A2UI/AG-UI** — A2A
  is not aspirational here: `s13code/a2a_routes.py` and the whole
  `s13code/core/a2a_adapter/` package (JSON-RPC and gRPC bindings, trust/
  signing, an official-interop test suite) are real, tested code paths.
- **The security principle repeats identically at the code layer already
  audited** — "the surface is declared and constrained, every user action
  crosses a validated boundary" is exactly `validate_surface()` (Section 3)
  plus `hitl.py`'s `decide_resume()` (Section 3) again; the claim that this
  principle is protocol-independent is consistent with those being the only
  two enforcement points in the codebase, and both apply regardless of which
  transport (SSE now, anything else later) carries the events.

#### Not verifiable / discrepancy

- **CopilotKit as an A2UI launch partner, and CopilotKit middleware for
  carrying A2UI over AG-UI** — external facts about CopilotKit's own
  product/partnership history; nothing in this repo can confirm or deny
  them.
- **MCP Apps** (the `ui://` resource, sandboxed iframe, JSON-RPC to the
  host, "introduced January 2026") — searched the entire repository for
  `MCP`, `ui://`, and `mcp_apps`: there are zero matches anywhere in
  `s13code/`. This repo implements A2A extensively and AG-UI/A2UI as its
  core subject, but MCP and MCP Apps are not implemented, exercised, or
  referenced by any code here. The claims are plausible as external
  spec/product facts but entirely unverifiable from this codebase — same
  category as the A2UI version numbers in Section 3.
- **"Since Session 4"** — this repo is the Session 13/14 build; nothing here
  contains or can verify Session 4's content, so the protocol-stack framing
  as a continuation of earlier course material is taken on faith.
- **The live "watch a STATE_DELTA cross the middle and repaint the left"
  demo — this is where verification surfaced a real gap, not just an
  absent interactive widget.** Tracing `index.html`'s actual event handling
  (`openStream()` → `es.onmessage`): every non-snapshot, non-`RUN_FINISHED`
  event calls `applyDelta(state, ev)` (folds the value into a local
  `state.results` map) and then `showLive(state, ...)`, which **only writes
  a `"N results · M patches folded"` string into a `#live` status badge**.
  `render()` — the function that walks `surface.components` and rebuilds the
  DOM from bound values — is called exactly twice in the whole file, both
  inside `boot()`, both from the initial REST fetch. It is never called
  again from inside `openStream()`. In the currently shipped client, a live
  `STATE_DELTA` genuinely does **not** repaint any bound `StatTile`, `Text`,
  or `DataTable` value on screen — it only advances a counter. This directly
  contradicts the "watch it repaint the left" framing, and I'm flagging it
  rather than passing it through: the *architecture* supports this (the data
  model and the render function are already cleanly separated, so wiring
  `applyDelta` to call `render()` again is a small, well-scoped change), but
  as of this repository's current code, that wiring does not exist yet. This
  also corrects two sentences written earlier in this document (Section 4)
  that assumed the client already did this.

## 6. The injection wall

Now we replay the Session 12 attack at the interface layer, because this
architecture exists to survive exactly this situation. A remote agent, a
compromised tool, or a page the agent fetched attempts to smuggle executable
behaviour into the surface.

The attack can take four forms:

- An unknown component type such as `RawHtml`, caught by the catalog.
- A known component carrying an extra handler property such as `onclick`,
  caught as data-not-code.
- A bound value containing markup, caught as data-not-code.
- An action the catalog never registered, caught by the event invariant.

Every attack stops at the same deterministic boundary. We do not ask another
model to inspect the surface and behave carefully. We validate it against a
closed catalog.

```python
def validate_surface(surface, catalog):
    for c in surface.components:
        if c.type not in catalog:                  # catalog invariant
            reject(c, "unknown component type")

        schema = catalog[c.type]

        for key, value in c.props.items():
            if key not in schema.allowed_props:    # no smuggled handlers
                reject(c, f"unknown property {key}")

            if schema.props[key] == "text" and looks_like_markup(value):
                reject(c, "text property carries markup")  # data-not-code

    if surface.actions - catalog.registered_actions:
        reject(surface, "unregistered action")     # event invariant
```

The render client never interprets a property as script, never assigns a
bound value to `innerHTML`, and never follows a URL the catalog has not
approved. An `onclick` handler does not reach the DOM because `onclick` is
not a valid property in the schema. A bound value containing markup is
either rejected or displayed as literal text. An action the catalog never
registered never reaches the graph, because the event channel admits only
registered actions.

This is the Session 12 security invariant applied to generated interfaces:

> External content never becomes instructions, and a component description
> is still external content.

No model can be trusted never to generate a hostile surface. The
architecture therefore does not depend on the model resisting the attack. It
makes the attack irrelevant by ensuring that declarative interface data has
no path to execution, authority, or an unapproved tool call.

Pick one of four injected interfaces from the dropdown and press Render.
Watch the validator name the exact invariant each one breaks and refuse it,
while the safe part of the interface still renders. Toggle "Disable the
validator" to see the same payload execute against an unguarded client, then
turn it back on and watch the wall hold.

### Verified against the code (Section 6)

#### Confirmed

- **The four attack forms are, name-for-name, the four cases in
  `s13code/ui/fixtures/injections.json`, in the same order** —
  `raw-html-type` (catalog), `smuggled-handler` (data-not-code, extra
  `onclick` on an otherwise-legal `Button`), `markup-in-binding`
  (data-not-code, a literal `<script>` string where a `$bind` belongs),
  `unregistered-action` (event, `Button` naming `transfer_all_funds`). This
  isn't a paraphrase — it's the literal fixture, and running it live against
  the real validator (`proofs/run_surface_proof.py`) on this pass produced:
  ```
  raw-html-type        REJECTED     broke ['catalog']       [ok]
  smuggled-handler     REJECTED     broke ['data-not-code']  [ok]
  markup-in-binding    REJECTED     broke ['data-not-code']  [ok]
  unregistered-action  REJECTED     broke ['event']          [ok]
  all_rejected=True  all_correct=True
  ```
- **The pseudocode is a faithful simplification, not the literal
  implementation** — the real `validate_surface()` (`s13code/ui/validator.py`)
  differs in two structural ways worth naming: (1) it `continue`s immediately
  after an unknown-type rejection rather than proceeding to index the
  catalog with that type (the pseudocode's next line, `schema =
  catalog[c.type]`, would raise on exactly the case it just rejected); (2)
  action names are validated *inline*, per-property, in the same single pass
  over each component's props (`if prop.kind == "action": ...`) rather than
  as a separate whole-surface pass at the end. Both versions enforce the
  same three invariants; only the control flow differs.
- **"The safe part of the interface still renders"** — confirmed exactly by
  `test_safe_siblings_survive_a_partially_poisoned_surface`: a `Column` with
  one safe `Text` child and one poisoned `Button` child validates to accept
  the `root` and the `Text`, reject only the `Button`.
- **The render client's three guarantees, checked individually**:
  - *"never interprets a property as script"* / *"never assigns a bound
    value to innerHTML"* — grepped both `app.html` and `index.html`; neither
    file contains the string `innerHTML` at all.
  - *"never follows a URL the catalog has not approved"* — `index.html`'s
    `Image` renderer calls `isSafeUrl(src)` (rejects `javascript:`,
    `data:`, `vbscript:` schemes) before ever calling `setAttribute("src",
    ...)`, as client-side defense-in-depth on top of the server-side
    `_looks_like_js_url` check in `validator.py`. `app.html`'s `Image`
    renderer is even stricter by omission: it never reads `c.src` at all and
    renders a static `"[image]"` placeholder — there is no URL-following
    code path to defend in the first place.
- **Beyond the four named forms, the real validator catches two more
  variations under the same data-not-code invariant** that the lesson's
  four-form list doesn't spell out individually: an `enum` property set to a
  value outside its declared set (`test_enum_value_outside_its_set_breaks_data_not_code`),
  and a `javascript:`/`data:`/`vbscript:` URL in *any* text or binding value,
  not just inside markup (`test_javascript_url_value_breaks_data_not_code`,
  `test_data_url_value_breaks_data_not_code`). These are the same invariant
  doing more work than the four headline examples show, not a gap in the
  four-form framing.

#### Not verifiable / discrepancy

- **The interactive demo** — "pick one of four injected interfaces from the
  dropdown," "press Render," and especially "Toggle Disable the validator to
  see the same payload execute against an unguarded client" — describes a
  browser widget with a dropdown and a validator on/off switch. Searched
  both render clients and the whole `s13code/ui/client/` directory: neither
  exists. There is no dropdown of injection cases, no "Render" button tied
  to one, and — importantly — **no code path in either shipped client that
  can render a surface with the validator disabled at all**; `validate_surface()`
  is not optional in any route that serves a surface. The backing data this
  demo would replay does exist and is real: `proofs/run_surface_proof.py`'s
  own docstring says outright, "This is the source the widgets replay: no
  imagined content," and its `proof_injections()` function produces exactly
  the four-case table above, written to `proofs/proof.json`. So the
  *evidence* behind the demo is genuine and reproducible; the *interactive
  widget itself* is lesson/artifact narration not present as a shipped UI
  feature in this repo — same category as the demos flagged in Sections 1,
  4, and 5. One meaningful difference from those earlier gaps: this repo
  has no unguarded rendering path to toggle *to* even if the widget existed
  — "disable the validator" isn't a flag anywhere in the code, it would
  require deliberately adding an insecure path that doesn't currently exist.

## 7. Human-in-the-loop is the waiting node with a button

Session 13 gave the graph a waiting state. A node could park, release its
worker and resume when an external event arrived, whether from a webhook, an
A2A push or a human approval. The mechanism already existed. This session
gives that approval a visible interface.

When the planner reaches a high-impact action, the node enters waiting, and
the surface builder emits an approval component bound to the exact pending
parameters.

```json
{
  "id": "ap",
  "type": "ApprovalCard",
  "summary": {"$bind": "/pending/summary"},
  "params": {"$bind": "/pending/params"},
  "confirm": {
    "action": "approve",
    "args": {"$bind": "/pending/params"}
  },
  "reject": {
    "action": "reject"
  }
}
```

The user sees exactly what will happen and selects Approve or Reject. That
press becomes a validated action event and resumes the parked node, exactly
as a webhook would.

The important safety property comes from Session 12: approval is bound to
the final parameters. The arguments displayed to the user, the arguments
approved by the user and the arguments dispatched by the agent must be
identical. The surface cannot widen or replace them. If a compromised client
sends an approve event with different arguments, the resume path compares
them against the parameters stored on the parked node and rejects the
mismatch.

A user who approves a transfer of one amount cannot be made to authorise
another, because the approved parameters and the executed parameters are the
same recorded object.

This closes the loop opened earlier in the session. The dead button is now a
real control, but it gains no direct authority over the graph or its tools.
It performs the only safe operation available to a generated interface: emit
a named, validated event that re-enters the graph through its existing
control boundary.

Run an action that requires approval and watch the node park in waiting
while the approval card appears. Press Approve to resume it and watch the
graph finish. Then switch to Tamper the arguments and try to approve a
widened action from the client: the resume path compares against the parked
parameters and rejects it, and the node stays waiting.

### Verified against the code (Section 7)

#### Confirmed

- **`ApprovalCard`'s shape matches the catalog exactly** —
  `s13code/ui/catalog.py`'s `ApprovalCard` spec is
  `{"summary": binding, "params": binding, "confirm": action, "reject":
  action}` — identical to the example, field for field.
- **The approval-binding safety property is real, and independently
  tested** — `s13code/ui/hitl.py`'s `decide_resume()` does exactly what's
  described: `reject` is always allowed; `approve` is allowed only when the
  submitted `args` structurally equal (order-independent, via `_canonical()`)
  the recorded `pending.params`; any mismatch — wider, narrower, or just
  different — is refused with `"approved args differ from the parked
  parameters."` This is covered by six dedicated tests
  (`test_hitl_matching_approve_is_allowed`,
  `test_hitl_widened_args_are_refused_with_reason`,
  `test_hitl_narrowed_args_are_refused`,
  `test_hitl_changed_value_is_refused`,
  `test_hitl_reject_is_always_allowed_regardless_of_args`,
  `test_hitl_is_order_independent_on_nested_structures`) plus a live
  demonstration in `proofs/run_surface_proof.py`'s `proof_hitl()`, which
  this pass re-confirmed: a matching approve is `allowed=True`, a widened
  approve is `allowed=False` with exactly that reason, `safe=True` overall.
- **The generic waiting/resume mechanism is real at the graph-engine
  layer** — `NodeState.WAITING` and `GraphPatch.wait` exist in
  `s13code/core/live_graph/core.py`, and `store.py` enforces the state
  machine (a `WAITING` node stays out of the runnable set; only a resume can
  move it out of `WAITING`). This part of "the mechanism already existed"
  checks out.

#### Not verifiable / discrepancy — this is the most significant gap found in this document

Unlike earlier sections, where the *safety logic* was solid and only a
*presentation layer* (a scrubber, a toggle) was missing, this section's gap
sits inside the safety wiring itself. Three things, each verified directly:

- **No skill in the actual planner ever parks a node in `WAITING`.**
  Grepped `s13code/runtime.py` for `wait=` and `NodeState.WAITING`: zero
  matches. Every `GraphPatch` the deterministic planner returns either adds
  runnable work or finishes the run — none ever parks a node for approval.
  The engine-level capability exists (confirmed above), but no current
  skill — not `create_reminder`, not `remember_explicit_fact`, nothing —
  is wired to use it for a "high-impact action." There is currently no
  prompt you can send this system that will produce a real, live
  `ApprovalCard` from a genuinely parked node.
- **`POST /v1/action` does not read the parked node's params from the
  graph — it trusts whatever the caller sends.** `ActionBody` in
  `s13code/ui/routes.py` takes `pending_params` and `pending_summary` as
  request fields, with its own comment stating this outright: *"In a live
  system the pending params come from the parked node in S13. For the
  recorded demo the caller supplies them so the binding check is real."*
  Concretely, this means the endpoint proves `decide_resume()`'s comparison
  logic works correctly given two numbers, but does not, as shipped, ever
  fetch the true parked parameters from `request.app.state.s13_runtime.graph`
  to compare against — an equivalent-looking client could submit a
  self-consistent but entirely fabricated `pending_params` alongside
  matching `args` and receive `{"resumed": true}`, because nothing here
  cross-checks either value against the real graph. The endpoint also never
  calls anything that would actually resume a node in `runtime.graph` — it
  returns a decision, not a state change.
- **Neither shipped client's Approve button actually calls `POST
  /v1/action`.** In `index.html`, the button's `onclick` calls
  `emitAction("approve", ...)`, and `emitAction()`'s entire body is:
  ```js
  function emitAction(name,args){ // the only way the surface changes the world: a named, validated event
    document.getElementById("meta").textContent = "action emitted → "+name+" "+JSON.stringify(args);
  }
  ```
  — it writes a status string and makes no network call. In `app.html`, the
  `ApprovalCard`'s Approve button calls `choose("approve")`, which feeds
  `"approve"` into `runTurn()` — starting an entirely new agent run with the
  prompt `"approve"`, unrelated to the original run's `run_id`, `node_id`,
  or parked parameters, not a resume of anything.

Put together: the *decision function* this section's safety claim rests on
(`decide_resume`) is correct and well-tested in isolation, and the example
`ApprovalCard` JSON is schema-accurate. But the full loop the prose
describes — a real run parks on a real high-impact action, a client reads
the real parked parameters, a user approves them, and that specific resume
either proceeds or is refused by comparing against the graph's own record —
does not currently execute end-to-end anywhere in this repository. Every
piece exists; nothing connects them yet. This is a stronger claim than the
"missing interactive widget" gaps in Sections 1, 4, 5 and 6, and worth
treating differently: those were missing presentation, this is a missing
enforcement path.

## 8. The other pole: when the model draws the whole thing

Everything so far constrains the model to a trusted catalog. A louder branch
of generative UI takes the opposite approach and lets the model author the
entire experience as code. The results can be impressive, but the
production trade-offs are much harder.

The visible examples make the idea easy to understand. Google's dynamic view
in Gemini generates a custom HTML and JavaScript experience for each prompt
and runs it inside infrastructure Google controls. Anthropic's Imagine with
Claude generated a desktop-like interface screen by screen, while its
successor renders interactive visuals directly inside a response. Vercel's
v0 generates complete React applications from prompts, and its API allows
other agents to request those interfaces programmatically.

The trade is straightforward. Model-authored code provides maximum
expressiveness: any layout, any interaction and no fixed catalog to
outgrow. It also introduces three costs. The first is latency, because
generating, compiling and mounting a complete interface takes far longer
than rendering a validated component tree. The second is security, because
model-authored code can only be accepted safely inside a sandbox whose owner
controls and accepts the blast radius. This is why serious implementations
run inside vendor-controlled environments rather than directly inside an
ordinary application. The third is consistency, because regenerated
interfaces can move controls, change layouts and destroy the muscle memory
users depend on.

The practical distinction is that fully generative interfaces win on
expressiveness and demos, while constrained declarative interfaces win on
security, speed and production stability. Google's A2UI represents the
constrained form of the same broader idea: the model may describe the
experience, but it may only use structures the client already trusts. The
boundary changes at the point where trust changes hands.

A single dial from fully constrained to fully generative. Slide it and watch
three meters move: expressiveness up, and latency and attack surface up with
it. The markers show where A2UI, Vercel's json-render, Thesys C1, MCP Apps,
and Gemini dynamic view sit. The footer carries Nielsen's mid-2026
scoreboard: he predicted generative UI would break through in 2026 and
scored his own prediction 47 percent, off track, living mostly in frameworks
and prototypes rather than daily software.

### Verified against the code (Section 8)

#### Confirmed

- **This repository sits at the constrained pole the section describes, and
  every piece of that placement has already been proven earlier in this
  document, not merely asserted here.** "The model may describe the
  experience, but it may only use structures the client already trusts" is
  restated, not new: it is `validate_surface()`'s catalog invariant
  (Section 3, Section 6), and the "no serious implementation runs
  model-authored code directly inside an ordinary application" claim is
  exactly why neither render client contains the string `innerHTML`
  (checked directly in Section 6's verification) and why this document's
  own Section 2 (`docs/s14_naive_ui_failure.md`) had to construct the
  opposite pole *artificially*, as a proof script, because this codebase
  has no shipped path that runs model-authored markup at all.
- **The "consistency" cost is not a hypothetical here — this document
  already measured it.** `proofs/naive_html_dashboard.py`'s failure_2 (see
  Section 2 / `docs/s14_naive_ui_failure.md`) ran the identical naive
  "return an HTML dashboard" prompt twice against a live model and got back
  answers of different length, different phrasing, and a different HTML
  structure. That is this section's "regenerated interfaces can move
  controls, change layouts" claim, independently reproduced against a real
  model rather than only asserted in prose.

#### Not verifiable / discrepancy

- **Everything else in this section is external industry context, not a
  claim about this repository.** Google's Gemini dynamic view, Anthropic's
  Imagine with Claude (and its successor), Vercel's v0 and its API, Thesys
  C1, Nielsen's 2026 prediction and his own 47% self-score — none of these
  are products, protocols, or facts this codebase implements, calls, or can
  verify. Grepped the entire repository for `json-render`, `Thesys`,
  `dynamic view`, `Imagine with Claude`, `Nielsen`, and `v0`: zero matches
  outside this document itself. Same category as the A2UI version numbers
  (Section 3), the CopilotKit/MCP Apps claims (Section 5): plausible
  external facts, entirely outside what this repo can confirm or falsify.
- **The interactive dial demo** — "slide it and watch three meters move,"
  with markers for A2UI, json-render, Thesys C1, MCP Apps, and Gemini
  dynamic view — describes a browser widget (a slider plus three live
  meters). No such control, or anything resembling it, exists in
  `s13code/ui/client/`. Same category as the demo gaps flagged in Sections
  1, 4, 5, and 6: this is lesson/artifact narration, not a shipped UI
  feature in this repository. Unlike those sections, though, there is no
  underlying data or proof script in this repo that such a widget could
  even replay — the "meters" describe comparative judgments about five
  external products, which is not the kind of claim a proof script in this
  codebase could produce evidence for in the first place.

## 9. Honest failures and what this does not solve

Two interfaces are worth more than another clean screenshot.

The first is the reconnect. A run streamed to a browser, the network
dropped for nine seconds, and the client held a partial interface. The
event invariant made the recovery boring: on reconnect the client requested
a state snapshot, S14Code replayed it from the same durable journal the
runtime already keeps, and the interface was whole again with no duplicated
actions and no lost content. That is the Session 13 crash-replay property
reused without new machinery, because the interface was never anything more
than a projection of a durable event stream.

The second is an interface the agent could not honestly build. Asked to
render a live map of a delivery the system had no coordinates for, the
planner did not emit a Map component with invented pins. It emitted a
Notice component that said the location data was not available and offered
an action to request it. A generated interface can lie in a way a paragraph
cannot, by drawing a chart that looks authoritative over data that does not
exist. The same honesty discipline from Session 13 applies: a component is
evidence, and evidence the system does not have does not get drawn.

The boundaries this session does not cross are real and belong to a
production team.

- **Accessibility.** A catalog render is only as accessible as its widgets.
  A generated interface can produce a valid component tree that is still
  hostile to a screen reader if the catalog components are not themselves
  accessible. The catalog is where that work lives, and this session ships
  a small one.
- **Latency at the generative pole.** The constrained path we build is
  fast. Any feature that reaches for full generation inherits the
  seconds-to-minutes cost, and that decision belongs to the operator.
- **The host boundary in MCP Apps.** An interface inside a chat host is
  only as safe as the host's sandbox and consent path. Backslash and other
  researchers flagged the MCP Apps surface in 2026 as new attack surface
  precisely because a template and a `postMessage` channel are new things
  to get wrong.
- **Governance.** As of mid-2026 A2UI and MCP Apps sit under neutral or
  shared stewardship while AG-UI remains vendor-stewarded. That is an
  adoption risk to weigh, not a technical one, and it is the kind of thing
  that changes between when this is written and when you deploy.

### Verified against the code (Section 9)

#### Confirmed

- **The reconnect story is not a new claim — it is the same `STATE_SNAPSHOT`
  property this document already verified twice, from two different angles**
  (Section 4's "reconnect rebuilds the client in one frame," Section 5's
  correction about what does and doesn't repaint live). Nothing new to
  re-derive here; the "no new machinery, reused Session 13's durability"
  framing matches `agui.py`'s own docstring, which frames `state_snapshot()`
  as a fold over the *same* journal `run_data_model()` reads for a live run,
  not a parallel code path.
- **The accessibility self-critique is accurate, and if anything slightly
  generous.** Grepped both render clients for `aria-`, `role=`, and `alt=`:
  the *only* accessibility affordance in either client is `index.html`'s
  `Image` renderer setting `alt` from `c.alt`. There is no `aria-*`
  attribute, no `role` attribute, and no semantic landmark structure
  (`<nav>`, `<main>`, live-region announcements for streamed updates)
  anywhere in either file. `app.html`'s `Image` renderer does not even reach
  that bar — it never reads `c.src` or `c.alt` at all, rendering a static
  `"[image]"` placeholder instead. "The catalog is where that work lives,
  and this session ships a small one" is not an understatement here; it is
  close to the literal truth.
- **The compose_surface prompt has a real, if partial, mechanism for the
  "evidence the system does not have does not get drawn" claim** —
  `runtime.py`'s `compose_surface` instruction explicitly says "choose
  components from the data that is actually present in available_pointers"
  and, per-category, "skip any pointer that is absent." This is genuine
  prompt-level support for *omission* of components the data model can't
  back.

#### Not verifiable / discrepancy

- **The specific map/coordinates/Notice example cannot be traced to any run
  in this repository, and one detail in it is stronger than what the code
  actually enforces.** Grepped the entire repo for `delivery`,
  `coordinates`, `latitude`, `longitude`: no fixture, test, or recorded run
  matches this scenario — it is an illustrative composite, not a replay of
  a captured run (unlike, say, Section 6's injection-wall claims, which
  were literal fixture cases). More importantly: **there is no `Map`
  component anywhere in the 23-type catalog** (`s13code/ui/catalog.py`).
  That means "the planner did not emit a Map component with invented pins"
  is true, but not for the reason the prose implies — it isn't a case of
  the model having a legal `Map` type available and *choosing* restraint;
  a `Map` component would be rejected by the catalog invariant exactly like
  `RawHtml` is, regardless of any honesty discipline, because it isn't a
  type this client can render at all. What *is* a genuine, checkable
  discipline is the "skip any pointer that is absent" instruction above —
  but that instructs omission, not the specific fallback of "emit a
  `Notice` explaining what's missing and an action to request it." A
  compose_surface run that has no coordinate data would, per the actual
  prompt, more likely omit any map-shaped component entirely than
  affirmatively construct a `Notice` about it — the `Notice` behavior in
  this example is plausible model behavior, not something the prompt
  mandates or this repo has recorded happening.
- **MCP Apps, Backslash's 2026 research, and the governance claims about
  A2UI/MCP Apps/AG-UI stewardship** — all external facts about other
  organizations and standards bodies, not implemented, referenced, or
  otherwise present anywhere in this codebase. Same category as the MCP
  Apps and A2UI-version claims flagged in Sections 3, 5, and 8.
