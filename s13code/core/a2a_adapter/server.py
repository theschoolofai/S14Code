"""A deliberately small local A2A JSON-RPC/SSE server used by S13Core tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .schema import validate_agent_card


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
PushCallback = Callable[[dict[str, Any]], Awaitable[None]]
TaskHandler = Callable[[str], Awaitable[str]]


@dataclass
class Task:
    id: str
    context_id: str
    text: str
    state: TaskState = TaskState.SUBMITTED
    history: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    callback_url: str | None = None
    callback_token: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def wire(self) -> dict[str, Any]:
        data = {"kind": "task", "id": self.id, "contextId": self.context_id,
                "status": {"state": self.state.value, "timestamp": self.updated_at}}
        if self.artifacts:
            data["artifacts"] = self.artifacts
        return data


class DurableTaskStore:
    """SQLite-backed task snapshots and idempotent push delivery ledger."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute("create table if not exists a2a_tasks(id text primary key, payload text not null)")
        self.db.execute("""create table if not exists a2a_push_delivery(
            event_id text primary key, task_id text not null, delivered integer not null default 0,
            attempts integer not null default 0, last_error text)""")
        self.db.commit()

    def save(self, task: Task) -> None:
        payload = asdict(task); payload["state"] = task.state.value
        self.db.execute("insert or replace into a2a_tasks values(?,?)", (task.id, json.dumps(payload)))
        self.db.commit()

    def load_all(self) -> dict[str, Task]:
        result: dict[str, Task] = {}
        for _, raw in self.db.execute("select id,payload from a2a_tasks"):
            data = json.loads(raw); data["state"] = TaskState(data["state"])
            task = Task(**data); result[task.id] = task
        return result

    def delivery(self, event_id: str) -> tuple[bool, int]:
        row = self.db.execute("select delivered,attempts from a2a_push_delivery where event_id=?", (event_id,)).fetchone()
        return (bool(row[0]), int(row[1])) if row else (False, 0)

    def record_delivery(self, event_id: str, task_id: str, *, delivered: bool, attempts: int, error: str = "") -> None:
        self.db.execute("insert or replace into a2a_push_delivery values(?,?,?,?,?)",
                        (event_id, task_id, int(delivered), attempts, error))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class A2ADemoServer:
    """Local reference adapter, not a replacement for the official A2A SDK.

    ``push_callback`` lets tests (and a future graph event bridge) receive the
    same JSON-RPC update a webhook would receive without external networking.
    """

    def __init__(self, card: dict[str, Any], *, push_callback: PushCallback | None = None,
                 task_handler: TaskHandler | None = None, task_db: str | Path = ":memory:",
                 bearer_tokens: set[str] | None = None, api_keys: set[str] | None = None,
                 push_signing_secret: str | None = None, push_http: httpx.AsyncClient | None = None,
                 push_attempts: int = 4, push_backoff: float = .05) -> None:
        validate_agent_card(card)
        self.card, self.push_callback, self.task_handler = card, push_callback, task_handler
        self.store = DurableTaskStore(task_db)
        self.tasks = self.store.load_all()
        self.bearer_tokens, self.api_keys = bearer_tokens or set(), api_keys or set()
        self.push_signing_secret, self.push_http = push_signing_secret, push_http
        self.push_attempts, self.push_backoff = push_attempts, push_backoff
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self.app = FastAPI(title="S13Core local A2A adapter")
        self.app.get("/.well-known/agent-card.json")(self.agent_card)
        self.app.post("/a2a")(self.rpc)

    async def agent_card(self) -> JSONResponse:
        return JSONResponse(self.card, headers={"Cache-Control": "max-age=60"})

    async def start(self) -> None:
        """Recover non-terminal durable tasks after a process restart."""
        for task in self.tasks.values():
            if task.state not in TERMINAL and task.id not in self._jobs:
                task.state = TaskState.WORKING
                task.updated_at = datetime.now(UTC).isoformat()
                self.store.save(task)
                self._jobs[task.id] = asyncio.create_task(self._complete_later(task, 0))

    async def rpc(self, request: Request):
        if self.bearer_tokens or self.api_keys:
            bearer = request.headers.get("authorization", "")
            bearer = bearer[7:] if bearer.lower().startswith("bearer ") else ""
            api_key = request.headers.get("x-api-key", "")
            if not ((bearer and bearer in self.bearer_tokens) or (api_key and api_key in self.api_keys)):
                return JSONResponse(self._error(None, -32003, "A2A transport authentication required"), status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
        body = await request.json()
        method, request_id = body.get("method"), body.get("id")
        params = body.get("params", {})
        try:
            if method == "message/send":
                return JSONResponse(self._response(request_id, await self.send(params)))
            if method == "message/stream":
                return StreamingResponse(self.stream(request_id, params), media_type="text/event-stream")
            if method == "tasks/get":
                return JSONResponse(self._response(request_id, self.get(str(params.get("id")))))
            if method == "tasks/cancel":
                return JSONResponse(self._response(request_id, await self.cancel(str(params.get("id")))))
            return JSONResponse(self._error(request_id, -32601, f"Unknown A2A method: {method}"), status_code=400)
        except ValueError as error:
            # Keep protocol failures as JSON-RPC errors rather than leaking an
            # HTTP 500 to the live-graph scheduler.
            return JSONResponse(self._error(request_id, -32001, str(error)), status_code=404)

    @staticmethod
    def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    async def send(self, params: dict[str, Any]) -> dict[str, Any]:
        task = self._new_task(params)
        if "async" in task.text.lower() or "slow" in task.text.lower():
            task.state = TaskState.WORKING
            task.updated_at = datetime.now(UTC).isoformat()
            self.store.save(task)
            await self._notify(task)
            self._jobs[task.id] = asyncio.create_task(self._complete_later(task, 0.08))
            return task.wire()
        await self._complete(task)
        return task.wire()

    async def stream(self, request_id: Any, params: dict[str, Any]):
        async for update in self.stream_updates(params):
            yield self._sse(self._response(request_id, update))

    async def stream_updates(self, params: dict[str, Any]):
        """Yield transport-neutral task snapshots for SSE and gRPC bindings."""
        task = self._new_task(params)
        task.state = TaskState.WORKING
        task.updated_at = datetime.now(UTC).isoformat()
        self.store.save(task)
        yield task.wire()
        await asyncio.sleep(0)
        if task.state not in TERMINAL:
            await self._complete(task)
        yield task.wire()

    @staticmethod
    def _sse(response: dict[str, Any]) -> str:
        return f"data: {json.dumps(response, separators=(',', ':'))}\n\n"

    def _new_task(self, params: dict[str, Any]) -> Task:
        message = params.get("message", {})
        parts = message.get("parts", [])
        text = " ".join(str(part.get("text", "")) for part in parts if part.get("kind") == "text")
        task = Task(id=str(uuid.uuid4()), context_id=str(message.get("contextId") or uuid.uuid4()), text=text)
        config = params.get("configuration", {})
        push = config.get("pushNotificationConfig", {})
        task.callback_url = push.get("url")
        task.callback_token = push.get("token") or push.get("authentication", {}).get("credentials")
        self.tasks[task.id] = task
        self.store.save(task)
        return task

    def get(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        return task.wire()

    async def cancel(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if task.state not in TERMINAL:
            task.state, task.updated_at = TaskState.CANCELED, datetime.now(UTC).isoformat()
            self.store.save(task)
            job = self._jobs.get(task.id)
            if job:
                job.cancel()
            await self._notify(task)
        return task.wire()

    async def _complete_later(self, task: Task, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if task.state not in TERMINAL:
                await self._complete(task)
        except asyncio.CancelledError:
            return

    async def _complete(self, task: Task) -> None:
        try:
            result = await self.task_handler(task.text) if self.task_handler else f"done: {task.text}"
            # A handler may answer with plain text, or with A2A parts of its own
            # when it has structured evidence to hand back rather than prose.
            parts = result if isinstance(result, list) else [{"kind": "text", "text": result}]
            task.state, task.updated_at = TaskState.COMPLETED, datetime.now(UTC).isoformat()
            task.artifacts = [{"artifactId": f"result-{task.id}", "parts": parts}]
        except Exception as error:
            task.state, task.updated_at = TaskState.FAILED, datetime.now(UTC).isoformat()
            task.artifacts = [{"artifactId": f"error-{task.id}", "parts": [{"kind": "text", "text": f"{type(error).__name__}: {error}"}]}]
        self.store.save(task)
        await self._notify(task)

    async def _notify(self, task: Task) -> None:
        if not task.callback_url:
            return
        event = {"jsonrpc": "2.0", "method": "tasks/statusUpdate", "params": task.wire(), "url": task.callback_url}
        if self.push_callback:
            await self.push_callback(event)
            return
        if not self.push_http:
            return
        event_id = hashlib.sha256(f"{task.id}:{task.state.value}:{task.updated_at}".encode()).hexdigest()
        delivered, attempts = self.store.delivery(event_id)
        if delivered:
            return
        payload = json.dumps({key: value for key, value in event.items() if key != "url"}, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", "Idempotency-Key": event_id,
                   "A2A-Task-ID": task.id}
        if task.callback_token:
            headers["Authorization"] = f"Bearer {task.callback_token}"
        if self.push_signing_secret:
            headers["A2A-Signature"] = "sha256=" + hmac.new(
                self.push_signing_secret.encode(), payload, hashlib.sha256
            ).hexdigest()
        last_error = ""
        for number in range(attempts + 1, self.push_attempts + 1):
            try:
                response = await self.push_http.post(task.callback_url, content=payload, headers=headers)
                response.raise_for_status()
                self.store.record_delivery(event_id, task.id, delivered=True, attempts=number)
                return
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                self.store.record_delivery(event_id, task.id, delivered=False, attempts=number, error=last_error)
                if number < self.push_attempts:
                    await asyncio.sleep(self.push_backoff * (2 ** (number - 1)))

    async def close(self) -> None:
        jobs = list(self._jobs.values())
        for job in jobs:
            if not job.done():
                job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        self.store.close()
