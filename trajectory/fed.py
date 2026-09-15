"""Fractional Effective Dose (FED) from convective heat exposure along a computed path.

FED = sum(dt / t_Iconv), where t_Iconv = 5e7 * T**-3.4 (T in degC, t_Iconv in
minutes) is the Purser convective-heat term of the standard FED model. The
radiant term (1/t_Irad) is assumed zero here per the user's request.

Accumulation is continuous across an occupant's path segments -- an occupant
who misses their first exit keeps accreting dose on the dashed leg to the
next one, the running total is never reset per leg. Accumulation stops the
instant either the occupant reaches an exit or cumulative FED crosses the
NFPA tenability limit (0.3), whichever comes first. If the limit is crossed
mid-leg, later legs are never evaluated -- the occupant is already modeled
as incapacitated at that point.
"""
from __future__ import annotations

from dataclasses import dataclass

from data.xt_parser import XTGrid
from trajectory.grid_sampler import GridSampler
from trajectory.segment import PathSegment

TENABILITY_LIMIT = 0.3
_LEG_NAMES = "abcdefgh"


def t_iconv_minutes(temp_c: float) -> float:
    """Time to incapacitation from convective heat, in minutes (Purser)."""
    if temp_c <= 0:
        return float("inf")  # no meaningful convective-heat dose at/below 0 degC
    return 5e7 * temp_c**-3.4


@dataclass
class FedCheckpoint:
    leg_label: str  # e.g. "Fa", "Fb", "La"
    final_fed: float
    reached_limit: bool
    position: float | None  # distance (m) where FED crossed the tenability limit
    distance_traveled: float | None  # cumulative path distance (m) walked at that point


def compute_fed_checkpoints(
    segments: list[PathSegment],
    temperature_grid: XTGrid | None,
    occupant_prefix: str,
    tenability: float = TENABILITY_LIMIT,
) -> list[FedCheckpoint]:
    if not segments or temperature_grid is None:
        return []

    sampler = GridSampler(temperature_grid)
    cumulative_fed = 0.0
    cumulative_distance = 0.0
    checkpoints: list[FedCheckpoint] = []

    for i, seg in enumerate(segments):
        leg_label = f"{occupant_prefix}{_LEG_NAMES[i] if i < len(_LEG_NAMES) else i}"
        reached_limit = False
        limit_position: float | None = None
        limit_distance: float | None = None

        points = seg.points
        for j in range(1, len(points)):
            t_prev, x_prev = points[j - 1]
            t_cur, x_cur = points[j]
            dt_minutes = (t_cur - t_prev) / 60.0
            t_mid, x_mid = (t_prev + t_cur) / 2.0, (x_prev + x_cur) / 2.0
            temp_c = sampler.at(x_mid, t_mid)
            cumulative_fed += dt_minutes / t_iconv_minutes(temp_c)
            cumulative_distance += abs(x_cur - x_prev)

            if cumulative_fed >= tenability:
                reached_limit = True
                limit_position = x_cur
                limit_distance = cumulative_distance
                break

        checkpoints.append(
            FedCheckpoint(
                leg_label=leg_label,
                final_fed=cumulative_fed,
                reached_limit=reached_limit,
                position=limit_position,
                distance_traveled=limit_distance,
            )
        )
        if reached_limit:
            break

    return checkpoints
