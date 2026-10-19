"""Batch-export temperature/opacity/CO trajectory heatmaps for many scenarios at once.

Drag-and-drop/browse uploads, same pattern as the individual per-slot CSV
upload -- reuses the exact figure-building/export path the interactive
single-scenario UI uses (viz.panel.build_panel_figure via batch.runner.run_batch)
with whatever legend/speed-model/label-side is currently set in the panels
above. Output is a single ZIP download (a browser can't be pointed at an
arbitrary folder on disk to write into). Doesn't touch the existing per-slot
drag-and-drop upload at all.
"""
from __future__ import annotations

import base64

import dash
from dash import Input, Output, State, dcc, html

from batch.config import parse_scenario_configs_text
from batch.discovery import read_scenario_id
from batch.runner import SLOTS, run_batch
from components.speed_editor import SHARED_SPEED_OWNER
from components.speed_editor import store_id as speed_store_id
from trajectory.speed_model import SpeedTable

_SLOT_LABELS = {
    "temperature": "Air temperature (C)",
    "opacity": "Air opacity (1/m)",
    "co": "CO concentration (ppm)",
}

_SOURCE_UPLOAD_ID = "batch-source-upload"
_CONFIG_UPLOAD_ID = "batch-config-upload"
_CONFIG_STATUS_ID = "batch-config-status"
_ZOOM_TOGGLE_ID = "batch-zoom-toggle"
_JETFAN_SHOW_TOGGLE_ID = "jetfan-show-toggle"
_JETFAN_OFF_SHOW_TOGGLE_ID = "jetfan-off-show-toggle"
_RUN_BTN_ID = "batch-run-btn"
_STATUS_ID = "batch-status"
_DOWNLOAD_ID = "batch-download"

_UPLOAD_STYLE = {
    "width": "100%",
    "height": "50px",
    "lineHeight": "50px",
    "borderWidth": "1px",
    "borderStyle": "dashed",
    "borderRadius": "4px",
    "textAlign": "center",
    "fontSize": "12px",
}


def _decode(contents: str) -> str:
    _header, b64data = contents.split(",", 1)
    return base64.b64decode(b64data).decode("utf-8-sig")


def build_batch_panel() -> html.Div:
    return html.Div(
        [
            html.H4("Batch export scenarios"),
            html.P(
                'Drag & drop (or click to browse) several combined per-scenario XT CSVs -- each file has '
                'temperature/opacity/CO stacked together, scenario id read from the file\'s own "Scenario:" '
                'line -- plus one config CSV (columns: scenario_id,start_x_1,evac_start_t_1,start_x_2,'
                'evac_start_t_2,exits,fire_position -- occupant 1\'s evac_start_t_1 is fixed as given; '
                'occupant 2\'s own start time is instead computed from whichever happens first, occupant 1 '
                'reaching occupant 2\'s position (+130s) or smoke reaching occupant 2\'s position (+80s) -- '
                'evac_start_t_2 is only used as a fallback if neither ever happens, and can be left blank. '
                'Exits are shared and "|"-separated e.g. "600|900", fire_position is '
                'optional -- required if you want the zoomed-graph option below). Exports all 3 heatmaps '
                "per matched scenario as a single ZIP download, using whatever legend/speed-model/label-side/"
                "exit-continuation setting is currently set above.",
                style={"fontSize": "12px", "color": "#666"},
            ),
            html.Label("Scenario CSVs (one or more)", style={"display": "block", "marginTop": "6px"}),
            dcc.Upload(
                id=_SOURCE_UPLOAD_ID,
                children=html.Div("Drag & drop scenario CSVs here, or click to browse"),
                multiple=True,
                style=_UPLOAD_STYLE,
            ),
            html.Label("Scenario config CSV", style={"display": "block", "marginTop": "10px"}),
            dcc.Upload(
                id=_CONFIG_UPLOAD_ID,
                children=html.Div("Drag & drop the config CSV here, or click to browse"),
                multiple=False,
                style=_UPLOAD_STYLE,
            ),
            html.Div(id=_CONFIG_STATUS_ID, style={"fontSize": "12px", "color": "#666", "marginTop": "4px"}),
            dcc.Checklist(
                id=_ZOOM_TOGGLE_ID,
                options=[
                    {
                        "label": " Also produce zoomed-in graphs (area around the fire/exits; needs fire_position)",
                        "value": "on",
                    }
                ],
                value=[],
                style={"fontSize": "13px", "marginTop": "8px"},
            ),
            dcc.Checklist(
                id=_JETFAN_SHOW_TOGGLE_ID,
                options=[{"label": " Show jet fan positions", "value": "on"}],
                value=["on"],
                style={"fontSize": "13px", "marginTop": "8px"},
            ),
            dcc.Checklist(
                id=_JETFAN_OFF_SHOW_TOGGLE_ID,
                options=[{"label": " Show out-of-service jet fans (JF2)", "value": "on"}],
                value=["on"],
                style={"fontSize": "13px", "marginTop": "8px"},
            ),
            html.Button("Run batch export", id=_RUN_BTN_ID, n_clicks=0, style={"marginTop": "8px"}),
            dcc.Download(id=_DOWNLOAD_ID),
            html.Pre(id=_STATUS_ID, style={"fontSize": "12px", "color": "#333", "whiteSpace": "pre-wrap", "marginTop": "8px"}),
        ],
        style={"border": "1px solid #ddd", "padding": "10px", "borderRadius": "6px", "marginTop": "20px"},
    )


