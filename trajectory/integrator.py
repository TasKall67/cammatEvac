"""Numerically integrate an occupant's position over time from a speed-vs-opacity model.

The primary leg (start -> first exit) is solid; if more exits are given the
occupant is assumed to keep walking past the first one (e.g. treating it as
unavailable), continuing leg-by-leg through the remaining exits in the order
given, each additional leg drawn dashed. Exits are consumed in the order the
caller supplies them (the UI asks for "nearest first"), not re-sorted here.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from data.xt_parser import XTGrid
from trajectory.segment import PathSegment
from trajectory.speed_model import SpeedTable


class OpacitySampler:
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


def _integrate_leg(
    sampler: OpacitySampler,
    speed_table: SpeedTable,
    start_x: float,
    start_t: float,
    target_x: float,
    dt: float,
) -> list[tuple[float, float]]:
    x, t = start_x, start_t
    points: list[tuple[float, float]] = [(t, x)]
    direction = 1.0 if target_x > x else (-1.0 if target_x < x else 0.0)
    if direction == 0.0:
        return points

    while t <= sampler.t_max:
        opacity = sampler.at(x, t)
        speed = speed_table.speed_at(opacity)
        if speed <= 0:
            break
        x_next = x + direction * speed * dt
        t_next = t + dt
        if (direction > 0 and x_next >= target_x) or (direction < 0 and x_next <= target_x):
            points.append((t_next, target_x))
            return points
        x, t = x_next, t_next
        points.append((t, x))
    return points


def compute_path(
    grid: XTGrid,
    start_x: float,
    start_t: float,
    exits: list[float],
    speed_table: SpeedTable,
    dt: float = 1.0,
) -> list[PathSegment]:
    if not exits:
        return []

    sampler = OpacitySampler(grid)
    segments: list[PathSegment] = []
    x, t = start_x, start_t

    for i, exit_x in enumerate(exits):
        points = _integrate_leg(sampler, speed_table, x, t, exit_x, dt)
        segments.append(PathSegment(points=points, style="solid" if i == 0 else "dashed"))
        if len(points) < 2 or points[-1][1] != exit_x:
            # ran out of simulated time, or occupant got stuck (speed hit 0) before reaching this exit
            break
        t, x = points[-1]

    return segments
