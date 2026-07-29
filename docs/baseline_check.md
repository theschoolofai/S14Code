# Baseline Check — Proof Suite

Established before making any changes.

## 11. The proof suite

```
cd glc_v3   && uv run pytest -q
cd ../S14Code && uv run pytest -q
```

Results:

- **glc_v3**: 245 passed, 8 skipped, 1 warning (6.82s)
- **S14Code**: 110 passed, 1 warning (22.85s)

Both floors are green. Clear to proceed with changes.

## Session 14 suite claims — verified against code

Claim (from spec/write-up):

> The Session 14 suite proves the three invariants directly: the catalog test
> rejects unknown types, the data-not-code test refuses smuggled markup and
> handlers, and the event test admits only registered actions. A render-client
> property test then asserts that the client executes no component property and
> never assigns a bound value to innerHTML under any input. Because S14Code is
> now the runtime, it also carries the full inherited Session 13 suite forward —
> the graph and memory tests run beside the new UI tests, roughly 110 in all —
> and the separate gateway suite confirms the models layer beneath is untouched.
>
> The non-browser benchmark reuses the Session 13 prompts and adds an interface
> for each. Before the UI layer earns new capabilities, it must first prove that
> it can present the existing work accurately, safely and without inventing
> evidence.

| Prompt family | What the interface proves |
|---|---|
| Compare three city populations | A table bound to graph state and updated as researcher nodes complete |
| Search asyncio, read top three | A live node view streamed from the graph journal through AG-UI events |
| Remember a birthday, make reminders | An approval card bound to the exact calendar-write parameters and resumed by a tap |
| Index the Attention paper | A document interface that renders chunks with source spans, never as raw HTML |
| Slow remote A2A report | A remote agent's A2UI payload validated against the local catalog before rendering |
| Render data the system does not have | An honest Notice instead of an invented chart |
| Four injected interfaces | The validator rejects each attack and identifies the invariant it violated |

### Precisely confirmed, by exact test

- **Catalog invariant** — `test_unknown_type_breaks_catalog_invariant`,
  `test_catalog_invariant_names_unknown_type` reject an unregistered
  `"Wormhole"` type.
- **Data-not-code invariant** — separate tests reject a smuggled `onclick`
  handler, a `javascript:`/`data:` URL value, a raw literal where a `$bind`
  pointer is required, and an out-of-enum value.
- **Event invariant** — `test_registered_component_with_unregistered_action_breaks_event`
  rejects a real component whose `onPress.action` isn't in `REGISTERED_ACTIONS`.
- **Render-client property test** —
  `test_render_client_never_uses_innerhtml_and_documents_the_contract` asserts
  `createTextNode` is used, `innerHTML =` never appears (via regex), and the
  word "innerHTML" appears exactly once (in the documented safety comment).
- **~110 tests, S13 carried forward** — `pytest --collect-only` returns exactly
  **110**, with `live_graph`/`memory` test files sitting alongside
  `test_s14_ui.py` in the same run.
- **Separate gateway suite, models layer untouched** —
  `tests/test_gateway_boundary.py` proves S13 calls the gateway with no
  provider key in the payload, and that S13 doesn't reimplement `/v1/chat` or
  `/v1/providers` (404 on both).
- **Four injected interfaces** — `s13code/ui/fixtures/injections.json` has
  exactly 4 cases (`raw-html-type`→catalog, `smuggled-handler`→data-not-code,
  `markup-in-binding`→data-not-code, `unregistered-action`→event), each
  asserted rejected by the correct invariant.
- **Honest Notice, no invented data** —
  `test_failed_node_yields_an_honest_notice` confirms the surface emits
  `"No result was invented"` rather than fabricating an answer.
- **Birthday approval card** —
  `test_birthday_creates_two_real_calendar_artifacts` + `hitl.py`'s
  `decide_resume` (widened/narrowed/changed args all refused) back the
  "resumed by a tap, bound to exact params" claim.
- **Slow remote report** — real "slow remote report" A2A tests exist in
  `test_adapter.py` / `test_hardening.py`.
- **Attention paper indexed** — `papers_corpus.json` fixture does include
  "Attention Is All You Need" (4 chunks, 2017).

### Claims that are loosely worded vs. the literal code

- "A table bound to graph state" for the city-population prompt: the actual UI
  is a per-node `Row` of `Text` + `StatTile` (state pills), not a literal
  `DataTable` component.
- "Renders chunks with source spans": the showcase dashboard shows aggregate
  per-paper stats (chunk count, words, year) — no per-chunk source-span
  rendering was found in the code. The chunking layer (`chunking.py`) does
  track offsets internally, but the UI doesn't expose them as spans.

Everything else in the write-up matches the code exactly.
