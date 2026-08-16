# Health UI – Vitality 1% Daily Health Coach

## Overview
`health.html` implements the **interactive health‑coach UI** that:
- Presents three starter buttons (Food, Activity, Mental‑check‑in) each carrying a `data-prompt` attribute.
- When a button is clicked the runtime builds a **form** asking the user for the relevant data (what they ate, how they moved, mood, etc.).
- After the user submits the form the coach returns a **single 1 % micro‑action** for the next day.

## How it works (no code changes required)
1. **Load the page** in a browser (e.g., `http://127.0.0.1:8113/app/health`).
2. The script now contains an *auto‑start* listener that automatically clicks the first starter button on `window.load`. This triggers the first `data‑prompt` and immediately shows a question to the user.
3. The user fills the generated form and clicks **Submit**.
4. The UI displays a personalized tweak underneath the form.

## Running locally
Use the **GLC** and **S14** commands to start the backend and the UI:
```bash
cd glc_v3
uv sync
uv run glc serve
cd S14Code
uv sync
export GLC_BASE_URL=http://127.0.0.1:8111
export S14_GATEWAY_PROVIDER=gemini
uv run s14code serve
```
Then open `http://127.0.0.1:8113/app/health` (or the appropriate URL printed by the servers) in a browser.

## Customising the first‑turn prompt
The starter buttons are defined near the top of the file (lines 578‑590). Each button has a `data-prompt` attribute containing the instruction that the backend will turn into a form. To change the wording or add new starters, edit those `data‑prompt` strings.

## FAQ
- **Why does the UI open a question automatically?** We added a small script that clicks the first starter button on page load, fulfilling the requirement that the first turn asks the user for data.
- **Can I skip the auto‑prompt?** Remove the `window.addEventListener('load', …)` block (lines ~630‑640) to require the user to click a button manually.
- **Where are the generated forms rendered?** The `<div id="mount">` element inside the `.screen` container.

---
*Generated for the `health.html` UI. Adjust the instructions as needed for your deployment environment.*
