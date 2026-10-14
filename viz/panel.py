"""Shared per-parameter figure assembly.

Used by both the interactive UI (app.py) and the batch scenario export
(batch.runner) so a scenario rendered interactively and the same scenario
rendered via batch produce identical figures.
"""
from __future__ import annotations

from data.xt_parser import XTGrid
from trajectory.fed import compute_fed_checkpoints, truncate_segments_at_time
from trajectory.segment import PathSegment
from viz.colorscale import ColorScale, get_scale_for
from viz.heatmap import (
    add_exit_icons,
    add_fire_zone,
    add_jetfan_lines,
    add_occupant_icon,
    add_path_traces,
    add_reference_lines,
    add_tunnel_icons,
    build_empty_figure,
    build_heatmap_figure,
)

OCCUPANT_ICON = "/assets/EvacPath_icon.png"
EXIT_ICON = "/assets/ExitDoor.png"


def build_panel_figure(
    slot_label: str,
    grid_data: dict | None,
    legend_data: dict | None,
    occupants_data,
    label_side: str = "left",
    fire_position: float | None = None,
    temperature_grid_data: dict | None = None,
    jetfan_positions: list[float] | None = None,
    jetfan_off_positions: list[float] | None = None,
    jetfan_counts: list[int] | None = None,
    jetfan_off_counts: list[int] | None = None,
    show_jetfans: bool = False,
    show_jetfans_off: bool = False,
):
    if grid_data is None:
        return build_empty_figure(f"No {slot_label} CSV loaded yet.")

    grid = XTGrid.from_dict(grid_data)
    scale = ColorScale.from_dict(legend_data) if legend_data else get_scale_for(slot_label)
    fig = build_heatmap_figure(grid, scale)
    x_range = (min(grid.distances), max(grid.distances))
    y_range = (min(grid.times), max(grid.times))

    fig = add_tunnel_icons(fig, x_range)
    if fire_position is not None:
        fig = add_fire_zone(fig, fire_position)
    if show_jetfans or show_jetfans_off:
        fig = add_jetfan_lines(
            fig,
            jetfan_positions,
            jetfan_off_positions,
            x_range,
            show_on=show_jetfans,
            show_off=show_jetfans_off,
            jetfan_counts=jetfan_counts,
            jetfan_off_counts=jetfan_off_counts,
        )

    temperature_grid = XTGrid.from_dict(temperature_grid_data) if temperature_grid_data else None

    for o, segments_data, refs_data in occupants_data:
        refs_data = refs_data or {}
        fig = add_reference_lines(
            fig,
            evac_start_t=refs_data.get("evac_start_t"),
            exits=refs_data.get("exits"),
            label_side=label_side,
            occupant_subscript=o["id"],
            label_above=(o["id"] == "2"),
        )
        fig = add_exit_icons(fig, refs_data.get("exits"), x_range, icon_path=EXIT_ICON)
        segments = [PathSegment.from_dict(s) for s in (segments_data or [])]

        incapacitated = False
        if temperature_grid is not None and segments:
            limit_cp = next(
                (cp for cp in compute_fed_checkpoints(segments, temperature_grid, o["id"]) if cp.reached_limit), None
            )
            if limit_cp is not None:
                segments = truncate_segments_at_time(segments, limit_cp.time_s)
                incapacitated = True

        fig = add_path_traces(
            fig, segments, color=o["color"], label=o["label"], x_range=x_range, y_range=y_range, incapacitated=incapacitated
        )
        fig = add_occupant_icon(fig, segments, x_range, y_range, icon_path=OCCUPANT_ICON)

    return fig
