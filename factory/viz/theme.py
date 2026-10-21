"""Colours for the app, taken from the validated reference palette of the dataviz method.

The categorical slots used here (blue, orange) were run through the method's palette validator in both modes: lightness
band, chroma floor, colour-blind separation and normal-vision separation all pass. Aqua (slot 3) is deliberately not
used: it is below 3:1 contrast on the light surface. Most charts use EMPHASIS (the accent colour against grey context)
rather than a categorical palette. Status colours are reserved for risk and always come with an icon and a label.
"""
from __future__ import annotations

from dataclasses import dataclass

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


@dataclass(frozen=True)
class Palette:
    mode: str
    surface: str  # chart background
    page: str
    ink: str  # values, titles
    ink_secondary: str  # labels, legends
    ink_muted: str  # axis text
    grid: str  # hairline gridlines
    baseline: str  # axis line
    accent: str  # categorical slot 1: the thing the chart is about
    accent_2: str  # categorical slot 2: only when two series are both the subject
    context: str  # de-emphasis grey: everything that is background to the accent


LIGHT = Palette(
    "light", surface="#fcfcfb", page="#f9f9f7", ink="#0b0b0b", ink_secondary="#52514e", ink_muted="#898781",
    grid="#e1e0d9", baseline="#c3c2b7", accent="#2a78d6", accent_2="#eb6834", context="#898781",
)
DARK = Palette(
    "dark", surface="#1a1a19", page="#0d0d0d", ink="#f0efec", ink_secondary="#c3c2b7", ink_muted="#898781",
    grid="#2c2c2a", baseline="#383835", accent="#3987e5", accent_2="#d95926", context="#898781",
)

# Status colours never change with the theme and never mean anything but state.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

# Risk status -> (icon, label, status colour). The icon and label carry the meaning; colour only reinforces it.
RISK = {
    "STOCKOUT": ("✕", "Stockout", STATUS["critical"]),
    "AT RISK": ("▲", "At risk", STATUS["serious"]),
    "WATCH": ("●", "Watch", STATUS["warning"]),
    "OK": ("✓", "OK", STATUS["good"]),
}


def palette(mode: str | None) -> Palette:
    return DARK if mode == "dark" else LIGHT


def risk_label(status: str) -> str:
    icon, label, _ = RISK[status]
    return f"{icon} {label}"


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
