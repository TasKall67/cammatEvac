"""Numerically integrate an occupant's position over time from a speed-vs-opacity model.

The primary leg (start -> first exit) is solid; if more exits are given the
occupant is assumed to keep walking past the first one (e.g. treating it as
unavailable), continuing leg-by-leg through the remaining exits in the order
given, each additional leg drawn dashed. Exits are consumed in the order the
caller supplies them, not re-sorted here -- callers use select_valid_exits()
below to turn a raw exit list into a fire-aware, nearest-first one first.
"""
from __future__ import annotations

from data.xt_parser import XTGrid
from trajectory.grid_sampler import GridSampler
from trajectory.segment import PathSegment
from trajectory.speed_model import SpeedTable


def _integrate_leg(
    sampler: GridSampler,
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


MIN_SAFE_DISTANCE_FROM_FIRE = 50  # meters -- an exit this close to the fire is too hot to use


def select_valid_exits(
    exits: list[float],
    start_x: float,
    fire_position: float | None,
    tunnel_bounds: tuple[float, float] | None = None,
    min_safe_distance_from_fire: float = MIN_SAFE_DISTANCE_FROM_FIRE,
) -> list[float]:
    """Drops any exit that would require crossing the fire's position to reach
    (an occupant won't run toward/through the fire for a nominally-closer
    exit), and any exit within min_safe_distance_from_fire of the fire even if
    on the correct side (too hot to actually use), then sorts what's left
    nearest-first from start_x -- so exit order no longer needs to be entered
    manually in "nearest first" order.

    tunnel_bounds (the tunnel's own start/end distances) are folded in as two
    extra candidate exits -- the tunnel portals are always a way out, even if
    no listed exit is reachable without crossing the fire -- but they're not
    drawn with their own exit icon/line, since the tunnel-portal icon already
    marks those two points."""
    candidates = list(exits)
    if tunnel_bounds is not None:
        candidates += [tunnel_bounds[0], tunnel_bounds[1]]
    if fire_position is not None:
        if start_x <= fire_position:
            candidates = [x for x in candidates if x <= fire_position]
        else:
            candidates = [x for x in candidates if x >= fire_position]
        candidates = [x for x in candidates if abs(x - fire_position) >= min_safe_distance_from_fire]
    return sorted(set(candidates), key=lambda x: abs(x - start_x))


def compute_zoom_x_range(
    exits: list[float],
    start_x: float,
    fire_position: float,
    tunnel_bounds: tuple[float, float],
) -> tuple[float, float]:
    """X-axis range for a batch 'zoomed' export: from 100m past the fire on the
    side AWAY from the occupant, in to 100m past the second-nearest-to-the-fire
    exit on the occupant's own side (or the tunnel portal on that side, if
    there's no second exit). "Second nearest to the fire" is a property of the
    scenario (same for both occupants), not of any one occupant's own start_x.
    """
    on_lower_side = start_x <= fire_position
    same_side = [x for x in exits if (x <= fire_position if on_lower_side else x >= fire_position)]
    same_side.sort(key=lambda x: abs(x - fire_position))  # nearest-to-fire first

    if on_lower_side:
        far_boundary = fire_position + 100
        near_boundary = (same_side[1] - 100) if len(same_side) >= 2 else tunnel_bounds[0]
    else:
        far_boundary = fire_position - 100
        near_boundary = (same_side[1] + 100) if len(same_side) >= 2 else tunnel_bounds[1]

    return (min(near_boundary, far_boundary), max(near_boundary, far_boundary))


def compute_triggered_evac_start_t(
    opacity_grid: XTGrid,
    speed_table: SpeedTable,
    leader_start_x: float,
    leader_start_t: float,
    follower_start_x: float,
    leader_reaction_time: float = 130.0,
    opacity_threshold: float = 0.1,
    smoke_reaction_time: float = 80.0,
    dt: float = 1.0,
) -> float | None:
    """Dynamic evacuation-start time for a "follower" occupant too far from
    the fire to notice it directly, who instead reacts to whichever of two
    cues comes first:
      (a) a "leader" occupant (already evacuating) physically walking past
          the follower's own start position -- leader_reaction_time seconds
          after that moment;
      (b) smoke (air opacity) itself reaching opacity_threshold at the
          follower's own (stationary, not-yet-moving) position --
          smoke_reaction_time seconds after that moment.
    Returns the EARLIER of the two trigger times, or None if neither cue ever
    occurs within the grid's simulated time window -- callers should fall
    back to a fixed evac-start time in that case. The leader's walk here is
    independent of whichever exit they eventually choose -- just "when do
    they pass through this x position" -- so it doesn't need exits at all."""
    sampler = GridSampler(opacity_grid)

    leader_points = _integrate_leg(sampler, speed_table, leader_start_x, leader_start_t, follower_start_x, dt)
    trigger_a = (
        leader_points[-1][0] + leader_reaction_time
        if len(leader_points) >= 2 and leader_points[-1][1] == follower_start_x
        else None
    )

    trigger_b = None
    t = 0.0
    while t <= sampler.t_max:
        if sampler.at(follower_start_x, t) >= opacity_threshold:
            trigger_b = t + smoke_reaction_time
            break
        t += dt

    candidates = [v for v in (trigger_a, trigger_b) if v is not None]
    return min(candidates) if candidates else None


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

    sampler = GridSampler(grid)
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
