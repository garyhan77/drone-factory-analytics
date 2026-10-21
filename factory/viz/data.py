"""The app's only route to the database: one cached query function.

The connection string comes from Streamlit secrets (the hosted app) or DATABASE_URL in the environment or .env
(local). It is never written into the code or the repo.

A hosted database may stop idle connections (Neon suspends after a few idle minutes), so the app keeps one shared
connection, and if a query fails because the connection was dropped it reconnects and tries once more.
"""
from __future__ import annotations

import os
import threading
from decimal import Decimal

import pandas as pd
import psycopg
import streamlit as st
from dotenv import load_dotenv

from factory.db import ROOT


def database_url() -> str:
    try:
        url = st.secrets["DATABASE_URL"]
    except Exception:  # no secrets file, or no such key
        url = None
    if not url:
        load_dotenv(ROOT / ".env")
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Add it to .streamlit/secrets.toml or to .env.")
    return url


def _connect(url: str) -> psycopg.Connection:
    # prepare_threshold=None: a pooled connection (pgbouncer) can hand each statement to a different server session,
    # which breaks prepared statements. autocommit: every query is a single read, so no transaction is left open.
    return psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=30)


class SharedConnection:
    """One connection shared by all sessions, one query at a time, replaced if the server dropped it."""

    def __init__(self, url: str, connect=_connect):
        self._url, self._connect, self._lock, self._conn = url, connect, threading.Lock(), None

    def fetch(self, sql: str, params: tuple | None = None) -> tuple[list[str], list[tuple]]:
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = self._connect(self._url)
                    cur = self._conn.execute(sql, params)
                    return [c.name for c in cur.description], cur.fetchall()
                except (psycopg.OperationalError, psycopg.InterfaceError):
                    self._discard()
                    if attempt == 2:
                        raise
            raise AssertionError("unreachable")

    def _discard(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None


@st.cache_resource(show_spinner=False)
def _shared(url: str) -> SharedConnection:
    return SharedConnection(url)


def to_frame(columns: list[str], rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:
        values = df[col].dropna()
        if df[col].dtype == object and len(values) and isinstance(values.iloc[0], Decimal):
            df[col] = df[col].astype(float)
    return df


@st.cache_data(ttl=600, show_spinner=False)
def _run(url: str, sql: str, params: tuple | None) -> pd.DataFrame:
    return to_frame(*_shared(url).fetch(sql, params))


def query(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame. Results are cached for ten minutes per database and query."""
    return _run(database_url(), sql, params)
