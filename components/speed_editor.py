"""Editable piecewise-linear speed-vs-opacity table.

There is a single shared instance (owner="shared") used by all occupants'
computed mode, so calibrating it once affects every occupant consistently.
"""
from __future__ import annotations

import base64
import json

import dash
from dash import ALL, Input, Output, State, ctx, dcc, html

from trajectory.speed_model import (
    DEFAULT_PRESET_NAME,
    SpeedTable,
    default_speed_table,
    get_speed_table,
    list_presets,
    load_preset,
    save_preset,
)

MIN_ROWS = 2
MAX_ROWS = 10

SHARED_SPEED_OWNER = "shared"


def _store_id(owner: str) -> dict:
    return {"type": "speed-store", "owner": owner}


def _rows_container_id(owner: str) -> dict:
    return {"type": "speed-rows", "owner": owner}


def _opacity_id(owner: str, index: int) -> dict:
    return {"type": "speed-opacity", "owner": owner, "index": index}


def _speed_id(owner: str, index: int) -> dict:
    return {"type": "speed-speed", "owner": owner, "index": index}


def _add_btn_id(owner: str) -> dict:
    return {"type": "speed-add", "owner": owner}


def _remove_btn_id(owner: str) -> dict:
    return {"type": "speed-remove", "owner": owner}


def _save_btn_id(owner: str) -> dict:
    return {"type": "speed-save", "owner": owner}


def _preset_name_id(owner: str) -> dict:
    return {"type": "speed-preset-name", "owner": owner}


def _preset_dropdown_id(owner: str) -> dict:
    return {"type": "speed-preset-dropdown", "owner": owner}


def _load_btn_id(owner: str) -> dict:
    return {"type": "speed-load", "owner": owner}


def _download_btn_id(owner: str) -> dict:
    return {"type": "speed-download-btn", "owner": owner}


def _download_id(owner: str) -> dict:
    return {"type": "speed-download", "owner": owner}


def _file_upload_id(owner: str) -> dict:
    return {"type": "speed-file-upload", "owner": owner}


def _reset_btn_id(owner: str) -> dict:
    return {"type": "speed-reset", "owner": owner}


def _status_id(owner: str) -> dict:
    return {"type": "speed-status", "owner": owner}


def _preset_options(owner: str) -> list[dict]:
    return [{"label": n, "value": n} for n in list_presets(owner)]


def store_id(owner: str) -> dict:
    return _store_id(owner)


def build_speed_editor(owner: str) -> html.Div:
    table = get_speed_table(owner)
    return html.Div(
        [
            html.H4("Speed vs opacity model (shared, all occupants)"),
            html.P(
                "Placeholder breakpoints — calibrate to CAMATT's opacity scale before relying on this.",
                style={"fontSize": "11px", "color": "#a00"},
            ),
            dcc.Store(id=_store_id(owner), data=table.to_dict()),
            html.Div(id=_rows_container_id(owner)),
            html.Div(
                [
                    html.Button("+ point", id=_add_btn_id(owner), n_clicks=0),
                    html.Button("- point", id=_remove_btn_id(owner), n_clicks=0),
                    html.Button("Reset to default", id=_reset_btn_id(owner), n_clicks=0),
                ],
                style={"display": "flex", "gap": "8px", "marginTop": "6px", "flexWrap": "wrap"},
            ),
            html.Div(
                [
                    dcc.Input(
                        id=_preset_name_id(owner),
                        type="text",
                        value=DEFAULT_PRESET_NAME,
                        placeholder="preset name",
                        style={"width": "130px"},
                    ),
                    html.Button("Save preset", id=_save_btn_id(owner), n_clicks=0),
                    dcc.Dropdown(
                        id=_preset_dropdown_id(owner),
                        options=_preset_options(owner),
                        placeholder="Saved presets…",
                        style={"width": "180px"},
                    ),
                    html.Button("Load", id=_load_btn_id(owner), n_clicks=0),
                ],
                style={"display": "flex", "gap": "8px", "marginTop": "6px", "alignItems": "center", "flexWrap": "wrap"},
            ),
            html.Div(
                [
                    html.Button("Download preset (.json)", id=_download_btn_id(owner), n_clicks=0),
                    dcc.Download(id=_download_id(owner)),
                    dcc.Upload(
                        id=_file_upload_id(owner),
                        children=html.Div("Drag & drop or click to load a .json speed table file"),
                        style={
                            "width": "240px",
                            "height": "32px",
                            "lineHeight": "32px",
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderRadius": "4px",
                            "textAlign": "center",
                            "fontSize": "10px",
                        },
                    ),
                ],
                style={"display": "flex", "gap": "8px", "marginTop": "6px", "alignItems": "center", "flexWrap": "wrap"},
            ),
            html.Div(id=_status_id(owner), style={"fontSize": "12px", "color": "#666"}),
        ],
        style={"border": "1px solid #ddd", "padding": "10px", "borderRadius": "6px"},
    )


