"""Per-scenario occupant configuration for batch trajectory export.

One CSV row per scenario, keyed by scenario_id (the "Scenario: <id>" value
embedded in each combined XT CSV, e.g. "Paramythias_R100N015"). Occupant 1
and occupant 2 each get their own start position and evacuation start time
(they can genuinely differ -- e.g. one occupant starting closer to the fire
or evacuating later); exits are shared by both. Exits are "|"-separated
within their own cell (e.g. "600|900") -- deliberately not "," or ";", since
Excel's own column delimiter varies by locale (many European settings --
including Greek -- default CSV exports to ";" because "," is the decimal
separator), so neither of those two is safe to also use as the in-cell list
separator. The outer column delimiter itself is auto-detected (comma or
semicolon, whichever the file actually uses) so this works with either.
See scenario_config_template.csv for the exact column layout.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass
class OccupantConfig:
    start_x: float
    evac_start_t: float


@dataclass
class ScenarioConfig:
    scenario_id: str
    exits: list[float]
    occupants: dict[str, OccupantConfig]  # keyed by occupant id, "1" / "2"


_REQUIRED_COLUMNS = ("scenario_id", "start_x_1", "evac_start_t_1", "start_x_2", "evac_start_t_2", "exits")


def _detect_delimiter(text: str) -> str:
    header_line = text.splitlines()[0] if text.splitlines() else ""
    try:
        return csv.Sniffer().sniff(header_line, delimiters=",;").delimiter
    except csv.Error:
        return ","


def parse_scenario_configs_text(text: str) -> dict[str, ScenarioConfig]:
    reader = csv.DictReader(io.StringIO(text), delimiter=_detect_delimiter(text))
    fieldnames = [f.strip() for f in (reader.fieldnames or [])]
    missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        raise ValueError(
            f"config CSV is missing column(s) {missing} -- found columns: {fieldnames}. "
            f"Check that each value is in its own cell (not all crammed into one), and that "
            f"exits use \"|\" between values (e.g. \"600|900\"), not \",\" or \";\"."
        )

    configs: dict[str, ScenarioConfig] = {}
    for i, row in enumerate(reader, start=2):  # start=2: row 1 is the header
        empty = [c for c in _REQUIRED_COLUMNS if not row.get(c)]
        if empty:
            raise ValueError(
                f"config CSV row {i} is missing value(s) for {empty} -- likely everything landed in one "
                f"cell instead of separate columns. Row as read: {row}"
            )
        scenario_id = row["scenario_id"].strip()
        exits = [float(v.strip()) for v in row["exits"].split("|") if v.strip()]
        configs[scenario_id] = ScenarioConfig(
            scenario_id=scenario_id,
            exits=exits,
            occupants={
                "1": OccupantConfig(start_x=float(row["start_x_1"]), evac_start_t=float(row["evac_start_t_1"])),
                "2": OccupantConfig(start_x=float(row["start_x_2"]), evac_start_t=float(row["evac_start_t_2"])),
            },
        )
    return configs
