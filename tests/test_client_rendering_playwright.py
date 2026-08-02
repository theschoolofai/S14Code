"""What the render client actually does in a browser.

Every other client test in this repository reads the source and asserts that a
dangerous construct is absent. That proves the code does not *contain* a way to
execute a value. It does not prove the widgets draw the right thing, and it
cannot prove that a hostile string stays inert once a real DOM gets hold of it.

These tests load the client into Chromium, hand the render engine a surface, and
read the resulting DOM. The injection cases matter most: the validator already
refuses markup server-side, so the client is the second wall. A second wall is
only worth having if someone checks it is there.
"""
from __future__ import annotations

from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_api.sync_playwright

CLIENT = Path(__file__).resolve().parents[1] / "s13code" / "ui" / "client" / "app.html"

GAUGE_SURFACE = {
    "root": "root",
    "components": [
        {"id": "root", "type": "Column", "children": ["g0"]},
        {"id": "g0", "type": "GaugeCluster", "title": "Machine",
         "gauges": {"$bind": "/gauges"}},
    ],
    "dataModel": {"gauges": [
        {"label": "CoreTemp", "value": 96, "min": -40, "max": 215, "unit": "degC"},
        {"label": "FanSpeed", "value": 2400, "min": 0, "max": 8000, "unit": "rpm"},
    ]},
}


@pytest.fixture(scope="module")
def browser():
    # `uv sync --dev` installs the playwright *package*; the browser binary is a
    # separate download (`uv run playwright install chromium`). CI does not run
    # it, so without this the import succeeds and every test in the file errors
    # on launch. A missing browser is a missing tool, not a failing client — so
    # it skips, the same way the rest of the suite treats an absent dependency.
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except playwright_api.Error as error:
            pytest.skip(f"chromium is not installed: {error}")
        yield browser
        browser.close()


@pytest.fixture()
def page(browser):
    page = browser.new_page()
    page.goto(CLIENT.as_uri(), wait_until="domcontentloaded")
    yield page
    page.close()


def render(page, surface: dict) -> None:
    page.evaluate("s => render(s)", surface)


# --------------------------------------------------------------------------- #
# GaugeCluster draws what it was bound to
# --------------------------------------------------------------------------- #

def test_a_gauge_is_drawn_for_every_bound_entry(page) -> None:
    render(page, GAUGE_SURFACE)

    assert page.locator("#mount svg").count() == 2


def test_a_gauge_shows_the_value_and_unit_from_the_data_model(page) -> None:
    render(page, GAUGE_SURFACE)

    texts = page.locator("#mount svg text").all_text_contents()

    assert "96" in texts
    assert "degC" in texts
    assert "2400" in texts
    assert "rpm" in texts


def test_a_gauge_labels_itself_with_the_signal_name(page) -> None:
    render(page, GAUGE_SURFACE)

    assert page.get_by_text("CoreTemp").count() == 1


def test_the_sweep_is_computed_from_the_bounds_the_data_gave_the_signal(page) -> None:
    """The same value reads differently on two scales, which is the entire
    reason the bounds may not come from the model."""
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [
            {"label": "wide", "value": 96, "min": 0, "max": 1000, "unit": "x"},
            {"label": "narrow", "value": 96, "min": 0, "max": 100, "unit": "x"},
        ]},
    }
    render(page, surface)

    # Each gauge draws a track then a value arc; the value arc is the second path.
    arcs = page.locator("#mount svg path").all()
    wide_len = page.evaluate("el => el.getTotalLength()", arcs[1].element_handle())
    narrow_len = page.evaluate("el => el.getTotalLength()", arcs[3].element_handle())

    assert narrow_len > wide_len * 5


def test_a_signal_near_its_limit_is_drawn_in_the_alarm_colour(page) -> None:
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [{"label": "CoreTemp", "value": 210, "min": -40,
                                  "max": 215, "unit": "degC"}]},
    }
    render(page, surface)

    value_arc = page.locator("#mount svg path").nth(1)

    assert value_arc.get_attribute("stroke") == "var(--red)"


