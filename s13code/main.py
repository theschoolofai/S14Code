"""Standalone Session 13 service.

HTTP 8113 owns graph/memory/document/A2A task semantics. GLC HTTP 8111 owns
models, keys, routing, quotas and cost accounting. The two processes share no
Python imports or database files.
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from s13code import a2a_routes, routes  # noqa: E402
from s13code.core.a2a_adapter.official import OfficialA2AServer  # noqa: E402
from s13code.core.a2a_adapter.server import A2ADemoServer  # noqa: E402
from s13code.core.a2a_adapter.trust import sign_card  # noqa: E402
from s13code.core.memory import MemoryScope  # noqa: E402
from s13code.gateway import GatewayClient  # noqa: E402
from s13code.runtime import S13Runtime  # noqa: E402
from s13code.ui.routes import router as ui_router  # noqa: E402

PORT = int(os.getenv("S13_PORT", "8113"))
HOST = os.getenv("S13_HOST", "127.0.0.1")
A2A_GRPC_HOST = os.getenv("S13_A2A_GRPC_HOST", "127.0.0.1")
A2A_GRPC_PORT = int(os.getenv("S13_A2A_GRPC_PORT", "8114"))


def _secrets(name: str) -> set[str]:
    return {item.strip() for item in os.getenv(name, "").split(",") if item.strip()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.gateway = GatewayClient()
    app.state.s13_runtime = S13Runtime()
    bearers, api_keys = _secrets("S13_A2A_BEARER_TOKENS"), _secrets("S13_A2A_API_KEYS")
    base_url = os.getenv("S13_BASE_URL", f"http://{HOST}:{PORT}").rstrip("/")
    card = {
        "name": "S13 live-agent runtime",
        "description": "Outcome-driven graph, scoped memory, semantic indexing and A2A delegation",
        "version": "0.1.0",
        "supportedInterfaces": [
            {"url": f"{base_url}/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
            {"url": f"dns:///{A2A_GRPC_HOST}:{A2A_GRPC_PORT}",
             "protocolBinding": "GRPC", "protocolVersion": "1.0"},
        ],
        "capabilities": {"streaming": True, "pushNotifications": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [{"id": "grounded-answer", "name": "Grounded answer",
                    "description": "Runs a live graph over explicitly scoped evidence.",
                    "tags": ["live-graph", "memory", "semantic-chunking"]}],
    }
    if bearers:
        card.setdefault("securitySchemes", {})["bearer"] = {
            "httpAuthSecurityScheme": {"description": "A2A bearer token", "scheme": "bearer"}}
        card.setdefault("securityRequirements", []).append({"schemes": {"bearer": {"list": []}}})
    if api_keys:
        card.setdefault("securitySchemes", {})["apiKey"] = {
            "apiKeySecurityScheme": {"description": "A2A API key", "location": "header", "name": "X-API-Key"}}
        card.setdefault("securityRequirements", []).append({"schemes": {"apiKey": {"list": []}}})
    if key_file := os.getenv("S13_A2A_PRIVATE_KEY_FILE"):
        card = sign_card(card, Path(key_file).read_bytes(), kid=os.getenv("S13_A2A_SIGNING_KID", "s13-local"))

    async def handle_a2a_task(text: str) -> str:
        result = await app.state.s13_runtime.run(
            prompt=text, scope=MemoryScope("a2a", "inbound", "remote-agent", "s13code"),
            llm=lambda prompt, system: app.state.gateway.complete(prompt, system),
            source_uri="a2a://inbound/task", source_author="remote-agent",
        )
        if result["status"] != "completed":
            raise RuntimeError("live graph completed without an answer")
        return result["answer"]

    data_dir = app.state.s13_runtime.root
    push_http = httpx.AsyncClient(timeout=10)
    app.state.s13_a2a_push_http = push_http
    app.state.s13_a2a = A2ADemoServer(
        card, task_handler=handle_a2a_task, task_db=data_dir / "a2a.sqlite",
        bearer_tokens=bearers, api_keys=api_keys,
        push_signing_secret=os.getenv("S13_A2A_PUSH_SIGNING_SECRET"), push_http=push_http,
    )
    await app.state.s13_a2a.start()
    app.state.s13_a2a_grpc = None
    if os.getenv("S13_A2A_GRPC_ENABLED", "1").lower() not in {"0", "false", "no"}:
        app.state.s13_a2a_grpc = OfficialA2AServer(
            app.state.s13_a2a, data_dir / "a2a.sqlite",
            address=f"{A2A_GRPC_HOST}:{A2A_GRPC_PORT}",
            bearer_tokens=bearers, api_keys=api_keys,
        )
        await app.state.s13_a2a_grpc.start()
    app.state.started_at = time.time()
    yield
    if app.state.s13_a2a_grpc:
        await app.state.s13_a2a_grpc.stop()
    await app.state.s13_a2a.close()
    await push_http.aclose()
    app.state.s13_runtime.close()
    await app.state.gateway.close()


app = FastAPI(title="S13Code — Live Graph, Memory, Semantic Chunking and A2A", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("S13_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes.router)
app.include_router(a2a_routes.router)
app.include_router(ui_router)


@app.get("/healthz")
async def healthz(request: Request):
    return {"ok": True, "service": "s13code", "port": PORT,
            "glc_base_url": request.app.state.gateway.base_url}


@app.get("/readyz")
async def readyz(request: Request):
    try:
        gateway = await request.app.state.gateway.health()
    except Exception as error:
        raise HTTPException(503, f"GLC is unavailable: {type(error).__name__}: {error}") from error
    return {"ok": True, "glc": gateway}
