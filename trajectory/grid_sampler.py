"""Generic (x, t) bilinear interpolation over an XT grid.

Shared by trajectory.integrator (speed-vs-opacity lookups while walking the
path) and trajectory.fed (sampling temperature along an already-computed
path) -- same interpolation, different physical quantity per caller.
"""
from __future__ import annotations

from scipy.interpolate import RegularGridInterpolator

from data.xt_parser import XTGrid


class GridSampler:
    def __init__(self, grid: XTGrid):
        self._x_min, self._x_max = float(grid.distances.min()), float(grid.distances.max())
        self._t_min, self._t_max = float(grid.times.min()), float(grid.times.max())
        self._interp = RegularGridInterpolator(
            (grid.distances, grid.times), grid.values, bounds_error=False, fill_value=None
        )

    def at(self, x: float, t: float) -> float:
        x = min(max(x, self._x_min), self._x_max)
        t = min(max(t, self._t_min), self._t_max)
        return float(self._interp([[x, t]])[0])

    @property
    def t_max(self) -> float:
        return self._t_max