def test_the_ring_does_not_bulge_when_the_value_passes_half_its_range(page) -> None:
    """The track is a half circle (180deg total), never a full one. The SVG
    large-arc-flag only matters past 180deg of sweep, which this arc can never
    reach — so it must always take the short way round.

    Getting this wrong is invisible below 50% of a gauge's range and glaring
    above it: the flag flips, the renderer draws the *other* arc between the
    same two points, and the fill bulges out past the track into a shape that
    looks like a second, misaligned ring instead of a clean progress arc.
    """
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [
            {"label": "justBelow", "value": 49, "min": 0, "max": 100, "unit": "x"},
            {"label": "justAbove", "value": 51, "min": 0, "max": 100, "unit": "x"},
        ]},
    }
    render(page, surface)

    arcs = page.locator("#mount svg path").all()
    below_len = page.evaluate("el => el.getTotalLength()", arcs[1].element_handle())
    above_len = page.evaluate("el => el.getTotalLength()", arcs[3].element_handle())

    # Two percentage points apart: the fill arc should barely move, not triple.
    assert above_len < below_len * 1.3, (
        f"fill arc jumped from {below_len:.1f} to {above_len:.1f} crossing 50%"
    )


def test_a_low_value_alarms_when_the_gauge_is_marked_low_is_bad(page) -> None:
    """Not every signal is dangerous at its top: a draining reservoir or a
    collapsing cache hit rate is dangerous near its *minimum*. Colouring every
    gauge as if danger only lives at the top end makes a fault the source has
    already reported look green on the dashboard — which is exactly the kind of
    lie this project holds an interface should never be able to tell."""
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [
            {"label": "LinePressure", "value": 105, "min": 100, "max": 350,
             "unit": "kPa", "invert": True},
        ]},
    }
    render(page, surface)

    value_arc = page.locator("#mount svg path").nth(1)

    assert value_arc.get_attribute("stroke") == "var(--red)"


def test_the_same_low_value_is_not_alarming_without_the_invert_flag(page) -> None:
    """The flag has to be what changes the colour, not the low value by itself —
    otherwise this is just the alarm-at-the-limit test with extra steps."""
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [
            {"label": "SomeSignal", "value": 105, "min": 100, "max": 350, "unit": "x"},
        ]},
    }
    render(page, surface)

    value_arc = page.locator("#mount svg path").nth(1)

    assert value_arc.get_attribute("stroke") == "var(--green)"


def _one_gauge(page, gauge: dict):
    render(page, {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [gauge]},
    })
    return page.locator("#mount svg path").nth(1)


def test_a_nominal_value_far_down_a_wide_scale_is_not_an_alarm(page) -> None:
    """A healthy pump draws ~1.2 A on a channel encodable to 25 A. Judging
    severity by fraction-of-range calls that a failure; the pump is fine. When
    the gauge carries the threshold that actually raises the fault, it agrees
    with the source instead of guessing from the axis."""
    arc = _one_gauge(page, {"label": "PumpCurrentA", "value": 1.2, "min": 0, "max": 25,
                            "unit": "A", "invert": True, "warn": 0.6, "alarm": 0.3})

    assert arc.get_attribute("stroke") == "var(--green)"


def test_the_same_signal_at_its_fault_threshold_is_an_alarm(page) -> None:
    arc = _one_gauge(page, {"label": "PumpCurrentB", "value": 0.0, "min": 0, "max": 25,
                            "unit": "A", "invert": True, "warn": 0.6, "alarm": 0.3})

    assert arc.get_attribute("stroke") == "var(--red)"


def test_a_value_between_the_thresholds_reads_as_a_warning(page) -> None:
    arc = _one_gauge(page, {"label": "PumpCurrentB", "value": 0.5, "min": 0, "max": 25,
                            "unit": "A", "invert": True, "warn": 0.6, "alarm": 0.3})

    assert arc.get_attribute("stroke") == "var(--amber)"


