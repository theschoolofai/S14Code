import asyncio
import hashlib
import hmac
import json

import grpc
import httpx
import pytest
from a2a.types import a2a_pb2 as p
from a2a.types import a2a_pb2_grpc as pb_grpc

from s13code.core.a2a_adapter.official import A2AGraphBridge, GraphA2ARemote, OfficialA2AServer
from s13code.core.a2a_adapter.schema import AgentCardError, negotiate_interface, validate_agent_card
from s13code.core.a2a_adapter.server import A2ADemoServer
from s13code.core.live_graph import GraphPatch, GraphStore, LiveGraphExecutor, TaskSpec


def card(versions=("1.0",)):
    return {
        "name": "durable", "description": "hardening fixture", "version": "1.2.3",
        "supportedInterfaces": [
            {"url": f"http://a2a.test/{v}", "protocolBinding": "JSONRPC", "protocolVersion": v}
            for v in versions
        ],
        "capabilities": {"streaming": True, "pushNotifications": True},
        "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
        "skills": [{"id": "echo", "name": "Echo", "description": "Echo", "tags": ["test"]}],
    }


def params(text="answer now", callback=None):
    result = {"message": {"kind": "message", "messageId": "m", "role": "user",
                          "parts": [{"kind": "text", "text": text}]}}
    if callback:
        result["configuration"] = {"pushNotificationConfig": callback}
    return result


@pytest.mark.asyncio
async def test_task_snapshot_survives_server_restart(tmp_path):
    path = tmp_path / "tasks.sqlite"
    first = A2ADemoServer(card(), task_db=path)
    done = await first.send(params())
    await first.close()
    second = A2ADemoServer(card(), task_db=path)
    try:
        assert second.get(done["id"]) == done
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_in_flight_task_recovers_and_completes_after_restart(tmp_path):
    path = tmp_path / "recover.sqlite"
    first = A2ADemoServer(card(), task_db=path)
    working = await first.send(params("slow durable work"))
    assert working["status"]["state"] == "working"
    await first.close()
    second = A2ADemoServer(card(), task_db=path)
    try:
        await second.start()
        await asyncio.sleep(.02)
        assert second.get(working["id"])["status"]["state"] == "completed"
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_push_is_authenticated_signed_retried_and_idempotent(tmp_path):
    calls = []

    async def callback(request: httpx.Request):
        calls.append(request)
        return httpx.Response(503 if len(calls) < 3 else 204)

    http = httpx.AsyncClient(transport=httpx.MockTransport(callback))
    server = A2ADemoServer(card(), task_db=tmp_path / "push.sqlite", push_http=http,
                           push_signing_secret="webhook-secret", push_attempts=4, push_backoff=0)
    try:
        result = await server.send(params(callback={"url": "https://callback.test/a2a", "token": "receiver-token"}))
        assert result["status"]["state"] == "completed"
        assert len(calls) == 3
        assert {r.headers["idempotency-key"] for r in calls} == {calls[0].headers["idempotency-key"]}
        assert calls[-1].headers["authorization"] == "Bearer receiver-token"
        expected = hmac.new(b"webhook-secret", calls[-1].content, hashlib.sha256).hexdigest()
        assert calls[-1].headers["a2a-signature"] == f"sha256={expected}"
        await server._notify(server.tasks[result["id"]])
        assert len(calls) == 3
    finally:
        await server.close(); await http.aclose()


