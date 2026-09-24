"""Identify which scenario an uploaded combined XT CSV's text belongs to.

The scenario_id is read from the file's own "Scenario: <id>" line rather
than the filename, since the file is the authoritative source.
"""
from __future__ import annotations

import csv
import io


def read_scenario_id(text: str) -> str | None:
    first_row = next(csv.reader(io.StringIO(text), delimiter=";"), None)
    if not first_row or not first_row[0]:
        return None
    line = first_row[0].strip()
    return line.split(":", 1)[1].strip() if ":" in line else None
