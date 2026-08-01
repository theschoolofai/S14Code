from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    monkeypatch.setenv("S13_DATA_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("S13_A2A_GRPC_ENABLED", "0")
    monkeypatch.setenv("S13_SANDBOX_ROOT", str(tmp_path / "sandbox"))
    monkeypatch.setenv("GLC_BASE_URL", "http://glc.test:8111")
    (tmp_path / "sandbox").mkdir()


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient
    from s13code.main import app

    with TestClient(app) as client:
        yield client