@pytest.mark.asyncio
async def test_jsonrpc_transport_requires_bearer_or_api_key():
    server = A2ADemoServer(card(), bearer_tokens={"bearer-good"}, api_keys={"key-good"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://a2a.test") as http:
        payload = {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": params()}
        assert (await http.post("/a2a", json=payload)).status_code == 401
        assert (await http.post("/a2a", json=payload, headers={"Authorization": "Bearer bearer-good"})).status_code == 200
        assert (await http.post("/a2a", json=payload, headers={"X-API-Key": "key-good"})).status_code == 200


def test_official_card_schema_and_version_negotiation():
    validate_agent_card(card(("1.0", "1.1")))
    assert negotiate_interface(card(("1.0", "1.1")), versions=("1.1", "1.0"))["protocolVersion"] == "1.1"
    with pytest.raises(AgentCardError, match="No mutually supported"):
        negotiate_interface(card(("1.1",)), versions=("1.0",))
    invalid = card(); invalid["unknownLegacyField"] = True
    with pytest.raises(AgentCardError, match="Invalid A2A"):
        validate_agent_card(invalid)


@pytest.mark.asyncio
async def test_official_grpc_mount_enforces_transport_auth(tmp_path):
    server = OfficialA2AServer(A2ADemoServer(card()), tmp_path / "grpc.sqlite", bearer_tokens={"grpc-good"})
    channel = grpc.aio.insecure_channel(await server.start()); stub = pb_grpc.A2AServiceStub(channel)
    request = p.SendMessageRequest(message=p.Message(message_id="m", role=p.ROLE_USER, parts=[p.Part(text="hello")]))
    try:
        with pytest.raises(grpc.aio.AioRpcError) as denied:
            await stub.SendMessage(request)
        assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
        response = await stub.SendMessage(request, metadata=(("authorization", "Bearer grpc-good"),))
        assert response.task.status.state == p.TASK_STATE_COMPLETED
    finally:
        await channel.close(); await server.stop()


@pytest.mark.asyncio
async def test_official_subscription_resumes_waiting_graph_and_maps_cancel(tmp_path):
    core = A2ADemoServer(card())
    server = OfficialA2AServer(core, tmp_path / "official.sqlite")
    channel = grpc.aio.insecure_channel(await server.start())
    bridge = A2AGraphBridge(GraphA2ARemote(pb_grpc.A2AServiceStub(channel)))
    store = GraphStore(tmp_path / "graph.sqlite")

    class Planner:
        async def plan(self, graph, event):
            if event.kind == "run_started":
                node = TaskSpec("remote", "a2a_result", {"run_id": graph.run_id}, {"agent": "remote-a2a"})
                return GraphPatch(add=(node,), wait=("remote",), reason="wait for remote subscription")
            if event.node_id == "remote":
                return GraphPatch(finish=True, reason="remote result joined graph")
            return GraphPatch()

    runner = LiveGraphExecutor(store, Planner(), {"a2a_result": bridge.result_skill})
    request = p.SendMessageRequest(message=p.Message(message_id="m", role=p.ROLE_USER,
                                                       parts=[p.Part(text="slow remote report")]))
    try:
        parked = await runner.run("remote-run")
        assert parked.waiting == ("remote",)
        final = await bridge.dispatch_waiting(store, "remote-run", "remote", request)
        assert final.status.state == p.TASK_STATE_COMPLETED
        assert store.node_state("remote-run", "remote") == "pending"
        done = await runner.run("remote-run", resume=True)
        assert done.finished and store.snapshot("remote-run").nodes["remote"]["result"]["remote_task_id"] == final.id

        parked = await runner.run("cancel-run")
        dispatch = asyncio.create_task(bridge.dispatch_waiting(store, "cancel-run", "remote", request))
        for _ in range(30):
            if ("cancel-run", "remote") in bridge.remote_ids: break
            await asyncio.sleep(.005)
        decision = store.record_external_event("cancel-run", "graph_cancel_requested", "remote", {})
        store.apply_patch("cancel-run", GraphPatch(cancel=("remote",), finish=True, reason="caller cancelled"),
                          trigger_event=decision.sequence)
        cancelled = await bridge.cancel_node(store, "cancel-run", "remote")
        assert cancelled.status.state == p.TASK_STATE_CANCELED
        await dispatch
        assert store.node_state("cancel-run", "remote") == "cancelled"
    finally:
        store.close(); await channel.close(); await server.stop(); await core.close()