def _render_rows(owner: str, data: dict) -> list:
    breakpoints = data["breakpoints"]
    speeds = data["speeds"]
    rows = [
        html.Div(
            [html.Span("opacity", style={"width": "80px", "fontWeight": "bold"}), html.Span("speed (m/s)", style={"fontWeight": "bold"})],
            style={"display": "flex", "gap": "10px", "fontSize": "12px"},
        )
    ]
    for i, (op, sp) in enumerate(zip(breakpoints, speeds)):
        rows.append(
            html.Div(
                [
                    dcc.Input(type="number", value=op, id=_opacity_id(owner, i), debounce=True, style={"width": "80px"}),
                    dcc.Input(type="number", value=sp, id=_speed_id(owner, i), debounce=True, style={"width": "80px"}),
                ],
                style={"display": "flex", "gap": "10px", "marginBottom": "3px"},
            )
        )
    return rows


def register_speed_editor_callbacks(app, owner: str) -> None:
    sid = _store_id(owner)
    rid = _rows_container_id(owner)

    @app.callback(Output(rid, "children"), Input(sid, "data"))
    def _render(data):
        return _render_rows(owner, data)

    @app.callback(
        Output(_preset_dropdown_id(owner), "options", allow_duplicate=True),
        Input(sid, "data"),
        prevent_initial_call="initial_duplicate",
    )
    def _refresh_preset_options(_data):
        return _preset_options(owner)

    @app.callback(
        Output(sid, "data", allow_duplicate=True),
        Input(_add_btn_id(owner), "n_clicks"),
        Input(_remove_btn_id(owner), "n_clicks"),
        Input(_reset_btn_id(owner), "n_clicks"),
        Input({"type": "speed-opacity", "owner": owner, "index": ALL}, "value"),
        Input({"type": "speed-speed", "owner": owner, "index": ALL}, "value"),
        State(sid, "data"),
        prevent_initial_call=True,
    )
    def _update(_add, _remove, _reset, opacity_values, speed_values, data):
        trigger = ctx.triggered_id

        if trigger == _reset_btn_id(owner):
            return default_speed_table().to_dict()

        if trigger == _add_btn_id(owner):
            breakpoints = list(data["breakpoints"])
            speeds = list(data["speeds"])
            if len(breakpoints) < MAX_ROWS:
                breakpoints.append(breakpoints[-1] + 0.1 if breakpoints else 0.1)
                speeds.append(0.0)
            return {"breakpoints": breakpoints, "speeds": speeds, "units": data.get("units", "m/s")}

        if trigger == _remove_btn_id(owner):
            breakpoints = list(data["breakpoints"])
            speeds = list(data["speeds"])
            if len(breakpoints) > MIN_ROWS:
                breakpoints.pop()
                speeds.pop()
            return {"breakpoints": breakpoints, "speeds": speeds, "units": data.get("units", "m/s")}

        if any(v is None for v in opacity_values) or any(v is None for v in speed_values):
            return data

        breakpoints = [float(v) for v in opacity_values]
        speeds = [float(v) for v in speed_values]
        if len(breakpoints) != len(speeds) or breakpoints != sorted(breakpoints):
            return data
        return {"breakpoints": breakpoints, "speeds": speeds, "units": data.get("units", "m/s")}

    @app.callback(
        Output(_status_id(owner), "children", allow_duplicate=True),
        Output(_preset_dropdown_id(owner), "options", allow_duplicate=True),
        Input(_save_btn_id(owner), "n_clicks"),
        State(sid, "data"),
        State(_preset_name_id(owner), "value"),
        prevent_initial_call=True,
    )
    def _save(_n, data, name):
        table = SpeedTable.from_dict(data)
        preset_name = (name or "").strip() or DEFAULT_PRESET_NAME
        save_preset(owner, table, name=preset_name)
        return f"Saved speed preset '{preset_name}'.", _preset_options(owner)

    @app.callback(
        Output(sid, "data", allow_duplicate=True),
        Output(_status_id(owner), "children", allow_duplicate=True),
        Input(_load_btn_id(owner), "n_clicks"),
        State(_preset_dropdown_id(owner), "value"),
        prevent_initial_call=True,
    )
    def _load(_n, name):
        if not name:
            return dash.no_update, "Pick a preset from the dropdown first."
        table = load_preset(owner, name=name)
        if table is None:
            return dash.no_update, f"Preset '{name}' not found."
        return table.to_dict(), f"Loaded speed preset '{name}'."

    @app.callback(
        Output(_download_id(owner), "data"),
        Input(_download_btn_id(owner), "n_clicks"),
        State(sid, "data"),
        State(_preset_name_id(owner), "value"),
        prevent_initial_call=True,
    )
    def _download(_n, data, name):
        fname_slug = "".join(c if c.isalnum() else "_" for c in (name or "speed_table").lower()).strip("_") or "speed_table"
        return dcc.send_string(json.dumps(data, indent=2), filename=f"{fname_slug}_speed_table.json")

    @app.callback(
        Output(sid, "data", allow_duplicate=True),
        Output(_status_id(owner), "children", allow_duplicate=True),
        Input(_file_upload_id(owner), "contents"),
        State(_file_upload_id(owner), "filename"),
        prevent_initial_call=True,
    )
    def _upload(contents, filename):
        try:
            _header, b64data = contents.split(",", 1)
            text = base64.b64decode(b64data).decode("utf-8-sig")
            table = SpeedTable.from_dict(json.loads(text))
        except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
            return dash.no_update, f"Error loading {filename}: {e}"
        return table.to_dict(), f"Loaded speed table from {filename}."
