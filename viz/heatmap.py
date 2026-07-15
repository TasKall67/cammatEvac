"""Build the X-T heatmap figure and overlay evacuation reference lines / paths on it.

Axis convention matches CAMATT's own trajectory plots: distance (m) on the X axis,
time (s) on the Y axis (see Vasilikou_LB_Q1_100MW180m_T_left_Trajectories.jpg).
"""
from __future__ import annotations

import plotly.graph_objects as go

from data.xt_parser import XTGrid
from viz.colorscale import ColorScale


def build_heatmap_figure(
    grid: XTGrid,
    colorscale: ColorScale,
    x_dtick: float | None = 100,
    y_dtick: float | None = 100,
) -> go.Figure:
    """x_dtick/y_dtick set the axis tick spacing (distance in m / time in s).
    Without these, Plotly auto-picks a "nice" interval based on the rendered
    plot's pixel size, which is why it can look inconsistent between panels
    or window sizes -- pass None to fall back to that auto behavior."""
    data_min = float(grid.values.min())
    data_max = float(grid.values.max())
    plotly_scale, zmin, zmax = colorscale.to_plotly_colorscale(data_min, data_max)

    tick_vals = list(colorscale.thresholds)
    tick_text = colorscale.tick_labels()[:-1]  # colorbar ticks label the boundaries only

    heatmap = go.Heatmap(
        x=grid.distances,
        y=grid.times,
        z=grid.values.T,  # values is (n_distance, n_time); z must be (n_y, n_x) = (n_time, n_distance)
        colorscale=plotly_scale,
        zmin=zmin,
        zmax=zmax,
        colorbar=dict(
            title=colorscale.units,
            tickmode="array",
            tickvals=tick_vals,
            ticktext=tick_text,
        ),
        hovertemplate="x=%{x}m<br>t=%{y}s<br>value=%{z}<extra></extra>",
    )

    fig = go.Figure(data=[heatmap])
    fig.update_layout(
        title=f"{grid.parameter_name} — {grid.scenario}",
        xaxis=dict(title="Distance (m)", dtick=x_dtick),
        yaxis=dict(title="Time (s)", dtick=y_dtick),
        margin=dict(l=60, r=40, t=60, b=140),  # b is fixed up front (not bumped conditionally) so the plot area
        # never resizes depending on whether exit icons happen to be drawn this render
        plot_bgcolor="white",
    )
    return fig


def build_empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{"text": message, "showarrow": False, "font": {"size": 16, "color": "#888"}}],
        plot_bgcolor="white",
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig


def add_reference_lines(
    fig: go.Figure,
    evac_start_t: float | None = None,
    exits: list[float] | None = None,
    label_side: str = "left",
) -> go.Figure:
    if evac_start_t is not None:
        # Evacuation START TIME is a moment in time -> horizontal line (constant t, y-axis).
        fig.add_shape(
            type="line",
            xref="paper",
            yref="y",
            x0=0,
            x1=1,
            y0=evac_start_t,
            y1=evac_start_t,
            line=dict(color="#FFD400", width=3, dash="dash"),
        )
        is_left = label_side != "right"
        fig.add_annotation(
            xref="paper",
            yref="y",
            x=0.01 if is_left else 0.99,
            y=evac_start_t,
            xanchor="left" if is_left else "right",
            yanchor="top",
            yshift=-4,
            text=f"<b>Evacuation start time, t = {evac_start_t:g}s</b>",
            showarrow=False,
            font=dict(size=14, color="yellow"),
            bgcolor="rgba(255,255,255,0.0)",
        )

    for exit_x in exits or []:
        # Exit DISTANCE is fixed along the tunnel -> vertical line (constant x, x-axis).
        fig.add_shape(
            type="line",
            xref="x",
            yref="paper",
            x0=exit_x,
            x1=exit_x,
            y0=0,
            y1=1,
            line=dict(color="#FF00FF", width=3, dash="dash"),
        )
    return fig


