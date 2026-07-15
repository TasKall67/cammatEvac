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


def parse_xt_csv_text(text: str, source_name: str = "") -> XTGrid:
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))

    if len(rows) < 8:
        raise ValueError(f"{source_name}: expected at least 8 rows, got {len(rows)}")

    scenario_line = rows[0][0] if rows[0] else ""
    scenario = scenario_line.split(":", 1)[1].strip() if ":" in scenario_line else scenario_line.strip()

    parameter_name = rows[5][0].strip() if rows[5] else ""

    header = rows[6]
    times: list[float] = []
    for cell in header[1:]:
        cell = cell.strip()
        if not cell:
            continue
        m = _TIME_HEADER_RE.search(cell)
        if not m:
            raise ValueError(f"{source_name}: could not parse time header cell {cell!r}")
        times.append(float(m.group(1)))

    distances: list[float] = []
    values_rows: list[list[float]] = []
    for row in rows[7:]:
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
    times_arr = np.asarray(times, dtype=float)
    values_arr = np.asarray(values_rows, dtype=float)

    if not np.all(np.diff(distances_arr) > 0):
        order = np.argsort(distances_arr)
        distances_arr = distances_arr[order]
        values_arr = values_arr[order, :]

    return XTGrid(
        scenario=scenario,
        parameter_name=parameter_name,
        distances=distances_arr,
        times=times_arr,
        values=values_arr,
        source_path=source_name,
    )


def parse_xt_csv(path: str | Path) -> XTGrid:
    path = Path(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        text = f.read()
    return parse_xt_csv_text(text, source_name=str(path))
