"""Deploy Career Pipeline (the Session 14 UI-only application) to Modal.

Shape of the deployment
-----------------------
ONE container, TWO processes:

  * ``glc`` — the LLM gateway — runs as a subprocess bound to 127.0.0.1:8111.
    It is never published, so nobody on the internet can spend the provider
    quota through it.
  * ``S14Code`` — the agent runtime and the UI layer — is the public ASGI app.

The provider key arrives from a Modal Secret and is handed to the gateway
subprocess only; this process deletes it from its own environment immediately
after spawning. The UI layer therefore holds no provider credential at runtime,
which is the same claim the local architecture makes.

There is no Ollama in the container, so the runtime uses the offline
``DeterministicEmbedder`` (``S13_EMBEDDER=deterministic``). That affects
memory recall quality only; every model completion still goes through the
gateway to Gemini.

Prerequisites (once):

    modal secret create s14-gemini GEMINI_API_KEY=<your key>

Deploy:

    modal deploy modal_app.py
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path

import modal

HERE = Path(__file__).parent
# The gateway package lives outside this repo (it is a separate project and is
# NOT vendored into git). Point at it with GLC_PACKAGE_DIR when deploying.
GLC_PACKAGE_DIR = Path(os.getenv("GLC_PACKAGE_DIR", HERE.parent.parent / "S#13" / "glc_v3" / "glc"))

app = modal.App("s14-career-pipeline")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        # S14Code (s13code.main pulls in the A2A adapter and the FAISS index)
        "fastapi>=0.110", "uvicorn[standard]>=0.27", "httpx>=0.27",
        "python-dotenv>=1.0", "pydantic>=2.6", "cryptography>=42",
        "grpcio>=1.70", "a2a-sdk[grpc]>=1.0,<2", "faiss-cpu>=1.11,<2",
        # the gateway
        "jsonschema>=4.21", "pyyaml>=6.0", "websockets>=12.0",
    )
    .env({
        "S13_DATA_DIR": "/data/s13",
        "S13_SANDBOX_ROOT": "/data/sandbox",
        "S13_GATEWAY_PROVIDER": "gemini",
        "GLC_BASE_URL": "http://127.0.0.1:8111",
        "GLC_CONFIG_DIR": "/data/glc",
        # no Ollama in the container
        "S13_EMBEDDER": "deterministic",
        # Gemini 2.5 Flash stops mid-JSON at the 4000 default; see README.
        "S14_SURFACE_MAX_TOKENS": "12000",
    })
    .add_local_dir(str(HERE / "s13code"), remote_path="/root/s13code")
    .add_local_dir(str(GLC_PACKAGE_DIR), remote_path="/root/glc")
    # glc.main mounts ./static at import time, so the directory must exist.
    .add_local_dir(str(GLC_PACKAGE_DIR.parent / "static"), remote_path="/root/static")
)

# Durable state: the graph and memory sqlite files, and the gateway's own dbs.
data_volume = modal.Volume.from_name("s14-career-pipeline-data", create_if_missing=True)

# GEMINI_API_KEY. Handed to the gateway subprocess, then dropped from this env.
gemini_secret = modal.Secret.from_name("s14-gemini")


def _start_gateway() -> None:
    """Run the gateway on loopback and wait until it answers /healthz."""
    for directory in ("/data/glc", "/data/s13", "/data/sandbox"):
        os.makedirs(directory, exist_ok=True)

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("modal secret s14-gemini did not supply GEMINI_API_KEY")

    # The gateway reads its providers from its own environment.
    gateway_env = {
        **os.environ,
        "GEMINI_API_KEY": key,
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "LLM_ORDER": "gemini",
        "GLC_PORT": "8111",
    }
    subprocess.Popen(
        ["python", "-m", "uvicorn", "glc.main:app", "--host", "127.0.0.1", "--port", "8111"],
        env=gateway_env, cwd="/root",
    )

    # This process must not keep the credential once the gateway owns it.
    os.environ.pop("GEMINI_API_KEY", None)

    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8111/healthz", timeout=3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("gateway did not become healthy within 120s")


@app.function(
    image=image,
    volumes={"/data": data_volume},
    secrets=[gemini_secret],
    timeout=900,
    min_containers=0,       # scale to zero when idle
    # EXACTLY ONE container, and this is load-bearing. A run lives in the
    # runtime's IN-PROCESS graph, and the client then reads it back with
    # GET /v1/runs/{id}/composed. Under autoscaling that second request can land
    # on a container that never saw the run, which 404s and shows the user "no
    # interface composed" even though the run succeeded. The graph and memory are
    # also SQLite on a shared Volume, which must not have concurrent writers.
    max_containers=1,
    # Keep the container warm between turns so a conversation - and a screen
    # recording - does not pay a cold start on every tap.
    scaledown_window=600,
)
@modal.concurrent(max_inputs=20)  # one container still serves parallel requests
@modal.asgi_app()
def web():
    """Serve S14Code; the gateway runs beside it on loopback."""
    _start_gateway()
    from s13code.main import app as s14_app
    return s14_app
