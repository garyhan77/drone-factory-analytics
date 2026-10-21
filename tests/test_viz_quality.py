"""The Quality & Traceability page: its findings, its charts, and the page itself."""
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
START = date(2026, 1, 5)


def station(code, name, weeks):
    """Weekly rows for one station from (inspections, passes) pairs."""
    return pd.DataFrame([(START + timedelta(weeks=i), code, name, n, p, p / n) for i, (n, p) in enumerate(weeks)],
                        columns=["week_start", "station_code", "station_name", "inspections", "passes", "fpy"])


# X: nine ordinary weeks of 19/20 and one small bad week of 8/10 (a 14-point drop, but only 10 inspections).
# Y: nine ordinary weeks of 39/40 and one bad week of 35/40 (a 9-point drop, but over 40 inspections).
X = station("X", "Xs", [(20, 19)] * 9 + [(10, 8)])
Y = station("Y", "Ys", [(40, 39)] * 9 + [(40, 35)])
LOTS = pd.DataFrame({"lot_id": ["SUB-1", "LOT-2"], "supplier_name": ["Spot", "Acme"], "drones_inspected": [22, 40],
                     "fails": [6, 2], "fail_rate": [6 / 22, 0.05], "station_fail_rate": [0.04, 0.04], "lift": [6.8, 1.2]})
RECALL = pd.DataFrame({"drones": [22], "shipped": [20], "packed": [1], "in_line": [1]})


# ---------------------------------------------------------------------------- findings, by hand

def test_the_dip_is_judged_against_chance_not_by_the_raw_gap():
    summary = findings.station_yield_summary(pd.concat([X, Y])).set_index("station_code")
    # X: overall 179/190 = 0.942, small week 0.8: z = -0.142 / sqrt(0.942 x 0.058 / 10) = -1.9.
    # Y: overall 386/400 = 0.965, bad week 0.875: z = -0.09 / sqrt(0.965 x 0.035 / 40) = -3.1.
    assert summary.loc["X", "z"] == pytest.approx(-1.92, abs=0.02) and summary.loc["Y", "z"] == pytest.approx(-3.10, abs=0.02)
    raw_gap = (summary["overall"] - summary["worst_fpy"]).idxmax()
    assert raw_gap == "X"                                  # the raw gap would have pointed at the small, noisy week...
    text = findings.quality_finding(pd.concat([X, Y]), LOTS.iloc[0:0], RECALL)[0]
    assert text.startswith("**Ys's first-pass yield dipped to 88% in the week of ")   # ...but the finding names Y
    assert "Xs" not in text


def test_no_dip_is_reported_when_every_week_is_within_normal_variation():
    steady = station("S", "Steady", [(20, 19)] * 10)
    assert findings.quality_finding(steady, LOTS.iloc[0:0], RECALL)[0].startswith("No station's weekly yield fell")
    just_noise = pd.concat([steady, station("T", "Tiny", [(20, 19)] * 9 + [(10, 8)])])   # only the small week dips (z about -1.9)
    assert findings.quality_finding(just_noise, LOTS.iloc[0:0], RECALL)[0].startswith("No station's weekly yield fell")


def test_weeks_with_very_few_inspections_are_never_called_a_dip():
    tiny_week = station("Z", "Zs", [(20, 19)] * 9 + [(5, 0)])
    assert len(findings.station_yield_summary(tiny_week)) == 1                           # the station is summarised...
    assert findings.station_yield_summary(tiny_week)["worst_n"].iloc[0] == 20            # ...but the 5-inspection week is ignored
    assert findings.quality_finding(tiny_week, LOTS.iloc[0:0], RECALL)[0].startswith("No station's weekly yield fell")


def test_lots_are_flagged_only_with_enough_drones_and_a_high_enough_lift():
    lots = pd.DataFrame({"lot_id": list("ABCD"), "drones_inspected": [9, 10, 40, 40], "lift": [9.0, 3.0, 2.99, 3.5]})
    assert list(findings.flagged_lots(lots)["lot_id"]) == ["D", "B"]    # A too few drones; C just under 3x; sorted by lift


def test_the_lot_and_recall_sentences_read_correctly_for_any_count():
    one = findings.quality_finding(X, LOTS, RECALL)[1:]
    assert one[0].startswith("**1 lot stands out.** Drones that received it failed first inspection 7 times as often")
    assert "The worst is SUB-1 (Spot): 6 of 22 drones failed (27% against 4.0%)." in one[0]
    assert one[1] == "22 drones contain this lot. Where they are now: 20 shipped, 1 packed and waiting, 1 still in the line."
    many = pd.concat([LOTS.iloc[[0]], LOTS.iloc[[0]].assign(lot_id="SUB-9", lift=4.2)])
    text = findings.quality_finding(X, many, RECALL)[1:]
    assert text[0].startswith("**2 lots stand out.** Drones that received them failed first inspection 4 to 7 times as often")
    assert text[1].startswith("22 drones contain one of these lots.")
    single = findings.quality_finding(X, LOTS, pd.DataFrame({"drones": [1], "shipped": [1], "packed": [0], "in_line": [0]}))[2]
    assert single == "1 drone contains this lot. Where it is now: 1 shipped, 0 packed and waiting, 0 still in the line."
    assert len(findings.quality_finding(X, LOTS.iloc[0:0], RECALL)) == 2                  # nothing flagged, so no recall sentence
    assert findings.quality_finding(X, LOTS.iloc[0:0], RECALL)[1] == "No lot's failure rate stands out from its station's."


# ---------------------------------------------------------------------------- charts

