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

# Occupant leg labels: "U<n>" for the first (primary) leg, "LU<n>" ("Lost User")
# for every leg after a missed exit. Plain ASCII digits -- a Unicode subscript
# version was tried, but a batch CSV reopened in Excel without explicit UTF-8
# detection mangles it (bytes get reinterpreted as Windows-1252), so plain
# digits are the robust choice across every tool this might get opened in.
def _leg_label(occupant_number: str, leg_index: int) -> str:
    prefix = "U" if leg_index == 0 else "LU"
    return f"{prefix}{occupant_number}"


def t_iconv_minutes(temp_c: float) -> float:
    """Time to incapacitation from convective heat, in minutes (Purser)."""
    if temp_c <= 0:
        return float("inf")  # no meaningful convective-heat dose at/below 0 degC
    return 5e7 * temp_c**-3.4


@dataclass
class FedCheckpoint:
    leg_label: str  # e.g. "U1", "LU1", "U2" (subscripted digit)
    final_fed: float
    reached_limit: bool
    position: float | None  # distance (m) where FED crossed the tenability limit
    distance_traveled: float | None  # cumulative path distance (m) walked at that point
    time_s: float | None = None  # elapsed time (s) at which FED crossed the tenability limit


def compute_fed_checkpoints(
    segments: list[PathSegment],
    temperature_grid: XTGrid | None,
    occupant_number: str,
    tenability: float = TENABILITY_LIMIT,
    stop_at_limit: bool = True,
) -> list[FedCheckpoint]:
    """stop_at_limit=True (the default, used for real walked paths) cuts
    accumulation off the instant FED crosses tenability -- the occupant is
    modeled as incapacitated, so continuing the sum past that point wouldn't
    mean anything physically. stop_at_limit=False keeps accumulating for the
    segment's full duration regardless (used for the stationary UTR/reference
    checkpoints, where the full-period dose total is the point, not a
    walked-path incapacitation moment) -- reached_limit/time_s/position still
    record the first moment the threshold was crossed either way."""
    if not segments or temperature_grid is None:
        return []

    sampler = GridSampler(temperature_grid)
    cumulative_fed = 0.0
    cumulative_distance = 0.0
    checkpoints: list[FedCheckpoint] = []

    for i, seg in enumerate(segments):
        leg_label = _leg_label(occupant_number, i)
        reached_limit = False
        limit_position: float | None = None
        limit_distance: float | None = None
        limit_time: float | None = None

        points = seg.points
        for j in range(1, len(points)):
            t_prev, x_prev = points[j - 1]
            t_cur, x_cur = points[j]
            dt_minutes = (t_cur - t_prev) / 60.0
            t_mid, x_mid = (t_prev + t_cur) / 2.0, (x_prev + x_cur) / 2.0
            temp_c = sampler.at(x_mid, t_mid)
            cumulative_fed += dt_minutes / t_iconv_minutes(temp_c)
            cumulative_distance += abs(x_cur - x_prev)

            if cumulative_fed >= tenability and not reached_limit:
                reached_limit = True
                limit_position = x_cur
                limit_distance = cumulative_distance
                limit_time = t_cur
                if stop_at_limit:
                    break

        checkpoints.append(
            FedCheckpoint(
                leg_label=leg_label,
                final_fed=cumulative_fed,
                reached_limit=reached_limit,
                position=limit_position,
                distance_traveled=limit_distance,
                time_s=limit_time,
            )
        )
        if reached_limit and stop_at_limit:
            break

    return checkpoints


@dataclass
class FedTimeseriesPoint:
    leg_label: str  # e.g. "U1", "LU1", "U2" (subscripted digit)
    time_s: float
    position_m: float
    temperature_c: float
    cumulative_fed: float


