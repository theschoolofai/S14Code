"""Prove AG-UI STATE_SNAPSHOT reconnect for real, against recorded S13 fixtures.

The claim (lecture §4/§9 + the event-tape widget): a client that loses its
connection mid-run does NOT have to replay every delta from the start. It asks
for one ``STATE_SNAPSHOT`` carrying the COMPLETE current data model and is whole
again in a single frame. This script makes that claim TRUE and checks it:

  1. Full replay  — fold the entire AG-UI stream from seq 0 → full_state.
  2. Mid drop     — a client folds only the first k events, then the socket dies.
  3. Reconnect    — the server sends ONE STATE_SNAPSHOT (the complete data model)
                    as the first frame; the client adopts it wholesale.
  4. Equality     — the snapshot-rebuilt state equals the full-replay state,
                    with no duplicated actions (patch log same length, not 2x).

No live gateway and no Ollama: the input is the recorded three_cities journal.
Writes proofs/reconnect_proof.json and prints a clear PASS/FAIL.

    uv run python proofs/reconnect_proof.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from s13code.ui.agui import (  # noqa: E402
    replay_state,
    run_data_model,
    state_snapshot,
    stream_agui,
)
from s13code.ui.fixtures import RecordedS13  # noqa: E402

OUT = Path(__file__).parent / "reconnect_proof.json"
DROP_AFTER = 6  # the socket dies partway through the run


def naive_replay_after_snapshot(snapshot_state: dict, remaining: list[dict]) -> dict:
    """A client that WRONGLY replays the already-covered tail on top of the
    snapshot. graph_patched is not idempotent, so its patch log doubles. This is
    the bug the snapshot exists to avoid — we compute it only to show the gap."""
    state = json.loads(json.dumps(snapshot_state))  # deep copy
    return replay_state(remaining, state=state)


def main() -> None:
    run = RecordedS13().get_run("three_cities")
    agui_events = list(stream_agui(run["events"], finished=run["finished"]))

    # 1. Full replay from seq 0 — the reference a whole client would hold.
    full_state = replay_state(agui_events)

    # 2. A client folds the first DROP_AFTER events, then the connection drops.
    before_drop = agui_events[:DROP_AFTER]
    remaining = agui_events[DROP_AFTER:]
    partial_state = replay_state(before_drop)

    # 3. Reconnect: the server hands back ONE STATE_SNAPSHOT of the complete
    #    data model. run_data_model is the fold of the run's own stream, so the
    #    snapshot is byte-identical to what a full replay produces.
    complete = run_data_model(run)
    snapshot_event = state_snapshot(complete)

    # The reconnecting client rebuilds from that single frame — it does NOT
    # replay the tail it already (or never) saw.
    rebuilt_state = snapshot_event["state"]

    # 4. Checks.
    equal_to_full = rebuilt_state == full_state
    snapshot_is_one_event = isinstance(snapshot_event, dict) and snapshot_event["type"] == "STATE_SNAPSHOT"
    # Same results and same-length patch log — no duplicated actions.
    no_dup_patches = len(rebuilt_state["patches"]) == len(full_state["patches"])
    same_result_nodes = set(rebuilt_state["results"]) == set(full_state["results"])

    # For contrast: a naive client that replays the tail on top of the snapshot
    # double-counts the graph patches. The snapshot path avoids exactly this.
    naive = naive_replay_after_snapshot(complete, remaining)
    naive_doubles_patches = len(naive["patches"]) > len(full_state["patches"])

    ok = (
        equal_to_full
        and snapshot_is_one_event
        and no_dup_patches
        and same_result_nodes
        and partial_state != full_state  # the drop really was mid-run
        and naive_doubles_patches        # the bug the snapshot prevents is real
    )

    proof = {
        "run_id": run["run_id"],
        "drop_after": DROP_AFTER,
        "total_agui_events": len(agui_events),
        "events_before_drop": before_drop,
        "partial_state_before_drop": partial_state,
        "state_snapshot": snapshot_event,
        "full_replay_state": full_state,
        "rebuilt_from_snapshot_state": rebuilt_state,
        "checks": {
            "rebuilt_equals_full_replay": equal_to_full,
            "snapshot_is_single_event": snapshot_is_one_event,
            "no_duplicated_patches": no_dup_patches,
            "same_result_nodes": same_result_nodes,
            "drop_was_mid_run": partial_state != full_state,
            "naive_tail_replay_doubles_patches": naive_doubles_patches,
        },
        "pass": ok,
    }
    OUT.write_text(json.dumps(proof, indent=2))

    print("\n=== AG-UI STATE_SNAPSHOT reconnect proof ===\n")
    print(f"run                     : {run['run_id']}")
    print(f"total AG-UI events      : {len(agui_events)}")
    print(f"connection drops after  : {DROP_AFTER} events")
    print(f"partial state @ drop     : {len(partial_state['results'])} results, "
          f"{len(partial_state['patches'])} patches")
    print(f"STATE_SNAPSHOT carries   : {len(rebuilt_state['results'])} results, "
          f"{len(rebuilt_state['patches'])} patches  (one frame)")
    print(f"full-replay state        : {len(full_state['results'])} results, "
          f"{len(full_state['patches'])} patches")
    print()
    for name, val in proof["checks"].items():
        print(f"  {'ok ' if val else 'FAIL'} {name} = {val}")
    print(f"\nsnapshot event type      : {snapshot_event['type']}")
    print(f"result nodes rebuilt     : {sorted(rebuilt_state['results'])}")
    print(f"\nwrote {OUT}")
    print("\n" + ("PASS — reconnect rebuilds the complete data model in one frame, "
                  "identical to a full replay, no duplicated actions."
                  if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
