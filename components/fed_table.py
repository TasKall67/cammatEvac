"""Small tenability table: cumulative convective-heat FED per occupant leg,
and where (if at all) the NFPA 0.3 tenability limit was first crossed.
"""
from __future__ import annotations

from dash import Input, Output, html

from components.file_panel import grid_store_id
from components.occupant_panel import segments_store_id
from data.xt_parser import XTGrid
from trajectory.fed import TENABILITY_LIMIT, compute_fed_checkpoints
from trajectory.segment import PathSegment

_TABLE_BODY_ID = "fed-table-body"
_HEADERS = ["Leg", "FED", f"Reached {TENABILITY_LIMIT:g}?", "Position (m)", "Distance traveled (m)"]
_CELL_STYLE = {"border": "1px solid #ddd", "padding": "4px 10px", "fontSize": "13px", "textAlign": "center"}

# Occupant order in OCCUPANTS is [Occupant 1, Occupant 2] -- F(irst)/L(ast) prefixes per leg label.
_PREFIXES = ["F", "L"]


def build_fed_table() -> html.Div:
    return html.Div(
        [
            html.H4("Tenability (FED, convective heat only)"),
            html.Table(
                [
                    html.Thead(html.Tr([html.Th(h, style=_CELL_STYLE) for h in _HEADERS])),
                    html.Tbody(id=_TABLE_BODY_ID),
                ],
                style={"borderCollapse": "collapse"},
            ),
        ],
        style={"marginTop": "20px"},
    )


def register_fed_table_callbacks(app, occupants: list[dict]) -> None:
    @app.callback(
        Output(_TABLE_BODY_ID, "children"),
        Input(grid_store_id("temperature"), "data"),
        [Input(segments_store_id(o["id"]), "data") for o in occupants],
    )
    def _update(temperature_grid_data, *segments_data_list):
        if not temperature_grid_data:
            return [html.Tr(html.Td("Load a temperature CSV to compute FED.", colSpan=len(_HEADERS), style=_CELL_STYLE))]

        grid = XTGrid.from_dict(temperature_grid_data)
        rows = []
        for segs_data, prefix in zip(segments_data_list, _PREFIXES):
            segments = [PathSegment.from_dict(s) for s in (segs_data or [])]
            checkpoints = compute_fed_checkpoints(segments, grid, prefix)
            if not checkpoints:
                rows.append(
                    html.Tr(
                        [html.Td(f"{prefix}–", style=_CELL_STYLE)]
                        + [html.Td("no path yet", style=_CELL_STYLE, colSpan=len(_HEADERS) - 1)]
                    )
                )
                continue
            for cp in checkpoints:
                rows.append(
                    html.Tr(
                        [
                            html.Td(cp.leg_label, style=_CELL_STYLE),
                            html.Td(f"{cp.final_fed:.3f}", style=_CELL_STYLE),
                            html.Td("Yes" if cp.reached_limit else "No", style=_CELL_STYLE),
                            html.Td(f"{cp.position:.1f}" if cp.position is not None else "not reached", style=_CELL_STYLE),
                            html.Td(
                                f"{cp.distance_traveled:.1f}" if cp.distance_traveled is not None else "not reached",
                                style=_CELL_STYLE,
                            ),
                        ]
                    )
                )
        return rows