def test_a_high_side_threshold_alarms_at_the_top_instead(page) -> None:
    """A temperature fails hot, so its thresholds run the other way. Same mechanism."""
    arc = _one_gauge(page, {"label": "CoreTemp", "value": 124, "min": -40, "max": 215,
                            "unit": "degC", "warn": 110, "alarm": 118})

    assert arc.get_attribute("stroke") == "var(--red)"


def test_a_gauge_below_its_fault_threshold_stays_calm_even_when_low_on_scale(page) -> None:
    """A tank at 41% is already past the limit its owner treats as critical —
    the gauge has to say so, where fraction-of-range would not."""
    arc = _one_gauge(page, {"label": "TankLevel", "value": 41, "min": 0, "max": 100,
                            "unit": "%", "invert": True, "warn": 60, "alarm": 45})

    assert arc.get_attribute("stroke") == "var(--red)"


def test_a_gauge_with_no_bounds_still_draws_without_inventing_a_scale(page) -> None:
    surface = {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [{"label": "Unknown", "value": 42,
                                  "min": None, "max": None, "unit": None}]},
    }
    render(page, surface)

    assert page.locator("#mount svg").count() == 1
    assert "42" in page.locator("#mount svg text").all_text_contents()


# --------------------------------------------------------------------------- #
# the client is the second wall: a hostile value stays inert in a real DOM
# --------------------------------------------------------------------------- #

INJECTED = "<img src=x onerror=\"window.__pwned=1\">"


def test_markup_in_a_bound_value_renders_as_literal_text(page) -> None:
    render(page, {
        "root": "root",
        "components": [{"id": "root", "type": "Text", "text": {"$bind": "/summary"}}],
        "dataModel": {"summary": INJECTED},
    })

    assert page.locator("#mount img").count() == 0
    assert INJECTED in page.locator("#mount").inner_text()


def test_an_injected_handler_never_executes(page) -> None:
    render(page, {
        "root": "root",
        "components": [{"id": "root", "type": "Text", "text": {"$bind": "/summary"}}],
        "dataModel": {"summary": INJECTED},
    })
    page.wait_for_timeout(150)

    assert page.evaluate("() => window.__pwned === undefined")


def test_markup_inside_a_gauge_label_stays_text(page) -> None:
    render(page, {
        "root": "root",
        "components": [{"id": "root", "type": "GaugeCluster", "title": "t",
                        "gauges": {"$bind": "/gauges"}}],
        "dataModel": {"gauges": [{"label": INJECTED, "value": 5, "min": 0,
                                  "max": 10, "unit": INJECTED}]},
    })
    page.wait_for_timeout(150)

    assert page.locator("#mount img").count() == 0
    assert page.evaluate("() => window.__pwned === undefined")


def test_a_binding_of_the_wrong_type_does_not_blank_the_whole_surface(page) -> None:
    """The validator checks component shape; nothing checks data model *types*.

    A model that binds a table's rows to an object instead of a list must cost
    that one widget, not the interface. A blank screen is the worst failure mode
    available here: the user is told nothing and cannot tell it went wrong.
    """
    render(page, {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["t", "g", "ok"]},
            {"id": "t", "type": "DataTable", "columns": "code", "rows": {"$bind": "/wrong"}},
            {"id": "g", "type": "GaugeCluster", "title": "gauges",
             "gauges": {"$bind": "/alsoWrong"}},
            {"id": "ok", "type": "Text", "text": {"$bind": "/summary"}},
        ],
        "dataModel": {"wrong": {"dtcs": [{"code": "P0217"}]},
                      "alsoWrong": {"gauges": []},
                      "summary": "the rest of the surface survives"},
    })

    assert "the rest of the surface survives" in page.locator("#mount").inner_text()


