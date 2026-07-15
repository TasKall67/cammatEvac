from __future__ import annotations

from datetime import datetime
from pathlib import Path

import dash
from dash import ALL, Input, Output, State, ctx, dcc, html

from components.file_panel import (
    SLOT_LABELS,
    SLOTS,
    build_file_panel,
    grid_store_id,
    register_file_panel_callbacks,
)
from components.legend_editor import build_legend_panel, register_legend_callbacks
from components.occupant_panel import (
    build_occupant_panel,
    refs_store_id,
    register_occupant_callbacks,
    segments_store_id,
)
from components.speed_editor import SHARED_SPEED_OWNER, build_speed_editor, register_speed_editor_callbacks
from data.xt_parser import XTGrid, parse_xt_csv
from trajectory.segment import PathSegment
from viz.colorscale import ColorScale, get_scale_for
from viz.heatmap import (
    add_exit_icons,
    add_occupant_icon,
    add_path_traces,
    add_reference_lines,
    build_empty_figure,
    build_heatmap_figure,
)
from viz.png_export import get_exporter

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_CSV = BASE_DIR / "Test03_Fire mode_XT.csv"
OCCUPANT_ICON = "/assets/EvacuationPath.jpg"
EXIT_ICON = "/assets/ExitDoor.png"

OCCUPANTS = [
    {"id": "1", "label": "Occupant 1", "color": "black"},
    {"id": "2", "label": "Occupant 2", "color": "black"},
]

app = dash.Dash(__name__)
app.title = "cammatEvac"
server = app.server  # WSGI entrypoint for gunicorn (`gunicorn app:server`)

_sample_grid = parse_xt_csv(SAMPLE_CSV)


def _heatmap_id(slot: str) -> dict:
    return {"type": "param-heatmap", "slot": slot}


def _export_btn_id(slot: str) -> dict:
    return {"type": "param-export", "slot": slot}


def _export_status_id(slot: str) -> dict:
    return {"type": "param-export-status", "slot": slot}


def _export_download_id(slot: str) -> dict:
    return {"type": "param-export-download", "slot": slot}


def _label_side_id(slot: str) -> dict:
    return {"type": "evac-label-side", "slot": slot}


def build_panel_figure(
    slot: str,
    grid_data: dict | None,
    legend_data: dict | None,
    occupants_data,
    label_side: str = "left",
):
    if grid_data is None:
        return build_empty_figure(f"No {SLOT_LABELS[slot]} CSV loaded yet.")

    grid = XTGrid.from_dict(grid_data)
    scale = ColorScale.from_dict(legend_data) if legend_data else get_scale_for(SLOT_LABELS[slot])
    fig = build_heatmap_figure(grid, scale)
    x_range = (min(grid.distances), max(grid.distances))
    y_range = (min(grid.times), max(grid.times))

    for o, segments_data, refs_data in occupants_data:
        refs_data = refs_data or {}
        fig = add_reference_lines(
            fig,
            evac_start_t=refs_data.get("evac_start_t"),
            exits=refs_data.get("exits"),
            label_side=label_side,
        )
        fig = add_exit_icons(fig, refs_data.get("exits"), x_range, icon_path=EXIT_ICON)
        segments = [PathSegment.from_dict(s) for s in (segments_data or [])]
        fig = add_path_traces(fig, segments, color=o["color"], label=o["label"], x_range=x_range, y_range=y_range)
        fig = add_occupant_icon(fig, segments, x_range, y_range, icon_path=OCCUPANT_ICON)

    return fig