def register_batch_panel_callbacks(app) -> None:
    @app.callback(
        Output(_STATUS_ID, "children"),
        Input(_SOURCE_UPLOAD_ID, "contents"),
        State(_SOURCE_UPLOAD_ID, "filename"),
        prevent_initial_call=True,
    )
    def _preview(contents_list, filenames):
        if not contents_list:
            return "No files selected."
        lines = [f"{len(contents_list)} file(s) selected:"]
        for contents, filename in zip(contents_list, filenames):
            try:
                scenario_id = read_scenario_id(_decode(contents)) or "(no Scenario: line found)"
            except Exception as e:  # noqa: BLE001 - surfaced to the user
                scenario_id = f"error reading file: {type(e).__name__}: {e}"
            lines.append(f"  {filename} -> {scenario_id}")
        return "\n".join(lines)

    @app.callback(
        Output(_CONFIG_STATUS_ID, "children"),
        Input(_CONFIG_UPLOAD_ID, "contents"),
        State(_CONFIG_UPLOAD_ID, "filename"),
        prevent_initial_call=True,
    )
    def _preview_config(contents, filename):
        if not contents:
            return "No file selected."
        try:
            configs = parse_scenario_configs_text(_decode(contents))
        except Exception as e:  # noqa: BLE001 - surfaced to the user
            return f"Error reading {filename}: {type(e).__name__}: {e}"
        return f"Loaded {filename}: {len(configs)} scenario row(s) -- {', '.join(sorted(configs))}"

    @app.callback(
        Output(_DOWNLOAD_ID, "data"),
        Output(_STATUS_ID, "children", allow_duplicate=True),
        Input(_RUN_BTN_ID, "n_clicks"),
        State(_SOURCE_UPLOAD_ID, "contents"),
        State(_SOURCE_UPLOAD_ID, "filename"),
        State(_CONFIG_UPLOAD_ID, "contents"),
        [State({"type": "legend-store", "param": _SLOT_LABELS[slot]}, "data") for slot in SLOTS],
        State(speed_store_id(SHARED_SPEED_OWNER), "data"),
        State("evac-label-side-store", "data"),
        State("continue-past-exit-toggle", "value"),
        State(_ZOOM_TOGGLE_ID, "value"),
        State(_JETFAN_SHOW_TOGGLE_ID, "value"),
        State(_JETFAN_OFF_SHOW_TOGGLE_ID, "value"),
        prevent_initial_call=True,
    )
    def _run(_n, source_contents, source_filenames, config_contents, *rest):
        legend_datas = rest[: len(SLOTS)]
        speed_data, label_side, continue_toggle, zoom_toggle, jetfan_toggle, jetfan_off_toggle = rest[len(SLOTS) :]

        if not source_contents:
            return dash.no_update, "Add at least one scenario CSV first."
        if not config_contents:
            return dash.no_update, "Add a scenario config CSV first."

        try:
            scenario_files = [(fn, _decode(c)) for fn, c in zip(source_filenames, source_contents)]
            config_text = _decode(config_contents)
        except Exception as e:  # noqa: BLE001 - surfaced to the user
            return dash.no_update, f"Error reading uploaded files: {type(e).__name__}: {e}"

        legend_data_by_slot = dict(zip(SLOTS, legend_datas))
        speed_table = SpeedTable.from_dict(speed_data)

        try:
            results, zip_bytes = run_batch(
                scenario_files,
                config_text,
                legend_data_by_slot,
                speed_table,
                label_side or "left",
                continue_past_exit="on" in (continue_toggle or []),
                produce_zoomed="on" in (zoom_toggle or []),
                show_jetfans="on" in (jetfan_toggle or []),
                show_jetfans_off="on" in (jetfan_off_toggle or []),
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the user instead of a bare 500
            return dash.no_update, f"Batch failed: {type(e).__name__}: {e}"

        ok = [r for r in results if r.status == "ok"]
        skipped = [r for r in results if r.status == "skipped"]
        errored = [r for r in results if r.status == "error"]

        warned = [r for r in ok if r.detail]

        total_files = sum(len(r.output_files) for r in ok)
        lines = [f"Exported {len(ok)} scenario(s), {total_files} PNG(s) total."]
        if warned:
            lines.append(f"Warnings ({len(warned)}):")
            lines += [f"  {r.scenario_id} -- {r.detail}" for r in warned]
        if skipped:
            lines.append(f"Skipped ({len(skipped)}):")
            lines += [f"  {r.scenario_id} -- {r.detail}" for r in skipped]
        if errored:
            lines.append(f"Errors ({len(errored)}):")
            lines += [f"  {r.scenario_id} -- {r.detail}" for r in errored]

        download = dcc.send_bytes(zip_bytes, filename="batch_export.zip") if zip_bytes else dash.no_update
        return download, "\n".join(lines)
