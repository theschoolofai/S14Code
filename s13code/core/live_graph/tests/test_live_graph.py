import asyncio
import time

import pytest

from s13code.core.live_graph import GraphPatch, GraphStore, LiveGraphExecutor, TaskSpec


class ScriptedPlanner:
    def __init__(self, script):
        self.script = script
        self.calls = []

    async def plan(self, graph, event):
        self.calls.append((event.kind, event.node_id, tuple(graph.nodes)))
        return self.script(graph, event)


@pytest.mark.asyncio
async def test_expands_only_after_real_outcome(tmp_path):
    def plan(graph, event):
        if event.kind == "run_started":
            return GraphPatch(add=(TaskSpec("research", "worker"),), reason="first frontier")
        if event.node_id == "research":
            assert event.payload == {"answer": "evidence"}
            return GraphPatch(add=(TaskSpec("verify", "worker"),), connect=(("research", "verify"),), reason="evidence changed frontier")
        return GraphPatch(finish=True, reason="verified")

    async def worker(task):
        return {"answer": "evidence" if task.id == "research" else "verified"}

    store = GraphStore(tmp_path / "graph.db")
    runner = LiveGraphExecutor(store, ScriptedPlanner(plan), {"worker": worker})
    report = await runner.run("expansion")
    assert report.finished and report.executed == ("research", "verify")
    patches = [e for e in store.events("expansion") if e.kind == "graph_patched"]
    assert patches[1].payload["add"] == ["verify"]


