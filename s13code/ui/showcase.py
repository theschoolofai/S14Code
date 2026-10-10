"""The showcase: an agent builds a complex live dashboard as declarative data.

This is the ceiling of Session 14. Given the outcome of a real S13 corpus run
(five papers indexed), the agent composes a full analytics dashboard from the
catalog: a KPI row of stat tiles, a bar chart, a sortable/filterable data
table, a sparkline, a progress bar, tabbed drill-downs, and a timeline of the
graph's own execution. Dozens of components, one data model, and not one line
of executable code. The same validator that guards the floor guards this.

The point it proves: schema-constrained UI is not a toy. An agent can build
something as rich as a hand-written dashboard, and every node is verifiable.
"""

from __future__ import annotations

from typing import Any


def build_corpus_dashboard(run: dict) -> dict:
    """Aggregate a five-paper S13 corpus run into a rich dashboard surface."""
    papers = [
        n["result"]
        for n in run["nodes"].values()
        if n["skill"] == "indexer" and n["state"] == "succeeded"
    ]
    papers.sort(key=lambda p: p["chunks"], reverse=True)

    total_chunks = sum(p["chunks"] for p in papers)
    total_words = sum(p["words"] for p in papers)
    below_floor = sum(p["below_floor"] for p in papers)

    data: dict[str, Any] = {
        "kpi_papers": len(papers),
        "kpi_chunks": total_chunks,
        "kpi_words": total_words,
        "kpi_floor": below_floor,
        "d_papers": "discovered at runtime",
        "d_chunks": f"across {len(papers)} papers",
        "d_words": f"~{total_words // len(papers)} per paper",
        "d_floor": f"{below_floor} kept without a model call",
        "chunks_by_paper": [{"label": p["short"], "value": p["chunks"]} for p in papers],
        "chunk_spark": [p["chunks"] for p in sorted(papers, key=lambda p: p["year"])],
        "index_progress": total_chunks,
        "table_rows": [
            {"Paper": p["paper"], "Chunks": p["chunks"], "Words": p["words"], "Year": p["year"]}
            for p in papers
        ],
        "timeline": [
            {"seq": e["sequence"], "kind": e["kind"], "node": e.get("node_id") or "—"}
            for e in run["events"]
        ],
    }
    # Per-paper drill-down text lives in the data model, bound by Text nodes.
    for i, p in enumerate(papers):
        data[f"paper_{i}_title"] = p["paper"]
        data[f"paper_{i}_detail"] = f"{p['chunks']} semantic chunks over {p['words']} words · indexed {p['year']}"

    C: list[dict] = []

    def add(comp: dict) -> str:
        C.append(comp)
        return comp["id"]

    # Header
    add({"id": "title", "type": "Text", "variant": "heading", "text": {"$bind": "/kpi_title"}})
    data["kpi_title"] = "Research corpus — 5 papers, live from the S13 index"

    # KPI row of stat tiles (A2UI Basic has no Grid; a Row of StatTiles is the
    # real layout for a KPI band).
    kpi_ids = [
        add({"id": "k_papers", "type": "StatTile", "label": "Papers", "value": {"$bind": "/kpi_papers"}, "unit": "", "delta": {"$bind": "/d_papers"}, "tone": "good"}),
        add({"id": "k_chunks", "type": "StatTile", "label": "Semantic chunks", "value": {"$bind": "/kpi_chunks"}, "unit": "", "delta": {"$bind": "/d_chunks"}, "tone": "neutral"}),
        add({"id": "k_words", "type": "StatTile", "label": "Words indexed", "value": {"$bind": "/kpi_words"}, "unit": "", "delta": {"$bind": "/d_words"}, "tone": "neutral"}),
        add({"id": "k_floor", "type": "StatTile", "label": "Below semantic floor", "value": {"$bind": "/kpi_floor"}, "unit": "", "delta": {"$bind": "/d_floor"}, "tone": "warn"}),
    ]
    add({"id": "kpi_row", "type": "Row", "align": "stretch", "justify": "spaceBetween", "children": kpi_ids})

    # Charts row
    add({"id": "bars", "type": "BarChart", "title": "Chunks per paper", "data": {"$bind": "/chunks_by_paper"}, "xKey": "label", "yKey": "value"})
    add({"id": "dual", "type": "DualAxisChart", "title": "Chunks vs Words Index", "data": {"$bind": "/table_rows"}, "xKey": "Paper", "barKey": "Chunks", "lineKey": "Words", "barLabel": "Chunks", "lineLabel": "Words"})
    add({"id": "spark", "type": "Sparkline", "data": {"$bind": "/chunk_spark"}, "tone": "good"})
    add({"id": "prog", "type": "ProgressBar", "value": {"$bind": "/index_progress"}, "max": 20, "tone": "good"})
    add({"id": "charts_row", "type": "Row", "align": "stretch", "justify": "spaceBetween", "children": ["bars", "dual", "spark", "prog"]})

    # Sortable / filterable data table
    add({"id": "table", "type": "DataTable", "columns": "Paper,Chunks,Words,Year", "rows": {"$bind": "/table_rows"}, "sortable": True, "filterKey": "Paper"})

    # Tabbed drill-downs (A2UI Basic Tabs takes its panels directly as children;
    # there is no separate Tab type — the labels string names each tab).
    tab_ids = []
    tab_labels = []
    for i, _p in enumerate(papers):
        tab_ids.append(add({"id": f"detail_{i}", "type": "Text", "variant": "body", "text": {"$bind": f"/paper_{i}_detail"}}))
        tab_labels.append(f"paper {i + 1}")
    add({"id": "tabs", "type": "Tabs", "labels": ",".join(tab_labels), "children": tab_ids})

    # Timeline of the graph's own execution
    add({"id": "tl", "type": "Timeline", "title": "How the graph earned this", "events": {"$bind": "/timeline"}})

    add({"id": "div", "type": "Divider"})

    root_children = ["title", "kpi_row", "charts_row", "table", "tabs", "div", "tl"]
    C.insert(0, {"id": "root", "type": "Column", "children": root_children})
    return {"root": "root", "components": C, "dataModel": data}
