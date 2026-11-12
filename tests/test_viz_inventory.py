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


RIDGELINE = pd.DataFrame({"supplier_name": ["Ridge"] * 4, "part_name": ["Prop nut"] * 4,
                          "expected_date": [date(2026, 1, 26), date(2026, 2, 12), date(2026, 3, 2), date(2026, 3, 9)],
                          "days_late": [0, 11, 0, 3], "short": [False, True, False, False]})


# ---------------------------------------------------------------------------- findings, by hand

def test_the_finding_names_the_worst_late_delivery_and_counts_the_late_ones():
    first = findings.inventory_finding(RIDGELINE)[0]
    assert first == "**Ridge's prop nut delivery due 12 February arrived 11 days late and short.** It was late on 2 of its 4 deliveries."


def test_nothing_is_said_when_no_delivery_was_late():
    assert findings.inventory_finding(RIDGELINE.assign(days_late=0)) == []
    assert findings.inventory_finding(RIDGELINE.iloc[0:0]) == []


def test_the_emergency_buys_are_mentioned_only_when_there_were_some():
    assert len(findings.inventory_finding(RIDGELINE, 0)) == 1
    assert findings.inventory_finding(RIDGELINE, 1)[1] == ("When the stock ran out, the line bought 1 emergency substitute lot "
                                                           "of prop nut from the spot-buy distributor.")
    assert "2 emergency substitute lots of prop nut" in findings.inventory_finding(RIDGELINE, 2)[1]


# ---------------------------------------------------------------------------- charts

@PALETTES
def test_stock_history_is_two_lines_on_one_axis_with_a_legend(pal):
    df = pd.DataFrame([(date(2026, 1, 5) + timedelta(days=d), loc, 100 - d if loc == "WAREHOUSE" else 5)
                       for d in range(5) for loc in ("WAREHOUSE", "LINE_SIDE")], columns=["snapshot_date", "location", "on_hand"])
    fig = charts.stock_history_chart(df, pal)
    assert [t.name for t in fig.data] == ["Warehouse", "Line-side"]
    assert [t.line.color for t in fig.data] == [pal.accent, pal.accent_2]
    assert list(fig.data[0].y) == [100, 99, 98, 97, 96] and list(fig.data[1].y) == [5] * 5
    assert fig.layout.showlegend is True and "yaxis2" not in fig.layout and all(t.yaxis in (None, "y") for t in fig.data)


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


def test_the_inventory_page_runs_and_opens_on_the_planted_story(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    at = AppTest.from_file(str(ROOT / "app" / "views" / "inventory.py"), default_timeout=90).run()
    assert not at.exception and at.title[0].value == "Inventory & Suppliers"
    text = " ".join(m.value for m in at.markdown)
    assert "Ridgeline Hardware's prop nut delivery" in text and "days late" in text and "emergency substitute" in text
    assert [s.value for s in at.subheader] == ["Deliveries from Ridgeline Hardware", "Stock history"]
    assert len([e for e in at.expander if e.label == "Table view"]) == 2
    assert "Prop nut" in at.selectbox[0].value                                    # opens on the part that ran out

    at.selectbox[0].select(at.selectbox[0].options[0]).run()
    assert not at.exception
    assert any("The reorder point for this part is" in c.value for c in at.caption)
