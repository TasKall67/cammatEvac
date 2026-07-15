"""Editable, per-parameter discrete color legend (breakpoints + colors).

Layout: for parameter P this renders a dcc.Store holding the ColorScale as a
dict, a row of [color swatch, threshold input] pairs terminated by one more
color swatch (the ">last threshold" band), plus add/remove/save/reset controls.
The store is the single source of truth; the heatmap callback in app.py reads
it directly, so any edit here is reflected live.
"""
from __future__ import annotations

import base64
import json

import dash
import dash_daq as daq
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html

from viz.colorscale import (
    DEFAULT_PRESET_NAME,
    ColorScale,
    default_scale_for,
    get_scale_for,
    list_presets,
    load_preset,
    save_preset,
)

MIN_BANDS = 2
MAX_BANDS = 10


def _store_id(param: str) -> dict:
    return {"type": "legend-store", "param": param}


def _rows_container_id(param: str) -> dict:
    return {"type": "legend-rows", "param": param}


def _threshold_id(param: str, index: int) -> dict:
    return {"type": "legend-threshold", "param": param, "index": index}


def _color_id(param: str, index: int) -> dict:
    return {"type": "legend-color", "param": param, "index": index}


def _swatch_id(param: str, index: int) -> dict:
    return {"type": "legend-swatch", "param": param, "index": index}


def _picker_id(param: str, index: int) -> dict:
    return {"type": "legend-picker", "param": param, "index": index}


def _picker_wrap_id(param: str, index: int) -> dict:
    return {"type": "legend-picker-wrap", "param": param, "index": index}


def _add_btn_id(param: str) -> dict:
    return {"type": "legend-add", "param": param}


def _remove_btn_id(param: str) -> dict:
    return {"type": "legend-remove", "param": param}


def _save_btn_id(param: str) -> dict:
    return {"type": "legend-save", "param": param}


def _preset_name_id(param: str) -> dict:
    return {"type": "legend-preset-name", "param": param}


def _preset_dropdown_id(param: str) -> dict:
    return {"type": "legend-preset-dropdown", "param": param}


def _load_btn_id(param: str) -> dict:
    return {"type": "legend-load", "param": param}


def _download_btn_id(param: str) -> dict:
    return {"type": "legend-download-btn", "param": param}


def _download_id(param: str) -> dict:
    return {"type": "legend-download", "param": param}


def _file_upload_id(param: str) -> dict:
    return {"type": "legend-file-upload", "param": param}


def _reset_btn_id(param: str) -> dict:
    return {"type": "legend-reset", "param": param}


def _preset_options(parameter_key: str) -> list[dict]:
    return [{"label": n, "value": n} for n in list_presets(parameter_key)]


def _status_id(param: str) -> dict:
    return {"type": "legend-status", "param": param}


def build_legend_panel(parameter_key: str) -> html.Div:
    scale = get_scale_for(parameter_key)
    return html.Div(
        [
            html.H4(f"{parameter_key} legend"),
            dcc.Store(id=_store_id(parameter_key), data=scale.to_dict()),
            html.Div(_render_rows(parameter_key, scale.to_dict()), id=_rows_container_id(parameter_key)),
            html.Div(
                [
                    html.Button("+ band", id=_add_btn_id(parameter_key), n_clicks=0),
                    html.Button("- band", id=_remove_btn_id(parameter_key), n_clicks=0),
                    html.Button("Reset to default", id=_reset_btn_id(parameter_key), n_clicks=0),
                ],
                style={"display": "flex", "gap": "8px", "marginTop": "6px"},
            ),
            html.Div(
                [
                    dcc.Input(
                        id=_preset_name_id(parameter_key),
                        type="text",
                        value=DEFAULT_PRESET_NAME,
                        placeholder="preset name",
                        style={"width": "130px"},
                    ),
                    html.Button("Save preset", id=_save_btn_id(parameter_key), n_clicks=0),
                    dcc.Dropdown(
                        id=_preset_dropdown_id(parameter_key),
                        options=_preset_options(parameter_key),
                        placeholder="Saved presets…",
                        style={"width": "180px"},
                    ),
                    html.Button("Load", id=_load_btn_id(parameter_key), n_clicks=0),
                ],
                style={"display": "flex", "gap": "8px", "marginTop": "6px", "alignItems": "center", "flexWrap": "wrap"},
            ),
            html.Div(
                [
                    html.Button("Download preset (.json)", id=_download_btn_id(parameter_key), n_clicks=0),
                    dcc.Download(id=_download_id(parameter_key)),
                    dcc.Upload(
                        id=_file_upload_id(parameter_key),
                        children=html.Div("Drag & drop or click to load a .json legend file"),
                        style={
                            "width": "220px",
                            "height": "32px",
                            "lineHeight": "32px",
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderRadius": "4px",
                            "textAlign": "center",
                            "fontSize": "12px",
                        },
                    ),
                ],
                style={"display": "flex", "gap": "8px", "marginTop": "6px", "alignItems": "center", "flexWrap": "wrap"},
            ),
            html.Div(id=_status_id(parameter_key), style={"fontSize": "12px", "color": "#666"}),
        ],
        style={"border": "1px solid #ddd", "padding": "10px", "borderRadius": "6px"},
    )


