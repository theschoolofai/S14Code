"""Run the REAL S14Code FastAPI app (s13code.main:app) for a live Part-2 demo,
on a machine that has glc_v3 (Gemini) but no local Ollama install.

S13Runtime hardcodes OllamaNomicEmbedder for memory-record embeddings, which
requires a local Ollama for /api/embed. Rather than edit runtime.py (a real
install SHOULD keep using Ollama), this swaps in the repo's own, already
documented DeterministicEmbedder ("Stable hashed bag-of-words vectors for
unit tests and offline demos" — s13code/core/memory/embeddings.py) purely for
this demo process, by patching the name S13Runtime.__init__ resolves BEFORE
importing s13code.main (which constructs S13Runtime() at FastAPI startup).
No production file is modified; this is a standalone runner.

    GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
    S13_DATA_DIR=/tmp/s14-demo S13_PORT=8113 \
    uv run python proofs/patched_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.core.memory.embeddings import DeterministicEmbedder  # noqa: E402
import s13code.runtime as runtime_mod  # noqa: E402

runtime_mod.OllamaNomicEmbedder = DeterministicEmbedder  # patch BEFORE s13code.main builds S13Runtime()

from s13code.main import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("S13_PORT", "8113"))
    uvicorn.run(app, host="127.0.0.1", port=port)