@pytest.mark.asyncio
async def test_planner_cancels_future_work_after_outcome(tmp_path):
    def plan(graph, event):
        if event.kind == "run_started":
            return GraphPatch(add=(TaskSpec("choose", "worker"), TaskSpec("obsolete", "worker")),
                              connect=(("choose", "obsolete"),))
        if event.node_id == "choose":
            return GraphPatch(cancel=("obsolete",), finish=True, reason="outcome made it unnecessary")
        raise AssertionError("cancelled task ran")

    async def worker(task): return {"choice": "done"}
    store = GraphStore(tmp_path / "graph.db")
    report = await LiveGraphExecutor(store, ScriptedPlanner(plan), {"worker": worker}).run("cancel")
    assert report.executed == ("choose",)
    assert store.snapshot("cancel").nodes["obsolete"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_ready_independent_tasks_run_bounded_concurrently(tmp_path):
    active = 0
    peak = 0
    lock = asyncio.Lock()

    def plan(graph, event):
        if event.kind == "run_started":
            return GraphPatch(add=(TaskSpec("a", "worker"), TaskSpec("b", "worker"), TaskSpec("c", "worker")))
        if len([n for n in graph.nodes.values() if n["state"] == "succeeded"]) == 3:
            return GraphPatch(finish=True)
        return GraphPatch()

    async def worker(task):
        nonlocal active, peak
        async with lock:
            active += 1; peak = max(peak, active)
        await asyncio.sleep(0.02)
        async with lock: active -= 1
        return {"task": task.id}

    store = GraphStore(tmp_path / "graph.db")
    report = await LiveGraphExecutor(store, ScriptedPlanner(plan), {"worker": worker}, max_workers=2).run("parallel")
    assert report.finished and peak == 2
    assert set(report.executed) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_resume_preserves_successful_nodes(tmp_path):
    counts = {"first": 0, "second": 0}
    def plan(graph, event):
        if event.kind == "run_started":
            return GraphPatch(add=(TaskSpec("first", "worker"), TaskSpec("second", "worker")), connect=(("first", "second"),))
        if event.node_id == "second": return GraphPatch(finish=True)
        return GraphPatch()
    async def worker(task):
        counts[task.id] += 1
        return {"task": task.id}

    store = GraphStore(tmp_path / "graph.db")
    runner = LiveGraphExecutor(store, ScriptedPlanner(plan), {"worker": worker})
    partial = await runner.run("resume", max_completed=1)
    assert not partial.finished and counts == {"first": 1, "second": 0}
    done = await runner.run("resume", resume=True)
    assert done.finished and counts == {"first": 1, "second": 1}


@pytest.mark.asyncio
async def test_fast_outcome_expands_before_slow_sibling_finishes(tmp_path):
    fast_done = asyncio.Event()
    allow_slow_to_finish = asyncio.Event()
    expanded = asyncio.Event()

    def plan(graph, event):
        if event.kind == "run_started":
            return GraphPatch(add=(TaskSpec("fast", "worker"), TaskSpec("slow", "worker")))
        if event.node_id == "fast":
            return GraphPatch(add=(TaskSpec("follow_up", "worker"),), connect=(("fast", "follow_up"),))
        if event.node_id == "follow_up":
            expanded.set()
            return GraphPatch()
        if event.node_id == "slow":
            return GraphPatch(finish=True)
        return GraphPatch()

    async def worker(task):
        if task.id == "fast":
            fast_done.set()
            return {"task": "fast"}
        if task.id == "slow":
            await allow_slow_to_finish.wait()
            return {"task": "slow"}
        return {"task": "follow_up"}

    store = GraphStore(tmp_path / "graph.db")
    runner = LiveGraphExecutor(store, ScriptedPlanner(plan), {"worker": worker}, max_workers=2)
    running = asyncio.create_task(runner.run("first-completion"))
    await asyncio.wait_for(fast_done.wait(), timeout=0.2)
    await asyncio.wait_for(expanded.wait(), timeout=0.2)
    assert store.node_state("first-completion", "slow") == "running"
    allow_slow_to_finish.set()
    report = await asyncio.wait_for(running, timeout=0.2)
    assert report.finished


@pytest.mark.asyncio
async def test_planner_cancels_running_sibling(tmp_path):
    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()

    def plan(graph, event):
        if event.kind == "run_started":
            return GraphPatch(add=(TaskSpec("decide", "worker"), TaskSpec("obsolete", "worker")))
        if event.node_id == "decide":
            return GraphPatch(cancel=("obsolete",), finish=True, reason="decision made sibling obsolete")
        return GraphPatch()

    async def worker(task):
        if task.id == "obsolete":
            slow_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise
        await slow_started.wait()
        return {"decision": "cancel sibling"}

    store = GraphStore(tmp_path / "graph.db")
    report = await asyncio.wait_for(
        LiveGraphExecutor(store, ScriptedPlanner(plan), {"worker": worker}, max_workers=2).run("cancel-running"),
        timeout=0.3,
    )
    assert report.finished
    assert store.node_state("cancel-running", "obsolete") == "cancelled"
    assert slow_cancelled.is_set()
    assert any(event.kind == "task_cancelled" and event.node_id == "obsolete"
               for event in store.events("cancel-running"))


@pytest.mark.asyncio
async def test_resume_replays_outcome_that_crashed_before_its_patch(tmp_path):
    """The outcome is durable first; its missing patch is recovered once."""
    def plan(graph, event):
        if event.kind == "run_started":
            return GraphPatch(add=(TaskSpec("first", "worker"),))
        if event.node_id == "first":
            return GraphPatch(add=(TaskSpec("second", "worker"),), connect=(("first", "second"),))
        if event.node_id == "second":
            return GraphPatch(finish=True)
        return GraphPatch()

    async def worker(task): return {"task": task.id}
    store = GraphStore(tmp_path / "graph.db")
    planner = ScriptedPlanner(plan)
    store.start("crash-gap")
    started = store.latest_event("crash-gap")
    assert started is not None
    store.apply_patch("crash-gap", plan(store.snapshot("crash-gap"), started), trigger_event=started.sequence)
    first = store.ready("crash-gap", limit=1)
    store.mark_running("crash-gap", first)
    outcome = store.record_outcome("crash-gap", "first", True, {"task": "first"})
    assert [event.sequence for event in store.pending_planner_events("crash-gap")] == [outcome.sequence]

    done = await LiveGraphExecutor(store, planner, {"worker": worker}).run("crash-gap", resume=True)
    assert done.finished and done.executed == ("second",)
    assert store.pending_planner_events("crash-gap") == []
    assert len([event for event in store.events("crash-gap") if event.kind == "graph_patched" and event.payload["trigger_event"] == outcome.sequence]) == 1


def test_record_outcome_measures_wall_clock_duration(tmp_path):
    """A UI reading 'how long did each step take' needs this on every node
    that has finished, without depending on the worker to report it itself --
    a worker cannot time its own execution honestly if the timer starts before
    the worker is even reached (queueing, retries)."""
    store = GraphStore(tmp_path / "graph.db")
    store.start("timing")
    store.apply_patch("timing", GraphPatch(add=(TaskSpec("slow", "worker"),), reason="start"),
                      trigger_event=store.latest_event("timing").sequence)
    ready = store.ready("timing", limit=1)
    store.mark_running("timing", ready)
    time.sleep(0.02)
    outcome = store.record_outcome("timing", "slow", True, {"answer": "done"})

    assert outcome.duration_ms is not None
    assert outcome.duration_ms >= 15  # slept 20ms; generous floor for CI jitter
    # The payload the worker returned stays exactly what it returned --
    # duration lives on the event, not smuggled into the result dict.
    assert outcome.payload == {"answer": "done"}

    node = store.snapshot("timing").nodes["slow"]
    assert node["duration_ms"] == pytest.approx(outcome.duration_ms)


def test_a_node_that_never_ran_has_no_duration(tmp_path):
    """A pending node was never started; None is honest, 0 would be a lie."""
    store = GraphStore(tmp_path / "graph.db")
    store.start("untimed")
    store.apply_patch("untimed", GraphPatch(add=(TaskSpec("never_started", "worker"),), reason="start"),
                      trigger_event=store.latest_event("untimed").sequence)
    node = store.snapshot("untimed").nodes["never_started"]
    assert node["duration_ms"] is None
