"""A rendered gallery of the whole trusted catalog.

Every component type, drawn once with sample data, as a single ordinary surface.
That last part is the point: the gallery is not a bespoke page with hand-written
markup, it is a normal ``{root, components, dataModel}`` that goes through
``validate_surface`` and the client's ordinary ``RENDERERS`` map like any surface
an agent composed. So it proves three things at once:

  * every type in ``COMPONENTS`` has a renderer and actually draws;
  * every type can be expressed in a surface the wall accepts;
  * the catalog and the clients have not drifted apart.

``test_gallery_covers_every_catalog_component`` fails the moment someone adds a
``ComponentSpec`` without a renderer, which is the drift this file exists to
catch.
"""

from __future__ import annotations

from typing import Any

from .catalog import COMPONENTS

# Sample values every binding in the gallery points at. Deliberately plausible
# rather than lorem: a reviewer should be able to read a widget and see what it
# is for.
DATA_MODEL: dict[str, Any] = {
    "title": "The trusted catalog, drawn",
    "subtitle": "Every component the agent may name, rendered by the real client",
    "body": "Structure and data travel apart. Nothing on this page was authored as markup.",
    "notice_ok": "All 27 component types rendered from one validated surface.",
    "notice_warn": "2 of 3 sources loaded; one request timed out.",
    "query": "asyncio best practices",
    "only_peer_reviewed": True,
    "max_sources": 6,
    "model_options": ["gemini-3.6-flash", "gemini-3.1-pro", "ollama/phi4"],
    "model_choice": "gemini-3.6-flash",
    "run_after": "2026-07-27T09:00",
    "modal_open": False,
    "tokens_by_stage": [
        {"stage": "search", "tokens": 120}, {"stage": "fetch", "tokens": 340},
        {"stage": "distill", "tokens": 210}, {"stage": "answer", "tokens": 90},
    ],
    "trend": [3, 5, 4, 8, 7, 11, 9],
    "p95_latency": 142,
    "p95_delta": "−18% vs last run",
    "progress_value": 72,
    "run_events": [
        {"time": "1", "label": "run_started"},
        {"time": "2", "label": "graph_patched · +[search_1, search_2, search_3]"},
        {"time": "3", "label": "task_succeeded · search_1"},
        {"time": "4", "label": "graph_patched · +[distill]"},
    ],
    "source_rows": [
        {"Source": "peps.python.org", "Status": "ok", "Tokens": 120},
        {"Source": "docs.python.org", "Status": "ok", "Tokens": 98},
        {"Source": "realpython.com", "Status": "timeout", "Tokens": 0},
    ],
    "approval_summary": "Create two calendar reminders for mom's birthday",
    "approval_params": {"dates": ["2026-05-01", "2026-05-15"], "title": "Mom's birthday"},
    # --- the Session 14 contribution ---------------------------------------
    "claim_corroborated": "9.19M",
    "sources_corroborated": [
        {"title": "World Population Review", "url": "https://worldpopulationreview.com/cities"},
        {"title": "ONS mid-year estimate", "url": "https://www.ons.gov.uk/populationestimates"},
    ],
    "claim_single": "3.78M",
    "sources_single": [{"title": "Statistik Berlin-Brandenburg", "url": "https://www.statistik-berlin-brandenburg.de"}],
    "claim_disputed": "5.80M",
    "sources_disputed": [{"title": "Metro-area figure (retry)", "url": "https://example.org/metro"}],
    "dissent_disputed": {"value": "3.78M", "source": "city-proper, first attempt"},
    "claim_unsupported": None,
    "sources_none": [],
    "graph_nodes": [
        {"id": "search_1", "label": "search_1 · London", "state": "succeeded"},
        {"id": "search_2", "label": "search_2 · Berlin", "state": "failed"},
        {"id": "search_3", "label": "search_3 · Paris", "state": "succeeded"},
        {"id": "retry", "label": "berlin_retry", "state": "succeeded"},
        {"id": "distill", "label": "distill", "state": "succeeded"},
        {"id": "surface", "label": "surface", "state": "succeeded"},
    ],
    "graph_edges": [
        {"from": "search_2", "to": "retry", "reason": "weak evidence for Berlin; an outcome must earn the next node"},
        {"from": "search_1", "to": "distill", "reason": ""},
        {"from": "search_3", "to": "distill", "reason": ""},
        {"from": "retry", "to": "distill", "reason": "corrected evidence"},
        {"from": "distill", "to": "surface", "reason": ""},
    ],
    "graph_highlight": "retry",
    # --- the Arbiter contribution -------------------------------------------
    "radar_axes": ["Throughput", "Durability", "Ops simplicity", "Latency"],
    "radar_series": [
        {"name": "Kafka", "values": [9, 9, 4, 6]},
        {"name": "RabbitMQ", "values": [6, 7, 7, 7]},
        {"name": "NATS", "values": [8, 5, 9, 9]},
    ],
    "whatif_criteria": [
        {"key": "latency", "label": "Reduce p99 latency", "weight": 50},
        {"key": "cost", "label": "Cut cloud spend", "weight": 30},
        {"key": "oncall", "label": "Improve on-call load", "weight": 20},
    ],
    "whatif_options": [
        {"name": "Reduce p99 latency", "scores": {"latency": 9, "cost": 3, "oncall": 4}},
        {"name": "Cut cloud spend", "scores": {"latency": 2, "cost": 9, "oncall": 3}},
        {"name": "Improve on-call load", "scores": {"latency": 4, "cost": 2, "oncall": 9}},
    ],
}


