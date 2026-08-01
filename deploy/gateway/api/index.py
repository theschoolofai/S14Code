"""A minimal stand-in for glc_v3, sized for a serverless host.

Deployed as its own project so the hosted Academy keeps the architecture the
course insists on: **provider credentials live only with the gateway**. The app
project never sees a key; it knows a ``GLC_BASE_URL`` and speaks the same
``POST /v1/chat`` contract that ``s13code/gateway.py`` speaks locally.

What it deliberately is NOT: the real glc_v3. There is no routing policy, no cost
accounting, no channels, no voice, no audit store. It is the one seam the hosted
demo needs — a key pool, a rotation, and an honest error — in about 150 lines,
because glc_v3's own dependency set (twilio, modal, whisper) does not belong in a
serverless function.

Quota, honestly: the Gemini keys behind this are free-tier. Two protections:

  1. a soft per-instance hourly cap, so a crawler that finds the URL cannot spend
     the whole day's budget in a minute. It is per-instance and therefore
     approximate — serverless gives no shared counter without a database, and a
     database is more machinery than a class demo warrants;
  2. an honest 429 passthrough. When the pool really is spent the app is told so
     in a shape it can render as a Notice, rather than being handed a blank
     screen or an invented answer.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
BASE = "https://generativelanguage.googleapis.com/v1beta"
CAP_PER_HOUR = int(os.getenv("GLC_CAP_PER_HOUR", "120"))

app = FastAPI(title="S14 hosted gateway")

# Soft, per-instance rate window. A list of unix timestamps, pruned on each call.
_calls: list[float] = []


def _keys() -> list[str]:
    """The key pool, from GEMINI_API_KEY_1..N (or a single GEMINI_API_KEY)."""
    pool = []
    single = os.getenv("GEMINI_API_KEY", "").strip()
    if single:
        pool.append(single)
    index = 1
    while True:
        value = os.getenv(f"GEMINI_API_KEY_{index}", "").strip()
        if not value:
            break
        pool.append(value)
        index += 1
    # Preserve order, drop duplicates.
    seen, ordered = set(), []
    for key in pool:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _over_cap() -> bool:
    now = time.time()
    _calls[:] = [stamp for stamp in _calls if now - stamp < 3600]
    return len(_calls) >= CAP_PER_HOUR


class ChatBody(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    system: str = ""
    max_tokens: int = 4000
    temperature: float = 0
    reasoning: str = "off"
    agent: str = "s14"
    provider: str = "gemini"
    session: str | None = None


@app.get("/healthz")
async def healthz():
    now = time.time()
    recent = len([stamp for stamp in _calls if now - stamp < 3600])
    return {"ok": True, "service": "s14-hosted-gateway", "model": MODEL,
            "keys": len(_keys()), "calls_this_hour": recent, "cap_per_hour": CAP_PER_HOUR}


@app.post("/v1/chat")
async def chat(body: ChatBody):
    pool = _keys()
    if not pool:
        return JSONResponse(
            {"detail": "no provider key configured on the gateway"}, status_code=503)
    if _over_cap():
        return JSONResponse(
            {"detail": f"demo cap reached ({CAP_PER_HOUR}/hour on this instance); "
                       "the free-tier key pool is protected. Try again shortly.",
             "quota": True},
            status_code=429)

    prompt = ""
    for message in body.messages:
        if message.get("role") in (None, "user"):
            prompt = str(message.get("content") or "")
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": body.max_tokens, "temperature": body.temperature},
    }
    if body.system:
        payload["systemInstruction"] = {"parts": [{"text": body.system}]}

    _calls.append(time.time())
    attempted: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=55) as client:
        for index, key in enumerate(pool, 1):
            try:
                response = await client.post(
                    f"{BASE}/models/{MODEL}:generateContent?key={key}", json=payload)
            except Exception as error:                                    # noqa: BLE001
                attempted.append({"provider": f"gemini_{index}", "reason": type(error).__name__})
                continue
            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates") or [{}]
                parts = ((candidates[0].get("content") or {}).get("parts") or [])
                text = "".join(str(part.get("text") or "") for part in parts)
                usage = data.get("usageMetadata") or {}
                return {
                    "provider": f"gemini_{index}", "model": MODEL, "text": text,
                    "tool_calls": [], "stop_reason": (candidates[0].get("finishReason") or "").lower(),
                    "input_tokens": usage.get("promptTokenCount", 0),
                    "output_tokens": usage.get("candidatesTokenCount", 0),
                    "attempted": attempted, "reasoning_applied": False,
                }
            # 429 / 503 are the ones worth rotating past; anything else too.
            attempted.append({"provider": f"gemini_{index}",
                              "reason": f"HTTP {response.status_code}"})

    # Every key refused. Say so plainly; the app turns this into a Notice.
    return JSONResponse(
        {"detail": "every key in the pool refused (free-tier quota is the usual cause)",
         "quota": True, "attempted": attempted},
        status_code=429)
