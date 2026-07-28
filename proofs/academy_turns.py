"""Trading Systems Academy: capture the UI-only application answering live.

This drives the RUNNING runtime over HTTP, exactly as the browser app does —
``POST /v1/agent/runs`` with ``respond_as: "ui"``, then ``GET
/v1/runs/{id}/composed`` — so what is captured is the real loop, not a
re-implementation of it.

Two things are proved:

  A. VARIETY  — three different prompts produce three genuinely different
     interfaces, each built from the components the data actually calls for.
  B. CONVERSATION — a three-turn thread where a tap in one interface shapes the
     next. The follow-up is not scripted: the script reads the Button labels the
     agent itself composed and taps one, exactly as a user would.

Prerequisites: glc_v3 on 8111 and this runtime on 8113.

    GLC_BASE_URL=http://127.0.0.1:8111 S13_GATEWAY_PROVIDER=gemini \
      S13_MAX_TOKENS=6000 S14_SURFACE_MAX_TOKENS=20000 uv run s14code serve

    uv run python proofs/academy_turns.py        # -> proofs/academy_turns.json
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

BASE = os.getenv("S14_BASE_URL", "http://127.0.0.1:8113").rstrip("/")
OUT = Path(__file__).parent / "academy_turns.json"

# Every turn spends several model calls (content, then compose). On free-tier
# Gemini keys the gateway's per-key RPM budget is the binding constraint: fire
# six turns back to back and the router burns every key in the pool and answers
# 502. Pace the capture and retry a turn that lost its compose node, so the
# proof measures the system rather than the quota.
PACE_SECONDS = float(os.getenv("S14_PACE_SECONDS", "30"))
ATTEMPTS = int(os.getenv("S14_ATTEMPTS", "3"))

# A. Three prompts whose data has three different shapes, so a catalog-reading
#    composer should reach for three different sets of components.
PROMPTS = [
    # a two-dimensional shape: topic x week
    "Teach me how a stock exchange matching engine works. I have 4 weeks. Show me how much "
    "study effort each core topic deserves in each week, plus the key numbers and a study path.",
    # a row/column shape: one row per order type
    "Compare market, limit, stop and iceberg orders side by side: how each behaves in the order "
    "book, its visibility, its typical use and its slippage risk. Give me the key counts too.",
    # a one-dimensional numeric series: latency per stage
    "Walk me through the path of a market data tick from the exchange to a trading application. "
    "For each stage give me the typical latency in microseconds so I can see where the time goes.",
]

# B. The conversation opens here; turns 2 and 3 are taps on what the agent drew.
THREAD_OPENER = (
    "Teach me for a trading-systems engineering interview. Ask me which area to study first."
)


def _post(path: str, body: dict, timeout: int = 900) -> dict:
    request = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _get(path: str, timeout: int = 120) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
        return json.load(response)


def _pointer(data_model: dict, path: str):
    current = data_model
    for segment in str(path).split("/")[1:]:
        if current is None:
            return None
        current = current.get(segment) if isinstance(current, dict) else None
    return current


def _resolve(value, data_model: dict):
    """The client's own resolve(): a {"$bind": "/ptr"} reads the data model, a
    literal passes through. Button labels are usually BOUND, so a proof that
    only looked at literals would see no tappable choices at all."""
    if isinstance(value, dict) and "$bind" in value:
        return _pointer(data_model, value["$bind"])
    return value


def compose(goal: str, attempts: int = ATTEMPTS) -> dict:
    """One turn of the app: start a UI run, then read the composed interface.

    Retries a turn whose compose node produced nothing, which on this stack means
    the gateway ran out of per-key RPM mid-run rather than the composer failing.
    """
    last: dict = {}
    for attempt in range(1, attempts + 1):
        try:
            run = _post("/v1/agent/runs", {
                "prompt": goal, "respond_as": "ui", "tenant_id": "course", "project_id": "s14",
                "user_id": "student-01", "agent_id": "academy",
            })
        except Exception as error:                                   # noqa: BLE001
            last = {"goal": goal, "error": f"{type(error).__name__}: {error}"}
            print(f"      attempt {attempt}/{attempts}: run failed — {last['error']}")
            time.sleep(PACE_SECONDS)
            continue

        run_id = run.get("run_id")
        if not run_id:
            last = {"goal": goal, "error": "no run_id", "raw": run}
            continue
        try:
            composed = _get(f"/v1/runs/{run_id}/composed")
            break
        except urllib.error.HTTPError as error:
            last = {"goal": goal, "run_id": run_id, "error": f"HTTP {error.code}",
                    "detail": error.read().decode()[:400]}
            print(f"      attempt {attempt}/{attempts}: {last['error']} — {last.get('detail','')[:90]}")
            if attempt < attempts:
                time.sleep(PACE_SECONDS)
    else:
        return last

    components = composed["surface"]["components"]
    data_model = composed["surface"].get("dataModel") or {}
    validator = composed.get("validator") or {}
    return {
        "goal": goal,
        "run_id": run_id,
        "provider": composed.get("provider"),
        "model": composed.get("model"),
        "component_count": composed["component_count"],
        "clean": composed["clean"],
        "component_types": dict(Counter(component["type"] for component in components)),
        "buttons": [_resolve(component.get("label"), data_model) for component in components
                    if component.get("type") == "Button"],
        "matrix_pointers": sorted(key for key in data_model if key.startswith("matrix_")),
        "used_heatmap": any(component["type"] == "Heatmap" for component in components),
        "validator": {"proposed": validator.get("proposed"), "accepted": validator.get("accepted"),
                      "rejected": validator.get("rejected"),
                      "rejections": validator.get("rejections") or []},
        "surface": composed["surface"],
    }


# The application's standing requirement (see KEEP_GOING in academy.html): a
# tap-driven app must always offer somewhere to go next. It names no component.
KEEP_GOING = ("\nAlways finish by offering 3 to 5 concrete next topics the learner can pick from. "
              "Label each one as a short topic name, not as a question.")


def thread_goal(trail: list[str]) -> str:
    """The exact goal string the browser app builds for turn N."""
    if len(trail) == 1:
        return trail[0] + KEEP_GOING
    return (trail[0] + "\nThe learner then chose, in order: " + " → ".join(trail[1:])
            + ".\nCompose the next interface for that choice, staying in the trading-systems domain."
            + KEEP_GOING)


def _load_previous() -> dict:
    """Successful turns are kept across invocations.

    A turn costs several large model calls, and on free-tier keys the daily
    request budget runs out before a six-turn capture finishes. Rather than throw
    away good captures every time the quota bites, already-captured turns are
    reused and only the missing ones are re-attempted. Every turn record keeps its
    own run_id, so nothing is stitched together that did not really happen.
    """
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        return {}


def main() -> int:
    print(f"runtime: {BASE}")
    print(f"pacing : {PACE_SECONDS}s between turns, {ATTEMPTS} attempts each")

    previous = _load_previous()
    done_variety = {turn.get("goal"): turn for turn in previous.get("variety", []) if "error" not in turn}
    done_thread = {turn.get("goal"): turn for turn in previous.get("thread", []) if "error" not in turn}
    if done_variety or done_thread:
        print(f"resuming : {len(done_variety)} variety and {len(done_thread)} thread turn(s) already captured")
    print()

    print("=== A. VARIETY — three prompts, three interfaces ===")
    variety = []
    for index, prompt in enumerate(PROMPTS, 1):
        print(f"\n[{index}/3] {prompt[:78]}…")
        if prompt in done_variety:
            cached = done_variety[prompt]
            variety.append(cached)
            print(f"      already captured ({cached['run_id']}): {cached['component_count']} "
                  f"components, types {cached['component_types']}")
            continue
        if index > 1:
            time.sleep(PACE_SECONDS)
        turn = compose(prompt)
        variety.append(turn)
        if "error" in turn:
            print(f"      ERROR {turn['error']} {turn.get('detail','')}")
            continue
        print(f"      {turn['component_count']} components · clean={turn['clean']} · {turn['model']}")
        print(f"      types: {turn['component_types']}")
        if turn["used_heatmap"]:
            print("      -> composed a Heatmap unprompted")

    print("\n=== B. CONVERSATION — a tap shapes the next turn ===")
    trail: list[str] = [THREAD_OPENER]
    thread = []
    for turn_number in range(1, 4):
        goal = thread_goal(trail)
        print(f"\n[turn {turn_number}] tapped: {trail[-1][:70]}")
        if goal in done_thread:
            turn = done_thread[goal]
            print(f"      already captured ({turn['run_id']}): {turn['component_count']} "
                  f"components, types {turn['component_types']}")
        else:
            time.sleep(PACE_SECONDS)
            turn = compose(goal)
            turn["trail"] = list(trail)
            if "error" in turn:
                thread.append(turn)
                print(f"      ERROR {turn['error']} {turn.get('detail','')}")
                break
            print(f"      {turn['component_count']} components · types: {turn['component_types']}")
        thread.append(turn)
        buttons = [label for label in turn["buttons"] if isinstance(label, str) and label.strip()]
        print(f"      offered {len(buttons)} tappable choices: {buttons[:4]}")
        if turn_number < 3:
            if not buttons:
                print("      no Button offered — the thread cannot continue by tapping")
                break
            trail.append(buttons[0])       # tap the first choice the AGENT drew

    all_types: Counter = Counter()
    for turn in variety + thread:
        all_types.update(turn.get("component_types") or {})

    proof = {
        "base_url": BASE,
        "variety": variety,
        "thread": thread,
        "summary": {
            "distinct_component_types": sorted(all_types),
            "component_type_counts": dict(all_types),
            "heatmap_composed_unprompted": any(turn.get("used_heatmap") for turn in variety + thread),
            "turns_captured": len([t for t in variety + thread if "error" not in t]),
            "every_turn_clean": all(turn.get("clean") for turn in variety + thread if "error" not in turn),
        },
    }
    OUT.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(f"turns captured   : {proof['summary']['turns_captured']}")
    print(f"distinct types   : {proof['summary']['distinct_component_types']}")
    print(f"heatmap unprompted: {proof['summary']['heatmap_composed_unprompted']}")
    print(f"every turn clean : {proof['summary']['every_turn_clean']}")
    print(f"\nwrote {OUT}")
    return 0 if proof["summary"]["turns_captured"] >= 5 else 3


if __name__ == "__main__":
    raise SystemExit(main())
