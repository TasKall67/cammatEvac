"""Batch-export trajectory heatmaps (temperature/opacity/CO) for many scenarios at once.

Reuses the exact same figure-building and PNG-export code as the interactive
single-scenario UI (viz.panel.build_panel_figure, viz.png_export.get_exporter)
-- a batch run is just that same logic looped over many uploaded scenario
files, with occupant start/evac-time pulled from a companion config CSV
instead of the occupant panel inputs. Occupants 1 and 2 each get their own
start position and evacuation start time (config.occupants["1"]/["2"]) and
share the scenario's exits. Runs entirely in memory -- inputs come from
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
from trajectory.fed import compute_fed_checkpoints, compute_fed_timeseries
from trajectory.integrator import compute_path, compute_zoom_x_range, select_valid_exits
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
_OCCUPANT_PREFIXES = {"1": "F", "2": "L"}  # matches components.fed_table's F(irst)/L(ast) convention


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
                for occupant in OCCUPANTS:
                    occ_config = config.occupants[occupant["id"]]
                    valid_exits = select_valid_exits(
                        config.exits, occ_config.start_x, config.fire_position, tunnel_bounds=tunnel_bounds
                    )
                    exits_to_walk = valid_exits if continue_past_exit else valid_exits[:1]
                    segments = compute_path(
                        grids["opacity"], occ_config.start_x, occ_config.evac_start_t, exits_to_walk, speed_table, dt=1.0
                    )
                    refs = {"evac_start_t": occ_config.evac_start_t, "exits": config.exits}
                    occupants_data.append((occupant, [s.to_dict() for s in segments], refs))

                    prefix = _OCCUPANT_PREFIXES[occupant["id"]]
                    fed_checkpoints = compute_fed_checkpoints(segments, grids["temperature"], prefix)
                    # "Evacuation completion" for the zoomed Y-range: wherever this occupant's
                    # drawn path actually ends -- the FED-incapacitation point if it was cut
                    # short (matches the red X in the figure), else the raw path's last point.
                    if fed_checkpoints and fed_checkpoints[-1].reached_limit:
                        completion_times.append(fed_checkpoints[-1].time_s)
                    elif segments and segments[-1].points:
                        completion_times.append(segments[-1].points[-1][0])
                    for cp in fed_checkpoints:
                        fed_rows.append(
                            {
                                "scenario_id": scenario_id,
                                "occupant_id": cp.leg_label,
                                "fed": f"{cp.final_fed:.4f}",
                                "reached_0.3": "yes" if cp.reached_limit else "no",
                                "position_m": f"{cp.position:.1f}" if cp.position is not None else "",
                                "distance_traveled_m": f"{cp.distance_traveled:.1f}" if cp.distance_traveled is not None else "",
                            }
                        )
                    for pt in compute_fed_timeseries(segments, grids["temperature"], prefix):
                        fed_timeseries_rows.append(
                            {
                                "scenario_id": scenario_id,
                                "occupant_id": pt.leg_label,
                                "time_s": f"{pt.time_s:g}",
                                "position_m": f"{pt.position_m:.1f}",
                                "temperature_c": f"{pt.temperature_c:.1f}",
                                "fed": f"{pt.cumulative_fed:.4f}",
                            }
                        )

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
                    fig = build_panel_figure(
                        SLOT_LABELS[slot],
                        grid.to_dict(),
                        legend_data_by_slot.get(slot),
                        occupants_data,
                        label_side=label_side,
                        fire_position=config.fire_position,
                        temperature_grid_data=temperature_grid_data,
                    )
                    png_bytes = exporter.render_png(fig.to_dict(), width=1400, height=900, scale=2)
                    out_name = f"{scenario_id}_{SLOT_DISPLAY_NAMES[slot]}_traj.png"
                    output_files += _write_grouped(zf, config.studies, out_name, png_bytes)
                    any_output = True

                    if x_zoom_range is not None:
                        # Reuses the exact same figure (traces/shapes/icons) built above --
                        # zooming is just a viewport change, not a different render.
                        fig.update_xaxes(range=list(x_zoom_range), dtick=None)
                        fig.update_yaxes(range=list(y_zoom_range), dtick=None)
                        zoom_png_bytes = exporter.render_png(fig.to_dict(), width=1400, height=900, scale=2)
                        zoom_name = f"z{scenario_id}_{SLOT_DISPLAY_NAMES[slot]}_traj.png"
                        output_files += _write_grouped(zf, config.studies, zoom_name, zoom_png_bytes)

                results.append(ScenarioResult(scenario_id, "ok", output_files=output_files))
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
