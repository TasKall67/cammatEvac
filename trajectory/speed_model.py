"""User-editable, piecewise-linear walking-speed-vs-opacity model.

speed(opacity) is linearly interpolated between (opacity, speed) breakpoints,
clamped to the first/last speed outside the defined range. Defaults are a
placeholder loosely inspired by visibility-based walking-speed degradation
(Jin-style smoke/visibility models) and MUST be recalibrated by the user to
CAMATT's actual opacity units/scale before being used for real analysis.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"

DEFAULT_BREAKPOINTS = [0.0, 0.5, 0.7, 1.0, 4.0, ]
DEFAULT_SPEEDS =      [1.5, 1.2, 1.0, 0.5, 0.3, ]


@dataclass
class SpeedTable:
    breakpoints: list[float]  # opacity values, ascending
    speeds: list[float]  # walking speed (m/s) at each breakpoint
    units: str = "m/s"

    def __post_init__(self):
        if len(self.breakpoints) != len(self.speeds):
            raise ValueError("breakpoints and speeds must be the same length")
        if len(self.breakpoints) < 2:
            raise ValueError("need at least 2 breakpoints")
        if list(self.breakpoints) != sorted(self.breakpoints):
            raise ValueError("breakpoints must be ascending")

    def speed_at(self, opacity: float) -> float:
        return float(np.interp(opacity, self.breakpoints, self.speeds))

    def to_dict(self) -> dict:
        return {"breakpoints": self.breakpoints, "speeds": self.speeds, "units": self.units}

    @classmethod
    def from_dict(cls, d: dict) -> "SpeedTable":
        return cls(breakpoints=list(d["breakpoints"]), speeds=list(d["speeds"]), units=d.get("units", "m/s"))


DEFAULT_PRESET_NAME = "default"


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower())


def _legacy_preset_path(owner: str) -> Path:
    """Pre-multi-preset filename convention (single preset per owner)."""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return PRESETS_DIR / f"{_slug(owner)}_speed_table.json"


def _preset_path(owner: str, name: str) -> Path:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    name_slug = _slug(name).strip("_") or "preset"
    return PRESETS_DIR / f"{_slug(owner)}--{name_slug}.json"


def save_preset(owner: str, table: SpeedTable, name: str = DEFAULT_PRESET_NAME) -> None:
    _preset_path(owner, name).write_text(json.dumps(table.to_dict(), indent=2), encoding="utf-8")


def load_preset(owner: str, name: str = DEFAULT_PRESET_NAME) -> SpeedTable | None:
    path = _preset_path(owner, name)
    if not path.exists() and name == DEFAULT_PRESET_NAME:
        path = _legacy_preset_path(owner)  # back-compat with presets saved before named presets existed
    if not path.exists():
        return None
    return SpeedTable.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_presets(owner: str) -> list[str]:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{_slug(owner)}--"
    names = sorted(p.stem[len(prefix):] for p in PRESETS_DIR.glob(f"{prefix}*.json"))
    if DEFAULT_PRESET_NAME not in names and _legacy_preset_path(owner).exists():
        names.insert(0, DEFAULT_PRESET_NAME)
    return names


def default_speed_table() -> SpeedTable:
    return SpeedTable(breakpoints=list(DEFAULT_BREAKPOINTS), speeds=list(DEFAULT_SPEEDS))


def get_speed_table(owner: str) -> SpeedTable:
    return load_preset(owner) or default_speed_table()