def test_a_component_type_the_client_does_not_know_is_skipped_not_drawn(page) -> None:
    render(page, {
        "root": "root",
        "components": [
            {"id": "root", "type": "Column", "children": ["bad", "ok"]},
            {"id": "bad", "type": "RawHtml", "html": INJECTED},
            {"id": "ok", "type": "Text", "text": {"$bind": "/summary"}},
        ],
        "dataModel": {"summary": "the safe part still renders"},
    })

    assert page.locator("#mount img").count() == 0
    assert "skipped RawHtml" in page.locator("#mount").inner_text()
    assert "the safe part still renders" in page.locator("#mount").inner_text()


# --------------------------------------------------------------------------- #
# a tap is the only way the interface changes anything
# --------------------------------------------------------------------------- #

def test_pressing_a_button_starts_the_next_turn_with_its_label(page) -> None:
    page.evaluate("() => { window.__turns = []; window.runTurn = t => window.__turns.push(t); }")
    render(page, {
        "root": "root",
        "components": [{"id": "root", "type": "Button", "label": "Investigate faults",
                        "onPress": {"action": "rerun"}}],
        "dataModel": {},
    })

    page.get_by_role("button", name="Investigate faults").click()

    assert page.evaluate("() => window.__turns") == ["Investigate faults"]


# --------------------------------------------------------------------------- #
# a failed reading must be the most visible one, not the least
# --------------------------------------------------------------------------- #

# A pump current is a low-is-bad signal: the failure is at the bottom of the
# range, and a total failure sits exactly at zero. The severity is carried by
# the arc, and the arc's length is the fraction of range — so the worse the
# fault, the less there is to draw. A pump drawing 0 A of a 25 A scale is the
# single most important thing on the dashboard and, drawn honestly, it is a
# fraction of a degree of sweep.
DEAD_CHANNEL = {
    "root": "root",
    "components": [
        {"id": "root", "type": "Column", "children": ["g0"]},
        {"id": "g0", "type": "GaugeCluster", "title": "Pumps",
         "gauges": {"$bind": "/gauges"}},
    ],
    "dataModel": {"gauges": [
        # dead: reads zero, alarm is 0.3 and low is the failing end
        {"label": "PumpCurrentB", "value": 0.0, "min": 0, "max": 25,
         "unit": "A", "invert": True, "warn": 0.6, "alarm": 0.3},
        # healthy, and also near the bottom of its range — this one is fine
        {"label": "AmbientLight", "value": 1513, "min": 0, "max": 65535,
         "unit": "lx"},
    ]},
}

# Half the ring is pi*r with r=40, so ~125.7 user units of track. Anything under
# a few units is a dot nobody reads as a warning.
VISIBLE = 6.0


def arc_lengths(page) -> list[float]:
    """Drawn length of each gauge's value arc, in SVG user units."""
    return page.evaluate(
        """() => [...document.querySelectorAll('#mount svg')]
                 .map(s => s.querySelectorAll('path')[1].getTotalLength())"""
    )


def test_a_dead_signal_in_alarm_still_draws_a_visible_arc(page) -> None:
    """The bug this pins: severity drawn as length means total failure draws
    nothing. A gauge in alarm has to be legible at a glance whatever it reads."""
    render(page, DEAD_CHANNEL)

    assert arc_lengths(page)[0] >= VISIBLE


def test_a_healthy_low_reading_is_not_inflated_into_looking_like_a_fault(page) -> None:
    """The floor is for severity, not for every small number. A signal sitting
    low in its range with nothing wrong must still read as nearly empty."""
    render(page, DEAD_CHANNEL)

    assert arc_lengths(page)[1] < VISIBLE


def test_the_value_readout_carries_the_severity_too(page) -> None:
    """Length is not the only channel, because length is the thing that fails.
    The number itself is toned, so severity survives a zero-length arc."""
    render(page, DEAD_CHANNEL)

    tones = page.evaluate(
        """() => [...document.querySelectorAll('#mount svg')]
                 .map(s => s.querySelectorAll('text')[0].getAttribute('fill'))"""
    )

    assert tones[0] == "var(--red)"
    assert tones[1] == "var(--ink)"


# --------------------------------------------------------------------------- #
# a surface whose declared root is missing still shows what it does have
# --------------------------------------------------------------------------- #

