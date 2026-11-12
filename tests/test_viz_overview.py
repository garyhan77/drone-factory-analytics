"""The Overview page: the story, and that it tells the same story as the two pages it summarises."""
import os

import pytest
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

from factory.build import build
from factory.db import ROOT

APP = str(ROOT / "app" / "Home.py")


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


def run(monkeypatch, database, view):
    monkeypatch.setenv("DATABASE_URL", database)
    return AppTest.from_file(str(ROOT / "app" / "views" / view), default_timeout=90).run()


def test_the_overview_opens_with_the_story_and_the_two_findings(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception and at.title[0].value == "Overview"
    text = " ".join(m.value for m in at.markdown)
    assert "drones were started" not in text
    for claim in ("a supplier ships late", "2 lots stand out",
                  "arrived", "emergency substitute"):
        assert claim in text, claim
    assert [c.value for c in at.caption if " · " in c.value] == [
        "QUALITY & TRACEABILITY  ·  QUALITY ENGINEER", "INVENTORY & SUPPLIERS  ·  MATERIAL PLANNER"]
    assert not any(e.label == "About this project" for e in at.expander)


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
    expected = {"quality.py": 2, "inventory.py": 2}
    for view, count in expected.items():
        sentences = findings_on(run(monkeypatch, database, view))
        assert len(sentences) == count, (view, sentences)
        assert all(s in overview for s in sentences), (view, [s for s in sentences if s not in overview])


def test_the_overview_links_to_the_two_other_pages(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    at = AppTest.from_file(APP, default_timeout=90).run()
    links = at.get("page_link")
    assert len(links) == 2
    assert [l.proto.label for l in links] == ["Open the Quality & Traceability page", "Open the Inventory & Suppliers page"]
