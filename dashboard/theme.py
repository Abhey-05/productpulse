"""
theme.py
--------
Shared visual system for the ProductPulse dashboard: a validated,
brand-neutral categorical palette (see dataviz skill / palette.md),
chart chrome tokens, and a small set of Plotly helpers so every page
renders as one coherent product-analytics tool instead of default
chart-library output.
"""

import plotly.graph_objects as go
import plotly.io as pio

# ---------------------------------------------------------------------
# Palette (validated: adjacent-pair CVD Delta E >= 8, normal-vision >= 15)
# ---------------------------------------------------------------------
CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
]
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = ["#256abf", "#f0efec", "#e34948"]  # blue -> neutral -> red

STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# Chart chrome (light mode — the dashboard doesn't implement a dark
# toggle, so we ship a clean, high-contrast light theme throughout).
SURFACE = "#fcfcfb"
PAGE_PLANE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def apply_plotly_theme():
    """Register a 'productpulse' Plotly template and make it the default."""
    template = go.layout.Template()
    template.layout = go.Layout(
        colorway=CATEGORICAL,
        font=dict(family=FONT_FAMILY, color=INK_PRIMARY, size=13),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        title=dict(font=dict(size=16, color=INK_PRIMARY)),
        xaxis=dict(
            gridcolor=GRIDLINE, linecolor=BASELINE, zerolinecolor=BASELINE,
            tickfont=dict(color=INK_MUTED, size=11), title_font=dict(color=INK_SECONDARY, size=12),
        ),
        yaxis=dict(
            gridcolor=GRIDLINE, linecolor=BASELINE, zerolinecolor=BASELINE,
            tickfont=dict(color=INK_MUTED, size=11), title_font=dict(color=INK_SECONDARY, size=12),
        ),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=INK_SECONDARY, size=12)),
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(bgcolor=SURFACE, font=dict(family=FONT_FAMILY, color=INK_PRIMARY, size=12),
                         bordercolor=BASELINE),
    )
    pio.templates["productpulse"] = template
    pio.templates.default = "productpulse"


CUSTOM_CSS = f"""
<style>
    .stApp {{ background-color: {PAGE_PLANE}; }}
    html, body, [class*="css"] {{ font-family: {FONT_FAMILY}; }}

    /* KPI card */
    div[data-testid="stMetric"] {{
        background-color: {SURFACE};
        border: 1px solid {GRIDLINE};
        border-radius: 10px;
        padding: 16px 18px 12px 18px;
    }}
    div[data-testid="stMetric"] label {{
        color: {INK_MUTED} !important;
        font-size: 0.78rem !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    div[data-testid="stMetricValue"] {{
        color: {INK_PRIMARY} !important;
        font-weight: 600;
    }}

    /* Section headers */
    h1, h2, h3 {{ color: {INK_PRIMARY}; font-weight: 600; }}
    h1 {{ font-size: 1.6rem !important; margin-bottom: 0.2rem; }}
    h2 {{ font-size: 1.15rem !important; margin-top: 1.4rem; }}
    h3 {{ font-size: 0.98rem !important; color: {INK_SECONDARY}; }}

    /* Insight callout card */
    .pp-callout {{
        background-color: {SURFACE};
        border-left: 4px solid {CATEGORICAL[0]};
        border-radius: 6px;
        padding: 14px 18px;
        margin: 10px 0 18px 0;
    }}
    .pp-callout.serious {{ border-left-color: {STATUS['serious']}; }}
    .pp-callout.critical {{ border-left-color: {STATUS['critical']}; }}
    .pp-callout.good {{ border-left-color: {STATUS['good']}; }}
    .pp-callout-label {{
        font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
        color: {INK_MUTED}; font-weight: 600; margin-bottom: 4px;
    }}
    .pp-callout-title {{ font-size: 1.0rem; font-weight: 600; color: {INK_PRIMARY}; margin-bottom: 6px; }}
    .pp-callout-body {{ font-size: 0.88rem; color: {INK_SECONDARY}; line-height: 1.5; }}
    .pp-callout-body b {{ color: {INK_PRIMARY}; }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{ background-color: {SURFACE}; border-right: 1px solid {GRIDLINE}; }}

    .pp-caption {{ color: {INK_MUTED}; font-size: 0.8rem; }}
</style>
"""