def _section(title: str, child_ids: list[str]) -> dict:
    return {"id": f"sec_{title.lower().replace(' ', '_').replace('&', 'and')}",
            "type": "Card", "title": title, "children": child_ids}


def build_gallery() -> dict:
    """One surface containing every catalog type, ready for validate_surface."""
    components: list[dict] = []
    sections: list[dict] = []

    def add(component: dict) -> str:
        components.append(component)
        return component["id"]

    # --- Layout ------------------------------------------------------------
    add({"id": "lay_a", "type": "Text", "variant": "caption", "text": {"$bind": "/body"}})
    add({"id": "lay_b", "type": "Text", "variant": "caption", "text": {"$bind": "/subtitle"}})
    add({"id": "g_row", "type": "Row", "align": "center", "justify": "spaceBetween",
         "children": ["lay_a", "lay_b"]})
    add({"id": "lay_c", "type": "Text", "variant": "caption", "text": {"$bind": "/body"}})
    add({"id": "g_col", "type": "Column", "children": ["lay_c"]})
    add({"id": "lay_d", "type": "Text", "variant": "caption", "text": {"$bind": "/subtitle"}})
    add({"id": "g_list", "type": "List", "children": ["lay_d"]})
    add({"id": "lay_e", "type": "Text", "variant": "caption", "text": {"$bind": "/body"}})
    add({"id": "g_card", "type": "Card", "title": "Card — a titled box", "children": ["lay_e"]})
    add({"id": "g_divider", "type": "Divider"})
    sections.append(_section("Layout", ["g_row", "g_col", "g_list", "g_card", "g_divider"]))

    # --- Content -----------------------------------------------------------
    add({"id": "g_heading", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}})
    add({"id": "g_body", "type": "Text", "variant": "body", "text": {"$bind": "/body"}})
    # No src: an Image with an unvetted scheme renders nothing but its alt text,
    # which is the scheme gate doing its job rather than a broken example.
    add({"id": "g_image", "type": "Image", "alt": "placeholder — no src, so nothing is fetched"})
    add({"id": "g_notice", "type": "Notice", "text": {"$bind": "/notice_warn"}, "tone": "warn"})
    sections.append(_section("Content", ["g_heading", "g_body", "g_image", "g_notice"]))

    # --- Input -------------------------------------------------------------
    add({"id": "g_textfield", "type": "TextField", "label": "Query",
         "value": {"$bind": "/query"}, "placeholder": "search…"})
    add({"id": "g_checkbox", "type": "CheckBox", "label": "Only peer-reviewed sources",
         "checked": {"$bind": "/only_peer_reviewed"}})
    add({"id": "g_slider", "type": "Slider", "label": "Max sources",
         "value": {"$bind": "/max_sources"}, "min": 1, "max": 10})
    add({"id": "g_choice", "type": "InputChoice", "label": "Model",
         "options": {"$bind": "/model_options"}, "value": {"$bind": "/model_choice"}})
    add({"id": "g_datetime", "type": "DateTime", "label": "Run after", "value": {"$bind": "/run_after"}})
    sections.append(_section("Input", ["g_textfield", "g_checkbox", "g_slider", "g_choice", "g_datetime"]))

    # --- Navigation --------------------------------------------------------
    add({"id": "tab_a", "type": "Text", "variant": "body", "text": {"$bind": "/body"}})
    add({"id": "tab_b", "type": "Text", "variant": "body", "text": {"$bind": "/subtitle"}})
    add({"id": "g_tabs", "type": "Tabs", "labels": "Overview,Sources", "children": ["tab_a", "tab_b"]})
    add({"id": "modal_body", "type": "Text", "variant": "body", "text": {"$bind": "/notice_ok"}})
    add({"id": "g_modal", "type": "Modal", "title": "Confirm deploy",
         "children": ["modal_body"], "open": {"$bind": "/modal_open"}})
    sections.append(_section("Navigation", ["g_tabs", "g_modal"]))

    # --- Charts and data ---------------------------------------------------
    add({"id": "g_bar", "type": "BarChart", "title": "Tokens by stage",
         "data": {"$bind": "/tokens_by_stage"}, "xKey": "stage", "yKey": "tokens"})
    add({"id": "g_spark", "type": "Sparkline", "data": {"$bind": "/trend"}, "tone": "good"})
    add({"id": "g_stat", "type": "StatTile", "label": "p95 latency",
         "value": {"$bind": "/p95_latency"}, "unit": " ms",
         "delta": {"$bind": "/p95_delta"}, "tone": "good"})
    add({"id": "g_progress", "type": "ProgressBar", "value": {"$bind": "/progress_value"},
         "max": 100, "tone": "good"})
    add({"id": "g_timeline", "type": "Timeline", "title": "Run trace",
         "events": {"$bind": "/run_events"}})
    add({"id": "g_table", "type": "DataTable", "columns": "Source,Status,Tokens",
         "rows": {"$bind": "/source_rows"}, "sortable": True, "filterKey": "Source"})
    # BarChart's SVG scales to its container (viewBox 300x150, width 100%), so a
    # full-width card would render it 400px tall with oversized labels. Pairing
    # the charts in Rows keeps each at a sane width — a composition fix in the
    # gallery rather than a change to rendering that is correct elsewhere.
    add({"id": "g_chart_row", "type": "Row", "align": "stretch", "justify": "spaceBetween",
         "children": ["g_bar", "g_spark"]})
    add({"id": "g_kpi_row", "type": "Row", "align": "stretch", "justify": "spaceBetween",
         "children": ["g_stat", "g_progress"]})
    sections.append(_section("Charts and data",
                             ["g_chart_row", "g_kpi_row", "g_timeline", "g_table"]))

    # --- Action ------------------------------------------------------------
    add({"id": "g_button", "type": "Button", "label": "Re-run",
         "onPress": {"action": "rerun"}})
    add({"id": "g_approval", "type": "ApprovalCard",
         "summary": {"$bind": "/approval_summary"}, "params": {"$bind": "/approval_params"},
         "confirm": {"action": "approve", "args": {"$bind": "/approval_params"}},
         "reject": {"action": "reject"}})
    sections.append(_section("Action", ["g_button", "g_approval"]))

    # --- Provenance: the Session 14 contribution ---------------------------
    # One tile per confidence level, so the whole ordinal scale is visible at
    # once — including 'unsupported', which renders degraded rather than
    # vanishing. That honesty is the component's reason to exist.
    add({"id": "g_ev_corroborated", "type": "EvidenceTile", "label": "London",
         "value": {"$bind": "/claim_corroborated"}, "confidence": "corroborated",
         "sources": {"$bind": "/sources_corroborated"}, "fallback": "StatTile"})
    add({"id": "g_ev_single", "type": "EvidenceTile", "label": "Berlin (city proper)",
         "value": {"$bind": "/claim_single"}, "confidence": "single-source",
         "sources": {"$bind": "/sources_single"}, "fallback": "StatTile"})
    add({"id": "g_ev_disputed", "type": "EvidenceTile", "label": "Berlin (after retry)",
         "value": {"$bind": "/claim_disputed"}, "confidence": "disputed",
         "sources": {"$bind": "/sources_disputed"}, "dissent": {"$bind": "/dissent_disputed"},
         "fallback": "StatTile"})
    add({"id": "g_ev_unsupported", "type": "EvidenceTile", "label": "Licence risk",
         "value": {"$bind": "/claim_unsupported"}, "confidence": "unsupported",
         "sources": {"$bind": "/sources_none"}, "fallback": "StatTile"})
    add({"id": "g_ev_row", "type": "Row", "align": "stretch", "justify": "spaceBetween",
         "children": ["g_ev_corroborated", "g_ev_single", "g_ev_disputed", "g_ev_unsupported"]})

    # RunGraph: the shape of the run that produced all of this.
    add({"id": "g_rungraph", "type": "RunGraph", "title": "The run that produced this",
         "nodes": {"$bind": "/graph_nodes"}, "edges": {"$bind": "/graph_edges"},
         "highlight": {"$bind": "/graph_highlight"}, "fallback": "Timeline"})
    sections.append(_section("Provenance (Session 14)",
                             ["g_ev_row", "g_rungraph"]))

    # Synthesis: the Arbiter contribution. Every component above renders a fact;
    # these two render a JUDGEMENT across several facts at once, and one of them
    # lets the reader question that judgement instead of just reading it.
    add({"id": "g_radar", "type": "TradeoffRadar", "title": "Kafka vs RabbitMQ vs NATS",
         "axes": {"$bind": "/radar_axes"}, "series": {"$bind": "/radar_series"},
         "fallback": "DataTable"})
    add({"id": "g_whatif", "type": "WhatIfSlider", "title": "Which initiative first?",
         "criteria": {"$bind": "/whatif_criteria"}, "options": {"$bind": "/whatif_options"},
         "fallback": "DataTable"})
    sections.append(_section("Synthesis (Arbiter)", ["g_radar", "g_whatif"]))

    components.extend(sections)
    components.insert(0, {"id": "gallery_title", "type": "Text", "variant": "heading",
                          "text": {"$bind": "/title"}})
    components.insert(0, {"id": "root", "type": "Column",
                          "children": ["gallery_title"] + [s["id"] for s in sections]})
    return {"root": "root", "components": components, "dataModel": DATA_MODEL}


def gallery_coverage() -> tuple[set[str], set[str]]:
    """(types the gallery draws, types the catalog declares) — for the drift test."""
    drawn = {c["type"] for c in build_gallery()["components"]}
    return drawn, set(COMPONENTS)
