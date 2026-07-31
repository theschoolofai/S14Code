"""Recorded Session 13 graph journals for replay.

The live UI reads the runtime's graph in-process (see routes.py). Offline, or in
tests and widget replays, it reads a recorded journal fixture captured from a
real S13 run. The recorded shape is byte-for-byte the S13
``GET /v1/agent/runs/{id}`` response: ``{run_id, finished, nodes, edges,
events}``.

The UI holds no provider credential and never talks to the gateway. It only
reads the graph the agent already produced.
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURES = Path(__file__).parent / "fixtures"


class RecordedS13:
    """Replay a recorded S13 journal fixture. Real shape, no live LLM needed."""

    def __init__(self, directory: Path = _FIXTURES):
        self.directory = directory

    def get_run(self, run_id: str) -> dict:
        path = self.directory / f"{run_id}.json"
        if not path.exists():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def available(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json") if p.stem != "injections")


def load_injections() -> dict:
    """The catalogue of malicious surfaces used by the injection wall widget."""
    return json.loads((_FIXTURES / "injections.json").read_text(encoding="utf-8"))
