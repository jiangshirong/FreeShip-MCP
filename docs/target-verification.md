# Target verification / 目标验收

Version 0.2.0 adds `verify_model_targets` and `check_export_source` (13 MCP tools).
The native protocol is now 2. Install the matching server and engine together.
No empirical targets or tolerances are selected by the server.

## Explicit checks

Example for the public synthetic box (`examples/box.fbm`):

```json
{
  "model_path": "box.fbm",
  "draft_m": 4,
  "targets": [
    {"metric": "project_length_m", "expected": 20, "absolute_tolerance": 0.001},
    {"metric": "displacement_t", "expected": 492, "absolute_tolerance": 0.01},
    {"metric": "section_top_above_keel_m", "section_x_m": 10, "expected": 8, "absolute_tolerance": 0.001},
    {"metric": "waterplane_coefficient_project", "expected": 1, "absolute_tolerance": 0.0001}
  ]
}
```

Each check returns expected/measured values, signed residual, absolute tolerance,
unit, measurement basis and `passed`, `failed` or `not_checked`.
Overall status is `failed` when any requested target fails, `incomplete` when a
requested measurement is unavailable, otherwise `passed`. It covers only requested
targets. Passing settings does not verify the geometry. Invalid/duplicate targets
are rejected. An input changed during calculation is rejected rather than mixed.

Supported metrics:

| Metrics | Basis |
|---|---|
| `project_length_m`, `project_beam_m`, `project_draft_m` | Stored settings, explicitly marked as not geometry verification |
| `draft_m` | Requested calculation condition |
| `waterline_length_m`, `waterline_beam_m` | Actual immersed waterline |
| `displacement_t` | Native volume/density/appendage calculation |
| `lcb_ap_m`, `lcb_midship_fraction` | Aft perpendicular; or fraction of project length forward of midship |
| `block_coefficient_project_geometry` | Raw volume / project length / project beam / requested draft |
| `waterplane_coefficient_project` | Waterplane area / project length / project beam |
| `block_coefficient_native`, `waterplane_coefficient_native` | Native configurable reference, preserved |
| `section_top_above_keel_m` | Highest point of a freshly calculated section on hydrostatics-enabled surfaces; explicit `section_x_m` required |
| `minimum_freeboard_m` | Lowest open boundary above upright waterplane; not checked at nonzero heel/trim |

The section measurement does not identify a main deck automatically. The caller
must choose an appropriate section/layers and interpret structures above the deck.
An empty section is `not_checked`; dry/nonpositive-draft hydrostatic targets are
`not_checked`. Hydrostatic failures do not prevent independent section/settings checks.
The model and its saved intersections are not modified.

`coefficient_basis` reports formulas, actual denominator lengths/beams, volume basis
and reference setting. Native block coefficient uses appendage-corrected volume;
the separate project-geometry coefficient uses raw volume. With `fcActualData`,
native coefficients use submerged extents, which need not equal waterline length.
For other native reference settings, the native waterplane coefficient follows the
upstream waterline dimensions while native block coefficient uses project dimensions.

## Export provenance

Every model calculation records the input model SHA-256, size, engine SHA-256,
upstream revision, protocol and request. Modified model results also record the new
model hash. Every DXF, CSV and XLSX export creates a sibling
`<output filename>.manifest.json` with those records and the artifact hash.
XLSX additionally contains a `Provenance` sheet with per-draft coefficient bases.

Call `check_export_source` with `model_path` and `export_path`:

- `current`: model and artifact hashes match the manifest.
- `stale_or_modified`: model or artifact differs.
- `unverified`: manifest absent; regenerate to establish provenance.

Keep each sidecar beside its export. An old artifact without a manifest is not
automatically upgraded. Hash consistency is not a digital signature or proof of a
correct hull. Export and sidecar use fresh filenames; failed publication removes
the newly written artifact rather than returning a partial success.

## 中文说明

验收时逐项提供目标值和绝对容差，单位沿用接口的米、吨和无量纲比例。
填写值、计算条件、实际水线和横剖面几何分别报告。型深不能通过项目参数证明；
用明确位置的横剖面最高点检查时，应由调用者确认该位置的上边界对应主甲板。
没有交线或没有有效浸水时返回“未检查”，不能当作通过。

原生系数和按项目尺度复核的系数独立返回，并附计算分母、容积基准和公式。
原生算法没有为迎合目标值而改变。

导出时同时保存模型及成果哈希、引擎版本和计算条件。换了模型后可用
`check_export_source` 检查旧图表是否仍对应当前模型。缺失清单返回“未验证”。
清单只证明文件一致性，不证明设计正确，也不防止恶意同时篡改清单。
