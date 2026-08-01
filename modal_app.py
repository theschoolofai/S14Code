"""
Modal deployment wrapper for S14Code (Session 14).
Deploy with: uv run modal deploy modal_app.py
"""
from pathlib import Path
import modal

app = modal.App("s14code-runtime")

LOCAL_S13CODE = Path(__file__).parent / "s13code"

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
        "modal>=1.5.3",
        "jsonschema>=4.21",
        "pyyaml>=6.0",
        "websockets>=12.0",
        "numpy>=2.0",
    )
    .env({
        "GLC_BASE_URL": "https://irenemarymathew--glc-v3-gateway-s14-fastapi-app.modal.run",
        "S14_GATEWAY_PROVIDER": "gemini",
        "S14_SURFACE_MAX_TOKENS": "8000",
        "S14_USE_DETERMINISTIC_EMBEDDER": "1",
    })
    .add_local_dir(str(LOCAL_S13CODE), remote_path="/root/s13code")
)

data_volume = modal.Volume.from_name("s14code-data", create_if_missing=True)

@app.function(
    image=image,
    volumes={"/data": data_volume},
    min_containers=0,
)
@modal.asgi_app()
def fastapi_app():
    import os
    os.environ.setdefault("S14_DATA_DIR", "/data/s14code")
    os.makedirs("/data/s14code", exist_ok=True)
    from s13code.main import app as web
    return web