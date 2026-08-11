## Capability

A prompt whose answer is a set of separate questions or topics a user would open
one at a time now produces an **Accordion surface** instead of a flat text blob.
The agent can present collapsible FAQ-style interfaces without any change to the
prompt — the model reaches for `Accordion` on its own because the compose
instruction now names it alongside Timeline and Cards as a valid layout for
`/sections` data.  Every section header, every bullet, and the expand event all
pass through the injection wall before the render client ever sees them.

## Proof

- [x] I added one evidence subsection to `README.md`.
- [x] It contains the exact prompt or API request.
- [x] It contains the graph and ordered event trace.
- [x] It contains the actual final result and evidence.
- [x] It identifies every agent/provider assignment.
- [x] It shows an adversarial failure before the fix and the same attack failing afterward.
- [x] It includes commands that reproduce the result from a fresh checkout.

## Boundaries

- [x] `glc_v3` still owns all provider credentials and model routing.
- [x] Memory authorization happens before retrieval.
- [x] No `.env`, credentials, personal memory, databases, or unrestricted local paths are committed.
- [x] `uv run ruff check .` passes.
- [x] `uv run pytest -q` passes.
