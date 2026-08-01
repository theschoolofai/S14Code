"""Local S13 runtime endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from s13code.core.memory import MemoryKind, MemoryScope, Principal

router = APIRouter(prefix="/v1/agent", tags=["S13 live agent"])


async def gateway_text_llm(app, prompt: str, system: str, max_tokens: int = 700):
    """Patchable test seam; production crosses HTTP through GatewayClient."""
    return await app.state.gateway.complete(prompt, system, max_tokens=max_tokens)


class ScopeBody(BaseModel):
    tenant_id: str
    project_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None

    def scope(self, run_id: str | None = None) -> MemoryScope:
        return MemoryScope(self.tenant_id, self.project_id, self.user_id, self.agent_id, run_id)


class RunBody(ScopeBody):
    prompt: str = Field(min_length=1, max_length=40_000)
    # How the run should answer: a plain text answer ("text", the default) or a
    # composed, validated A2UI interface ("ui"). Additive and domain-agnostic.
    respond_as: str = Field(default="text", pattern="^(text|ui)$")


class ResumeBody(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)


class FactBody(ScopeBody):
    text: str = Field(min_length=1, max_length=20_000)
    source_uri: str
    source_author: str = "user"
    supersedes_id: str | None = None


class IndexBody(ScopeBody):
    text: str = Field(min_length=1, max_length=500_000)
    source_uri: str
    source_author: str = "indexer"


class SearchBody(ScopeBody):
    query: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=5, ge=1, le=50)
    kinds: list[MemoryKind] | None = None


@router.post("/runs")
async def run(body: RunBody, request: Request):
    runtime = request.app.state.s13_runtime
    try:
        return await runtime.run(prompt=body.prompt, scope=body.scope(),
                                 llm=lambda prompt, system, max_tokens=700: gateway_text_llm(request.app, prompt, system, max_tokens),
                                 source_uri="api://agent/runs", source_author=body.user_id or "api-user",
                                 respond_as=body.respond_as)
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@router.post("/runs/{run_id}/resume")
async def resume(run_id: str, request: Request):
    runtime = request.app.state.s13_runtime
    try:
        return await runtime.run(prompt=None, scope=None,
                                 llm=lambda prompt, system, max_tokens=700: gateway_text_llm(request.app, prompt, system, max_tokens),
                                 source_uri=None, source_author=None, run_id=run_id, resume=True)
    except KeyError:
        raise HTTPException(404, "run not found") from None
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@router.post("/facts")
async def fact(body: FactBody, request: Request):
    return request.app.state.s13_runtime.remember_fact(text=body.text, scope=body.scope(), source_uri=body.source_uri,
        source_author=body.source_author, principal=Principal("gateway", "gateway"), supersedes_id=body.supersedes_id)


@router.post("/documents")
async def document(body: IndexBody, request: Request):
    return request.app.state.s13_runtime.index_document(text=body.text, source_uri=body.source_uri,
                                                        scope=body.scope(), source_author=body.source_author)


@router.post("/memory/search")
async def memory_search(body: SearchBody, request: Request):
    hits = request.app.state.s13_runtime.memory.recall(body.query, body.scope(),
                                                       kinds=body.kinds, limit=body.limit)
    return {"query": body.query, "hits": [{"id": hit.id, "kind": hit.kind.value,
            "text": hit.text, "sources": [source.uri for source in hit.sources],
            "metadata": hit.metadata} for hit in hits]}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    runtime = request.app.state.s13_runtime
    try:
        snapshot = runtime.graph.snapshot(run_id)
    except KeyError:
        raise HTTPException(404, "run not found") from None
    return {"run_id": run_id, "finished": snapshot.finished, "nodes": snapshot.nodes, "edges": snapshot.edges,
            "events": [event.__dict__ for event in runtime.graph.events(run_id)]}
