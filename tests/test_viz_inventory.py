"""The Inventory & Suppliers page: its findings, its charts, and the page itself."""
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


def risk_rows(*rows):
    return pd.DataFrame(rows, columns=["part_name", "supplier_name", "cushion_days", "risk_status"])


RISK = risk_rows(("Pushrod", "Ridge", -9.3, "AT RISK"), ("Thread locker", "Ridge", -9.1, "AT RISK"),
                 ("Control horn", "Ridge", -9.0, "STOCKOUT"), ("Servo", "Cobalt", 3.0, "OK"), ("Cog", "Cobalt", 7.0, "WATCH"))
PERF = pd.DataFrame({"supplier_name": ["Ridge", "North", "Summit"], "otif_rate": [0.74, 0.84, 0.89]})
GAP = pd.DataFrame({"part_name": ["Foam", "Pushrod"], "station_name": ["Wing", "Wing"], "days_short_at_line": [23, 46]})


# ---------------------------------------------------------------------------- findings, by hand

def test_the_finding_counts_stockouts_and_at_risk_parts_and_names_the_most_urgent():
    first = findings.inventory_finding(RISK, PERF, GAP)[0]
    # 3 of 5 are AT RISK or STOCKOUT. The three lowest cushions are Pushrod, Thread locker and Control horn, all from Ridge.
    assert first == ("**3 of 5 parts are at risk or out of stock**: their stock is expected to run out before the next delivery "
                     "arrives, even allowing for a bad delivery. The most urgent are Pushrod, Thread locker and Control horn, all from Ridge.")


def test_urgency_is_the_lowest_cushion_and_parts_with_no_cushion_come_last():
    shuffled = risk_rows(("Safe", "A", 12.0, "OK"), ("NoDemand", "B", float("nan"), "OK"), ("Worst", "A", -4.0, "AT RISK"),
                         ("Mid", "C", -1.0, "AT RISK"), ("Next", "C", 0.5, "WATCH"))
    text = findings.inventory_finding(shuffled, PERF, GAP)[0]
    assert "The most urgent are Worst, Mid and Next, from A and C." in text
    assert "NoDemand" not in text


def test_the_supplier_sentence_compares_the_worst_with_the_rest():
    second = findings.inventory_finding(RISK, PERF, GAP)[1]
    assert second == ("**Ridge is the least reliable supplier**: 74% of its shipments arrived on time and in full, "
                      "against 84% to 89% for the other regular suppliers.")
    assert len(findings.inventory_finding(RISK, PERF.iloc[[0]], GAP)) == 2          # one supplier cannot be compared


def test_the_wrong_place_sentence_names_the_worst_part_and_station():
    third = findings.inventory_finding(RISK, PERF, GAP)[2]
    assert third == ("**Right part, wrong place.** 2 parts were short at the line on at least one weekday while the warehouse held "
                     "enough for a drone. The worst is Pushrod at Wing, short on 46 weekdays.")
    assert len(findings.inventory_finding(RISK, PERF, GAP.iloc[0:0])) == 2
    assert findings.inventory_finding(RISK.iloc[0:0], PERF.iloc[0:0], GAP.iloc[0:0]) == []


@pytest.mark.parametrize("names, expected", [(["a"], "a"), (["a", "b"], "a and b"), (["a", "b", "c"], "a, b and c")])
def test_lists_are_joined_in_plain_english(names, expected):
    assert findings._join(names) == expected


# ---------------------------------------------------------------------------- charts

CUSHION = pd.DataFrame({"label": ["P1", "P2", "P3", "P4"], "cushion_days": [-9.3, -6.8, -1.0, 4.0],
                        "risk_status": ["AT RISK", "AT RISK", "STOCKOUT", "OK"],
                        "days_remaining": [3.7, 8.0, 0.0, 20.0], "arrival_bad_case_days": [13, 14.8, 1, 16]})


