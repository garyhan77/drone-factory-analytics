import os

import pytest
from dotenv import load_dotenv

from factory.db import ROOT, apply_schema, connect


@pytest.fixture
def conn():
    """A connection to the TEST database with a freshly applied schema."""
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    # apply_schema drops tables, so never run it against anything but a test database.
    if not url.rstrip("/").rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point at a database whose name ends in _test, got: {url}")
    c = connect(url)
    apply_schema(c)
    yield c
    c.close()
