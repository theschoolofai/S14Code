"""Modal deployment for the Session 14 CodeWorks demo.

One Modal container, two co-tenant FastAPI apps:
  * glc_v3 (the model gateway) bound to 127.0.0.1:8111 as a background asyncio
    task inside the s14code lifespan — invisible to the outside world.
  * s14code (this project) served as the public ASGI app on Modal's HTTPS URL.

The two apps talk over localhost; only s14code is exposed. That's how a
reviewer gets a single clean URL (no glc.modal.run to chase), and how the
gateway's admin surface stays off the public internet.

BYOK: /codeworks ships a "Your Gemini key" input. When a visitor pastes a key,
the browser sends it as X-User-Gemini-Key on every /v1/agent/runs request;
s14code forwards it verbatim to glc, which honors it for that one request
(context-scoped) and never persists it. If a visitor leaves the input blank,
we fall back to the host's Modal secret.

Deploy:
    modal secret create s14-gemini-key GEMINI_API_KEY_1=<key>
    modal deploy deploy/modal_app.py

Local dry-run:
    modal serve deploy/modal_app.py     # runs on modal.run without persisting
"""

from __future__ import annotations

from pathlib import Path

import modal

# The Modal "app" is a namespace for all resources deployed under this name.
app = modal.App("s14code-codeworks")

# Repo layout: this file lives at s14code/deploy/modal_app.py. glc_v3 is a
# sibling directory (EAGv3/Session13/glc_v3) because the two packages ship
# separately in the course tree. We copy both into the image so the container
# can import them without any editable-install shenanigans.
REPO_ROOT = Path(__file__).resolve().parent.parent
GLC_ROOT = Path.home() / "Desktop" / "EAGv3" / "Session13" / "glc_v3"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        # s14code deps
        "fastapi>=0.110",
        "uvicorn[standard]>=0.27",
        "httpx>=0.27",
        "python-dotenv>=1.0",
        "pydantic>=2.6",
        "cryptography>=42",
        "grpcio>=1.70",
        "a2a-sdk[grpc]>=1.0,<2",
        "faiss-cpu>=1.11,<2",
        # glc_v3 additional deps (not needed by s14code but required to import
        # the module cleanly at container startup)
        "jsonschema>=4.21",
        "pyyaml>=6.0",
        "websockets>=12.0",
    )
    .env({
        # Point s14code's GatewayClient at the in-container glc.
        "GLC_BASE_URL": "http://127.0.0.1:8111",
        # gemini-flash-latest is the model that survived free-tier eligibility
        # checks during proof capture; older names (gemini-2.5-flash) 404 for
        # new API keys, and Modal will always be a "new" key.
        "GEMINI_MODEL": "gemini-flash-latest",
        # Gemini-only in the hosted demo — no NVIDIA/Ollama credentials.
        "LLM_ORDER": "gemini",
        "ROUTER_ORDER": "gemini",
        "S13_GATEWAY_PROVIDER": "gemini",
        # Content-role JSON on richer CodeBlock prompts truncates at 700; widen
        # so a hosted visitor gets a full surface first shot.
        "S13_GATEWAY_MAX_TOKENS": "6000",
        # Turn off the A2A gRPC listener in-container — nothing on the public
        # ASGI URL can reach it anyway, and skipping it avoids grpcio port
        # binding races on Modal's shared kernel.
        "S13_A2A_GRPC_ENABLED": "0",
        # Local dev embeds via Ollama on 11434; Modal containers have no Ollama.
        # The deterministic bag-of-words embedder ships in-package and needs no
        # network — swap it in so the memory store can index without hanging.
        "S13_EMBEDDER": "deterministic",
        # glc writes its audit DB and pairing DB somewhere writable.
        "GLC_CONFIG_DIR": "/tmp/glc",
        # s14code writes memory.sqlite / graph.sqlite here; must be writable.
        "S13_DATA_DIR": "/tmp/s13code",
    })
    .add_local_dir(str(REPO_ROOT / "s13code"), remote_path="/root/s13code")
    .add_local_dir(str(GLC_ROOT / "glc"), remote_path="/root/glc")
    # glc.main mounts /static at import time — the dir sits next to the glc/
    # package. Ship it so import doesn't RuntimeError-out during container boot.
    .add_local_dir(str(GLC_ROOT / "static"), remote_path="/root/static")
)

# The Modal secret holding GEMINI_API_KEY_1. Reviewers who want to try the app
# without setting their own key hit this fallback; reviewers who paste a key
# in the BYOK box bypass it entirely (contextvar override).
gemini_secret = modal.Secret.from_name("s14-gemini-key")


@app.function(
    image=image,
    secrets=[gemini_secret],
    min_containers=0,    # scale-to-zero when nobody's on the page
    timeout=600,         # per-request; codeworks turns can take ~30s on gemini-flash
)
@modal.asgi_app()
def web():
    """Serve s14code publicly; run glc_v3 as an internal background task."""
    import asyncio
    import os
    from contextlib import asynccontextmanager

    import uvicorn

    # glc writes to $GLC_CONFIG_DIR at import time (audit DB init). Make sure
    # the directory exists before glc.main is imported.
    os.makedirs(os.environ.get("GLC_CONFIG_DIR", "/tmp/glc"), exist_ok=True)

    from glc.main import app as glc_app  # noqa: E402
    from s13code.main import app as s14_app, lifespan as s14_lifespan  # noqa: E402

    # Wrap s14's lifespan so we boot the in-container gateway alongside it.
    # glc runs on 127.0.0.1:8111 (matches GLC_BASE_URL env). It's an asyncio
    # background task, not a subprocess — one Python process, one event loop.
    @asynccontextmanager
    async def combined_lifespan(app):
        cfg = uvicorn.Config(glc_app, host="127.0.0.1", port=8111,
                             log_level="warning", access_log=False,
                             lifespan="on")
        server = uvicorn.Server(cfg)
        gateway_task = asyncio.create_task(server.serve(), name="glc_gateway")
        # Wait for the gateway to accept connections before we let s14 boot;
        # s14's readyz check hits /healthz on the gateway on startup.
        for _ in range(50):   # up to ~5 s
            if server.started:
                break
            await asyncio.sleep(0.1)
        try:
            async with s14_lifespan(app):
                yield
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(gateway_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    # Rebind the s14 app's lifespan. FastAPI stashes it on router.lifespan_context.
    s14_app.router.lifespan_context = combined_lifespan
    return s14_app