def add_exit_icons(
    fig: go.Figure,
    exits: list[float] | None,
    x_range: tuple[float, float],
    icon_path: str = "/assets/exit.png",
) -> go.Figure:
    """Places an exit icon below the x-axis at each exit distance, with a black
    arrow pointing up from the icon to the foot of that exit's magenta line."""
    if not exits:
        return fig

    span = max(x_range[1] - x_range[0], 1e-6)
    for exit_x in exits:
        fig.add_annotation(
            x=exit_x,
            y=0,
            xref="x",
            yref="paper",
            ax=0,
            ay=25,  # pixel offset: tail 45px below the plot's bottom edge
            showarrow=True,
            arrowhead=2,
            arrowsize=1.2,
            arrowwidth=2,
            arrowcolor="black",
            text="",
        )
        fig.add_layout_image(
            dict(
                source=icon_path,
                x=exit_x,
                y=-0.12,
                xref="x",
                yref="paper",
                xanchor="center",
                yanchor="middle",
                sizex=0.2 * span,
                sizey=0.1,
                layer="above",
            )
        )
    return fig


def add_occupant_icon(
    fig: go.Figure,
    segments: list,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    icon_path: str,
    size_frac: float = 0.15,
    offset_frac: float = 0.05,
) -> go.Figure:
    """Places an icon near the middle of the occupant's trajectory, nudged up
    (toward higher t) by offset_frac * y_span so it sits above the line rather
    than sitting directly on top of / blocking it."""
    points = [p for seg in segments for p in seg.points]
    if not points:
        return fig

    mid_t, mid_x = points[len(points) // 2]
    x_span = max(x_range[1] - x_range[0], 1e-6)
    y_span = max(y_range[1] - y_range[0], 1e-6)
    fig.add_layout_image(
        dict(
            source=icon_path,
            x=mid_x,
            y=mid_t + offset_frac * y_span,
            xref="x",
            yref="y",
            xanchor="center",
            yanchor="middle",
            sizex=size_frac * x_span,
            sizey=size_frac * y_span,
            layer="above",
        )
    )
    return fig


def add_path_traces(
    fig: go.Figure,
    segments: list,
    color: str = "black",
    label: str = "",
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    arrow_frac: float = 0.015,
) -> go.Figure:
    """segments: list of PathSegment(points=[(t, x), ...], style='solid'|'dashed')."""
    x_span = max(x_range[1] - x_range[0], 1e-6) if x_range else 1.0
    y_span = max(y_range[1] - y_range[0], 1e-6) if y_range else 1.0

    for i, seg in enumerate(segments):
        if not seg.points:
            continue
        ts = [p[0] for p in seg.points]
        xs = [p[1] for p in seg.points]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ts,
                mode="lines",
                line=dict(color=color, width=3, dash="solid" if seg.style == "solid" else "dash"),
                name=f"{label} segment {i + 1}".strip(),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        if len(seg.points) >= 2:
            # Arrowhead at the end of every segment (solid and any continued-dashed legs).
            # The underlying simulation points are only dt=1s apart, so using just the
            # last two literal points is often near-degenerate, and extrapolating a
            # synthetic straight line from them drifts off a curved path. Instead, walk
            # backward through the segment's REAL points, accumulating normalized
            # (axis-fraction) distance, until the tail has moved far enough to be
            # visible -- both endpoints then always lie exactly on the rendered curve.
            t_end, x_end = seg.points[-1]
            tail_t, tail_x = seg.points[-2]
            accumulated = 0.0
            for j in range(len(seg.points) - 2, -1, -1):
                pt_t, pt_x = seg.points[j]
                accumulated = (((x_end - pt_x) / x_span) ** 2 + ((t_end - pt_t) / y_span) ** 2) ** 0.5
                tail_t, tail_x = pt_t, pt_x
                if accumulated >= arrow_frac:
                    break

            if accumulated < 1e-9:
                continue

            fig.add_annotation(
                x=x_end,
                y=t_end,
                xref="x",
                yref="y",
                ax=tail_x,
                ay=tail_t,
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=1.0,
                arrowwidth=2.0,
                arrowcolor=color,
                text="",
            )
    return fig
