"""Parser for CAMATT X-T (distance x time) CSV exports.

File layout (semicolon-delimited):
    row 1: "Scenario: <name>"
    row 2: "<mode> - <date>"
    row 3: blank
    row 4: "<tunnel name>"
    row 5: blank
    row 6: "<parameter name>"          e.g. "Air opacity", "Air temperature", "CO concentration"
    row 7: "Length(m);t = 0s;t = 10s;...;"   (header, trailing ';' produces one empty column)
    row 8+: "<distance>;<v0>;<v1>;...;"       (one row per distance station)
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_TIME_HEADER_RE = re.compile(r"t\s*=\s*([0-9.]+)\s*s", re.IGNORECASE)


@dataclass
class XTGrid:
    scenario: str
    parameter_name: str
    distances: np.ndarray  # shape (n_x,), meters, ascending
    times: np.ndarray  # shape (n_t,), seconds, ascending
    values: np.ndarray  # shape (n_x, n_t)
    source_path: str

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "parameter_name": self.parameter_name,
            "distances": self.distances.tolist(),
            "times": self.times.tolist(),
            "values": self.values.tolist(),
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "XTGrid":
        return cls(
            scenario=d["scenario"],
            parameter_name=d["parameter_name"],
            distances=np.asarray(d["distances"], dtype=float),
            times=np.asarray(d["times"], dtype=float),
            values=np.asarray(d["values"], dtype=float),
            source_path=d.get("source_path", ""),
        )


def _parse_time_header(header: list[str], source_name: str) -> list[float]:
    times: list[float] = []
    for cell in header[1:]:
        cell = cell.strip()
        if not cell:
            continue
        m = _TIME_HEADER_RE.search(cell)
        if not m:
            raise ValueError(f"{source_name}: could not parse time header cell {cell!r}")
        times.append(float(m.group(1)))
    return times


def _parse_data_rows(data_rows: list[list[str]], times: list[float], source_name: str) -> tuple:
    distances: list[float] = []
    values_rows: list[list[float]] = []
    for row in data_rows:
        if not row or not row[0].strip():
            continue
        distances.append(float(row[0]))
        vals = [float(v) for v in row[1 : 1 + len(times)]]
        if len(vals) != len(times):
            raise ValueError(
                f"{source_name}: row for distance {row[0]} has {len(vals)} values, expected {len(times)}"
            )
        values_rows.append(vals)

    distances_arr = np.asarray(distances, dtype=float)
    values_arr = np.asarray(values_rows, dtype=float)

    if not np.all(np.diff(distances_arr) > 0):
        order = np.argsort(distances_arr)
        distances_arr = distances_arr[order]
        values_arr = values_arr[order, :]

    return distances_arr, values_arr


def parse_xt_csv_text(text: str, source_name: str = "") -> XTGrid:
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))

    if len(rows) < 8:
        raise ValueError(f"{source_name}: expected at least 8 rows, got {len(rows)}")

    scenario_line = rows[0][0] if rows[0] else ""
    scenario = scenario_line.split(":", 1)[1].strip() if ":" in scenario_line else scenario_line.strip()

    parameter_name = rows[5][0].strip() if rows[5] else ""

    times = _parse_time_header(rows[6], source_name)
    distances_arr, values_arr = _parse_data_rows(rows[7:], times, source_name)

    return XTGrid(
        scenario=scenario,
        parameter_name=parameter_name,
        distances=distances_arr,
        times=np.asarray(times, dtype=float),
        values=values_arr,
        source_path=source_name,
    )


def parse_xt_csv(path: str | Path) -> XTGrid:
    path = Path(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        text = f.read()
    return parse_xt_csv_text(text, source_name=str(path))


def _iter_parameter_blocks(rows: list[list[str]]):
    """Yield (parameter_name, header_row, data_rows) for each stacked parameter
    block in a combined multi-parameter XT CSV. A block is any row with a
    non-empty first cell immediately followed by a "Length(m);..." header row --
    this doesn't assume fixed line numbers, so it's agnostic to how many blocks
    are stacked or what shared header lines (scenario/tunnel name) precede them."""
    i = 0
    n = len(rows)
    while i < n:
        row = rows[i]
        next_row = rows[i + 1] if i + 1 < n else None
        if row and row[0].strip() and next_row and next_row[0].strip().lower().startswith("length"):
            parameter_name = row[0].strip()
            header = next_row
            j = i + 2
            data_rows: list[list[str]] = []
            while j < n and rows[j] and rows[j][0].strip():
                data_rows.append(rows[j])
                j += 1
            yield parameter_name, header, data_rows
            i = j
        else:
            i += 1


def _classify_parameter(parameter_name: str) -> str:
    """Map a block's parameter-name text to a slot key. CO's block isn't always
    literally labeled "CO" (CAMATT exports have used "Pollutant concentration"),
    so temperature/opacity are matched by keyword and whatever's left over is
    treated as CO by elimination -- there are always exactly 3 blocks."""
    key = parameter_name.lower()
    if "temp" in key:
        return "temperature"
    if "opac" in key:
        return "opacity"
    return "co"


def parse_combined_xt_csv_text(text: str, source_name: str = "") -> dict[str, XTGrid]:
    """Parse a CAMATT export with all 3 parameters (temperature, opacity, CO)
    stacked in one file under a single shared scenario/tunnel header."""
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    scenario_line = rows[0][0] if rows and rows[0] else ""
    scenario = scenario_line.split(":", 1)[1].strip() if ":" in scenario_line else scenario_line.strip()

    grids: dict[str, XTGrid] = {}
    for parameter_name, header, data_rows in _iter_parameter_blocks(rows):
        times = _parse_time_header(header, source_name)
        distances_arr, values_arr = _parse_data_rows(data_rows, times, source_name)
        slot = _classify_parameter(parameter_name)
        grids[slot] = XTGrid(
            scenario=scenario,
            parameter_name=parameter_name,
            distances=distances_arr,
            times=np.asarray(times, dtype=float),
            values=values_arr,
            source_path=source_name,
        )
    return grids


def parse_combined_xt_csv(path: str | Path) -> dict[str, XTGrid]:
    path = Path(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        text = f.read()
    return parse_combined_xt_csv_text(text, source_name=str(path))