# Found by running a real model against the shipping prompt: it composed eleven
# valid components, every one of them accepted by the validator, and declared a
# root of "root" without ever emitting a component with that id. The client read
# byId["root"], got undefined, and threw — blanking an interface where nothing
# was actually wrong with the parts. The catalog invariant holds the model to
# known TYPES; it says nothing about the model remembering to emit a container,
# so the client cannot assume one is there.
ROOTLESS = {
    "root": "root",
    "components": [
        {"id": "h", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        {"id": "g", "type": "GaugeCluster", "title": "Nodes", "gauges": {"$bind": "/gauges"}},
    ],
    "dataModel": {"title": "Render farm",
                  "gauges": [{"label": "CoreTemp", "value": 61, "min": 20, "max": 95,
                              "unit": "degC"}]},
}


def test_a_missing_root_does_not_blank_the_whole_surface(page) -> None:
    render(page, ROOTLESS)

    assert page.get_by_text("Render farm").count() == 1
    assert page.locator("#mount svg").count() == 1


def test_a_missing_root_keeps_the_components_in_the_order_given(page) -> None:
    """Order is the only layout information left when the container is gone, so
    it is the one thing worth preserving."""
    render(page, ROOTLESS)

    # DOCUMENT_POSITION_FOLLOWING (4) means the gauge comes after the heading.
    assert page.evaluate(
        """() => {
             const h = [...document.querySelectorAll('#mount *')]
                       .find(e => e.textContent === 'Render farm');
             const svg = document.querySelector('#mount svg');
             return h.compareDocumentPosition(svg) & 4;
           }"""
    )


def test_a_child_of_a_present_container_is_not_also_drawn_at_the_top(page) -> None:
    """Falling back must not double-draw: anything another component claims as a
    child belongs to that component, not to the top level."""
    render(page, {
        "root": "absent",
        "components": [
            {"id": "row", "type": "Row", "children": ["a"]},
            {"id": "a", "type": "Text", "text": {"$bind": "/only"}},
        ],
        "dataModel": {"only": "once"},
    })

    assert page.locator("#mount").inner_text().count("once") == 1


# --------------------------------------------------------------------------- #
# a table whose columns were never named still shows its rows
# --------------------------------------------------------------------------- #

# The other half of what the real model got wrong: it bound rows correctly and
# left columns null. `(c.columns||"").split(",")` then yields one empty column
# name, so every row rendered as a single blank cell — a table with the right
# data in it, drawing nothing. The row keys are right there, and they are data
# the harness owns rather than anything the model authored, so use them.
ROWS_ONLY = {
    "root": "t",
    "components": [{"id": "t", "type": "DataTable", "rows": {"$bind": "/rows"},
                    "columns": None}],
    "dataModel": {"rows": [{"Node": "node-01", "State": "idle"},
                           {"Node": "node-02", "State": "rendering"}]},
}


def test_a_table_with_no_columns_falls_back_to_the_keys_of_its_rows(page) -> None:
    render(page, ROWS_ONLY)

    body = page.locator("#mount").inner_text()

    assert "node-01" in body and "rendering" in body


def test_the_fallback_headers_are_the_row_keys(page) -> None:
    render(page, ROWS_ONLY)

    # textContent, not inner_text: the stylesheet upper-cases headers for display
    # and the question here is what the client put in the cell, not how it looks.
    headers = page.eval_on_selector_all("#mount th", "els => els.map(e => e.textContent)")

    assert headers == ["Node", "State"]


def test_named_columns_still_win_and_still_restrict(page) -> None:
    """The fallback is for the absent case only. When columns ARE named, they
    stay authoritative — a table that quietly widened itself to every key would
    show a column its author chose to leave out."""
    render(page, {
        "root": "t",
        "components": [{"id": "t", "type": "DataTable", "rows": {"$bind": "/rows"},
                        "columns": "Node"}],
        "dataModel": {"rows": [{"Node": "node-01", "Secret": "hidden"}]},
    })

    assert "hidden" not in page.locator("#mount").inner_text()
