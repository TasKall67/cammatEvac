"""Batch-export trajectory heatmaps (temperature/opacity/CO) for many scenarios at once.

Reuses the exact same figure-building and PNG-export code as the interactive
single-scenario UI (viz.panel.build_panel_figure, viz.png_export.get_exporter)
-- a batch run is just that same logic looped over many uploaded scenario
files, with occupant start/evac-time pulled from a companion config CSV
instead of the occupant panel inputs. Occupants 1 and 2 each get their own
start position (config.occupants["1"]/["2"]) and share the scenario's exits.
Occupant 1's evac-start time is always config.occupants["1"].evac_start_t as
given. Occupant 2's is instead normally computed dynamically -- too far from
the fire to notice it directly, they react to whichever comes first: occupant
1 physically reaching occupant 2's own start position (+130s reaction time),
or smoke (air opacity) reaching occupant 2's own position (+80s reaction
time) -- see trajectory.integrator.compute_triggered_evac_start_t. Only if
neither of those ever happens within the simulated time does occupant 2 fall
back to config.occupants["2"].evac_start_t (if given at all; otherwise
occupant 2 is skipped for that one scenario, noted in the ScenarioResult's
detail even though the scenario as a whole still succeeds). Runs entirely in
memory -- inputs come from
uploaded file contents, output is a single ZIP containing the PNGs plus
fed_results.csv (same per-leg FED checkpoints as the interactive FED table)
and fed_timeseries.csv (time/temperature/FED at every step, for plotting).
When produce_zoomed is set and a scenario has a fire_position, each PNG gets
a companion "z"-prefixed version cropped to the area of interest (see
trajectory.integrator.compute_zoom_x_range for the X range rule; Y runs from
0 to the latest occupant's path-completion time + 200s). A scenario's
optional study list (config.studies) groups its output PNGs into one
subfolder per named study in the ZIP (a multi-study scenario appears whole
in each); scenarios without a study go to the ZIP root. Runs entirely in
memory -- inputs come from uploaded file contents, output is a single ZIP,
since a browser can't be pointed at an arbitrary folder on disk to read from
or write to.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from batch.config import parse_scenario_configs_text
from batch.discovery import read_scenario_id
from components.occupant_panel import OCCUPANTS
from data.xt_parser import parse_combined_xt_csv_text
from trajectory.fed import (
    FedCheckpoint,
    FedTimeseriesPoint,
    compute_fed_checkpoints,
    compute_fed_timeseries,
    compute_stationary_fed_checkpoint,
    compute_stationary_fed_timeseries,
)
from trajectory.integrator import (
    compute_path,
    compute_triggered_evac_start_t,
    compute_zoom_x_range,
    select_valid_exits,
)
from trajectory.speed_model import SpeedTable
from viz.panel import build_panel_figure
from viz.png_export import get_exporter

SLOTS = ("temperature", "opacity", "co")
SLOT_DISPLAY_NAMES = {"temperature": "Temperature", "opacity": "Opacity", "co": "CO"}
SLOT_LABELS = {
    "temperature": "Air temperature (C)",
    "opacity": "Air opacity (1/m)",
    "co": "CO concentration (ppm)",
}


def _write_grouped(zf: zipfile.ZipFile, studies: list[str], filename: str, data: bytes) -> list[str]:
    """Writes data once per study subfolder (so a multi-study scenario, e.g.
    "RASnoDG+SHI", is a complete copy in each folder), or to the ZIP root if
    studies is empty (old behavior, no grouping). Always "/" as the in-zip
    separator -- that's the zip spec, not an OS path. Returns the in-zip
    path(s) written, for ScenarioResult.output_files."""
    paths = [f"{study}/{filename}" for study in studies] if studies else [filename]
    for path in paths:
        zf.writestr(path, data)
    return paths

_FED_CSV_HEADERS = ["scenario_id", "occupant_id", "fed", "reached_0.3", "position_m", "distance_traveled_m"]
_FED_TIMESERIES_HEADERS = ["scenario_id", "occupant_id", "time_s", "position_m", "temperature_c", "fed"]


def _fed_row(scenario_id: str, cp: FedCheckpoint) -> dict:
    return {
        "scenario_id": scenario_id,
        "occupant_id": cp.leg_label,
        "fed": f"{cp.final_fed:.4f}",
        "reached_0.3": "yes" if cp.reached_limit else "no",
        "position_m": f"{cp.position:.1f}" if cp.position is not None else "",
        "distance_traveled_m": f"{cp.distance_traveled:.1f}" if cp.distance_traveled is not None else "",
    }


def _fed_timeseries_row(scenario_id: str, pt: FedTimeseriesPoint) -> dict:
    return {
        "scenario_id": scenario_id,
        "occupant_id": pt.leg_label,
        "time_s": f"{pt.time_s:g}",
        "position_m": f"{pt.position_m:.1f}",
        "temperature_c": f"{pt.temperature_c:.1f}",
        "fed": f"{pt.cumulative_fed:.4f}",
    }


@dataclass
class ScenarioResult:
    scenario_id: str
    status: str  # "ok" | "skipped" | "error"
    detail: str = ""
    output_files: list[str] = field(default_factory=list)


def run_batch(
    scenario_files: list[tuple[str, str]],  # (filename, decoded_text) pairs
    config_csv_text: str,
    legend_data_by_slot: dict[str, dict | None],
    speed_table: SpeedTable,
    label_side: str,
    continue_past_exit: bool = False,
    produce_zoomed: bool = False,
    show_jetfans: bool = False,
    show_jetfans_off: bool = False,
) -> tuple[list[ScenarioResult], bytes | None]:
    configs = parse_scenario_configs_text(config_csv_text)
    exporter = get_exporter()

    results: list[ScenarioResult] = []
    fed_rows: list[dict] = []
    fed_timeseries_rows: list[dict] = []
    zip_buffer = BytesIO()
    any_output = False

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, text in scenario_files:
            scenario_id = read_scenario_id(text)
            if not scenario_id:
                results.append(ScenarioResult(filename, "error", 'could not read a "Scenario:" line from this file'))
                continue

            config = configs.get(scenario_id)
            if config is None:
                results.append(ScenarioResult(scenario_id, "skipped", "no matching row in config CSV"))
                continue

            try:
                grids = parse_combined_xt_csv_text(text, source_name=filename)
            except Exception as e:  # noqa: BLE001 - surfaced per-scenario, one bad file shouldn't kill the batch
                results.append(ScenarioResult(scenario_id, "error", f"failed to parse {filename}: {type(e).__name__}: {e}"))
                continue

            missing = set(SLOTS) - set(grids)
            if missing:
                results.append(ScenarioResult(scenario_id, "skipped", f"missing {', '.join(sorted(missing))} block in CSV"))
                continue

            try:
                # config.exits (all of them, as given) still goes into refs, for drawing
                # every exit marker regardless of fire-crossing or the toggle -- only the
                # WALKED path is filtered: exits requiring crossing the fire are dropped
                # and the rest sorted nearest-first per occupant's own start_x, then (by
                # default) only the first of those is walked to, since continuing through
                # missed exits is opt-in via continue_past_exit.
                tunnel_bounds = (float(grids["opacity"].distances.min()), float(grids["opacity"].distances.max()))
                occupants_data = []
                completion_times = []
                scenario_warnings = []
                for occupant in OCCUPANTS:
                    occ_config = config.occupants[occupant["id"]]
                    evac_start_t = occ_config.evac_start_t

                    if occupant["id"] == "2":
                        leader = config.occupants["1"]
                        triggered_t = compute_triggered_evac_start_t(
                            grids["opacity"], speed_table, leader.start_x, leader.evac_start_t, occ_config.start_x
                        )
                        if triggered_t is not None:
                            evac_start_t = triggered_t
                        elif occ_config.evac_start_t is not None:
                            evac_start_t = occ_config.evac_start_t
                        else:
                            scenario_warnings.append(
                                "occupant 2 skipped: neither trigger (occupant 1 reaching their position, or "
                                "smoke reaching their position) occurred within the simulated time, and no "
                                "fallback evac_start_t_2 was given"
                            )
                            continue

                    valid_exits = select_valid_exits(
                        config.exits, occ_config.start_x, config.fire_position, tunnel_bounds=tunnel_bounds
                    )
                    exits_to_walk = valid_exits if continue_past_exit else valid_exits[:1]
                    segments = compute_path(
                        grids["opacity"], occ_config.start_x, evac_start_t, exits_to_walk, speed_table, dt=1.0
                    )
                    refs = {"evac_start_t": evac_start_t, "exits": config.exits}
                    occupants_data.append((occupant, [s.to_dict() for s in segments], refs))

                    fed_checkpoints = compute_fed_checkpoints(segments, grids["temperature"], occupant["id"])
                    # "Evacuation completion" for the zoomed Y-range: wherever this occupant's
                    # drawn path actually ends -- the FED-incapacitation point if it was cut
                    # short (matches the red X in the figure), else the raw path's last point.
                    if fed_checkpoints and fed_checkpoints[-1].reached_limit:
                        completion_times.append(fed_checkpoints[-1].time_s)
                    elif segments and segments[-1].points:
                        completion_times.append(segments[-1].points[-1][0])
                    for cp in fed_checkpoints:
                        fed_rows.append(_fed_row(scenario_id, cp))
                    for pt in compute_fed_timeseries(segments, grids["temperature"], occupant["id"]):
                        fed_timeseries_rows.append(_fed_timeseries_row(scenario_id, pt))

                    # Stationary reference rows: this occupant standing still at their own
                    # start position from t=0 until evac_start_t -- exposure while waiting,
                    # for personal testing only, never drawn on the heatmap itself.
                    tr_number = f"TR{occupant['id']}"
                    stationary_cp = compute_stationary_fed_checkpoint(
                        occ_config.start_x, evac_start_t, grids["temperature"], tr_number
                    )
                    if stationary_cp is not None:
                        fed_rows.append(_fed_row(scenario_id, stationary_cp))
                    for pt in compute_stationary_fed_timeseries(
                        occ_config.start_x, evac_start_t, grids["temperature"], tr_number
                    ):
                        fed_timeseries_rows.append(_fed_timeseries_row(scenario_id, pt))

                # Zoomed view is only computable with a fire position to anchor it -- scenarios
                # without one just don't get zoomed exports, the normal ones are unaffected.
                x_zoom_range = None
                y_zoom_range = None
                if produce_zoomed and config.fire_position is not None:
                    x_zoom_range = compute_zoom_x_range(
                        config.exits, config.occupants["1"].start_x, config.fire_position, tunnel_bounds
                    )
                    y_zoom_range = (0, max(completion_times, default=0) + 200)

                temperature_grid_data = grids["temperature"].to_dict()
                output_files = []
                for slot in SLOTS:
                    grid = grids[slot]
                    common_kwargs = dict(
                        slot_label=SLOT_LABELS[slot],
                        grid_data=grid.to_dict(),
                        legend_data=legend_data_by_slot.get(slot),
                        occupants_data=occupants_data,
                        label_side=label_side,
                        fire_position=config.fire_position,
                        temperature_grid_data=temperature_grid_data,
                        jetfan_positions=config.jetfan_positions,
                        jetfan_off_positions=config.jetfan_off_positions,
                        jetfan_counts=config.jetfan_counts,
                        jetfan_off_counts=config.jetfan_off_counts,
                        show_jetfans=show_jetfans,
                        show_jetfans_off=show_jetfans_off,
                    )
                    fig = build_panel_figure(**common_kwargs)
                    png_bytes = exporter.render_png(fig.to_dict(), width=1400, height=900, scale=2)
                    out_name = f"{scenario_id}_{SLOT_DISPLAY_NAMES[slot]}_traj.png"
                    output_files += _write_grouped(zf, config.studies, out_name, png_bytes)
                    any_output = True

                    if x_zoom_range is not None:
                        # A separate figure, not a viewport tweak of the one above --
                        # icon_x_range/icon_y_range re-derive icon sizes (and the
                        # tunnel icon's edge nudge) from the zoomed viewport's own
                        # span, so they read at the same relative size/position as in
                        # the normal export instead of the same fixed number of
                        # meters looking oversized/off-boundary once squeezed into
                        # the much narrower zoomed window.
                        zoom_fig = build_panel_figure(
                            **common_kwargs, icon_x_range=x_zoom_range, icon_y_range=y_zoom_range
                        )
                        zoom_fig.update_xaxes(range=list(x_zoom_range), dtick=None)
                        zoom_fig.update_yaxes(range=list(y_zoom_range), dtick=None)
                        zoom_png_bytes = exporter.render_png(zoom_fig.to_dict(), width=1400, height=900, scale=2)
                        zoom_name = f"z{scenario_id}_{SLOT_DISPLAY_NAMES[slot]}_traj.png"
                        output_files += _write_grouped(zf, config.studies, zoom_name, zoom_png_bytes)

                results.append(
                    ScenarioResult(scenario_id, "ok", detail="; ".join(scenario_warnings), output_files=output_files)
                )
            except Exception as e:  # noqa: BLE001 - surfaced per-scenario, one bad scenario shouldn't kill the batch
                results.append(ScenarioResult(scenario_id, "error", f"{type(e).__name__}: {e}"))

        if fed_rows:
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=_FED_CSV_HEADERS)
            writer.writeheader()
            writer.writerows(fed_rows)
            zf.writestr("fed_results.csv", csv_buffer.getvalue())

        if fed_timeseries_rows:
            ts_buffer = io.StringIO()
            ts_writer = csv.DictWriter(ts_buffer, fieldnames=_FED_TIMESERIES_HEADERS)
            ts_writer.writeheader()
            ts_writer.writerows(fed_timeseries_rows)
            zf.writestr("fed_timeseries.csv", ts_buffer.getvalue())

    return results, (zip_buffer.getvalue() if any_output else None)
