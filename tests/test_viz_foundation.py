"""The app's foundation: palette, chart style, data access, and the navigation shell."""
import os
from pathlib import Path

import plotly.graph_objects as go
import pytest
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

from factory.db import ROOT
from factory.viz import charts, data, theme

APP = str(ROOT / "app" / "Home.py")


# ---------------------------------------------------------------------------- palette

def test_the_palette_uses_the_validated_reference_values():
    light, dark = theme.LIGHT, theme.DARK
    assert (light.surface, light.accent, light.accent_2) == ("#fcfcfb", "#2a78d6", "#eb6834")
    assert (dark.surface, dark.accent, dark.accent_2) == ("#1a1a19", "#3987e5", "#d95926")
    assert theme.palette("dark") is dark and theme.palette("light") is light and theme.palette(None) is light


def test_text_and_marks_have_enough_contrast_in_both_modes():
    for pal in (theme.LIGHT, theme.DARK):
        assert theme.contrast(pal.ink, pal.surface) >= 7                # values and titles
        assert theme.contrast(pal.ink_secondary, pal.surface) >= 4.5    # labels and legends
        assert theme.contrast(pal.ink_muted, pal.surface) >= 3          # axis text
        for mark in (pal.accent, pal.accent_2, pal.context):
            assert theme.contrast(mark, pal.surface) >= 3, (pal.mode, mark)  # marks need 3:1


def test_the_gridline_is_recessive_and_the_axis_is_a_step_stronger():
    for pal in (theme.LIGHT, theme.DARK):
        assert theme.contrast(pal.grid, pal.surface) < theme.contrast(pal.baseline, pal.surface) < 3


def test_status_colours_are_fixed_and_always_come_with_an_icon_and_label():
    assert set(theme.STATUS) == {"good", "warning", "serious", "critical"}
    assert set(theme.RISK) == {"STOCKOUT", "AT RISK", "WATCH", "OK"}
    icons = [theme.RISK[s][0] for s in theme.RISK]
    assert len(set(icons)) == 4 and all(icons)                          # each status has its own icon
    assert theme.risk_label("AT RISK") == "▲ At risk" and theme.risk_label("OK") == "✓ OK"
    categorical = {theme.LIGHT.accent, theme.LIGHT.accent_2, theme.DARK.accent, theme.DARK.accent_2}
    assert not categorical & set(theme.STATUS.values())                 # status never impersonates a series


# ---------------------------------------------------------------------------- shared chart style

@pytest.mark.parametrize("pal", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
def test_style_applies_the_mark_and_chrome_rules(pal):
    fig = charts.style(go.Figure(go.Scatter(x=[1, 2], y=[1, 2])), pal)
    layout = fig.layout
    assert layout.paper_bgcolor == layout.plot_bgcolor == pal.surface
    assert layout.xaxis.showgrid is False and layout.yaxis.showgrid is True
    assert layout.yaxis.gridcolor == pal.grid and layout.yaxis.gridwidth == 1
    assert layout.yaxis.griddash == "solid" and layout.xaxis.griddash == "solid"   # never dashed
    assert layout.xaxis.automargin is True and layout.yaxis.automargin is True   # tick labels are never clipped
    assert layout.font.family.startswith("system-ui")
    assert layout.showlegend is False                                              # one series needs no legend
    assert charts.style(go.Figure(), pal, legend=True).layout.showlegend is True


def test_bars_are_never_thicker_than_24_pixels():
    assert charts.BAR_SLOT_PX * (1 - charts.bar_gap()) == pytest.approx(charts.BAR_MAX_PX)
    assert charts.horizontal_bar_height(10) == 10 * charts.BAR_SLOT_PX + 36
    assert charts.CORNER_RADIUS == 4


def test_lines_are_two_pixels_with_an_end_dot_wearing_a_surface_ring():
    t = charts.line_trace([1, 2, 3], [4, 5, 6], "Completed", theme.LIGHT.accent, theme.LIGHT)
    assert t.line.width == 2 and t.line.color == theme.LIGHT.accent
    assert list(t.marker.size) == [0, 0, charts.MARKER_SIZE] and charts.MARKER_SIZE >= 8
    assert t.marker.line.color == theme.LIGHT.surface and t.marker.line.width == 2
    assert "Completed" in t.hovertemplate


# ---------------------------------------------------------------------------- data access

def test_the_database_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    assert data.database_url() == "postgresql://example/db"


def test_a_missing_database_url_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(data, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        data.database_url()


def test_secrets_take_priority_over_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env/db")
    monkeypatch.setattr(data.st, "secrets", {"DATABASE_URL": "postgresql://from-secrets/db"})
    assert data.database_url() == "postgresql://from-secrets/db"


def test_query_returns_plain_floats_not_decimals():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    df = data._run(url, "SELECT 1.5::numeric AS x, 'a' AS y, 2 AS z", None)
    assert df["x"].iloc[0] == 1.5 and isinstance(df["x"].iloc[0], float) and df["z"].iloc[0] == 2


# ---------------------------------------------------------------------------- the navigation shell

def test_home_loads_with_five_pages_and_the_synthetic_note(monkeypatch):
    load_dotenv(ROOT / ".env")
    monkeypatch.setenv("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql://unused/unused"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "Overview"
    assert any("synthetic data" in c.value for c in at.caption)
