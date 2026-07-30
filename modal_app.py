"""Modal deployment for the Session 14 UI runtime — a public, replay-only build.

This file changes no application code. It describes, for Modal:

  1. the container image,
  2. a persistent Volume holding the graph journal,
  3. the seed journal copied onto that Volume on first boot,
  4. which object to serve  ->  the existing FastAPI app, s13code.main:app.

The deployment carries **no provider credential**. It serves interfaces that were
already composed live against the real gateway, re-read from the durable journal
it ships with — which is the session's own claim made operational: an interface
is a projection of a durable event stream, so it outlives the run that produced
it and needs no model to show it again. ``S14_REPLAY_ONLY=1`` makes that explicit
rather than implicit: ``POST /v1/agent/runs`` refuses with a reason, and ``/jobs``
offers the captured runs instead of a Compose box that could only ever fail.

To compose new interfaces, run it locally against glc_v3 — see the README.

    uv run modal deploy modal_app.py

Deps mirror the runtime's own pyproject list exactly. A replay build only reads
SQLite and renders, so FAISS and the A2A/gRPC stack are never *used* — but
``s13code.main`` imports the memory package, which imports faiss at module load,
so trimming them produced a container that could not start at all. The image
follows the application's imports, not a guess about its runtime behaviour.
"""

from pathlib import Path

import modal

app = modal.App("s14code-pipeline")

LOCAL_PKG = Path(__file__).parent / "s13code"
LOCAL_SEED = Path(__file__).parent / "deploy" / "journal_seed.sqlite"

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
    .env({
        # The journal lives on the Volume, so runs survive restarts and redeploys.
        "S13_DATA_DIR": "/data",
        # No key is mounted, so composing is refused with a reason rather than a 502.
        "S14_REPLAY_ONLY": "1",
        # Semantic chunking would reach for a local Ollama that is not there.
        "S13_LIVE_SEMANTIC_CHUNKING": "0",
    })
    # The whole package, so its client pages and fixtures travel with it.
    .add_local_dir(str(LOCAL_PKG), remote_path="/root/s13code")
    .add_local_file(str(LOCAL_SEED), remote_path="/root/journal_seed.sqlite")
)

# The journal: 11 runs, every one of them cited in the pull request.
journal_volume = modal.Volume.from_name("s14code-journal", create_if_missing=True)


@app.function(
    image=image,
    volumes={"/data": journal_volume},
    min_containers=0,      # scale to zero when idle -> protects the free tier
    max_containers=2,
)
@modal.asgi_app()
def fastapi_app():
    """Serve the unchanged S14Code FastAPI app against the seeded journal."""
    import os
    import shutil

    # Seed on first boot only. A redeploy must not clobber a journal that has
    # already been served — and copying every cold start would be a silent
    # rewrite of the one durable thing this deployment owns.
    target = "/data/graph.sqlite"
    if not os.path.exists(target):
        shutil.copyfile("/root/journal_seed.sqlite", target)
        journal_volume.commit()

    from s13code.main import app as web

    return web