app.layout = html.Div(
    [
        html.H2("cammatEvac — Tunnel Fire/Evacuation Paths Visualization"),
        dcc.Store(id="evac-label-side-store", data="left"),
        html.Div(
            [
                dcc.Store(id=grid_store_id("opacity"), data=_sample_grid.to_dict()),
                dcc.Store(id=grid_store_id("temperature")),
                dcc.Store(id=grid_store_id("co")),
                build_file_panel(),
            ]
        ),
        html.Div(
            [
                html.Div(
                    dcc.Tabs(
                        id="param-tabs",
                        value=SLOTS[0],
                        children=[
                            dcc.Tab(
                                label=SLOT_LABELS[slot],
                                value=slot,
                                children=[
                                    dcc.Graph(id=_heatmap_id(slot), style={"height": "75vh"}),
                                    html.Div(
                                        [
                                            html.Label(
                                                "Evacuation start time label side:",
                                                style={"marginRight": "8px", "fontSize": "13px"},
                                            ),
                                            dcc.RadioItems(
                                                id=_label_side_id(slot),
                                                options=[
                                                    {"label": " Left", "value": "left"},
                                                    {"label": " Right", "value": "right"},
                                                ],
                                                value="left",
                                                labelStyle={"display": "inline-block", "marginRight": "12px"},
                                            ),
                                        ],
                                        style={"marginTop": "6px", "marginBottom": "10px"},
                                    ),
                                    html.Button("Export PNG", id=_export_btn_id(slot), n_clicks=0),
                                    dcc.Download(id=_export_download_id(slot)),
                                    html.Span(id=_export_status_id(slot), style={"marginLeft": "8px", "fontSize": "12px", "color": "#666"}),
                                    build_legend_panel(SLOT_LABELS[slot]),
                                ],
                            )
                            for slot in SLOTS
                        ],
                    ),
                    style={"flex": "1"},
                ),
                html.Div(
                    [build_speed_editor(SHARED_SPEED_OWNER)] + [build_occupant_panel(o["id"], o["label"]) for o in OCCUPANTS],
                    style={"width": "340px", "display": "flex", "flexDirection": "column", "gap": "16px"},
                ),
            ],
            style={"display": "flex", "gap": "20px"},
        ),
    ],
    style={"fontFamily": "sans-serif", "margin": "20px"},
)

register_file_panel_callbacks(app)
for slot in SLOTS:
    register_legend_callbacks(app, SLOT_LABELS[slot])
register_speed_editor_callbacks(app, SHARED_SPEED_OWNER)
for o in OCCUPANTS:
    register_occupant_callbacks(app, o["id"])


@app.callback(
    Output("evac-label-side-store", "data"),
    Input({"type": "evac-label-side", "slot": ALL}, "value"),
    prevent_initial_call=True,
)
def _sync_label_side_store(_values):
    # only the RadioItems the user actually clicked carries the new value
    return ctx.triggered[0]["value"]


@app.callback(
    Output({"type": "evac-label-side", "slot": ALL}, "value"),
    Input("evac-label-side-store", "data"),
)
def _sync_label_side_radios(label_side):
    n = len(SLOTS)
    return [label_side] * n


for slot in SLOTS:

    @app.callback(
        Output(_heatmap_id(slot), "figure"),
        Input(grid_store_id(slot), "data"),
        Input({"type": "legend-store", "param": SLOT_LABELS[slot]}, "data"),
        Input("evac-label-side-store", "data"),
        [Input(segments_store_id(o["id"]), "data") for o in OCCUPANTS],
        [Input(refs_store_id(o["id"]), "data") for o in OCCUPANTS],
        prevent_initial_call=False,
    )
    def _update_panel(grid_data, legend_data, label_side, *occupant_data, slot=slot):
        n = len(OCCUPANTS)
        segs = occupant_data[:n]
        refs = occupant_data[n:]
        occupants_data = list(zip(OCCUPANTS, segs, refs))
        return build_panel_figure(slot, grid_data, legend_data, occupants_data, label_side=label_side or "left")

    @app.callback(
        Output(_export_download_id(slot), "data"),
        Output(_export_status_id(slot), "children"),
        Input(_export_btn_id(slot), "n_clicks"),
        State(_heatmap_id(slot), "figure"),
        prevent_initial_call=True,
    )
    def _export_panel(_n, figure, slot=slot):
        if not figure or not figure.get("data"):
            return dash.no_update, "Nothing to export yet."
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{slot}_{timestamp}.png"
        png_bytes = get_exporter().render_png(figure, width=1400, height=900, scale=2)
        return dcc.send_bytes(png_bytes, filename=filename), f"Downloaded {filename}"


if __name__ == "__main__":
    app.run(debug=False, port=8050)
