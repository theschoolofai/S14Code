"""The GaugeCluster renderer, checked at the source level.

A component is only safely in the catalog once every client can draw it without
executing any part of it. The repository already asserts the no-innerHTML
contract for the run client; the same property has to hold for the application
shell and for the new component in both.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CLIENTS = Path(__file__).resolve().parents[1] / "s13code" / "ui" / "client"
CLIENT_FILES = ("index.html", "app.html")


@pytest.mark.parametrize("filename", CLIENT_FILES)
def test_every_client_can_draw_a_gauge_cluster(filename: str) -> None:
    html = (CLIENTS / filename).read_text()

    assert "GaugeCluster:" in html, f"{filename} has no GaugeCluster renderer"


@pytest.mark.parametrize("filename", CLIENT_FILES)
def test_no_client_ever_assigns_innerhtml(filename: str) -> None:
    """Not for a bound value, not for a status line, not anywhere.

    A single innerHTML assignment is a path a future edit can route data into.
    Removing it entirely makes the property checkable rather than argued.
    """
    html = (CLIENTS / filename).read_text()

    assert not re.search(r"innerHTML\s*=", html)


@pytest.mark.parametrize("filename", CLIENT_FILES)
def test_the_gauge_renderer_reads_its_values_through_the_binding(filename: str) -> None:
    """A gauge draws the data model, not a value the model wrote inline."""
    html = (CLIENTS / filename).read_text()
    renderer = html.split("GaugeCluster:", 1)[1].split("},\n", 1)[0]

    assert "resolve(c.gauges" in renderer


@pytest.mark.parametrize("filename", CLIENT_FILES)
def test_the_gauge_is_drawn_as_svg_built_from_nodes(filename: str) -> None:
    html = (CLIENTS / filename).read_text()

    # The arc is geometry computed from a number, not markup handed to a parser.
    assert "createElementNS" in html
    assert 'setAttribute("stroke-width","9")' in html


@pytest.mark.parametrize("filename", CLIENT_FILES)
def test_no_client_evaluates_a_string(filename: str) -> None:
    html = (CLIENTS / filename).read_text()

    assert not re.search(r"\beval\s*\(", html)
    assert not re.search(r"new\s+Function\s*\(", html)
    assert not re.search(r"document\.write\s*\(", html)


@pytest.mark.parametrize("filename", CLIENT_FILES)
def test_every_client_floors_the_sweep_of_a_gauge_in_alarm(filename: str) -> None:
    """Three clients draw this component, and a severity that only one of them
    shows is a severity the other two hide. The browser test proves the
    behaviour in `app.html`; this proves nobody shipped the fix to one file.
    """
    html = (CLIENTS / filename).read_text()

    assert "ALARM_MIN_SWEEP" in html
    assert "Math.max(frac,ALARM_MIN_SWEEP)" in html


@pytest.mark.parametrize("filename", CLIENT_FILES)
def test_every_client_tones_the_value_readout_as_well_as_the_arc(filename: str) -> None:
    """The arc can vanish; the number cannot."""
    html = (CLIENTS / filename).read_text()

    assert 'num.setAttribute("fill",severe?tone:"var(--ink)")' in html
