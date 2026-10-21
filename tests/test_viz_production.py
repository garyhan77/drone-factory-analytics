"""The Production page: its findings, its charts, and the page itself."""
import os
from datetime import date, timedelta

import pandas as pd
import pytest
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

from factory.build import build
from factory.db import ROOT
from factory.viz import charts, findings, theme

PALETTES = pytest.mark.parametrize("pal", [theme.LIGHT, theme.DARK], ids=["light", "dark"])


# ---------------------------------------------------------------------------- findings, by hand

def weekly(n, started=10, finished=8):
    return pd.DataFrame({"week_start": [date(2026, 1, 5) + timedelta(weeks=i) for i in range(n)],
                         "units_started": [started] * n, "units_completed": [finished] * n})


SUMMARY = pd.DataFrame({"station_name": ["A", "B", "C", "D", "E"], "avg_wait_hours": [float("nan"), 20.0, 100.0, 4.0, 3.0]})


def test_the_last_partial_week_is_dropped():
    df = weekly(5)
    assert len(findings.drop_partial_last_week(df)) == 4
    assert findings.drop_partial_last_week(df)["week_start"].max() == date(2026, 1, 26)
    assert findings.drop_partial_last_week(df.iloc[0:0]).empty


def test_the_finding_names_the_bottleneck_and_compares_it_with_the_rest():
    wip = pd.DataFrame({"stage": ["Waiting for C", "In B"], "drones": [82, 3]})
    first, second = findings.production_finding(SUMMARY, weekly(11), wip)
    # C waits 100 h; the next longest is B at 20 h; the rest are at most 4 h.
    assert first == ("**C is the bottleneck.** Drones wait 100 hours on average before reaching it, against 20 hours "
                     "before B and 4 hours or less at the other stations.")
    # 11 weeks drop the partial one, leaving 10; the last 8 full weeks started 8 x 10 = 80 and finished 8 x 8 = 64.
    assert second == "Over the last 8 full weeks the line started 80 drones and finished 64, and 82 drones are now queued for C."


def test_the_finding_still_reads_when_nobody_is_queued_or_data_is_thin():
    no_queue = pd.DataFrame({"stage": ["In B"], "drones": [3]})
    assert findings.production_finding(SUMMARY, weekly(11), no_queue)[1].endswith("finished 64.")
    fewer = findings.production_finding(weekly(2).assign(station_name="x", avg_wait_hours=1.0), weekly(11), no_queue)
    assert fewer == ["There is not enough station data to identify a bottleneck."]
    short = findings.production_finding(SUMMARY, weekly(4), no_queue)   # 3 full weeks only
    assert "last 3 full weeks the line started 30 drones and finished 24" in short[1]


# ---------------------------------------------------------------------------- charts

@PALETTES
def test_weekly_output_is_two_lines_with_a_legend_and_one_axis(pal):
    fig = charts.weekly_output_chart(weekly(6), pal)
    started, finished = fig.data
    assert (started.name, finished.name) == ("Started", "Finished")
    assert (started.line.color, finished.line.color) == (pal.accent, pal.accent_2)
    assert started.line.width == finished.line.width == 2
    assert fig.layout.showlegend is True
    assert "yaxis2" not in fig.layout and fig.layout.yaxis.rangemode == "tozero"      # no second scale
    assert all(t.yaxis in (None, "y") for t in fig.data)                             # and no trace uses one
    assert list(started.y) == [10] * 6 and list(finished.y) == [8] * 6


WAITS = pd.DataFrame([(date(2026, 1, 5) + timedelta(weeks=w), seq, name, 10.0 * seq + w)
                      for seq, name in ((2, "Wing"), (3, "Motor"), (4, "Avionics"), (5, "Test")) for w in range(5)],
                     columns=["week_start", "station_seq", "station_name", "avg_wait_hours"])


@PALETTES
def test_wait_panels_highlight_one_station_and_grey_the_rest(pal):
    fig = charts.wait_small_multiples(WAITS, pal, highlight="Avionics")
    assert [t.name for t in fig.data] == ["Wing", "Motor", "Avionics", "Test"]             # in line order
    colours = {t.name: t.line.color for t in fig.data}
    assert colours["Avionics"] == pal.accent
    assert {c for n, c in colours.items() if n != "Avionics"} == {pal.context}
    assert fig.layout.showlegend is False                                                 # each panel is titled instead
    assert [a.text for a in fig.layout.annotations] == ["Wing", "Motor", "Avionics", "Test"]
    for axis in ("yaxis2", "yaxis3", "yaxis4"):
        assert fig.layout[axis].matches == "y"                                            # one shared scale
    assert all(t.line.width == 2 for t in fig.data)


@PALETTES
def test_stage_bars_are_thin_ordered_and_only_the_highlight_is_coloured(pal):
    labels, values = ["Waiting for X", "In Y", "In Z"], [82, 23, 3]
    fig = charts.horizontal_bar(labels, values, pal, highlight="Waiting for X")
    bar = fig.data[0]
    assert list(bar.y) == labels and list(bar.x) == values and bar.orientation == "h"
    assert list(bar.marker.color) == [pal.accent, pal.context, pal.context]
    assert bar.marker.cornerradius == 4 and list(bar.text) == ["82", "23", "3"]
    assert fig.layout.yaxis.autorange == "reversed"                                       # the largest is at the top
    assert fig.layout.height == charts.horizontal_bar_height(3)
    slot = (fig.layout.height - 36) / 3
    assert slot * (1 - fig.layout.bargap) <= charts.BAR_MAX_PX + 1e-9                    # never thicker than 24px
    assert fig.layout.showlegend is False


def test_bars_with_no_highlight_are_all_the_accent_colour():
    fig = charts.horizontal_bar(["a", "b"], [2, 1], theme.LIGHT)
    assert set(fig.data[0].marker.color) == {theme.LIGHT.accent}


@PALETTES
def test_lead_time_and_dwell_are_two_lines_on_one_axis(pal):
    df = weekly(5).assign(avg_lead_days=[3, 4, 8, 12, 20], avg_dwell_days=[2, 2, 2, 2, 2])
    fig = charts.lead_dwell_chart(df, pal)
    assert [t.name for t in fig.data] == ["Lead time", "Dwell after test"]
    assert [t.line.color for t in fig.data] == [pal.accent, pal.accent_2]
    assert fig.layout.showlegend is True and "yaxis2" not in fig.layout
    assert all(t.yaxis in (None, "y") for t in fig.data)


# ---------------------------------------------------------------------------- the page

@pytest.fixture(scope="module")
def database():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not url.rstrip("/").rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point at a database ending in _test, got: {url}")
    build(url=url, write_files=False)
    return url


def test_the_production_page_runs_and_tells_the_story(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    at = AppTest.from_file(str(ROOT / "app" / "views" / "production.py"), default_timeout=90).run()
    assert not at.exception
    assert at.title[0].value == "Production"
    text = " ".join(m.value for m in at.markdown)
    assert "Avionics is the bottleneck" in text and "queued for Avionics" in text
    assert [s.value for s in at.subheader] == ["Drones started and finished each week", "Where drones wait",
                                              "Where drones are now", "What it does to delivery", "Station summary"]
    assert len([e for e in at.expander if e.label == "Table view"]) == 4              # every chart has a table view
    assert any("synthetic data" in c.value for c in at.caption)