@PALETTES
def test_the_yield_chart_marks_the_lowest_week_and_labels_the_overall_rate(pal):
    fig = charts.yield_chart(X, 0.942, pal)
    line, low = fig.data
    assert line.line.color == pal.accent and line.line.width == 2 and list(line.y) == list(X["fpy"])
    assert list(low.x) == [X["week_start"].iloc[9]] and list(low.y) == [0.8]           # the 8-of-10 week
    assert low.text[0] == "Lowest: 80%" and low.marker.size >= 8 and low.marker.line.color == pal.surface
    shape = fig.layout.shapes[0]
    assert shape.y0 == shape.y1 == 0.942 and shape.line.width == 1 and shape.line.dash in (None, "solid")   # solid reference
    assert fig.layout.annotations[0].text == "Overall 94%"
    assert fig.layout.showlegend is False and fig.layout.yaxis.tickformat == ".0%"
    assert fig.layout.yaxis.range == (0.7, 1.0)                                         # a tenth below the lowest week (0.8)


@pytest.mark.parametrize("lowest, floor", [(0.8, 0.7), (0.7, 0.6), (0.9, 0.8), (0.5, 0.4), (0.3, 0.2), (0.15, 0.0), (0.97, 0.8)])
def test_the_axis_floor_is_a_tenth_below_the_lowest_week_without_float_error(lowest, floor):
    """0.3 - 0.1 is 0.2 in arithmetic but 0.19999999999999998 in floating point; the axis must not drop a whole tenth."""
    df = station("Z", "Zs", [(20, 20)] * 4).assign(fpy=[1.0, lowest, 1.0, 1.0])
    assert charts.yield_chart(df, 0.95, theme.LIGHT).layout.yaxis.range == (floor, 1.0)


def test_the_lowest_week_ignores_weeks_too_small_to_judge():
    df = station("Z", "Zs", [(20, 19)] * 5 + [(5, 0)] + [(20, 19)] * 4)                # a 5-inspection week with yield 0%
    low = charts.yield_chart(df, 0.9, theme.LIGHT).data[1]
    assert low.y[0] == 0.95                                                              # not the 0% week


LOT_ROWS = pd.DataFrame({"lot_id": ["SUB-A", "SUB-B", "LOT-C"], "lift": [7.4, 4.9, 2.8], "is_emergency": [True, True, False],
                         "fails": [6, 4, 3], "drones_inspected": [22, 22, 40], "fail_rate": [0.27, 0.18, 0.075],
                         "station_fail_rate": [0.037] * 3})


@PALETTES
def test_the_lot_chart_separates_emergency_lots_with_a_legend_and_two_reference_lines(pal):
    fig = charts.lot_lift_chart(LOT_ROWS, pal, flag_at=3)
    emergency, regular = fig.data
    assert (emergency.name, regular.name) == ("Emergency lot (spot-buy)", "Regular lot")
    assert emergency.marker.color == pal.accent and regular.marker.color == pal.context
    assert list(emergency.y) == ["SUB-A", "SUB-B"] and list(regular.y) == ["LOT-C"]
    assert list(emergency.text) == ["7.4×", "4.9×"] and emergency.marker.cornerradius == 4
    assert fig.layout.showlegend is True and fig.layout.barmode == "overlay"
    assert sorted(s.x0 for s in fig.layout.shapes) == [1, 3] and all(s.line.width == 1 for s in fig.layout.shapes)
    assert {a.text for a in fig.layout.annotations} == {"Station average", "Flagged at 3×"}
    assert list(fig.layout.yaxis.categoryarray) == ["SUB-A", "SUB-B", "LOT-C"]           # worst first


def test_the_lot_chart_works_without_a_flag_line():
    fig = charts.lot_lift_chart(LOT_ROWS, theme.LIGHT)
    assert [s.x0 for s in fig.layout.shapes] == [1]


def test_defect_bars_highlight_every_code_at_the_chosen_station():
    fig = charts.horizontal_bar(["AVN-X", "MTR-A", "MTR-B"], [14, 12, 5], theme.LIGHT, highlight={"MTR-A", "MTR-B"})
    assert list(fig.data[0].marker.color) == [theme.LIGHT.context, theme.LIGHT.accent, theme.LIGHT.accent]
    assert charts.horizontal_bar(["a", "b"], [2, 1], theme.LIGHT, highlight="a").data[0].marker.color == (theme.LIGHT.accent, theme.LIGHT.context)


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


def page(monkeypatch, database):
    monkeypatch.setenv("DATABASE_URL", database)
    return AppTest.from_file(str(ROOT / "app" / "views" / "quality.py"), default_timeout=90).run()


def test_the_quality_page_opens_on_the_planted_story(database, monkeypatch):
    at = page(monkeypatch, database)
    assert not at.exception and at.title[0].value == "Quality & Traceability"
    text = " ".join(m.value for m in at.markdown)
    assert "Motor & Prop's first-pass yield dipped to" in text                              # not a noisy station
    assert "3 lots stand out" in text and "58 drones contain one of these lots" in text
    assert at.selectbox[0].value == "Motor & Prop" and at.selectbox[1].value.startswith("SUB-MTR-")
    assert [m.label for m in at.metric] == ["Already shipped", "Packed, waiting to ship", "Still in the line"]
    assert len([e for e in at.expander if e.label.startswith("Table view")]) == 4


def test_changing_the_station_and_the_lot_updates_the_page(database, monkeypatch):
    at = page(monkeypatch, database)
    at.selectbox[0].select("Avionics").run()
    assert not at.exception
    assert "First-pass yield at Avionics, by week" in [s.value for s in at.subheader]
    lots = at.selectbox[1].options
    at.selectbox[1].select(lots[1]).run()
    assert not at.exception and f"contain {lots[1]}" in " ".join(c.value for c in at.caption)
