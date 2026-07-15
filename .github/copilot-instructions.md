# cammatEvac — repo instructions for AI coding assistants

## What this is

A Python/Dash web app for a tunnel fire & evacuation safety engineer. It loads
CAMATT simulation exports (X-T CSVs: distance x time grid of opacity /
temperature / CO), renders them as heatmaps with an editable discrete color
legend, and overlays occupant evacuation paths (manual waypoints or computed
from a speed-vs-opacity model) identically across all three parameter panels.

Reference image the visual style is modeled on:
`Vasilikou_LB_Q1_100MW180m_T_left_Trajectories.jpg` (project root).

## Run it

```
D:\Apps\cammatEvac\venv\Scripts\python.exe app.py
```
Open `http://localhost:8050`. No hot-reload (`debug=False` in `app.py`) —
restart the process after code changes. (`debug=True` was tried first and
caused a flaky first-load React error in this environment; not yet root-caused,
may be fine in a normal browser — worth re-testing if useful.)

## Architecture (see the file for details, this is just the map)

- `data/xt_parser.py` — parses the CAMATT CSV layout (row 6 = parameter name,
  row 7 = header with `Length(m)` + `t = Ns` columns, rows 8+ = data). Has both
  a file-path (`parse_xt_csv`) and text/upload (`parse_xt_csv_text`) entry
  point, plus `XTGrid.to_dict/from_dict` for JSON round-tripping through Dash
  `dcc.Store`.
- `viz/colorscale.py` — `ColorScale`: N ascending thresholds + N+1 colors,
  rendered as a **stepped/banded** Plotly colorscale (not interpolated), to
  match CAMATT's discrete legend look. Presets saved per parameter under
  `presets/<slug>_legend.json`.
- `viz/heatmap.py` — builds the Plotly figure. **Axis convention: distance (m)
  on X, time (s) on Y** — matches the reference image, NOT the raw CSV's own
  row/column orientation (CSV rows are distance stations, so `values.T` is
  needed when passed as `z`). Also draws the yellow dashed evac-start-time
  line (horizontal, constant t) and magenta dashed exit-distance line(s)
  (vertical, constant x).
- `trajectory/segment.py` — `PathSegment(points: list[(t, x)], style: "solid"|"dashed")`,
  the shared format both manual and computed trajectories produce.
- `trajectory/speed_model.py` — `SpeedTable`: piecewise-linear opacity->speed
  (m/s) breakpoints. **Defaults are placeholders** — real CAMATT opacity units
  are unconfirmed (sample data ranges ~1e-24 to a few tenths); calibrate
  before relying on computed-mode output for real analysis.
- `trajectory/integrator.py` — `compute_path(grid, start_x, start_t, exits, speed_table, dt)`:
  forward-Euler integration, bilinear-interpolating opacity via
  `RegularGridInterpolator`. `exits` is a list consumed **in the order given**
  (UI asks the user for "nearest first" — not re-sorted here). Leg 1 (start ->
  exits[0]) is solid; each subsequent leg (treating the prior exit as
  unavailable, continuing to the next) is dashed. Stops early if the occupant
  runs out of simulated time or speed hits 0 (stuck).
- `components/legend_editor.py`, `components/speed_editor.py` — near-identical
  Dash patterns: a `dcc.Store` holding the list as the source of truth, one
  callback rendering rows from the store, one callback merging
  add/remove/reset/edit events back into the store (via `ALL` pattern-matching
  inputs), one callback saving to a JSON preset.
- `components/occupant_panel.py` — per-occupant UI (mode toggle manual/computed,
  evac start time, exit list, waypoints or speed table). The Apply callback
  reads the **opacity** grid store regardless of which parameter tab is
  active — computed mode is always driven by opacity.
- `components/file_panel.py` — `dcc.Upload` x3 (opacity/temperature/CO), each
  parses into a `dcc.Store` (`grid_store_id(slot)`, slots = `opacity`,
  `temperature`, `co`). Opacity is pre-loaded at startup from
  `Test03_Fire mode_XT.csv`; temperature/CO start empty until uploaded.
- `app.py` — wires it all together: `dcc.Tabs` (one per parameter slot), each
  tab's figure rebuilt from that slot's grid store + its own legend store +
  **both** occupants' segment/ref stores (loop-generated callbacks, careful
  with the `slot=slot` / `o=o` default-arg closure trick). Also has a
  per-tab "Export PNG" button (`kaleido`, saves to `exports/`).

## Dash-version quirks hit in this environment (dash 4.4.0)

- **`dash.html.Input` does not exist** in this version (avoids clashing with
  `dash.Input` the callback dependency). Native `<input type="color">` isn't
  available through `html`; the color editors use `dcc.Input(type="text")`
  (hex string) plus a plain `html.Div` colored swatch instead.
- Pattern-matching component ids (dict ids like
  `{"type": "legend-color", "param": ..., "index": ...}`) are used throughout
  for per-row/per-occupant/per-slot components — this is intentional Dash
  idiom, not incidental complexity. When testing in a browser automation tool,
  some accessibility-tree readers choke on these ids (invalid CSS selector
  from the JSON-ish id string) — query via plain `document.querySelectorAll`
  + `JSON.parse(el.id)` instead if that happens.

## Status / what's left

All 6 planned build stages are done and were verified end-to-end in-browser:
CSV parsing, editable legend with presets, manual trajectory + reference
lines, computed trajectory (speed-vs-opacity integrator), multi-exit chaining
+ 2-occupant support, and the 3-panel tabbed view with shared overlay + PNG
export.

Not built (deferred, explicitly out of scope for now): packaging into a
standalone desktop `.exe`. The plan is `pywebview` + `PyInstaller` wrapping
the same Dash server (chromeless native window pointed at `localhost`) — no
rewrite needed, just an added launcher script + build step, whenever that's
wanted.

Known placeholders that need real-world calibration, not code changes: the
opacity legend thresholds (`viz/colorscale.py: default_scale_for`) and the
speed-vs-opacity table (`trajectory/speed_model.py: DEFAULT_BREAKPOINTS/DEFAULT_SPEEDS`).
