"""Modal deployment for the Session 14 runtime — StudyCoach and the UI routes.

This changes no application code. It describes, for Modal:
  1. the container image,
  2. a persistent Volume for the graph / memory databases,
  3. the Secret that supplies GLC_BASE_URL (the gateway still owns every
     provider key — nothing here holds one),
  4. which object to serve -> the existing FastAPI app, ``s13code.main:app``.

Two environment choices matter in a serverless container and are made here
rather than in application code:

* ``S13_EMBEDDER=deterministic`` — there is no Ollama sidecar to embed against,
  and an unreachable embedder fails every memory write.
* ``S13_A2A_GRPC_ENABLED=0`` — a second listener on its own port cannot be
  reached through Modal's single ASGI ingress, so starting one only risks a
  failed startup. The JSON-RPC A2A surface stays available over HTTP.

Deploy with:

    modal secret create s14code-gateway GLC_BASE_URL=https://<gateway-host>
    uv run modal deploy modal_app.py

Then open ``https://<app-host>/coach``.
"""

from pathlib import Path

import modal

app = modal.App("s14code-studycoach")

LOCAL_PACKAGE = Path(__file__).parent / "s13code"

# The dependency set mirrors pyproject.toml. The a2a / grpc extras travel because
# s13code.main imports the A2A adapter at module scope even when the gRPC
# listener is switched off.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi>=0.110",
        "uvicorn[standard]>=0.27",
        "httpx>=0.27",
        "python-dotenv>=1.0",
        "pydantic>=2.6",
        "cryptography>=42",
        "grpcio>=1.70",
        "a2a-sdk[grpc]>=1.0,<2",
        "faiss-cpu>=1.11,<2",
    )
    .env({
        "S13_DATA_DIR": "/data/s14code",
        "S13_SANDBOX_ROOT": "/data/s14code/sandbox",
        "S13_GATEWAY_PROVIDER": "gemini",
        "S13_EMBEDDER": "deterministic",
        "S13_A2A_GRPC_ENABLED": "0",
    })
    .add_local_dir(str(LOCAL_PACKAGE), remote_path="/root/s13code")
)

# graph.sqlite and memory.sqlite live here so a redeploy does not wipe the
# conversation history the UI routes read.
data_volume = modal.Volume.from_name("s14code-data", create_if_missing=True)

# GLC_BASE_URL only. The runtime calls the gateway over HTTP and never sees a
# provider credential — that boundary is the point, so this Secret must not
# carry one.
gateway_secret = modal.Secret.from_name("s14code-gateway")


@app.function(
    image=image,
    volumes={"/data": data_volume},
    secrets=[gateway_secret],
    min_containers=0,
    timeout=600,
)
@modal.asgi_app()
def fastapi_app():
    """Serve the unchanged S14Code FastAPI app."""
    import os

    # The runtime opens its databases during lifespan startup, so the mounted
    # directory has to exist first.
    os.makedirs("/data/s14code/sandbox", exist_ok=True)

    from s13code.main import app as web

    return web
