"""Official A2A 1.0 protobuf adapter and graph-facing remote-task facade."""
from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import grpc
from google.protobuf.empty_pb2 import Empty
from google.protobuf.timestamp_pb2 import Timestamp

from a2a.types import a2a_pb2 as p
from a2a.types import a2a_pb2_grpc as pb_grpc

from .server import A2ADemoServer, TaskState
from s13code.core.live_graph import GraphPatch, NodeState


def _task(task) -> p.Task:
    stamp = Timestamp(); stamp.FromDatetime(datetime.now(UTC))
    states = {TaskState.SUBMITTED: p.TASK_STATE_SUBMITTED, TaskState.WORKING: p.TASK_STATE_WORKING,
              TaskState.COMPLETED: p.TASK_STATE_COMPLETED, TaskState.FAILED: p.TASK_STATE_FAILED,
              TaskState.CANCELED: p.TASK_STATE_CANCELED}
    out = p.Task(id=task.id, context_id=task.context_id, status=p.TaskStatus(state=states[task.state], timestamp=stamp))
    for artifact in task.artifacts:
        out.artifacts.add(artifact_id=artifact["artifactId"], parts=[p.Part(text=x["text"]) for x in artifact["parts"]])
    return out


class DurablePushConfigs:
    """Small SQLite store: configs survive process restart; task execution is separate."""
    def __init__(self, path: str | Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute("create table if not exists a2a_push(task_id text,id text primary key,url text,token text)")
    def put(self, c: p.TaskPushNotificationConfig) -> p.TaskPushNotificationConfig:
        self.db.execute("insert or replace into a2a_push values(?,?,?,?)", (c.task_id,c.id,c.url,c.token)); self.db.commit(); return c
    def get(self, ident: str) -> p.TaskPushNotificationConfig | None:
        row=self.db.execute("select task_id,id,url,token from a2a_push where id=?",(ident,)).fetchone()
        return p.TaskPushNotificationConfig(task_id=row[0],id=row[1],url=row[2],token=row[3]) if row else None
    def list(self, task_id: str) -> list[p.TaskPushNotificationConfig]:
        return [p.TaskPushNotificationConfig(task_id=r[0],id=r[1],url=r[2],token=r[3]) for r in self.db.execute("select task_id,id,url,token from a2a_push where task_id=?",(task_id,))]
    def delete(self, task_id: str, ident: str) -> bool:
        cur=self.db.execute("delete from a2a_push where task_id=? and id=?",(task_id,ident)); self.db.commit(); return bool(cur.rowcount)


class OfficialA2AServicer(pb_grpc.A2AServiceServicer):
    def __init__(self, core: A2ADemoServer, pushes: DurablePushConfigs, *, bearer_tokens: set[str] | None = None,
                 api_keys: set[str] | None = None) -> None:
        self.core,self.pushes=core,pushes
        self.bearer_tokens,self.api_keys=bearer_tokens or set(),api_keys or set()
    async def _auth(self, context) -> None:
        if not (self.bearer_tokens or self.api_keys): return
        metadata={item.key.lower():item.value for item in context.invocation_metadata()}
        authorization=metadata.get("authorization","")
        bearer=authorization[7:] if authorization.lower().startswith("bearer ") else ""
        if not ((bearer and bearer in self.bearer_tokens) or metadata.get("x-api-key") in self.api_keys):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED,"A2A transport authentication required")
    @staticmethod
    def _params(request: p.SendMessageRequest) -> dict:
        return {"message":{"messageId":request.message.message_id,"contextId":request.message.context_id,
                "parts":[{"kind":"text","text":x.text} for x in request.message.parts if x.HasField("text")]}}
    async def SendMessage(self, request, context):
        await self._auth(context)
        result=await self.core.send(self._params(request)); return p.SendMessageResponse(task=_task(self.core.tasks[result["id"]]))
    async def SendStreamingMessage(self, request, context) -> AsyncIterator[p.StreamResponse]:
        await self._auth(context)
        async for update in self.core.stream_updates(self._params(request)): yield p.StreamResponse(task=_task(self.core.tasks[update["id"]]))
    async def GetTask(self, request, context):
        await self._auth(context)
        try: return _task(self.core.tasks[request.id])
        except KeyError: await context.abort(grpc.StatusCode.NOT_FOUND,"task not found")
    async def CancelTask(self, request, context):
        await self._auth(context)
        try: await self.core.cancel(request.id); return _task(self.core.tasks[request.id])
        except ValueError: await context.abort(grpc.StatusCode.NOT_FOUND,"task not found")
    async def SubscribeToTask(self, request, context) -> AsyncIterator[p.StreamResponse]:
        await self._auth(context)
        task=self.core.tasks.get(request.id)
        if not task: await context.abort(grpc.StatusCode.NOT_FOUND,"task not found")
        yield p.StreamResponse(task=_task(task))
        if task.state not in {TaskState.COMPLETED,TaskState.FAILED,TaskState.CANCELED}:
            while task.state not in {TaskState.COMPLETED,TaskState.FAILED,TaskState.CANCELED}:
                await asyncio.sleep(.02); yield p.StreamResponse(task=_task(task))
            yield p.StreamResponse(task=_task(task))
    async def CreateTaskPushNotificationConfig(self, request, context): await self._auth(context); return self.pushes.put(request)
    async def GetTaskPushNotificationConfig(self, request, context):
        await self._auth(context)
        found=self.pushes.get(request.id)
        if not found: await context.abort(grpc.StatusCode.NOT_FOUND,"push config not found")
        return found
    async def ListTaskPushNotificationConfigs(self, request, context):
        await self._auth(context)
        return p.ListTaskPushNotificationConfigsResponse(configs=self.pushes.list(request.task_id))
    async def DeleteTaskPushNotificationConfig(self, request, context):
        await self._auth(context)
        if not self.pushes.delete(request.task_id, request.id): await context.abort(grpc.StatusCode.NOT_FOUND,"push config not found")
        return Empty()


