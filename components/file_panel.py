"""Upload/select the three CAMATT X-T CSVs for one scenario (opacity, temperature, CO).

Each slot gets its own dcc.Upload + dcc.Store holding the parsed XTGrid as a
dict (JSON-serializable). Opacity is the slot the trajectory integrator reads
from; temperature/CO are optional extra panels that share the same overlay.
"""
from __future__ import annotations

import base64

from dash import Input, Output, State, dcc, html

from data.xt_parser import XTGrid, parse_xt_csv_text

SLOTS = ["opacity", "temperature", "co"]
SLOT_LABELS = {"opacity": "Air opacity (1/m)", "temperature": "Air temperature (C)", "co": "CO concentration (ppm)"}


def grid_store_id(slot: str) -> dict:
    return {"type": "grid-store", "slot": slot}


def _upload_id(slot: str) -> dict:
    return {"type": "grid-upload", "slot": slot}


def _status_id(slot: str) -> dict:
    return {"type": "grid-status", "slot": slot}


def build_file_panel() -> html.Div:
    rows = []
    for slot in SLOTS:
        rows.append(
            html.Div(
                [
                    html.Label(f"{SLOT_LABELS[slot]} CSV"),
                    dcc.Upload(
                        id=_upload_id(slot),
                        children=html.Div("Drag & drop or click to select"),
                        style={
                            "width": "100%",
                            "height": "36px",
                            "lineHeight": "36px",
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderRadius": "4px",
                            "textAlign": "center",
                            "fontSize": "12px",
                        },
                    ),
                    html.Div(id=_status_id(slot), style={"fontSize": "12px", "color": "#666"}),
                ],
                style={"marginBottom": "8px"},
            )
        )
    return html.Div(
        [html.H4("Scenario files")] + rows,
        style={"border": "1px solid #ddd", "padding": "10px", "borderRadius": "6px"},
    )


def register_file_panel_callbacks(app) -> None:
    for slot in SLOTS:

        @app.callback(
            Output(grid_store_id(slot), "data"),
            Output(_status_id(slot), "children"),
            Input(_upload_id(slot), "contents"),
            State(_upload_id(slot), "filename"),
            prevent_initial_call=True,
        )
        def _on_upload(contents, filename, slot=slot):
            try:
                _header, b64data = contents.split(",", 1)
                text = base64.b64decode(b64data).decode("utf-8-sig")
                grid = parse_xt_csv_text(text, source_name=filename or slot)
            except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
                return None, f"Error parsing {filename}: {e}"
            return grid.to_dict(), f"Loaded {filename} ({grid.parameter_name}, {len(grid.distances)}x{len(grid.times)})."
