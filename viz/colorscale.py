"""Discrete, user-editable color legends (banded, not interpolated) for X-T heatmaps.

A ColorScale is defined by N ascending thresholds and N+1 colors:
    value <= thresholds[0]                 -> colors[0]  (flat base color)
    colors[i] sits exactly AT thresholds[i], for i in 0..N-1, gradient-interpolated
    between consecutive thresholds
    value >= thresholds[-1]               -> colors[-1]   (flat plateau, shown as "≥ thresholds[-1]" on the legend)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"

# Defaults mirror the sample CAMATT legend (temperature, deg C).
DEFAULT_PRESETS: dict[str, "ColorScale"] = {}


@dataclass
class ColorScale:
    thresholds: list[float]
    colors: list[str]  # len(colors) == len(thresholds) + 1
    units: str = ""

    def __post_init__(self):
        if len(self.colors) != len(self.thresholds) + 1:
            raise ValueError(
                f"ColorScale needs len(colors) == len(thresholds)+1, "
                f"got {len(self.colors)} colors and {len(self.thresholds)} thresholds"
            )
        if list(self.thresholds) != sorted(self.thresholds):
            raise ValueError("thresholds must be ascending")

    def tick_labels(self) -> list[str]:
        return [f"{t:g}" for t in self.thresholds] + [f">{self.thresholds[-1]:g}"]

    def to_plotly_colorscale(self, data_min: float, data_max: float) -> tuple[list[list], float, float]:
        zmin = min(self.thresholds[0], data_min)
        zmax = max(self.thresholds[-1], data_max)
        if zmax <= zmin:
            zmax = zmin + 1.0

        def pos(v: float) -> float:
            return (v - zmin) / (zmax - zmin)

        # colors[i] (i < N) sits exactly at thresholds[i] -- the row showing a given
        # threshold input also owns the color that appears AT that value, not the
        # color from the row before it. colors[0] is flat from zmin up to
        # thresholds[0]; colors[-1] is a flat plateau from thresholds[-1] to zmax.
        colorscale: list[list] = [[0.0, self.colors[0]]]
        for i, t in enumerate(self.thresholds):
            colorscale.append([pos(t), self.colors[i]])
        colorscale.append([pos(self.thresholds[-1]), self.colors[-1]])  # hard step into the plateau color
        colorscale.append([1.0, self.colors[-1]])
        return colorscale, zmin, zmax

    def to_dict(self) -> dict:
        return {"thresholds": self.thresholds, "colors": self.colors, "units": self.units}

    @classmethod
    def from_dict(cls, d: dict) -> "ColorScale":
        return cls(thresholds=list(d["thresholds"]), colors=list(d["colors"]), units=d.get("units", ""))


DEFAULT_PRESET_NAME = "default"


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower())


def _legacy_preset_path(parameter_key: str) -> Path:
    """Pre-multi-preset filename convention (single preset per parameter)."""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return PRESETS_DIR / f"{_slug(parameter_key)}_legend.json"


def _preset_path(parameter_key: str, name: str) -> Path:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    name_slug = _slug(name).strip("_") or "preset"
    return PRESETS_DIR / f"{_slug(parameter_key)}--{name_slug}.json"


def save_preset(parameter_key: str, scale: ColorScale, name: str = DEFAULT_PRESET_NAME) -> None:
    path = _preset_path(parameter_key, name)
    path.write_text(json.dumps(scale.to_dict(), indent=2), encoding="utf-8")


def load_preset(parameter_key: str, name: str = DEFAULT_PRESET_NAME) -> ColorScale | None:
    path = _preset_path(parameter_key, name)
    if not path.exists() and name == DEFAULT_PRESET_NAME:
        path = _legacy_preset_path(parameter_key)  # back-compat with presets saved before named presets existed
    if not path.exists():
        return None
    return ColorScale.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_presets(parameter_key: str) -> list[str]:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{_slug(parameter_key)}--"
    names = sorted(p.stem[len(prefix):] for p in PRESETS_DIR.glob(f"{prefix}*.json"))
    if DEFAULT_PRESET_NAME not in names and _legacy_preset_path(parameter_key).exists():
        names.insert(0, DEFAULT_PRESET_NAME)
    return names


def default_scale_for(parameter_key: str) -> ColorScale:
    key = parameter_key.lower()
    if "temp" in key:
        return ColorScale(
            thresholds=[15, 50, 100, 150, 200, 250],
            colors=["#0000FF", "#00C0C0", "#008000", "#FFFF00", "#FF6A00", "#FF0000", "#000000"],
            units="°C",
        )
    if "opac" in key:
        return ColorScale(
            thresholds=[1, 2, 3, 4, 5, 6],
            colors=["#0000FF", "#00C0C0", "#008000", "#FFFF00", "#FF6A00", "#FF0000", "#800000"],
            units="1/m",
        )
    if "co" in key:
        return ColorScale(
            thresholds=[25, 50, 100, 200, 400, 800],
            colors=["#0000FF", "#00C0C0", "#008000", "#FFFF00", "#FF6A00", "#FF0000", "#000000"],
            units="ppm",
        )
    return ColorScale(
        thresholds=[15, 50, 100, 150, 200, 250],
        colors=["#0000FF", "#00C0C0", "#008000", "#FFFF00", "#FF6A00", "#FF0000", "#000000"],
        units="",
    )


def get_scale_for(parameter_key: str) -> ColorScale:
    return load_preset(parameter_key) or default_scale_for(parameter_key)
