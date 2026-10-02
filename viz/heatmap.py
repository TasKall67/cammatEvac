"""Build the X-T heatmap figure and overlay evacuation reference lines / paths on it.

Axis convention matches CAMATT's own trajectory plots: distance (m) on the X axis,
time (s) on the Y axis (see Vasilikou_LB_Q1_100MW180m_T_left_Trajectories.jpg).
"""
from __future__ import annotations

import base64
import io
import mimetypes
from functools import lru_cache
from pathlib import Path

import plotly.graph_objects as go
from PIL import Image, ImageDraw, ImageFont

from data.xt_parser import XTGrid
from viz.colorscale import ColorScale

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


@lru_cache(maxsize=None)
def _asset_data_uri(icon_path: str) -> str:
    """Kaleido's headless PNG export has no Dash server/page context, so a
    relative "/assets/..." image source (which resolves fine in the live
    browser) fails to load and the icon is silently missing from exports.
    Embedding the image as a base64 data URI works in both contexts."""
    file_path = ASSETS_DIR / Path(icon_path).name
    mime, _ = mimetypes.guess_type(file_path.name)
    data = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >=10.1
    except TypeError:
        return ImageFont.load_default()  # older Pillow: fixed small bitmap font


@lru_cache(maxsize=None)
def _tunnel_icon_with_length_uri(icon_path: str, length_label: str) -> str:
    """Bakes the tunnel-length text directly onto the icon image (in its green
    caption band, measured empirically: ~65-96% down, ~20-80% across) instead
    of layering a separate Plotly annotation on top. This way the text scales
    together with the icon whenever its display size changes, and sidesteps a
    Kaleido quirk where annotations placed near a layout image positioned at
    the exact axis boundary get clipped."""
    file_path = ASSETS_DIR / Path(icon_path).name
    img = Image.open(file_path).convert("RGBA")
    w, h = img.size
    band_top, band_bottom = 0.66, 0.96

    font = _load_font(int(h * 0.18))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), length_label, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    band_center_y = h * (band_top + band_bottom) / 2
    draw.text(
        (w / 2 - text_w / 2 - bbox[0], band_center_y - text_h / 2 - bbox[1]),
        length_label,
        fill="white",
        font=font,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


def build_heatmap_figure(
    grid: XTGrid,
    colorscale: ColorScale,
    x_dtick: float | None = 100,
    y_dtick: float | None = 200,
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
        margin=dict(l=60, r=40, t=60, b=170),  # b is fixed up front (not bumped conditionally) so the plot area
        # never resizes depending on whether exit icons happen to be drawn this render; 170 (up from 140)
        # leaves room for the tunnel-icon length label below the exit icons' row
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
    occupant_subscript: str = "",
    label_above: bool = False,
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
        t_label = f"t<sub>{occupant_subscript}</sub>" if occupant_subscript else "t"
        # label_above lets two occupants with close evac_start_t values sit on opposite
        # sides of their own line instead of overlapping each other.
        yanchor = "bottom" if label_above else "top"
        yshift = 4 if label_above else -4
        fig.add_annotation(
            xref="paper",
            yref="y",
            x=0.01 if is_left else 0.99,
            y=evac_start_t,
            xanchor="left" if is_left else "right",
            yanchor=yanchor,
            yshift=yshift,
            text=f"<b>Χρόνος έναρξης εκκένωσης, {t_label} = {evac_start_t:g}s</b>",
            showarrow=False,
            font=dict(size=16, color="yellow"),
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
            y=-0.018,
            xref="x",
            yref="paper",
            ax=0,
            ay=40,  # pixel offset: tail starts below the x-axis tick labels, not on top of them
            showarrow=True,
            arrowhead=2,
            arrowsize=1.2,
            arrowwidth=2,
            arrowcolor="black",
            text="",
        )
        fig.add_layout_image(
            dict(
                source=_asset_data_uri(icon_path),
                x=exit_x,
                y=-0.12,
                xref="x",
                yref="paper",
                xanchor="center",
                yanchor="middle",
                sizex=0.04 * span,
                sizey=0.1,
                layer="above",
            )
        )
    return fig


def add_tunnel_icons(
    fig: go.Figure,
    x_range: tuple[float, float],
    icon_path: str = "/assets/Tunnel_Icon.png",
) -> go.Figure:
    """Places the tunnel-portal icon at both ends of the x-axis (start and end
    of the tunnel), each labeled with its own distance value (0 at the start,
    the tunnel's full length at the end) baked into the icon's own green band
    via _tunnel_icon_with_length_uri -- so resizing the icon (sizex/sizey
    below) scales the text right along with it, as one image."""
    span = max(x_range[1] - x_range[0], 1e-6)
    sizex = 0.04 * span  # icon width, fraction of the x-axis (distance) span -- matches add_exit_icons
    sizey = 0.1  # icon height, fraction of the plot's paper height -- matches add_exit_icons
    # Kaleido clips a layout image positioned at the exact axis boundary
    # (x_range[0]/[1] precisely) -- a small inward nudge avoids that rendering
    # quirk while still reading as "at the tunnel ends".
    edge_nudge = 0.015 * span

    for boundary_x, icon_x in (
        (x_range[0], x_range[0] + edge_nudge),
        (x_range[1], x_range[1] - edge_nudge),
    ):
        icon_src = _tunnel_icon_with_length_uri(icon_path, f"{round(boundary_x)}m")
        # Arrow points at the exact tunnel endpoint (0 or the full length), same style
        # as add_exit_icons' arrows -- the icon itself sits at the nudged position just
        # beside it (see edge_nudge above), but the arrow marks the true boundary.
        fig.add_annotation(
            x=boundary_x,
            y=-0.018,
            xref="x",
            yref="paper",
            ax=0,
            ay=40,
            showarrow=True,
            arrowhead=2,
            arrowsize=1.2,
            arrowwidth=2,
            arrowcolor="black",
            text="",
        )
        fig.add_layout_image(
            dict(
                source=icon_src,
                x=icon_x,
                y=-0.12,
                xref="x",
                yref="paper",
                xanchor="center",
                yanchor="middle",
                sizex=sizex,
                sizey=sizey,
                layer="below",
            )
        )
    return fig


def add_fire_zone(
    fig: go.Figure,
    fire_position: float,
    zone_width: float = 100,
    line_color: str = "white",
    label: str = "Ζώνη 100m",
) -> go.Figure:
    """Two dashed-dot vertical lines bracketing a zone_width-meter zone ending
    at the fire's position (fire_position - zone_width to fire_position), with
    a vertically-oriented label centered between them. Uses "dashdot" rather
    than the evacuation-start-time line's "dash" so the two are visually
    distinct at a glance."""
    x_far = fire_position - zone_width
    for x in (x_far, fire_position):
        fig.add_shape(
            type="line",
            xref="x",
            yref="paper",
            x0=x,
            x1=x,
            y0=0,
            y1=1,
            line=dict(color=line_color, width=3, dash="dashdot"),
        )
    fig.add_annotation(
        x=(x_far + fire_position) / 2,
        y=0.5,
        xref="x",
        yref="paper",
        xanchor="center",
        yanchor="middle",
        text=label,
        showarrow=False,
        textangle=-90,
        font=dict(size=26, color="white", family="Arial Black"),
    )
    return fig


def add_occupant_icon(
    fig: go.Figure,
    segments: list,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    icon_path: str,
    size_frac: float = 0.08,
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
            source=_asset_data_uri(icon_path),
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
    incapacitated: bool = False,
) -> go.Figure:
    """segments: list of PathSegment(points=[(t, x), ...], style='solid'|'dashed').
    incapacitated=True marks the END of the LAST segment with a red X instead of
    the normal arrowhead -- segments should already be truncated by the caller
    to stop exactly at the point cumulative FED crossed the tenability limit."""
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

        if incapacitated and i == len(segments) - 1:
            t_end, x_end = seg.points[-1]
            fig.add_trace(
                go.Scatter(
                    x=[x_end],
                    y=[t_end],
                    mode="markers",
                    marker=dict(symbol="x-thin", size=16, color="red", line=dict(width=4, color="red")),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            continue  # incapacitated -- no arrowhead, occupant can't proceed past this point

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
