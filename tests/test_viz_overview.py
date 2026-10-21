"""The Overview page: the status line, and that it tells the same story as the four pages it summarises."""
import os
from datetime import date

import pandas as pd
import pytest
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

from factory.build import build
from factory.db import ROOT
from factory.viz import findings

APP = str(ROOT / "app" / "Home.py")


def test_the_status_line_states_the_period_and_where_the_drones_are():
    status = pd.Series({"started": 738, "shipped": 609, "launch": date(2026, 1, 5), "as_of": date(2026, 7, 3)})
    assert findings.status_line(status) == ("738 drones were started between 5 January and 3 July 2026: "
                                            "609 have shipped and 129 are still in the factory.")
    one = pd.Series({"started": 10, "shipped": 10, "launch": date(2026, 3, 12), "as_of": date(2026, 12, 31)})
    assert findings.status_line(one).endswith("between 12 March and 31 December 2026: 10 have shipped and 0 are still in the factory.")


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


def run(monkeypatch, database, view):
    monkeypatch.setenv("DATABASE_URL", database)
    return AppTest.from_file(str(ROOT / "app" / "views" / view), default_timeout=90).run()


def test_the_overview_opens_with_the_status_line_and_the_four_findings(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception and at.title[0].value == "Overview"
    text = " ".join(m.value for m in at.markdown)
    assert "drones were started between 5 January and 3 July 2026" in text and "are still in the factory" in text
    assert "735 drones were started" in text                                         # the drones that actually reached a first station
    for claim in ("Avionics is the bottleneck", "Motor & Prop's first-pass yield dipped", "3 lots stand out",
                  "parts are at risk or out of stock", "is the least reliable supplier", "planted errors were caught"):
        assert claim in text, claim
    assert [c.value for c in at.caption if " · " in c.value] == [
        "PRODUCTION  ·  PRODUCTION LEAD", "QUALITY & TRACEABILITY  ·  QUALITY ENGINEER",
        "INVENTORY & SUPPLIERS  ·  MATERIAL PLANNER", "DATA QUALITY  ·  DATA ANALYST"]
    assert any(e.label == "About this project" for e in at.expander)


def findings_on(at):
    """The sentences a page opens with: the markdown between its question heading and its first section heading."""
    out, started = [], False
    for element in at.main:
        kind = type(element).__name__
        if kind == "Subheader":
            break
        if kind == "Markdown" and started:
            out.append(element.value)
        if kind == "Markdown" and element.value.startswith("####"):
            started = True
    return out


def test_every_finding_on_the_overview_is_exactly_the_one_on_its_own_page(database, monkeypatch):
    """The Overview must never disagree with the pages it summarises: compare the sentences word for word."""
    monkeypatch.setenv("DATABASE_URL", database)
    overview = {m.value for m in AppTest.from_file(APP, default_timeout=90).run().markdown}
    expected = {"production.py": 2, "quality.py": 3, "inventory.py": 3, "data_quality.py": 2}
    for view, count in expected.items():
        sentences = findings_on(run(monkeypatch, database, view))
        assert len(sentences) == count, (view, sentences)
        assert all(s in overview for s in sentences), (view, [s for s in sentences if s not in overview])


def test_the_overview_links_to_the_four_other_pages(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    at = AppTest.from_file(APP, default_timeout=90).run()
    links = at.get("page_link")
    assert len(links) == 4
    assert [l.proto.label for l in links] == ["Open the Production page", "Open the Quality & Traceability page",
                                              "Open the Inventory & Suppliers page", "Open the Data Quality page"]
