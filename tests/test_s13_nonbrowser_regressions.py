from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import s13code.routes as agent_route
import s13code.runtime as runtime_module
from s13code.core.memory.embeddings import DeterministicEmbedder


def _fake_answer(monkeypatch):
    async def answer(_app, prompt, _system):
        return {"text": "grounded answer", "provider": "fake", "model": "fake"}
    monkeypatch.setattr(agent_route, "gateway_text_llm", answer)


def test_search_outcome_expands_into_parallel_fetches(app_client, monkeypatch):
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    _fake_answer(monkeypatch)

    async def search(query, max_results=3):
        return {"query": query, "hits": [{"title": f"result {i}", "url": f"https://source/{i}",
                                           "snippet": "async advice"} for i in range(max_results)]}

    async def fetch(url):
        return {"url": url, "status": 200, "content_type": "text/plain", "text": f"content from {url}"}

    monkeypatch.setattr(runtime_module, "web_search", search)
    monkeypatch.setattr(runtime_module, "fetch_url", fetch)
    result = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "p",
        "prompt": 'Search for "Python asyncio best practices", read the top 3 results, and summarize.'}).json()
    assert result["events"][1]["payload"]["add"] == ["search"]
    expansion = next(event for event in result["events"]
                     if event["kind"] == "graph_patched" and event["payload"]["add"] == ["fetch_1", "fetch_2", "fetch_3"])
    assert expansion["payload"]["connect"] == [["search", "fetch_1"], ["search", "fetch_2"], ["search", "fetch_3"]]
    starts = [event["node_id"] for event in result["events"] if event["kind"] == "task_started"]
    assert starts[1:4] == ["fetch_1", "fetch_2", "fetch_3"]


def test_index_prompt_indexes_before_recall(app_client, monkeypatch, tmp_path):
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    _fake_answer(monkeypatch)
    paper = tmp_path / "paper.md"
    paper.write_text("# Result\nThe Transformer uses attention and parallel computation.")
    monkeypatch.setenv("S13_SANDBOX_ROOT", str(tmp_path))
    result = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "p",
        "prompt": "Index the file paper.md and tell me its key result."}).json()
    assert result["events"][1]["payload"]["add"] == ["index_file"]
    assert [event["node_id"] for event in result["events"] if event["kind"] == "task_started"] == [
        "index_file", "recall", "distill", "answer"]
    assert result["graph"]["nodes"]["recall"]["result"]["hits"][0]["sources"][0] == paper.as_uri()


def test_directory_discovery_expands_into_parallel_indexing(app_client, monkeypatch, tmp_path):
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    _fake_answer(monkeypatch)
    papers = tmp_path / "papers"
    papers.mkdir()
    for name in ("a.md", "b.md", "c.md"):
        (papers / name).write_text(f"# {name}\nA distinct paper about {name}.")
    monkeypatch.setenv("S13_SANDBOX_ROOT", str(tmp_path))
    result = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "p",
        "prompt": "Index every .md file under papers/. Confirm how many chunks were indexed in total."}).json()
    starts = [event["node_id"] for event in result["events"] if event["kind"] == "task_started"]
    assert starts[:4] == ["list_directory", "index_1", "index_2", "index_3"]
    expansion = next(event for event in result["events"]
                     if event["kind"] == "graph_patched" and event["payload"]["add"] == ["index_1", "index_2", "index_3"])
    assert expansion["payload"]["connect"] == [
        ["list_directory", "index_1"], ["list_directory", "index_2"], ["list_directory", "index_3"]]
    assert starts[-1] == "answer"


def test_population_prompt_launches_independent_city_searches_together(app_client, monkeypatch):
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    _fake_answer(monkeypatch)

    async def search(query, max_results=3):
        return {"query": query, "hits": [{"title": query, "url": "https://population.test", "snippet": "1m"}]}

    monkeypatch.setattr(runtime_module, "web_search", search)
    result = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "p",
        "prompt": "Find the populations of London, Paris, Berlin and tell me which two are closest in size."}).json()
    assert result["events"][1]["payload"]["add"] == ["search_1", "search_2", "search_3"]
    starts = [event["node_id"] for event in result["events"] if event["kind"] == "task_started"]
    assert starts[:3] == ["search_1", "search_2", "search_3"]


def test_birthday_creates_two_real_calendar_artifacts(app_client, monkeypatch):
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    _fake_answer(monkeypatch)
    body = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "birthday",
        "prompt": "My mom's birthday is 15 May 2026. Remember that and give me a calendar reminder for two weeks before and on the day."}).json()
    artifacts = body["graph"]["nodes"]["reminder"]["result"]["artifacts"]
    assert len(artifacts) == 2
    assert all(Path(url2pathname(urlparse(uri).path)).read_text().startswith("BEGIN:VCALENDAR") for uri in artifacts)


def test_missing_file_is_safely_attempted_and_failure_reaches_answer(app_client, monkeypatch, tmp_path):
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    captured = {}
    async def answer(_app, prompt, _system):
        captured["prompt"] = prompt
        return {"text": "The file could not be found.", "provider": "fake", "model": "fake"}
    monkeypatch.setattr(agent_route, "gateway_text_llm", answer)
    monkeypatch.setenv("S13_SANDBOX_ROOT", str(tmp_path))
    body = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "failure",
        "prompt": "Read /nonexistent/path.txt and tell me what's in it."}).json()
    assert body["graph"]["nodes"]["read_file"]["state"] == "failed"
    assert "PermissionError" in captured["prompt"]


def test_structured_population_uses_distiller_then_validator(app_client, monkeypatch):
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    async def answer(_app, prompt, _system):
        return {"text": "structured result", "provider": "gemini_1", "model": "fake"}
    monkeypatch.setattr(agent_route, "gateway_text_llm", answer)
    async def search(query, max_results=3):
        return {"query": query, "hits": [{"title": query, "url": "https://population.test", "snippet": "population evidence"}]}
    monkeypatch.setattr(runtime_module, "web_search", search)
    body = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "parallel",
        "prompt": "Compare the populations of Mumbai, Cairo, and Lagos and identify which is growing fastest. Return structured fields per city."}).json()
    assert body["graph"]["nodes"]["distill"]["state"] == "succeeded"
    assert body["graph"]["nodes"]["validate"]["state"] == "succeeded"
    assert body["trace"]["agents"]["distill"]["agent"] == "distiller"
    assert body["trace"]["agents"]["validate"]["agent"] == "structured_validator"
