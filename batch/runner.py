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
and fed_timeseries.csv (time/temperature/FED at every step, for plotting),
since a browser can't be pointed at an arbitrary folder on disk to read
from or write to.
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
from trajectory.integrator import compute_path
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
                occupants_data = []
                for occupant in OCCUPANTS:
                    occ_config = config.occupants[occupant["id"]]
                    segments = compute_path(
                        grids["opacity"], occ_config.start_x, occ_config.evac_start_t, config.exits, speed_table, dt=1.0
                    )
                    refs = {"evac_start_t": occ_config.evac_start_t, "exits": config.exits}
                    occupants_data.append((occupant, [s.to_dict() for s in segments], refs))

                    prefix = _OCCUPANT_PREFIXES[occupant["id"]]
                    for cp in compute_fed_checkpoints(segments, grids["temperature"], prefix):
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

                output_files = []
                for slot in SLOTS:
                    grid = grids[slot]
                    fig = build_panel_figure(
                        SLOT_LABELS[slot], grid.to_dict(), legend_data_by_slot.get(slot), occupants_data, label_side=label_side
                    )
                    png_bytes = exporter.render_png(fig.to_dict(), width=1400, height=900, scale=2)
                    out_name = f"{scenario_id}_{SLOT_DISPLAY_NAMES[slot]}_traj.png"
                    zf.writestr(out_name, png_bytes)
                    output_files.append(out_name)
                    any_output = True

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