@PALETTES
def test_cushion_bars_wear_status_colours_named_in_the_legend_with_icons(pal):
    fig = charts.cushion_chart(CUSHION, pal)
    by_name = {t.name: t for t in fig.data}
    assert set(by_name) == {"✕ Stockout", "▲ At risk", "✓ OK"}                          # only the statuses present
    assert by_name["▲ At risk"].marker.color == theme.STATUS["serious"]
    assert by_name["✕ Stockout"].marker.color == theme.STATUS["critical"]
    assert by_name["✓ OK"].marker.color == theme.STATUS["good"]                         # fixed in light and dark
    assert fig.layout.showlegend is True and fig.layout.barmode == "overlay"
    assert all(t.orientation == "h" and t.marker.cornerradius == 4 for t in fig.data)
    assert list(fig.layout.yaxis.categoryarray) == ["P1", "P2", "P3", "P4"]             # most urgent at the top
    assert list(by_name["▲ At risk"].text) == ["-9.3 days", "-6.8 days"] and by_name["✓ OK"].text[0] == "+4.0 days"


def test_a_single_status_still_gets_a_legend_so_the_colour_is_named():
    only_at_risk = CUSHION.iloc[[0, 1]]
    fig = charts.cushion_chart(only_at_risk, theme.LIGHT)
    assert [t.name for t in fig.data] == ["▲ At risk"] and fig.layout.showlegend is True


def test_the_cushion_axis_leaves_room_for_the_value_labels_at_both_ends():
    fig = charts.cushion_chart(CUSHION, theme.LIGHT)
    low, high = fig.layout.xaxis.range
    assert low < -9.3 and high > 4.0                                                    # beyond the longest bars on both sides
    assert (-9.3 - low) >= 0.25 * (4.0 + 9.3)                                           # a label's worth of space
    shape = fig.layout.shapes[0]
    assert shape.x0 == shape.x1 == 0 and shape.line.width == 1                         # the zero line


def test_the_cushion_axis_still_works_when_every_value_is_positive_or_zero():
    fig = charts.cushion_chart(CUSHION.assign(cushion_days=[0.0, 2.0, 5.0, 9.0], risk_status="OK"), theme.LIGHT)
    low, high = fig.layout.xaxis.range
    assert low <= 0 and high > 9.0


@PALETTES
def test_stock_history_is_two_lines_on_one_axis_with_a_legend(pal):
    df = pd.DataFrame([(date(2026, 1, 5) + timedelta(days=d), loc, 100 - d if loc == "WAREHOUSE" else 5)
                       for d in range(5) for loc in ("WAREHOUSE", "LINE_SIDE")], columns=["snapshot_date", "location", "on_hand"])
    fig = charts.stock_history_chart(df, pal)
    assert [t.name for t in fig.data] == ["Warehouse", "Line-side"]
    assert [t.line.color for t in fig.data] == [pal.accent, pal.accent_2]
    assert list(fig.data[0].y) == [100, 99, 98, 97, 96] and list(fig.data[1].y) == [5] * 5
    assert fig.layout.showlegend is True and "yaxis2" not in fig.layout and all(t.yaxis in (None, "y") for t in fig.data)


def test_a_rate_bar_chart_shows_percent_labels_and_highlights_one_supplier():
    fig = charts.horizontal_bar(["Ridge", "North"], [74.0, 84.0], theme.LIGHT, highlight="Ridge", unit="%")
    assert list(fig.data[0].text) == ["74%", "84%"] and list(fig.data[0].marker.color) == [theme.LIGHT.accent, theme.LIGHT.context]


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


def test_the_inventory_page_runs_and_opens_on_the_planted_story(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    at = AppTest.from_file(str(ROOT / "app" / "views" / "inventory.py"), default_timeout=90).run()
    assert not at.exception and at.title[0].value == "Inventory & Suppliers"
    text = " ".join(m.value for m in at.markdown)
    assert "of 40 parts are at risk or out of stock" in text and "all from Ridgeline Hardware" in text
    assert "Ridgeline Hardware is the least reliable supplier" in text
    assert "Pushrod at Wing Assembly" in text
    assert [s.value for s in at.subheader] == ["The most urgent parts", "Supplier delivery performance", "Right part, wrong place", "Stock history"]
    assert len([e for e in at.expander if e.label == "Table view"]) == 4
    assert at.selectbox[0].value == at.selectbox[0].options[0] and "Pushrod" in at.selectbox[0].value   # the most urgent part

    at.selectbox[0].select(at.selectbox[0].options[5]).run()
    assert not at.exception
    assert any("The reorder point for this part is" in c.value for c in at.caption)
