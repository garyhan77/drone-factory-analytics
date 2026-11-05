"""The Causal & Experiments page: its finding, its tables, its charts, and the page itself (no database needed)."""
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from factory.db import ROOT
from factory.viz import analysis_results as ar
from factory.viz import charts, theme

PALETTES = pytest.mark.parametrize("pal", [theme.LIGHT, theme.DARK], ids=["light", "dark"])

CAUSAL = pd.DataFrame({
    "station": ["MTR"] * 3, "estimator": ["naive", "adjusted", "ipw"], "mean_estimate": [0.26, 0.18, 0.195],
    "bias": [0.065, -0.015, 0.0], "coverage": [0.78, 0.91, 0.94]})
RESULTS = pd.DataFrame({
    "metric": ["shipped"] * 2, "comparison": ["B vs A", "C vs B"], "difference": [58.0, 8.0],
    "adj_ci_lo": [50.0, 2.0], "adj_ci_hi": [66.0, 14.0], "mean_base": [600.0, 658.0], "mean_arm": [658.0, 666.0]})
GUARDRAIL = pd.DataFrame({"difference": [1.4, 3.1]})


def test_the_finding_is_written_from_the_numbers_and_applies_the_bar():
    first, second = ar.analysis_finding(CAUSAL, RESULTS, GUARDRAIL)
    assert "about 19.5 points" in first and "overstates it at 26.0" in first
    assert "third Avionics lane ships about 58 more drones" in second and "a fourth adds only 8" in second
    assert "The third lane clears the 25-drone bar and the fourth does not" in second
    assert "rises at most 3.1 hours" in second


def test_a_fourth_lane_that_clears_the_bar_is_reported_as_clearing_it():
    better = RESULTS.assign(adj_ci_lo=[50.0, 30.0], difference=[58.0, 40.0], adj_ci_hi=[66.0, 50.0])
    assert "Both lanes clear the 25-drone bar" in ar.analysis_finding(CAUSAL, better, GUARDRAIL)[1]


def test_causal_rows_are_in_display_order_with_percentages():
    rows = ar.causal_rows(CAUSAL)
    assert list(rows["Estimator"]) == ["Naive", "Adjusted for week", "Inverse-probability weighting"]
    assert list(rows["Mean estimate (points)"]) == [26.0, 18.0, 19.5]
    assert list(rows["95% interval covers the truth"]) == ["78%", "91%", "94%"]


def test_lane_gains_and_outcomes_read_the_right_rows():
    gains = ar.lane_gains(RESULTS)
    assert list(gains["label"]) == ["Third lane (3 vs 2)", "Fourth lane (4 vs 3)"] and list(gains["gain"]) == [58.0, 8.0]
    secondary = pd.DataFrame({
        "metric": ["avionics_queue_at_extract"] * 2 + ["avionics_wait_h"] * 2, "comparison": ["B vs A", "C vs B"] * 2,
        "mean_base": [80.0, 24.0, 160.0, 59.0], "mean_arm": [24.0, 14.0, 59.0, 44.0]})
    out = ar.lane_outcomes(RESULTS, secondary)
    assert list(out["Avionics lanes"]) == [2, 3, 4] and list(out["Drones shipped"]) == [600.0, 658.0, 666.0]
    assert list(out["Queued at Avionics at the end"]) == [80.0, 24.0, 14.0] and list(out["Average Avionics wait (h)"]) == [160.0, 59.0, 44.0]


@PALETTES
def test_the_estimator_chart_marks_the_truth_with_one_labelled_line(pal):
    fig = charts.estimator_chart(ar.causal_rows(CAUSAL), 19.5, pal)
    assert fig.data[0].marker.color == pal.accent and fig.layout.showlegend is False
    assert len(fig.layout.shapes) == 1 and fig.layout.shapes[0].x0 == 19.5
    assert "True effect 19.5" in [a.text for a in fig.layout.annotations]
    slot = (fig.layout.height - 64) / 3
    assert slot * (1 - fig.layout.bargap) <= charts.BAR_MAX_PX + 1e-9


@PALETTES
def test_the_lane_chart_shows_the_interval_and_the_bar(pal):
    fig = charts.lane_gain_chart(ar.lane_gains(RESULTS), 25.0, pal)
    assert list(fig.data[0].x) == [58.0, 8.0]
    assert list(fig.data[0].error_x.array) == [8.0, 6.0] and list(fig.data[0].error_x.arrayminus) == [8.0, 6.0]
    assert fig.layout.shapes[0].x0 == 25.0


def test_the_page_renders_from_the_saved_results_without_a_database():
    at = AppTest.from_file(str(ROOT / "app" / "views" / "causal_experiments.py"), default_timeout=60).run()
    assert not at.exception and at.title[0].value == "Causal Analysis & Experiments"
    text = " ".join(m.value for m in at.markdown)
    assert "third Avionics lane ships about 58 more drones" in text and "a fourth adds only 8" in text
    assert [s.value for s in at.subheader] == ["Did the emergency fastener lots cause the failures?",
                                              "How much does each queued drone add to the wait?", "Should we add Avionics lanes?"]
    assert len(at.metric) == 3
