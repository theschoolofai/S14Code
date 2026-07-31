from __future__ import annotations

import re
from pathlib import Path

import s13code.routes as agent_route
import s13code.runtime as runtime_module
from s13code.core.memory.embeddings import DeterministicEmbedder, OllamaNomicEmbedder
from s13code.runtime import S13Runtime


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
    assert all(Path(uri.removeprefix("file://")).read_text().startswith("BEGIN:VCALENDAR") for uri in artifacts)


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


def test_a_plain_comparison_with_no_research_and_no_choices_still_earns_a_tap(app_client, monkeypatch):
    """A real failure: a casually-capitalized comparison ('Compare databricks,
    azure and aws sagemaker...', nothing capitalized at all) never fires
    _entity_list -- no research fan-out, no /choices (the model had no reason
    to treat a comparison as a pick). The only tappable material left is the
    content role's own section headings, which the harness previously never
    looked at: the composed surface had no Button in it at all."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)
    import json as jsonlib

    async def answer(_app, prompt, system):
        if "You are the content role" in system:
            return {"text": jsonlib.dumps({
                "title": "Data Science Platform Comparison",
                "intro": "A comparison of three cloud-native platforms.",
                "sections": [{"heading": "Databricks", "points": ["Spark-native"]},
                             {"heading": "Azure ML", "points": ["Enterprise MLOps"]},
                             {"heading": "AWS SageMaker", "points": ["End-to-end lifecycle"]}],
            }), "provider": "gemini_1", "model": "fake"}
        return {"text": jsonlib.dumps({
            "root": "root", "components": [
                {"id": "root", "type": "Column", "children": ["title"]},
                {"id": "title", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
            ]}), "provider": "gemini_2", "model": "fake"}

    monkeypatch.setattr(agent_route, "gateway_text_llm", answer)
    body = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "cmp",
        "prompt": "Compare databricks, azure and aws sagemaker for data science",
        "respond_as": "ui"}).json()
    surface_node = body["graph"]["nodes"]["surface"]["result"]
    types = {c["type"] for c in surface_node["surface"]["components"]}
    assert "Button" in types
    assert "Button" in surface_node["harness_appended"]
    labels = {c["label"] for c in surface_node["surface"]["components"] if c["type"] == "Button"}
    assert labels == {"Databricks", "Azure ML", "AWS SageMaker"}


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


def test_run_graph_shows_the_composing_step_as_succeeded_not_running(app_client, monkeypatch):
    """A real UX bug: the compose_surface node's own entry in graph_nodes is
    built from INSIDE that same coroutine, before it has returned, so the
    graph store's own record for it still says 'running' at that instant.
    But a client only ever sees this via GET .../composed, which is
    unreachable until compose_surface has already returned successfully --
    by the time anyone looks, 'running' is stale and reads as a hang for a
    step that, from the viewer's side, is always already done."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)

    async def answer(_app, prompt, system):
        return {"text": "irrelevant for this test", "provider": "gemini_3", "model": "fake"}
    monkeypatch.setattr(agent_route, "gateway_text_llm", answer)

    body = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "trace",
        "prompt": "Explain zero-knowledge proofs simply.", "respond_as": "ui"}).json()
    graph_nodes = body["graph"]["nodes"]["surface"]["result"]["data_model"]["graph_nodes"]
    surface_row = next(n for n in graph_nodes if n["id"] == "surface")
    assert surface_row["state"] == "succeeded"
    assert "composing this view" in surface_row["detail"]


def test_run_graph_detail_carries_provider_and_duration(app_client, monkeypatch):
    """The two things asked after 'what happened': which provider actually
    answered, and how long it took. Provider comes from the node's own
    result (already returned by every LLM-calling skill); duration comes
    from GraphStore, which times every node regardless of what it does."""
    app_client.app.state.s13_runtime.memory.embedder = DeterministicEmbedder(128)

    async def answer(_app, prompt, system):
        return {"text": "irrelevant for this test", "provider": "gemini_3", "model": "fake"}
    monkeypatch.setattr(agent_route, "gateway_text_llm", answer)

    body = app_client.post("/v1/agent/runs", json={"tenant_id": "t", "project_id": "trace",
        "prompt": "Explain zero-knowledge proofs simply.", "respond_as": "ui"}).json()
    graph_nodes = body["graph"]["nodes"]["surface"]["result"]["data_model"]["graph_nodes"]
    content_row = next(n for n in graph_nodes if n["id"] == "content")
    assert "gemini_3" in content_row["detail"]
    assert re.search(r"\d+(\.\d+)?(ms|s)\b", content_row["detail"]), \
        f"no duration in detail: {content_row['detail']!r}"


def test_default_runtime_still_wires_ollama_embedder(tmp_path, monkeypatch):
    """A local checkout's behavior must not change: no env var, no surprise."""
    monkeypatch.delenv("S13_EMBEDDER", raising=False)
    runtime = S13Runtime(root=tmp_path)
    try:
        assert isinstance(runtime.memory.embedder, OllamaNomicEmbedder)
    finally:
        runtime.close()


def test_s13_embedder_env_var_switches_to_the_network_free_embedder(tmp_path, monkeypatch):
    """A container with no Ollama process opts in via S13_EMBEDDER=deterministic
    instead of crashing the first time a run writes an episode to memory."""
    monkeypatch.setenv("S13_EMBEDDER", "deterministic")
    runtime = S13Runtime(root=tmp_path)
    try:
        assert isinstance(runtime.memory.embedder, DeterministicEmbedder)
    finally:
        runtime.close()