def _render_rows(parameter_key: str, data: dict) -> list:
    thresholds = data["thresholds"]
    colors = data["colors"]
    rows = []
    for i, color in enumerate(colors):
        band_label = f"≥ {thresholds[-1]:g}" if i == len(colors) - 1 else f"@ {thresholds[i]:g}"
        row = [
            html.Div(
                [
                    html.Div(
                        id=_swatch_id(parameter_key, i),
                        n_clicks=0,
                        style={
                            "width": "18px",
                            "height": "18px",
                            "backgroundColor": color,
                            "border": "1px solid #999",
                            "flexShrink": 0,
                            "cursor": "pointer",
                        },
                    ),
                    html.Div(
                        daq.ColorPicker(id=_picker_id(parameter_key, i), value={"hex": color}, size=150),
                        id=_picker_wrap_id(parameter_key, i),
                        style={
                            "display": "none",
                            "position": "absolute",
                            "bottom": "22px",  # opens upward from the swatch, so it doesn't run off the bottom of the viewport
                            "left": "22px",  # opens to the right of the swatch, so it doesn't cover the color input
                            "zIndex": 1000,
                            "backgroundColor": "white",
                            "border": "1px solid #ccc",
                            "borderRadius": "4px",
                            "padding": "4px",
                            "boxShadow": "0 2px 8px rgba(0,0,0,0.2)",
                        },
                    ),
                ],
                style={"position": "relative"},
            ),
            dcc.Input(type="text", value=color, id=_color_id(parameter_key, i), style={"width": "70px"}),
            html.Span(band_label, style={"width": "90px", "color": "#666", "fontSize": "12px"}),
        ]
        if i < len(thresholds):
            row.append(html.Span("threshold:", style={"fontSize": "12px", "color": "#999"}))
            row.append(
                dcc.Input(
                    type="number",
                    value=thresholds[i],
                    id=_threshold_id(parameter_key, i),
                    debounce=True,
                    style={"width": "70px"},
                )
            )
        rows.append(html.Div(row, style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "4px"}))
    return rows


