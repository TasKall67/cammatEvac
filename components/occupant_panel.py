"""Per-occupant trajectory panel: evac start time, exit list, manual waypoints
or computed (speed-vs-opacity) mode.

Each occupant gets its own dcc.Store holding a list of PathSegment dicts
(the shared overlay format consumed by viz.heatmap.add_path_traces) plus the
evac-start-time / exit-list values used for the reference lines.
"""
from __future__ import annotations

from dash import Input, Output, State, dcc, html

from components.file_panel import grid_store_id
from components.speed_editor import SHARED_SPEED_OWNER
from components.speed_editor import store_id as speed_store_id
from data.xt_parser import XTGrid
from trajectory.integrator import compute_path
from trajectory.segment import PathSegment
from trajectory.speed_model import SpeedTable

MODE_MANUAL = "manual"
MODE_COMPUTED = "computed"


def _segments_store_id(occupant_id: str) -> dict:
    return {"type": "occupant-segments", "occupant": occupant_id}


def _refs_store_id(occupant_id: str) -> dict:
    return {"type": "occupant-refs", "occupant": occupant_id}


def _mode_id(occupant_id: str) -> dict:
    return {"type": "occupant-mode", "occupant": occupant_id}


def _evac_start_id(occupant_id: str) -> dict:
    return {"type": "occupant-evac-start", "occupant": occupant_id}


def _start_x_id(occupant_id: str) -> dict:
    return {"type": "occupant-start-x", "occupant": occupant_id}


def _exits_id(occupant_id: str) -> dict:
    return {"type": "occupant-exits", "occupant": occupant_id}


def _waypoints_id(occupant_id: str) -> dict:
    return {"type": "occupant-waypoints", "occupant": occupant_id}


def _apply_btn_id(occupant_id: str) -> dict:
    return {"type": "occupant-apply", "occupant": occupant_id}


def _status_id(occupant_id: str) -> dict:
    return {"type": "occupant-status", "occupant": occupant_id}


def segments_store_id(occupant_id: str) -> dict:
    return _segments_store_id(occupant_id)


def refs_store_id(occupant_id: str) -> dict:
    return _refs_store_id(occupant_id)


def build_occupant_panel(occupant_id: str, label: str) -> html.Div:
    return html.Div(
        [
            html.H4(label),
            dcc.Store(id=_segments_store_id(occupant_id), data=[]),
            dcc.Store(id=_refs_store_id(occupant_id), data={"evac_start_t": None, "exits": []}),
            dcc.RadioItems(
                id=_mode_id(occupant_id),
                options=[
                    {"label": " Manual waypoints", "value": MODE_MANUAL},
                    {"label": " Computed (speed vs opacity)", "value": MODE_COMPUTED},
                ],
                value=MODE_MANUAL,
                labelStyle={"display": "block"},
            ),
            html.Label("Evacuation start time (s)", style={"marginTop": "6px", "display": "block"}),
            dcc.Input(type="number", id=_evac_start_id(occupant_id), placeholder="e.g. 80", style={"width": "100%"}),
            html.Label("Exit distance(s) (m), comma-separated, nearest first", style={"marginTop": "6px", "display": "block"}),
            dcc.Input(type="text", id=_exits_id(occupant_id), placeholder="e.g. 245, 420", style={"width": "100%"}),
            html.Div(
                [
                    html.Label("Manual waypoints: one 'distance,time' pair per line", style={"marginTop": "6px", "display": "block"}),
                    dcc.Textarea(
                        id=_waypoints_id(occupant_id),
                        placeholder="0,80\n50,140\n120,260",
                        style={"width": "100%", "height": "80px"},
                    ),
                ],
                id={"type": "occupant-manual-section", "occupant": occupant_id},
            ),
            html.Div(
                [
                    html.Label("Start distance (m)", style={"marginTop": "6px", "display": "block"}),
                    dcc.Input(type="number", id=_start_x_id(occupant_id), placeholder="e.g. 0", style={"width": "100%"}),
                    html.P(
                        "Speed vs opacity model is shared across all occupants — edit it once above.",
                        style={"fontSize": "11px", "color": "#666", "marginTop": "6px"},
                    ),
                ],
                id={"type": "occupant-computed-section", "occupant": occupant_id},
                style={"display": "none"},
            ),
            html.Button("Apply", id=_apply_btn_id(occupant_id), n_clicks=0, style={"marginTop": "6px"}),
            html.Div(id=_status_id(occupant_id), style={"fontSize": "12px", "color": "#666"}),
        ],
        style={"border": "1px solid #ddd", "padding": "10px", "borderRadius": "6px"},
    )


