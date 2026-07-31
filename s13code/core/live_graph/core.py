"""A live task graph: small plans, durable events, and bounded parallel work.

The planner is deliberately *not* asked for a complete DAG.  It sees a graph
snapshot plus one event, then returns a GraphPatch containing only the next
useful mutations.  That makes an outcome capable of expanding, cancelling, or
waiting a graph before more work is launched.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

if TYPE_CHECKING:
    from .store import GraphStore


class NodeState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING = "waiting"


@dataclass(frozen=True)
class TaskSpec:
    """A named unit of work. Task ids are planner-owned and stable on resume."""

    id: str
    skill: str
    input: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphPatch:
    """The only way a planner mutates a graph.

    ``connect`` uses ``(parent, child)`` pairs. A waited node can be made
    runnable later with ``resume``; it is never silently retried.
    """

    add: tuple[TaskSpec, ...] = ()
    connect: tuple[tuple[str, str], ...] = ()
    cancel: tuple[str, ...] = ()
    wait: tuple[str, ...] = ()
    resume: tuple[str, ...] = ()
    finish: bool = False
    reason: str = ""


@dataclass(frozen=True)
class Event:
    sequence: int
    kind: str
    node_id: str | None
    payload: dict[str, Any]
    # Wall-clock time the node spent running, set only on task_succeeded /
    # task_failed. Kept separate from `payload` (which is exactly what the
    # worker returned) rather than folded into it, so nothing that compares
    # a worker's own result payload has to account for an unrelated field.
    duration_ms: float | None = None


@dataclass(frozen=True)
class GraphSnapshot:
    run_id: str
    finished: bool
    nodes: dict[str, dict[str, Any]]
    edges: tuple[tuple[str, str], ...]


class Planner(Protocol):
    async def plan(self, graph: GraphSnapshot, event: Event) -> GraphPatch: ...


Skill = Callable[[TaskSpec], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class RunReport:
    run_id: str
    finished: bool
    executed: tuple[str, ...]
    waiting: tuple[str, ...]


class LiveGraphExecutor:
    """Runs only ready independent nodes, then replans from real outcomes."""

    def __init__(
        self, store: GraphStore, planner: Planner, skills: dict[str, Skill], *, max_workers: int = 3
    ):
        if max_workers < 1:
            raise ValueError("max_workers must be at least one")
        self.store, self.planner, self.skills, self.max_workers = store, planner, skills, max_workers

    async def run(self, run_id: str, *, resume: bool = False, max_completed: int | None = None) -> RunReport:
        """Run until finished, externally waiting, or the optional test stop.

        A resumed run retains successful nodes. Only nodes interrupted while
        ``running`` are returned to ``pending``; their previous attempt stays
        visible in the event journal.
        """
        if resume:
            self.store.resume(run_id)
        else:
            self.store.start(run_id)

        # Outcomes and their planner mutations are separately crash-safe. On
        # startup/recovery replay every terminal event that has no idempotent
        # patch record before launching new work.
        await self._replay_pending_planner_events(run_id)

        executed: list[str] = []
        in_flight: dict[asyncio.Task[tuple[TaskSpec, bool, dict[str, Any]]], TaskSpec] = {}
        while True:
            # Fill free worker slots before waiting.  Crucially, after *one*
            # task completes below we come back here and can launch work from
            # its patch while unrelated siblings are still in flight.
            if not self.store.is_finished(run_id):
                capacity = self.max_workers - len(in_flight)
                if max_completed is not None:
                    capacity = min(capacity, max_completed - len(executed) - len(in_flight))
                if capacity > 0:
                    ready = self.store.ready(run_id, limit=capacity)
                    if ready:
                        self.store.mark_running(run_id, ready)
                        for task in ready:
                            in_flight[asyncio.create_task(self._execute(task))] = task

            if not in_flight:
                # No ready local work is either a genuinely finished run or a
                # deliberately waiting graph (for example an A2A push).
                break

            done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
            # Several tasks may finish in one loop tick. Stable ordering makes
            # the journal replayable, while FIRST_COMPLETED avoids a wave-wide
            # barrier when one sibling is slow.
            for future in sorted(done, key=lambda item: in_flight[item].id):
                task = in_flight.pop(future)
                try:
                    completed_task, success, payload = future.result()
                except asyncio.CancelledError:
                    # apply_patch journalled task_cancelled before cancelling
                    # the coroutine, so there is no synthetic failed outcome.
                    continue

                # A sibling completion may have caused the planner to cancel
                # this task in the same event-loop turn. Its late result is
                # intentionally discarded: cancellation is a graph decision,
                # not an execution race the worker gets to win.
                if self.store.node_state(run_id, task.id) == NodeState.CANCELLED:
                    continue
                event = self.store.record_outcome(run_id, completed_task.id, success, payload)
                executed.append(completed_task.id)
                if not self.store.is_finished(run_id):
                    await self._plan(run_id, event)
                    self._cancel_graph_cancelled_tasks(run_id, in_flight)

                if max_completed is not None and len(executed) >= max_completed:
                    # The optional test stop never leaves an unjournalled
                    # coroutine behind: launch capacity above prevented extra
                    # work from entering this process.
                    return self._report(run_id, executed)

            if self.store.is_finished(run_id):
                self._cancel_graph_cancelled_tasks(run_id, in_flight, cancel_all=True)
        return self._report(run_id, executed)

    async def _execute(self, task: TaskSpec) -> tuple[TaskSpec, bool, dict[str, Any]]:
        worker = self.skills.get(task.skill)
        if worker is None:
            return task, False, {"error": f"unknown skill: {task.skill}"}
        try:
            return task, True, await worker(task)
        except Exception as exc:  # worker failures become planner-visible events
            return task, False, {"error": f"{type(exc).__name__}: {exc}"}

    def _cancel_graph_cancelled_tasks(
        self,
        run_id: str,
        in_flight: dict[asyncio.Task[tuple[TaskSpec, bool, dict[str, Any]]], TaskSpec],
        *,
        cancel_all: bool = False,
    ) -> None:
        """Propagate graph cancellation to local asyncio workers.

        The durable store records cancellation first. Cancelling the coroutine
        is therefore safe even if the process dies before the task observes
        ``CancelledError``.
        """
        for future, task in tuple(in_flight.items()):
            if cancel_all or self.store.node_state(run_id, task.id) == NodeState.CANCELLED:
                future.cancel()

    async def _plan(self, run_id: str, event: Event | None) -> GraphPatch:
        if event is None:
            raise RuntimeError("run has no start event")
        patch = await self.planner.plan(self.store.snapshot(run_id), event)
        self.store.apply_patch(run_id, patch, trigger_event=event.sequence)
        return patch

    async def _replay_pending_planner_events(self, run_id: str) -> None:
        for event in self.store.pending_planner_events(run_id):
            if self.store.is_finished(run_id):
                return
            await self._plan(run_id, event)

    def _report(self, run_id: str, executed: list[str]) -> RunReport:
        snapshot = self.store.snapshot(run_id)
        waiting = tuple(nid for nid, node in snapshot.nodes.items() if node["state"] == NodeState.WAITING)
        return RunReport(run_id, snapshot.finished, tuple(executed), waiting)
