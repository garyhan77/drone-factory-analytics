"""Chart styling shared by every chart, following the dataviz method's mark specifications.

Marks: lines 2px, end-dots 8px with a 2px ring in the surface colour, bars at most 24px thick with a 4px rounded data
end, gridlines solid and hairline, no dashes, no border around marks. A legend appears only when two or more series are
drawn. Every chart is paired with a table view (see render.py).
"""
from __future__ import annotations

import plotly.graph_objects as go

from .theme import FONT, Palette

LINE_WIDTH = 2
MARKER_SIZE = 8
RING_WIDTH = 2
BAR_MAX_PX = 24
BAR_SLOT_PX = 40  # vertical room given to each bar; the bar fills at most BAR_MAX_PX of it
CORNER_RADIUS = 4


def style(fig: go.Figure, pal: Palette, *, height: int = 340, legend: bool = False, hovermode: str = "x unified") -> go.Figure:
    """Apply the shared look: recessive hairline grid, system sans, quiet ink, no mode bar."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=16, t=36 if legend else 12, b=8),
        paper_bgcolor=pal.surface, plot_bgcolor=pal.surface,
        font=dict(family=FONT, size=13, color=pal.ink_secondary),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(color=pal.ink_secondary)),
        hovermode=hovermode,
        hoverlabel=dict(bgcolor=pal.surface, bordercolor=pal.baseline, font=dict(family=FONT, size=13, color=pal.ink)),
    )
    axis = dict(showline=True, linecolor=pal.baseline, linewidth=1, ticks="", tickfont=dict(color=pal.ink_muted),
                zeroline=False, griddash="solid", gridwidth=1, title_font=dict(color=pal.ink_muted, size=12),
                automargin=True)  # let Plotly make room for tick labels and axis titles instead of clipping them
    fig.update_xaxes(showgrid=False, **axis)
    fig.update_yaxes(showgrid=True, gridcolor=pal.grid, **axis)
    return fig


def horizontal_bar_height(n_bars: int, *, extra: int = 36) -> int:
    """Chart height that gives each bar its own slot, so a bar never grows past BAR_MAX_PX."""
    return n_bars * BAR_SLOT_PX + extra


def bar_gap() -> float:
    """The bargap that makes a bar BAR_MAX_PX thick inside a BAR_SLOT_PX slot."""
    return 1 - BAR_MAX_PX / BAR_SLOT_PX


def line_trace(x, y, name: str, colour: str, pal: Palette, *, end_dot: bool = True, hover: str = "%{y}") -> go.Scatter:
    """A 2px line with an optional 8px end-dot wearing a 2px surface ring."""
    marker_sizes = [0] * (len(x) - 1) + [MARKER_SIZE] if end_dot and len(x) else None
    return go.Scatter(
        x=x, y=y, name=name, mode="lines+markers", line=dict(color=colour, width=LINE_WIDTH, shape="linear"),
        marker=dict(color=colour, size=marker_sizes or 0, line=dict(color=pal.surface, width=RING_WIDTH)),
        hovertemplate=f"{hover}<extra>{name}</extra>",
    )






def horizontal_bar(labels, values, pal: Palette, highlight=None, *, unit: str = "") -> go.Figure:
    """One bar per label, largest first. Highlighted bars (a label or a set of labels) are the accent colour, the rest grey.

    With no highlight every bar is the accent colour: one series, one colour.
    """
    order = list(labels)
    chosen = {highlight} if isinstance(highlight, str) else (set(highlight) if highlight is not None else None)
    colours = [pal.accent if chosen is None or lab in chosen else pal.context for lab in order]
    fig = go.Figure(go.Bar(
        y=order, x=list(values), orientation="h", marker=dict(color=colours, cornerradius=CORNER_RADIUS),
        text=[f"{v:,.0f}{unit}" for v in values], textposition="outside", cliponaxis=False,
        textfont=dict(color=pal.ink_secondary), hovertemplate="%{y}: %{x:,.0f}" + unit + "<extra></extra>",
    ))
    style(fig, pal, height=horizontal_bar_height(len(order)), hovermode="closest")
    fig.update_layout(bargap=bar_gap(), margin=dict(l=8, r=56, t=8, b=8))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, showticklabels=False, showline=False)
    return fig




# ---------------------------------------------------------------------------- Quality & Traceability

def lot_failure_chart(df, pal: Palette, flag_at: float | None = None) -> go.Figure:
    """The share of drones that failed inspection, by lot. Emergency lots in the accent colour, regular lots grey."""
    df = df.sort_values("fail_rate", ascending=False)
    fig = go.Figure()
    for is_emergency, name, colour in ((True, "Emergency lot (spot-buy)", pal.accent), (False, "Regular lot", pal.context)):
        part = df[df["is_emergency"] == is_emergency]
        fig.add_trace(go.Bar(
            y=part["lot_id"], x=part["fail_rate"] * 100, name=name, orientation="h",
            marker=dict(color=colour, cornerradius=CORNER_RADIUS), text=[f"{v:.0%}" for v in part["fail_rate"]],
            textposition="outside", cliponaxis=False, textfont=dict(color=pal.ink_secondary),
            customdata=part[["fails", "drones_inspected"]].to_numpy(),
            hovertemplate="%{y}: %{customdata[0]} of %{customdata[1]} drones failed (%{x:.0f}%)<extra></extra>"))
    style(fig, pal, height=horizontal_bar_height(len(df), extra=64), legend=True, hovermode="closest")
    fig.update_layout(bargap=bar_gap(), barmode="overlay", margin=dict(l=8, r=56, t=36, b=8))
    fig.update_yaxes(categoryorder="array", categoryarray=list(df["lot_id"]), autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, showticklabels=False, showline=False, rangemode="tozero")
    if flag_at:
        fig.add_vline(x=flag_at * 100, line=dict(color=pal.ink_muted, width=1), annotation_text=f"Flagged at {flag_at:.0%}",
                      annotation_position="top", annotation_font=dict(color=pal.ink_secondary, size=12))
    return fig


# ---------------------------------------------------------------------------- Inventory & Suppliers


def stock_history_chart(df, pal: Palette) -> go.Figure:
    """Warehouse and line-side stock over time for one part: two series that are both the subject."""
    fig = go.Figure()
    for location, name, colour in (("WAREHOUSE", "Warehouse", pal.accent), ("LINE_SIDE", "Line-side", pal.accent_2)):
        part = df[df["location"] == location].sort_values("snapshot_date")
        fig.add_trace(line_trace(part["snapshot_date"], part["on_hand"], name, colour, pal, hover="%{y:,.0f} units"))
    style(fig, pal, height=320, legend=True)
    fig.update_yaxes(title_text="Units on hand at the end of the day", rangemode="tozero")
    return fig
