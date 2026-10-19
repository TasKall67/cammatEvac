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
evac_start_t_2 is optional: occupant 2's actual evac-start time is normally
computed dynamically at run time (see batch.runner / trajectory.integrator.
compute_triggered_evac_start_t -- they react to whichever comes first, another
occupant reaching their position or smoke reaching it), and evac_start_t_2
here is used only as a fallback if that computation can't determine a trigger
time at all (and even then only if given -- otherwise occupant 2 is skipped
for that one scenario, noted in the batch status output).
An optional fire_position column (meters) draws the fire-zone lines on the
exported heatmaps; scenarios without it just don't get those lines. An
optional study column ("+"-separated, e.g. "RASnoDG+SHI") groups this
scenario's batch output into one subfolder per named study in the ZIP;
scenarios without it go to the ZIP root, as before. Two further optional
columns, jetfan_positions and jetfan_off_positions, are "|"-separated like
exits -- positions (m) of working jet fans and of out-of-service jet fans
(JF2-style scenarios) respectively; a position can appear in both (some fans
at that point are off, others still running). Two more optional columns,
jetfan_counts and jetfan_off_counts, align one-to-one with those two position
columns and give how many fans (1-3) are at each position; if missing, empty,
or mismatched in length, every position is just treated as a single fan. See
scenario_config_template.csv for the exact column layout.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


@dataclass
class OccupantConfig:
    start_x: float
    evac_start_t: float | None  # None only possible for occupant 2 (fallback not given) -- see module docstring


@dataclass
class ScenarioConfig:
    scenario_id: str
    exits: list[float]
    occupants: dict[str, OccupantConfig]  # keyed by occupant id, "1" / "2"
    fire_position: float | None = None  # optional -- fire-zone lines are skipped if not given
    studies: list[str] = field(default_factory=list)  # optional -- empty means "ZIP root, no subfolder"
    jetfan_positions: list[float] = field(default_factory=list)  # optional -- working jet fans
    jetfan_off_positions: list[float] = field(default_factory=list)  # optional -- out-of-service jet fans (JF2)
    jetfan_counts: list[int] = field(default_factory=list)  # optional -- fan count per jetfan_positions entry
    jetfan_off_counts: list[int] = field(default_factory=list)  # optional -- fan count per jetfan_off_positions entry


_REQUIRED_COLUMNS = ("scenario_id", "start_x_1", "evac_start_t_1", "start_x_2", "exits")


def _parse_counts(raw: str, positions: list[float]) -> list[int]:
    """Parses a "|"-separated counts column aligned with a positions list. Any
    mismatch (missing, empty, wrong length) just falls back to "1 fan at every
    position" rather than raising -- the counts columns are a cosmetic extra,
    not something a batch run should ever fail over."""
    parts = [v.strip() for v in (raw or "").split("|") if v.strip()]
    if len(parts) != len(positions):
        return [1] * len(positions)
    try:
        return [int(float(v)) for v in parts]
    except ValueError:
        return [1] * len(positions)


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
        empty = [c for c in _REQUIRED_COLUMNS if c != "exits" and not row.get(c)]
        if empty:
            raise ValueError(
                f"config CSV row {i} is missing value(s) for {empty} -- likely everything landed in one "
                f"cell instead of separate columns. Row as read: {row}"
            )
        scenario_id = row["scenario_id"].strip()
        exits = [float(v.strip()) for v in row["exits"].split("|") if v.strip()]
        evac_start_t_2_raw = (row.get("evac_start_t_2") or "").strip()
        fire_position_raw = (row.get("fire_position") or "").strip()
        studies = [s.strip() for s in (row.get("study") or "").split("+") if s.strip()]
        jetfan_positions = [float(v.strip()) for v in (row.get("jetfan_positions") or "").split("|") if v.strip()]
        jetfan_off_positions = [
            float(v.strip()) for v in (row.get("jetfan_off_positions") or "").split("|") if v.strip()
        ]
        jetfan_counts = _parse_counts(row.get("jetfan_counts") or "", jetfan_positions)
        jetfan_off_counts = _parse_counts(row.get("jetfan_off_counts") or "", jetfan_off_positions)
        configs[scenario_id] = ScenarioConfig(
            scenario_id=scenario_id,
            exits=exits,
            occupants={
                "1": OccupantConfig(start_x=float(row["start_x_1"]), evac_start_t=float(row["evac_start_t_1"])),
                "2": OccupantConfig(
                    start_x=float(row["start_x_2"]),
                    evac_start_t=float(evac_start_t_2_raw) if evac_start_t_2_raw else None,
                ),
            },
            fire_position=float(fire_position_raw) if fire_position_raw else None,
            studies=studies,
            jetfan_positions=jetfan_positions,
            jetfan_off_positions=jetfan_off_positions,
            jetfan_counts=jetfan_counts,
            jetfan_off_counts=jetfan_off_counts,
        )
    return configs
