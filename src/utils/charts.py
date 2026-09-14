"""
Plotly charts for the dashboard.

Colours:
  - Risk levels use fixed status colours (critical red, serious orange, good
    green) and always appear with the level name, so colour is never the only
    signal.
  - Single-series charts use one blue.
Streamlit's own theme supplies fonts, gridlines and dark-mode backgrounds.
"""

import plotly.graph_objects as go

import config

RISK_LEVEL_COLORS = {"HIGH": "#d03b3b", "MEDIUM": "#ec835a", "LOW": "#0ca30c"}
SERIES_COLOR = "#2a78d6"
REFERENCE_LINE_COLOR = "#898781"

BAR_HEIGHT_PX = 34
CHART_PADDING_PX = 110


def _chart_height(bar_count):
    return max(220, bar_count * BAR_HEIGHT_PX + CHART_PADDING_PX)


def site_risk_chart(site_risk, selected_site=None):
    """
    Horizontal bar chart of site risk scores, highest at the top, coloured by
    risk level, with dashed lines at the LOW/MEDIUM and MEDIUM/HIGH limits.
    If a site is selected, the other bars are faded.
    """
    data = site_risk.sort_values("risk_score", ascending=True, kind="stable")
    fig = go.Figure()

    # HIGH first so the legend reads HIGH, MEDIUM, LOW
    for level, _ in reversed(config.RISK_LEVELS):
        subset = data[data["risk_level"] == level]
        if subset.empty:
            continue
        opacity = [
            1.0 if selected_site in (None, site_id) else 0.3
            for site_id in subset["site_id"]
        ]
        fig.add_trace(go.Bar(
            x=subset["risk_score"],
            y=subset["site_id"],
            orientation="h",
            name=level,  # the legend already shows a colour swatch, so no icon here
            marker={"color": RISK_LEVEL_COLORS.get(level, SERIES_COLOR), "opacity": opacity, "cornerradius": 4},
            # Score AND level word on every bar, so the chart does not rely on colour
            text=[f"{score} {level}" for score in subset["risk_score"]],
            textposition="outside",
            cliponaxis=False,
            customdata=subset[["risk_level", "total_deviations", "patients"]],
            hovertemplate=(
                "<b>%{y}</b><br>Risk score: %{x}<br>Risk level: %{customdata[0]}"
                "<br>Deviations: %{customdata[1]}<br>Patients: %{customdata[2]}<extra></extra>"
            ),
        ))

    # Dashed lines at the level limits (30 and 60 by default)
    for _, highest_score in config.RISK_LEVELS[:-1]:
        fig.add_vline(x=highest_score, line_dash="dash", line_width=1, line_color=REFERENCE_LINE_COLOR)

    fig.update_layout(
        barmode="overlay",
        bargap=0.35,
        height=_chart_height(len(data)),
        margin={"l": 10, "r": 30, "t": 70, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0,
                "title": {"text": ""}},
        xaxis={"title": "Risk score (0-100)", "range": [0, 125], "tickvals": [0, 30, 60, 100]},
        yaxis={"title": None, "categoryorder": "array", "categoryarray": data["site_id"].tolist()},
    )
    return fig


def horizontal_count_chart(labels, values, value_title, hover_label="Count"):
    """Simple single-colour horizontal bar chart; first label is drawn at the top."""
    labels = list(labels)
    values = list(values)
    fig = go.Figure(go.Bar(
        x=values[::-1],
        y=labels[::-1],
        orientation="h",
        marker={"color": SERIES_COLOR, "cornerradius": 4},
        text=values[::-1],
        textposition="outside",
        cliponaxis=False,
        hovertemplate=f"<b>%{{y}}</b><br>{hover_label}: %{{x}}<extra></extra>",
    ))
    largest = max(values) if values else 0
    fig.update_layout(
        height=_chart_height(len(labels)),
        bargap=0.35,
        margin={"l": 10, "r": 30, "t": 10, "b": 40},
        showlegend=False,
        xaxis={"title": value_title, "range": [0, max(1, largest) * 1.15], "rangemode": "tozero"},
        yaxis={"title": None},
    )
    return fig


def risk_factor_chart(breakdown):
    """Risk points per factor for one site (from the Phase 4 scoring)."""
    return horizontal_count_chart(
        breakdown["Risk factor"], breakdown["Risk points"], "Risk points", hover_label="Risk points"
    )