def register_legend_callbacks(app, parameter_key: str) -> None:
    store_id = _store_id(parameter_key)
    rows_id = _rows_container_id(parameter_key)

    @app.callback(Output(rows_id, "children"), Input(store_id, "data"))
    def _render(data):
        return _render_rows(parameter_key, data)

    @app.callback(
        Output(_preset_dropdown_id(parameter_key), "options", allow_duplicate=True),
        Input(store_id, "data"),
        prevent_initial_call="initial_duplicate",
    )
    def _refresh_preset_options(_data):
        # Re-scans presets/ from disk on every page load (store's initial-call fire),
        # since app.layout is built once at server start and won't reflect files
        # saved in other sessions or added directly on disk after that.
        return _preset_options(parameter_key)

    @app.callback(
        Output(store_id, "data", allow_duplicate=True),
        Output(_status_id(parameter_key), "children", allow_duplicate=True),
        Input(_add_btn_id(parameter_key), "n_clicks"),
        Input(_remove_btn_id(parameter_key), "n_clicks"),
        Input(_reset_btn_id(parameter_key), "n_clicks"),
        Input({"type": "legend-threshold", "param": parameter_key, "index": ALL}, "value"),
        Input({"type": "legend-color", "param": parameter_key, "index": ALL}, "value"),
        State(store_id, "data"),
        prevent_initial_call=True,
    )
    def _update(_add, _remove, _reset, threshold_values, color_values, data):
        trigger = ctx.triggered_id

        if trigger == _reset_btn_id(parameter_key):
            return default_scale_for(parameter_key).to_dict(), ""

        if trigger == _add_btn_id(parameter_key):
            thresholds = list(data["thresholds"])
            colors = list(data["colors"])
            if len(colors) < MAX_BANDS:
                last_t = thresholds[-1] if thresholds else 0.0
                thresholds.append(last_t + 10.0)
                colors.insert(-1, colors[-1])
            return {"thresholds": thresholds, "colors": colors, "units": data.get("units", "")}, ""

        if trigger == _remove_btn_id(parameter_key):
            thresholds = list(data["thresholds"])
            colors = list(data["colors"])
            if len(colors) > MIN_BANDS:
                thresholds.pop()
                colors.pop(-2)
            return {"thresholds": thresholds, "colors": colors, "units": data.get("units", "")}, ""

        # a threshold or color input changed
        if any(v is None for v in threshold_values):
            return data, "Threshold can't be empty."
        thresholds = [float(v) for v in threshold_values]
        colors = list(color_values)
        if len(colors) != len(thresholds) + 1:
            # inconsistent partial update (row count mismatch mid-rebuild) -> ignore
            return data, ""
        if thresholds != sorted(thresholds):
            old_thresholds = data["thresholds"]
            changed = [i for i, (a, b) in enumerate(zip(thresholds, old_thresholds)) if a != b]
            idx = changed[0] if changed else 0
            bounds = []
            if idx > 0:
                bounds.append(f"greater than {thresholds[idx - 1]:g}")
            if idx + 1 < len(thresholds):
                bounds.append(f"less than {thresholds[idx + 1]:g}")
            return data, f"Threshold {idx} must be {' and '.join(bounds)} — edit ignored. Adjust the neighboring threshold first if you need to go further."
        return {"thresholds": thresholds, "colors": colors, "units": data.get("units", "")}, ""

    @app.callback(
        Output({"type": "legend-picker-wrap", "param": parameter_key, "index": ALL}, "style"),
        Input({"type": "legend-swatch", "param": parameter_key, "index": ALL}, "n_clicks"),
        State({"type": "legend-picker-wrap", "param": parameter_key, "index": ALL}, "style"),
        prevent_initial_call=True,
    )
    def _toggle_picker(_n_clicks, styles):
        clicked_index = ctx.triggered_id["index"]
        new_styles = []
        for i, style in enumerate(styles):
            style = dict(style or {})
            was_open = style.get("display") == "block"
            style["display"] = "block" if (i == clicked_index and not was_open) else "none"
            new_styles.append(style)
        return new_styles

    @app.callback(
        Output(_color_id(parameter_key, MATCH), "value"),
        Input(_picker_id(parameter_key, MATCH), "value"),
        prevent_initial_call=True,
    )
    def _picker_to_hex(picker_value):
        return picker_value["hex"]

    @app.callback(
        Output(_status_id(parameter_key), "children", allow_duplicate=True),
        Output(_preset_dropdown_id(parameter_key), "options", allow_duplicate=True),
        Input(_save_btn_id(parameter_key), "n_clicks"),
        State(store_id, "data"),
        State(_preset_name_id(parameter_key), "value"),
        prevent_initial_call=True,
    )
    def _save(_n, data, name):
        scale = ColorScale.from_dict(data)
        preset_name = (name or "").strip() or DEFAULT_PRESET_NAME
        save_preset(parameter_key, scale, name=preset_name)
        return f"Saved preset '{preset_name}' for '{parameter_key}'.", _preset_options(parameter_key)

    @app.callback(
        Output(store_id, "data", allow_duplicate=True),
        Output(_status_id(parameter_key), "children", allow_duplicate=True),
        Input(_load_btn_id(parameter_key), "n_clicks"),
        State(_preset_dropdown_id(parameter_key), "value"),
        prevent_initial_call=True,
    )
    def _load(_n, name):
        if not name:
            return dash.no_update, "Pick a preset from the dropdown first."
        scale = load_preset(parameter_key, name=name)
        if scale is None:
            return dash.no_update, f"Preset '{name}' not found."
        return scale.to_dict(), f"Loaded preset '{name}'."

    @app.callback(
        Output(_download_id(parameter_key), "data"),
        Input(_download_btn_id(parameter_key), "n_clicks"),
        State(store_id, "data"),
        State(_preset_name_id(parameter_key), "value"),
        prevent_initial_call=True,
    )
    def _download(_n, data, name):
        fname_slug = "".join(c if c.isalnum() else "_" for c in (name or parameter_key).lower()).strip("_") or "legend"
        return dcc.send_string(json.dumps(data, indent=2), filename=f"{fname_slug}_legend.json")

    @app.callback(
        Output(store_id, "data", allow_duplicate=True),
        Output(_status_id(parameter_key), "children", allow_duplicate=True),
        Input(_file_upload_id(parameter_key), "contents"),
        State(_file_upload_id(parameter_key), "filename"),
        prevent_initial_call=True,
    )
    def _upload(contents, filename):
        try:
            _header, b64data = contents.split(",", 1)
            text = base64.b64decode(b64data).decode("utf-8-sig")
            scale = ColorScale.from_dict(json.loads(text))
        except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
            return dash.no_update, f"Error loading {filename}: {e}"
        return scale.to_dict(), f"Loaded legend from {filename}."