def compute_fed_timeseries(
    segments: list[PathSegment],
    temperature_grid: XTGrid | None,
    occupant_number: str,
    tenability: float = TENABILITY_LIMIT,
    stop_at_limit: bool = True,
) -> list[FedTimeseriesPoint]:
    """Same accumulation as compute_fed_checkpoints, but returns every step
    (not just the per-leg summary) -- for plotting temperature/FED vs time.
    cumulative_fed lines up exactly with compute_fed_checkpoints' final_fed
    values since both use the same midpoint-sampled increment; temperature_c
    here is instead sampled at the actual point for a more intuitive reading.
    See compute_fed_checkpoints for what stop_at_limit controls."""
    if not segments or temperature_grid is None:
        return []

    sampler = GridSampler(temperature_grid)
    cumulative_fed = 0.0
    out: list[FedTimeseriesPoint] = []

    for i, seg in enumerate(segments):
        leg_label = _leg_label(occupant_number, i)
        points = seg.points
        if not points:
            continue

        t0, x0 = points[0]
        out.append(FedTimeseriesPoint(leg_label, t0, x0, sampler.at(x0, t0), cumulative_fed))

        reached_limit = False
        for j in range(1, len(points)):
            t_prev, x_prev = points[j - 1]
            t_cur, x_cur = points[j]
            dt_minutes = (t_cur - t_prev) / 60.0
            t_mid, x_mid = (t_prev + t_cur) / 2.0, (x_prev + x_cur) / 2.0
            cumulative_fed += dt_minutes / t_iconv_minutes(sampler.at(x_mid, t_mid))
            out.append(FedTimeseriesPoint(leg_label, t_cur, x_cur, sampler.at(x_cur, t_cur), cumulative_fed))

            if cumulative_fed >= tenability and not reached_limit:
                reached_limit = True
                if stop_at_limit:
                    break

        if reached_limit and stop_at_limit:
            break

    return out


def _stationary_segment(start_x: float, wait_until_t: float, dt: float = 1.0) -> PathSegment | None:
    """A constant-position "path" from t=0 to wait_until_t, at the same dt a
    real walked path uses -- for FED purposes, standing still is just a path
    that never changes x, so the existing accumulation loop applies as-is."""
    if wait_until_t <= 0:
        return None
    n_steps = int(wait_until_t // dt)
    points = [(i * dt, start_x) for i in range(n_steps + 1)]
    if points[-1][0] < wait_until_t:
        points.append((wait_until_t, start_x))
    return PathSegment(points=points, style="solid")


def compute_stationary_fed_checkpoint(
    start_x: float,
    wait_until_t: float,
    temperature_grid: XTGrid | None,
    occupant_number: str,
    tenability: float = TENABILITY_LIMIT,
    dt: float = 1.0,
) -> FedCheckpoint | None:
    """FED for someone who stays put at start_x from t=0 until wait_until_t
    (e.g. before they start evacuating) -- not a real walked path, just
    exposure while waiting. Pass e.g. occupant_number="TR1" to get a
    "UTR1"-style label. Always runs stop_at_limit=False: the point is the
    full-period dose total, even past 0.3 -- reached_limit/time_s still
    record when 0.3 was first crossed, but final_fed is the complete sum
    through wait_until_t, not cut short there."""
    segment = _stationary_segment(start_x, wait_until_t, dt)
    if segment is None or temperature_grid is None:
        return None
    checkpoints = compute_fed_checkpoints(
        [segment], temperature_grid, occupant_number, tenability, stop_at_limit=False
    )
    return checkpoints[0] if checkpoints else None


def compute_stationary_fed_timeseries(
    start_x: float,
    wait_until_t: float,
    temperature_grid: XTGrid | None,
    occupant_number: str,
    tenability: float = TENABILITY_LIMIT,
    dt: float = 1.0,
) -> list[FedTimeseriesPoint]:
    """Timeseries counterpart to compute_stationary_fed_checkpoint -- same
    "standing still" segment, every step instead of just the summary, also
    always running the full wait_until_t duration (stop_at_limit=False)."""
    segment = _stationary_segment(start_x, wait_until_t, dt)
    if segment is None or temperature_grid is None:
        return []
    return compute_fed_timeseries([segment], temperature_grid, occupant_number, tenability, stop_at_limit=False)


def truncate_segments_at_time(segments: list[PathSegment], time_s: float) -> list[PathSegment]:
    """Cuts a path's segments off at time_s, dropping everything after it --
    used to stop drawing an occupant's path at the exact point their FED
    crossed the tenability limit, since they can't physically continue past
    that point. time_s is expected to exactly match one of the segments'
    existing points (it comes from the same walk compute_fed_checkpoints did)."""
    truncated: list[PathSegment] = []
    for seg in segments:
        kept_points = [p for p in seg.points if p[0] <= time_s]
        if not kept_points:
            break
        truncated.append(PathSegment(points=kept_points, style=seg.style))
        if kept_points[-1][0] >= time_s:
            break
    return truncated