def _parse_waypoints(text: str) -> list[tuple[float, float]]:
    points = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace(";", ",").split(",")]
        if len(parts) != 2:
            raise ValueError(f"Expected 'distance,time' pair, got {line!r}")
        x, t = float(parts[0]), float(parts[1])
        points.append((t, x))
    points.sort(key=lambda p: p[0])
    return points


def _parse_exits(text: str) -> list[float]:
    if not text:
        return []
    return [float(v.strip()) for v in text.split(",") if v.strip()]


def register_occupant_callbacks(app, occupant_id: str) -> None:
    @app.callback(
        Output({"type": "occupant-manual-section", "occupant": occupant_id}, "style"),
        Output({"type": "occupant-computed-section", "occupant": occupant_id}, "style"),
        Input(_mode_id(occupant_id), "value"),
    )
    def _toggle_mode(mode):
        if mode == MODE_COMPUTED:
            return {"display": "none"}, {"display": "block"}
        return {"display": "block"}, {"display": "none"}

    @app.callback(
        Output(_segments_store_id(occupant_id), "data"),
        Output(_refs_store_id(occupant_id), "data"),
        Output(_status_id(occupant_id), "children"),
        Input(_apply_btn_id(occupant_id), "n_clicks"),
        State(_mode_id(occupant_id), "value"),
        State(_waypoints_id(occupant_id), "value"),
        State(_evac_start_id(occupant_id), "value"),
        State(_exits_id(occupant_id), "value"),
        State(_start_x_id(occupant_id), "value"),
        State(speed_store_id(SHARED_SPEED_OWNER), "data"),
        State(grid_store_id("opacity"), "data"),
        prevent_initial_call=True,
    )
    def _apply(_n, mode, waypoints_text, evac_start_t, exits_text, start_x, speed_data, opacity_grid_data):
        try:
            exits = _parse_exits(exits_text)
        except ValueError as e:
            return [], {"evac_start_t": evac_start_t, "exits": []}, f"Error: {e}"

        refs = {"evac_start_t": evac_start_t, "exits": exits}

        if mode == MODE_MANUAL:
            try:
                points = _parse_waypoints(waypoints_text)
            except ValueError as e:
                return [], refs, f"Error: {e}"
            if not points:
                return [], refs, "No waypoints entered."
            segment = PathSegment(points=points, style="solid")
            return [segment.to_dict()], refs, f"Applied {len(points)} waypoint(s)."

        # computed mode
        if start_x is None or evac_start_t is None:
            return [], refs, "Error: start distance and evacuation start time are required."
        if not exits:
            return [], refs, "Error: at least one exit distance is required."
        if opacity_grid_data is None:
            return [], refs, "Error: no opacity CSV loaded — computed mode needs it to drive the speed model."

        opacity_grid = XTGrid.from_dict(opacity_grid_data)
        speed_table = SpeedTable.from_dict(speed_data)
        segments = compute_path(opacity_grid, float(start_x), float(evac_start_t), exits, speed_table, dt=1.0)
        if not segments:
            return [], refs, "Computation produced no path."
        total_points = sum(len(s.points) for s in segments)
        return (
            [s.to_dict() for s in segments],
            refs,
            f"Computed {len(segments)} segment(s), {total_points} point(s).",
        )
