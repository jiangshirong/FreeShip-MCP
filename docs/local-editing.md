# Local editing, diagnostics and linesplans (0.3.0)

[简体中文](local-editing.zh-CN.md)

The server and native engine use protocol 3 together. These tools have no vessel-type,
station-count, dimension, LCB or acceptance-limit defaults taken from a particular design.
Coordinates are in the model frame, in metres; they are not the rotated hydrostatics frame.

## Inspect, edit, then recalculate

1. Call `inspect_model` with `include_control_net: true`. Read `control_net_points`,
   `control_net_edges`, `control_net_faces` and `provenance.model.sha256`.
2. Choose explicit indices and one edit. Pass that SHA-256 as `expected_model_sha256`.
   The server rejects a stale snapshot instead of applying old indices to a newer model.
3. Choose a new FBM/FTM output path. The input is never overwritten. The native engine
   rebuilds and checks topology, writes the model, reloads it and compares the complete
   point/edge/face tables. Failure publishes no output.
4. Inspect the saved output before another edit. Topology changes can renumber indices.
   `changed_points` refers to the input indices of coordinate edits; output tables give
   the saved model's indices. The new hash is in `provenance.output_model.sha256`.
5. Recalculate hydrostatics at explicit draft/trim/heel and compare against your own
   targets with `verify_model_targets`. Local editing does not imply hydrostatic approval.
   Stored project dimensions and section positions are not automatically rescaled.

For example, align selected points to a supplied half-breadth. Replace the SHA and
indices with those from inspection; the numbers below are illustrative, not design rules:

```json
{
  "model_path": "hull.fbm",
  "output_path": "aligned.fbm",
  "expected_model_sha256": "<SHA-256 from inspect_model>",
  "edit": {"action": "align_points", "point_indices": [1, 2], "axis": "y", "value_m": 2.5}
}
```

### Edit actions

| `action` | Required fields | Behaviour |
|---|---|---|
| `move_points` | `points: [{index, x_m?, y_m?, z_m?}]` | Replace only supplied coordinates |
| `translate_points` | `point_indices`, optional `dx_m/dy_m/dz_m` | Same explicit offset for selected points |
| `align_points` | `point_indices`, `axis`, `value_m` | Set one coordinate |
| `relax_points` | `point_indices`, `relaxation` | Synchronous neighbour averaging; `iterations` defaults to 1 |
| `split_edge` | `edge_index`, optional `fraction` | Native insertion, default fraction 0.5 |
| `set_edge_crease` | `edge_index`, `crease` | Explicit native crease flag |
| `split_face` | `face_index`, two `point_indices` | Native split between nonadjacent vertices |
| `add_face` | Ordered `point_indices`, `layer_index` | Use existing vertices; ordering determines orientation |
| `delete_face` | `face_index` | Native face deletion; can deliberately create an opening |

Locked points are refused unless `allow_locked: true`; their lock flags are restored.
Desktop anchor/linear-constrained points are reported and refused: raw editing does not
silently bypass those constraints. Unselected coordinate changes also cause rejection.
Nonmanifold edges, inconsistent adjacent normals and degenerate faces prevent publication.
Open boundaries above water can be legitimate; waterplane leakage is checked by hydrostatics.

Relaxation is **not** a design-aware fairing optimizer. It can shrink or alter a hull.
Boundary and crease points are protected by default; moving them requires explicit
`preserve_boundary: false` / `preserve_creases: false`. The averaging factor and selected
indices are always caller supplied. There is no automatic Lackenby transform after an edit.

## `analyze_hull_quality`

This is read-only. Optional `stations_m`, `waterlines_m`, `buttocks_m` regenerate the
specified section families only in memory; omitted families retain their saved positions.
`sample_count` defaults to 201 (21–1001), plus original native spline knuckles.

The result includes topology diagnostics, per-curve endpoints, sampled turning angles,
discrete curvature, adjacent curvature changes, their maxima/coordinates and projected
curvature-sign changes. Optional `alignment_rules` test selected point coordinates:

```json
{
  "model_path": "aligned.fbm",
  "stations_m": [5, 10, 15],
  "waterlines_m": [1, 2, 3],
  "max_turn_degrees": 20,
  "alignment_rules": [{"point_indices": [1, 2], "axis": "y", "value_m": 2.5, "tolerance_m": 0.001}]
}
```

The optional curve limits are `max_turn_degrees`, `max_curvature_per_m` and
`max_curvature_step_per_m`. No acceptance limits are inferred. `measured` means no
limits were supplied. `issues_found` means topology, explicit constraints or sampled
limits need review. `no_requested_issues_found` covers only the checks requested;
missing curves with requested curve limits yield `incomplete`. No curves is also marked
`curve_checks: not_checked`. A native knuckle may be intentional. Each curve returns at
most 20 finding details and the full finding count.

For consecutive points A,B,C: turn = atan2(|AB×BC|, AB·BC), curvature =
2|AB×BC|/(|AB||BC||AC|). Curvature-step is the absolute difference between adjacent
sample estimates, not a derivative per unit arc length. These quantities depend on
sampling; compare like sampling with like. Numerical duplicate-point filtering is not
a design tolerance. This does not prove surface fairness or absence of self-intersections.

## `export_linesplan_dxf`

Default export contains profile, plan and split body views; native intersection splines;
actual subdivided surface boundaries, crease edges and view silhouettes; grids, baseline,
centreline, coordinate labels and station indices. Linesplan-disabled layers are excluded
from outlines. The three views use translations only, plus the conventional aft/fore
reflection in the body view. All drawing coordinates and text heights use metres.

```json
{
  "model_path": "aligned.fbm", "output_path": "lines.dxf",
  "options": {
    "stations_m": [0, 5, 10, 15, 20],
    "waterlines_m": [0, 1, 2, 3, 4], "buttocks_m": [1, 2],
    "body_split_x_m": 10, "title": "Example hull"
  }
}
```

Positions in `options` generate temporary native sections as well as the corresponding
grid. An empty list removes that family from this export; omitted families use saved
positions. The model file remains unchanged. The split defaults to the stored project
split location; it is not inferred from an LCB target.

`include_boundaries`, `include_creases`, `include_silhouettes`, `include_grid` and
`include_labels` default to true. `gap_m` and `text_height_m` optionally control layout.
Body labels group coincident endpoints and use leaders. Curves are independent open
polylines; edge outlines are independent real mesh segments. Nothing joins unrelated
endpoints or invents closure. Silhouettes are mesh approximations, with no hidden-line
removal. A closed surface still has silhouettes when it has no open boundaries.

Check the returned per-view curve/outline/grid counts and `empty_sections`. A station
at a point stem can legitimately be empty; the exporter does not invent a section.
Zero intersections is not presented as a complete section set, even when real outlines
can be exported. The file is independently reopened/audited with ezdxf, and its manifest
records the model hash, native request and all export options. Keep the manifest beside
it and call `check_export_source` after subsequent model changes.

Missing requested section positions are returned in `empty_sections`. When other curves
exist, `curve_checks` is `partial`; requested curve limits cannot yield a completed
result while section coverage is missing. Empty point-stem sections may be legitimate.