class GraphA2ARemote:
    """The only surface a live graph needs: start, wait/resume, cancel."""
    def __init__(self, stub): self.stub=stub
    async def start(self, request: p.SendMessageRequest) -> p.Task: return (await self.stub.SendMessage(request)).task
    async def wait(self, task_id: str) -> p.Task:
        final=None
        async for event in self.stub.SubscribeToTask(p.SubscribeToTaskRequest(id=task_id)):
            final=event.task
        return final
    async def cancel(self, task_id: str) -> p.Task: return await self.stub.CancelTask(p.CancelTaskRequest(id=task_id))


class A2AGraphBridge:
    """Durable graph seam: remote subscriptions resume deliberately waiting nodes."""
    def __init__(self, remote: GraphA2ARemote) -> None:
        self.remote, self.remote_ids, self.results = remote, {}, {}

    async def dispatch_waiting(self, store, run_id: str, node_id: str, request: p.SendMessageRequest) -> p.Task:
        if store.node_state(run_id, node_id) != NodeState.WAITING:
            raise ValueError(f"graph node {node_id} must be waiting before A2A dispatch")
        started = await self.remote.start(request)
        self.remote_ids[(run_id, node_id)] = started.id
        final = await self.remote.wait(started.id)
        self.results[(run_id, node_id)] = final
        event = store.record_external_event(run_id, "a2a_task_completed", node_id,
                                            {"remote_task_id": final.id, "state": final.status.state})
        if store.node_state(run_id, node_id) == NodeState.WAITING:
            store.apply_patch(run_id, GraphPatch(resume=(node_id,), reason="official A2A subscription completed"),
                              trigger_event=event.sequence)
        return final

    async def result_skill(self, task) -> dict:
        final = self.results[(task.input["run_id"], task.id)]
        return {"remote_task_id": final.id, "state": final.status.state,
                "artifacts": [artifact.artifact_id for artifact in final.artifacts]}

    async def cancel_node(self, store, run_id: str, node_id: str) -> p.Task:
        remote_id = self.remote_ids[(run_id, node_id)]
        final = await self.remote.cancel(remote_id)
        store.record_external_event(run_id, "a2a_task_cancelled", node_id,
                                    {"remote_task_id": remote_id, "state": final.status.state})
        return final


class OfficialA2AServer:
    """Lifecycle wrapper used by production startup and the interoperability test."""
    def __init__(self, core: A2ADemoServer, db_path: str | Path = ":memory:", *, address: str = "127.0.0.1:0",
                 bearer_tokens: set[str] | None = None, api_keys: set[str] | None = None) -> None:
        self.server=grpc.aio.server(); self.servicer=OfficialA2AServicer(
            core, DurablePushConfigs(db_path), bearer_tokens=bearer_tokens, api_keys=api_keys)
        pb_grpc.add_A2AServiceServicer_to_server(self.servicer, self.server); self.port=None; self.address=address
    async def start(self) -> str:
        self.port=self.server.add_insecure_port(self.address)
        if not self.port: raise RuntimeError("could not bind A2A gRPC server")
        await self.server.start(); return self.address.rsplit(":", 1)[0] + f":{self.port}"
    async def stop(self) -> None: await self.server.stop(0)
