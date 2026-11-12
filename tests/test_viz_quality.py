"""The Quality & Traceability page: its findings, its chart, and the page itself."""
import os

import pandas as pd
import pytest
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

from factory.build import build
from factory.db import ROOT
from factory.viz import charts, findings, theme

PALETTES = pytest.mark.parametrize("pal", [theme.LIGHT, theme.DARK], ids=["light", "dark"])

LOTS = pd.DataFrame({"lot_id": ["SUB-1", "LOT-2", "LOT-3"], "supplier_name": ["Spot", "Acme", "Acme"], "drones_inspected": [22, 40, 40],
                     "fails": [6, 2, 2], "fail_rate": [6 / 22, 0.05, 0.05]})
RECALL = pd.DataFrame({"drones": [22], "shipped": [20], "packed": [1], "in_line": [1]})


# ---------------------------------------------------------------------------- findings, by hand

def test_lots_are_flagged_only_with_enough_drones_and_a_high_enough_failure_rate():
    lots = pd.DataFrame({"lot_id": list("ABCD"), "drones_inspected": [9, 10, 40, 40], "fail_rate": [0.9, 0.20, 0.19, 0.45]})
    assert list(findings.flagged_lots(lots)["lot_id"]) == ["D", "B"]    # A has too few drones; C is just under 20%; sorted by rate


def test_the_lot_and_recall_sentences_read_correctly_for_any_count():
    one = findings.quality_finding(LOTS, RECALL)
    assert one[0] == ("**1 lot stands out.** 27% of the drones that received it failed inspection, against 5% for a typical lot. "
                      "The worst is SUB-1 (Spot): 6 of 22 drones failed.")
    assert one[1] == "22 drones contain this lot. Where they are now: 20 shipped, 1 packed and waiting, 1 still in the line."
    many = pd.concat([LOTS.iloc[[0]], LOTS.iloc[[0]].assign(lot_id="SUB-9", fail_rate=0.40, fails=9)])
    text = findings.quality_finding(many, RECALL)
    assert text[0].startswith("**2 lots stand out.** 27% to 40% of the drones that received them failed inspection")
    assert text[1].startswith("22 drones contain one of these lots.")
    single = findings.quality_finding(LOTS, pd.DataFrame({"drones": [1], "shipped": [1], "packed": [0], "in_line": [0]}))[1]
    assert single == "1 drone contains this lot. Where it is now: 1 shipped, 0 packed and waiting, 0 still in the line."
    assert findings.quality_finding(LOTS.iloc[1:], RECALL) == ["No lot had 20% or more of its drones fail inspection."]


# ---------------------------------------------------------------------------- charts

LOT_ROWS = pd.DataFrame({"lot_id": ["LOT-C", "SUB-A", "SUB-B"], "fail_rate": [0.075, 0.29, 0.25], "is_emergency": [False, True, True],
                         "fails": [3, 7, 6], "drones_inspected": [40, 24, 24]})


@PALETTES
def test_the_lot_chart_separates_emergency_lots_with_a_legend_and_a_flag_line(pal):
    fig = charts.lot_failure_chart(LOT_ROWS, pal, flag_at=0.2)
    emergency, regular = fig.data
    assert (emergency.name, regular.name) == ("Emergency lot (spot-buy)", "Regular lot")
    assert emergency.marker.color == pal.accent and regular.marker.color == pal.context
    assert list(emergency.y) == ["SUB-A", "SUB-B"] and list(regular.y) == ["LOT-C"]
    assert list(emergency.text) == ["29%", "25%"] and emergency.marker.cornerradius == 4
    assert fig.layout.showlegend is True and fig.layout.barmode == "overlay"
    assert [s.x0 for s in fig.layout.shapes] == [20] and fig.layout.shapes[0].line.width == 1
    assert [a.text for a in fig.layout.annotations] == ["Flagged at 20%"]
    assert list(fig.layout.yaxis.categoryarray) == ["SUB-A", "SUB-B", "LOT-C"]           # worst first


def test_the_lot_chart_works_without_a_flag_line():
    assert not charts.lot_failure_chart(LOT_ROWS, theme.LIGHT).layout.shapes


# ---------------------------------------------------------------------------- the page

@pytest.fixture(scope="module")
def database():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not url.rstrip("/").rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point at a database ending in _test, got: {url}")
    build(url=url)
    return url


def page(monkeypatch, database):
    monkeypatch.setenv("DATABASE_URL", database)
    return AppTest.from_file(str(ROOT / "app" / "views" / "quality.py"), default_timeout=90).run()


def test_the_quality_page_opens_on_the_planted_story(database, monkeypatch):
    at = page(monkeypatch, database)
    assert not at.exception and at.title[0].value == "Quality & Traceability"
    text = " ".join(m.value for m in at.markdown)
    assert "2 lots stand out" in text and "40 drones contain one of these lots" in text
    assert at.selectbox[0].value.startswith("SUB-MTR-")
    assert [m.label for m in at.metric] == ["Already shipped", "Packed, waiting to ship", "Still in the line"]
    assert [s.value for s in at.subheader] == ["Which lots?", "Recall scope"]


def test_changing_the_lot_updates_the_page(database, monkeypatch):
    at = page(monkeypatch, database)
    lots = at.selectbox[0].options
    at.selectbox[0].select(lots[1]).run()
    assert not at.exception and f"contain {lots[1]}" in " ".join(c.value for c in at.caption)
