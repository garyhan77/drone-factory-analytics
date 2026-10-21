"""The Data Quality page: its findings, its chart, and the page itself."""
import os

import pandas as pd
import pytest
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

from factory.build import build
from factory.db import ROOT
from factory.viz import charts, findings, theme

PALETTES = pytest.mark.parametrize("pal", [theme.LIGHT, theme.DARK], ids=["light", "dark"])


def results(*rows):
    df = pd.DataFrame(rows, columns=["category", "planted_rows", "caught", "missed", "false_positives"])
    return df.astype({c: "Int64" for c in ("planted_rows", "caught", "missed", "false_positives")})


PERFECT = results(("planted", 12, 12, 0, 0), ("planted", 3, 3, 0, 0), ("reconciliation", 3, 3, 0, 0), ("guard", 0, 0, 0, 0),
                  ("sanity", 0, 0, 0, 0), ("operational", pd.NA, pd.NA, pd.NA, pd.NA))
IMPACT = pd.DataFrame({"raw_rows": [100, 50], "clean_rows": [95, 50], "changed": [4, 1]})


# ---------------------------------------------------------------------------- findings, by hand

def test_the_finding_counts_planted_errors_caught_across_the_scored_checks():
    first, second = findings.data_quality_finding(PERFECT, IMPACT)
    # Only the 'planted' category counts toward "planted errors": 12 + 3 = 15. Five checks are scored (the operational one is not).
    assert first == "**15 of 15 planted errors were caught**, with 0 missed and 0 false positives across 5 scored checks."
    assert second.startswith("**10 rows were dropped, repaired or relabelled before any metric was computed**: 5 dropped and 5 kept with a fix")


def test_misses_and_false_positives_are_reported_from_every_scored_category():
    worse = results(("planted", 12, 11, 1, 0), ("reconciliation", 3, 1, 2, 0), ("guard", 0, 0, 0, 2), ("sanity", 0, 0, 0, 1),
                    ("operational", pd.NA, pd.NA, pd.NA, pd.NA))
    # Misses come from the planted check (1) and the reconciliation check (2); false positives from the guard (2) and sanity (1) checks.
    assert findings.data_quality_finding(worse, IMPACT)[0] == (
        "**11 of 12 planted errors were caught**, with 3 missed and 3 false positives across 4 scored checks.")


def test_the_finding_copes_with_missing_results_or_cleaning_impact():
    assert findings.data_quality_finding(PERFECT, IMPACT.iloc[0:0]) == [findings.data_quality_finding(PERFECT, IMPACT)[0]]
    assert len(findings.data_quality_finding(PERFECT.iloc[0:0], IMPACT)) == 1


# ---------------------------------------------------------------------------- chart

DETECTORS = pd.DataFrame({"label": ["Duplicate work orders", "Over receipt"], "planted_rows": [12, 3], "caught": [12, 3],
                          "missed": [0, 0], "false_positives": [0, 0]})


@PALETTES
def test_the_detection_chart_shows_caught_rows_in_the_accent_colour_with_one_label_per_bar(pal):
    fig = charts.detection_chart(DETECTORS, pal)
    assert [t.name for t in fig.data] == ["Caught"]                                      # nothing missed, so no second series
    assert fig.data[0].marker.color == pal.accent and list(fig.data[0].x) == [12, 3] and fig.data[0].orientation == "h"
    assert fig.layout.showlegend is False                                                # one series needs no legend
    assert [a.text for a in fig.layout.annotations] == ["12 of 12 caught", "3 of 3 caught"]
    assert fig.layout.barmode == "stack" and fig.layout.yaxis.autorange == "reversed"
    slot = (fig.layout.height - 48) / 2
    assert slot * (1 - fig.layout.bargap) <= charts.BAR_MAX_PX + 1e-9                    # never thicker than 24px


@PALETTES
def test_a_missed_error_appears_in_the_critical_colour_with_an_icon_and_a_legend(pal):
    fig = charts.detection_chart(DETECTORS.assign(caught=[11, 3], missed=[1, 0]), pal)
    assert [t.name for t in fig.data] == ["Caught", "✕ Missed"]
    assert fig.data[1].marker.color == theme.STATUS["critical"] and list(fig.data[1].x) == [1, 0]
    assert fig.layout.showlegend is True
    assert fig.layout.annotations[0].text == "11 of 12 caught"                           # the label tells the truth about the miss


def test_the_axis_leaves_room_for_the_label_outside_the_longest_bar():
    fig = charts.detection_chart(DETECTORS, theme.LIGHT)
    assert fig.layout.xaxis.range[0] == 0 and fig.layout.xaxis.range[1] > 12
    assert fig.layout.margin.r >= 100


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
    return AppTest.from_file(str(ROOT / "app" / "views" / "data_quality.py"), default_timeout=90).run()


def test_the_data_quality_page_reports_the_scores_and_what_cleaning_did(database, monkeypatch):
    at = page(monkeypatch, database)
    assert not at.exception and at.title[0].value == "Data Quality"
    text = " ".join(m.value for m in at.markdown)
    assert "38 of 38 planted errors were caught" in text and "0 missed and 0 false positives across 25 scored checks" in text
    assert "38 rows were dropped, repaired or relabelled" in text and "15 dropped and 23 kept with a fix" in text
    assert [s.value for s in at.subheader] == ["What the checks caught", "All checks", "Flagged records", "What cleaning changed",
                                              "What the bad data would have hidden"]
    behind_the_chart = at.dataframe[0].value                                                             # the chart's table view
    assert len(behind_the_chart) == 7 and not any(behind_the_chart[c].dtype.kind == "f" for c in ("Planted rows", "Caught", "Missed"))
    scoreboard = at.dataframe[1].value
    assert len(scoreboard) == 26 and list(scoreboard.columns) == ["Check", "Type", "Flagged", "Planted", "Caught", "Missed", "False positives"]
    assert scoreboard.loc[scoreboard["Check"] == "duplicate_work_orders", "Planted"].iloc[0] == "12"        # whole numbers, not 12.0
    assert scoreboard.loc[scoreboard["Check"] == "overdue_open_shipments", "Planted"].iloc[0] == "-"        # not scored
    for col in ("Planted", "Caught", "Missed", "False positives"):
        assert all(isinstance(v, str) and (v == "-" or v.isdigit()) for v in scoreboard[col]), col         # never "12.0"


def test_the_flagged_records_table_checks_each_record_against_the_answer_key(database, monkeypatch):
    at = page(monkeypatch, database)
    assert at.selectbox[0].value == "duplicate_work_orders"
    flagged = at.dataframe[2].value
    assert len(flagged) == 12 and set(flagged["Planted?"]) == {"Yes, it was planted"}

    at.selectbox[0].select("negative_inventory").run()
    assert not at.exception and len(at.dataframe[2].value) == 8

    at.selectbox[0].select("status_timestamp_mismatch").run()                          # a guard that should flag nothing
    assert not at.exception and at.success[0].value == "No records flagged."


def test_the_page_shows_the_raw_against_cleaned_comparisons(database, monkeypatch):
    at = page(monkeypatch, database)
    labels = [(m.label, m.value) for m in at.metric]
    assert labels[0] == ("In the raw data", "9 of 13") and labels[1] == ("After cleaning", "13 of 13")      # the defect spike
    raw, cleaned = (int(m.value.replace(",", "")) for m in at.metric[2:4])
    assert raw != cleaned and raw < cleaned                                              # negative readings made the shortage look worse
