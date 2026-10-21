"""The app's only route to the database: one cached query function.

The connection string comes from Streamlit secrets (the hosted app) or DATABASE_URL in the environment or .env
(local). It is never written into the code or the repo.
"""
from __future__ import annotations

import os
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


@st.cache_data(ttl=600, show_spinner=False)
def _run(url: str, sql: str, params: tuple | None) -> pd.DataFrame:
    with psycopg.connect(url) as conn:
        cur = conn.execute(sql, params)
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for col in df.columns:
        if len(df) and df[col].dtype == object and isinstance(df[col].dropna().iloc[0] if df[col].notna().any() else None, Decimal):
            df[col] = df[col].astype(float)
    return df


def query(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame. Results are cached for ten minutes per database and query."""
    return _run(database_url(), sql, params)
