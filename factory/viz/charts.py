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


# ---------------------------------------------------------------------------- Production

from plotly.subplots import make_subplots  # noqa: E402


def weekly_output_chart(df, pal: Palette) -> go.Figure:
    """Drones started and finished each week: two series that are both the subject, so two colours and a legend."""
    fig = go.Figure([
        line_trace(df["week_start"], df["units_started"], "Started", pal.accent, pal, hover="%{y} drones"),
        line_trace(df["week_start"], df["units_completed"], "Finished", pal.accent_2, pal, hover="%{y} drones"),
    ])
    style(fig, pal, height=340, legend=True)
    fig.update_yaxes(title_text="Drones per week", rangemode="tozero")
    return fig


def wait_small_multiples(df, pal: Palette, highlight: str) -> go.Figure:
    """Average wait before each station, one small panel per station on a shared scale.

    The highlighted station is the point (accent colour); the others are context (grey), so no legend is needed:
    each panel is titled with its station.
    """
    stations = list(df.sort_values("station_seq")["station_name"].unique())
    fig = make_subplots(rows=1, cols=len(stations), shared_yaxes=True, subplot_titles=stations, horizontal_spacing=0.025)
    for col, name in enumerate(stations, start=1):
        part = df[df["station_name"] == name].sort_values("week_start")
        colour = pal.accent if name == highlight else pal.context
        fig.add_trace(line_trace(part["week_start"], part["avg_wait_hours"], name, colour, pal, hover="%{y:.0f} hours"), row=1, col=col)
    style(fig, pal, height=330, hovermode="x")
    fig.update_layout(margin=dict(l=8, r=16, t=44, b=8))  # room for the panel titles
    fig.update_yaxes(title_text="Average wait before the station (hours)", row=1, col=1, rangemode="tozero")
    fig.update_xaxes(tickformat="%b", nticks=4)
    for ann in fig.layout.annotations:  # panel titles in quiet ink, left aligned
        ann.update(font=dict(color=pal.ink_secondary, size=13), xanchor="left", x=ann.x - 0.07)
    return fig


def horizontal_bar(labels, values, pal: Palette, highlight: str | None = None, *, unit: str = "") -> go.Figure:
    """One bar per label, largest first. The highlighted bar (if any) is the accent colour, the rest grey."""
    order = list(labels)
    colours = [pal.accent if highlight is None or lab == highlight else pal.context for lab in order]
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


def lead_dwell_chart(df, pal: Palette) -> go.Figure:
    """Lead time (first station to shipped) against dwell (test passed to shipped), per week of shipping."""
    fig = go.Figure([
        line_trace(df["week_start"], df["avg_lead_days"], "Lead time", pal.accent, pal, hover="%{y:.1f} days"),
        line_trace(df["week_start"], df["avg_dwell_days"], "Dwell after test", pal.accent_2, pal, hover="%{y:.1f} days"),
    ])
    style(fig, pal, height=320, legend=True)
    fig.update_yaxes(title_text="Days (weekly average)", rangemode="tozero")
    return fig
