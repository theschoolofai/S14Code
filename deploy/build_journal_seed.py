"""Prune a local graph journal down to the runs this pull request cites.

The public deployment carries no provider credential, so the only thing it can
show is work that already happened — which it reads out of a journal shipped
beside it. That journal is this file's output.

Pruning rather than copying is deliberate. A development journal accumulates
every run ever made, and a deployment should carry the evidence it actually
cites and nothing else: smaller, reviewable, and free of anything incidental.

    uv run python deploy/build_journal_seed.py          # -> deploy/journal_seed.sqlite
    uv run python deploy/build_journal_seed.py --list   # what is in the seed today

The seed is committed (against the repo's own *.sqlite ignore) because without
it `modal deploy` produces a live URL with nothing to render.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

SOURCE = Path(os.getenv("S13_DATA_DIR", str(Path.home() / ".s13code"))) / "graph.sqlite"
TARGET = Path(__file__).parent / "journal_seed.sqlite"

# Every run named in the pull request, and nothing else.
CITED: dict[str, str] = {
    "run-95ac36ad7ec1": "turn 1 · the pipeline board (Kanban, StatTile, Timeline)",
    "run-46b669967469": "turn 2 · tapped a company card (BarChart, ProgressBar)",
    "run-947ba9e7badf": "turn 3 · tapped the interview round (DataTable)",
    "run-fa666b624248": "the attack the validator refused (3 unregistered actions)",
    "run-f1f8599bc1d8": "adversarial · direct instruction",
    "run-173a937c9b62": "adversarial · a lie about the catalog",
    "run-ff9afe1fc1bb": "adversarial · markup smuggled as data",
    "run-6b14550dcca6": "Part 1 · Gemini picks Kanban unprompted",
    "run-59e7457c1705": "the same board composed by gemini-3-flash-preview",
    "run-bb066c0e6cdd": "after the /run_events fix — no plumbing drawn",
    "run-b282f6e74ce2": "same code, another domain: an IIT JEE roadmap",
}

TABLES = ("runs", "nodes", "edges", "events", "patches")


def build() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"no journal at {SOURCE} — run the app locally first")
    if TARGET.exists():
        TARGET.unlink()

    source = sqlite3.connect(SOURCE)
    target = sqlite3.connect(TARGET)
    for name, sql in source.execute(
            "select name, sql from sqlite_master where type='table' and sql is not null"):
        if name.startswith("sqlite_"):      # internal bookkeeping, rebuilt on demand
            continue
        target.execute(sql)

    ids = sorted(CITED)
    marks = ",".join("?" * len(ids))
    missing = [rid for rid in ids
               if not source.execute("select 1 from runs where id=?", (rid,)).fetchone()]
    if missing:
        print("WARNING: not in the local journal, so not in the seed:")
        for rid in missing:
            print(f"  {rid}  {CITED[rid]}")

    for table in TABLES:
        column = "id" if table == "runs" else "run_id"
        rows = list(source.execute(f"select * from {table} where {column} in ({marks})", ids))
        if rows:
            target.executemany(
                f"insert into {table} values ({','.join('?' * len(rows[0]))})", rows)
        print(f"  {table}: {len(rows)} rows")

    target.commit()
    target.close()
    source.close()
    print(f"\nwrote {TARGET} ({TARGET.stat().st_size} bytes, {len(ids) - len(missing)} runs)")
    return 1 if missing else 0


def show() -> int:
    if not TARGET.exists():
        raise SystemExit(f"no seed at {TARGET}")
    db = sqlite3.connect(TARGET)
    present = {row[0] for row in db.execute("select id from runs")}
    for rid, what in CITED.items():
        print(f"  {'✓' if rid in present else '✗'} {rid}  {what}")
    db.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show what the seed contains")
    raise SystemExit(show() if parser.parse_args().list else build())
