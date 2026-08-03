"""Modal deployment wrapper for S14Code — the hosted Waypoint application.

This file changes NO application code. It describes, for Modal:
  1. the container image,
  2. a persistent Volume for the graph and memory databases,
  3. a Secret holding the URL of the deployed gateway and the bearer used to
     reach it — and NO provider key, because this service must not have one,
  4. which object to serve -> the existing FastAPI app, s13code.main:app.

Two things differ from a laptop, and both are configuration rather than code:

``S13_EMBEDDER=deterministic``
    There is no Ollama beside this container. Every run writes an episode to
    durable memory, so an unreachable embedder would not merely weaken
    retrieval, it would fail the run and the user would get no interface at all.
    The hosted app trades embedding quality for a working graph; the store
    fingerprints each backend so vectors from one are never read as the other's.

``S13_A2A_GRPC_ENABLED=0``
    Modal serves one HTTP port per ASGI app. The gRPC A2A binding needs its own
    listener, so it is disabled here rather than started and left unreachable.
    The JSON-RPC A2A interface on the HTTP port is unaffected.

The credential boundary is the point of the split. `glc_v3` is deployed
separately and owns every provider key; this app holds only a shared bearer for
talking to it. Deploy the gateway first, then:

    modal secret create s14code-gateway \
        GLC_BASE_URL=https://<your-glc-app>.modal.run \
        GLC_AUTH_TOKEN=<the same token the gateway enforces>

    uv run modal deploy modal_app.py
"""

from pathlib import Path

import modal

app = modal.App("s14code-waypoint")

LOCAL_PKG = Path(__file__).parent / "s13code"
LOCAL_PROOFS = Path(__file__).parent / "proofs"

image = (
    modal.Image.debian_slim(python_version="3.11")
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
    .env(
        {
            "S13_DATA_DIR": "/data/s13code",
            # No Ollama in this container — see the module docstring.
            "S13_EMBEDDER": "deterministic",
            # One HTTP port per Modal ASGI app; gRPC would have nowhere to listen.
            "S13_A2A_GRPC_ENABLED": "0",
            "S13_GATEWAY_PROVIDER": "gemini",
        }
    )
    .add_local_dir(str(LOCAL_PKG), remote_path="/root/s13code")
    # /v1/harness/surface replays a recorded proof, so the artifacts travel too.
    .add_local_dir(str(LOCAL_PROOFS), remote_path="/root/proofs")
)

# The graph and memory databases live here and survive redeploys. Without the
# Volume every restart would drop the runs the UI routes read back.
data_volume = modal.Volume.from_name("s14code-data", create_if_missing=True)

# Where the gateway is and how to authenticate to it. Deliberately NOT provider
# keys: `glc_v3` owns those, and this app cannot reach a model without it.
gateway_secret = modal.Secret.from_name("s14code-gateway")


@app.function(
    image=image,
    volumes={"/data": data_volume},
    secrets=[gateway_secret],
    min_containers=0,  # scale to zero when idle -> protects the free tier
    timeout=600,       # a composed turn spends two sequential model calls
)
@modal.asgi_app()
def fastapi_app():
    """Serve the unchanged S14Code FastAPI app."""
    import os

    # The runtime opens its SQLite databases on startup, so the directory has to
    # exist on the mounted Volume before the app's lifespan runs.
    os.makedirs("/data/s13code", exist_ok=True)

    from s13code.main import app as web  # the real app, imported as-is

    return web
