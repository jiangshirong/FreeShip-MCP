# Units and numerical semantics / 单位与数值含义

## Coordinates

`scale_model` optionally accepts `project_length_m`, `project_beam_m` and
`project_draft_m` to set design metadata explicitly after scaling the mesh. When
omitted, stored dimensions scale with the geometry. Setting metadata does not
make actual waterline dimensions equal to the design values.
The optional `x_offset_m` translates mesh points and, when enabled, markers after
scaling. It does not move the aft-perpendicular coordinate reference or existing sections.

The native model axes are x longitudinal (forward), y transverse and z upward.
The adapter assumes the aft perpendicular is x=0, consistent with FreeShip project
settings. Geometry may extend beyond either perpendicular. It does not move the
origin to the minimum mesh x-coordinate.

The aft-perpendicular LCB coordinate is `lcb_ap_m`. The fraction-based conversion is
`lcb_ap_m = (0.5 + midship_forward_fraction) * project_length_m`.
The fraction is a dimensionless longitudinal offset divided by project length, not a percentage.

Draft is measured above the model's lowest hydrostatic point. Native positive trim
means bow-down: waterplane height is `lowest + draft - trim/2` at x=0 and
`lowest + draft + trim/2` at x=project length. Heel is in degrees.

Hydrostatic centres retain the native frame: keel z is removed, then the specified
trim/heel rotation is applied. `vcb_m` is height above that keel datum, not an absolute
model z-coordinate. `keel_model_z_m` and `centres_reference` identify the reference.
For upright/zero-trim calculations, x is the original model x referenced to the aft perpendicular.

项目尺度、控制网格范围、浸水几何范围、水线尺度分别报告。控制网格最大 x 值或水线长度
都不能直接替代项目填写的垂线间长。

## Volume, mass and imperial models

`inspect_model(include_control_net=True)` returns indexed control-point coordinates
in metres. `scale_model(point_updates=[...])` accepts explicit, unique point indices
and optional `x_m`, `y_m`, `z_m` coordinates after XYZ scaling. The paired parameters
`z_cut_m` and `z_above_factor` map points above that plane to
`z_cut_m + (z - z_cut_m) * z_above_factor`; points below it remain unchanged.
These are geometric edits, not project-depth metadata. Recompute hydrostatics and
regenerate sections after editing. Project name, designer and comment can be set
explicitly; an empty string clears the corresponding field.

`block_coefficient` and `waterplane_coefficient` retain the native FreeShip reference
setting. Separate `block_coefficient_project_geometry` and
`waterplane_coefficient_project` report raw volume divided by stored project
length × beam × requested draft, and waterplane area divided by project length × beam.
The latter fields do not change the native coefficients. Both references can differ.
`minimum_open_boundary_z_m` and `minimum_freeboard_m` report the lowest open deck
edge and its clearance from the requested waterplane; the mesh maximum is not depth.

`include_control_net=True` 可读取带索引的控制点；`point_updates` 按明确索引修改坐标。
`z_cut_m` 与 `z_above_factor` 成对使用，改变指定平面以上的几何高度。修改后须重新
计算静水力并生成交线。项目名称、作者、注释可明确设置，空字符串表示清除。
原生丰满系数沿用模型的基准设置；带 `_project` 的新增指标单独按项目尺度复核，
不覆盖原生结果。最低开口边界、相应干舷与网格最高点分别报告。

The native hydrostatic routine first integrates raw geometric volume. It calculates
displacement using density and the appendage coefficient, then stores the **corrected**
volume in `TFreeHydrostaticsData.Volume`. The API returns both `volume_geometry_m3` and
`volume_corrected_m3`; the appendage coefficient is applied once.

公制模型采用米和吨。英制模型坐标由英尺换算成米，密度由 lb/ft³ 换算为 t/m³；
原生长吨结果按 `1 long ton = 1.0160469088 t` 换算。原模型单位与原始密度另行保留。
上游的“公制切换英制”设置函数使用非标准 `Lbs=0.44642857` 常数，本适配器不调用该函数
转换用户模型，也不静默改写密度。请核对 `density_t_m3` 是否符合模型的物理含义。

## Lackenby

The adapter copies the upstream two-half-body Simpson integration and longitudinal
point transformation. Each half uses 40 intervals. It preserves the upstream
convergence tests: relative SAC volume error <= 1e-4 and LCB/length error <= 5e-5,
with the upstream alternative absolute LCB tolerance of 0.002 **model length units**.
Default maximum iterations: 15. A nonconverged iteration creates no final output.

`sac_lcb_length_relative_residual` is the actual relative residual. The separate
`sac_lcb_convergence_metric` preserves the upstream value used by its stopping rule
(which sets this metric to 4.9e-5 once the absolute tolerance is met).

Lackenby 的剖面积分与三维曲面静水力积分是两条上游数值路径。接口另外计算
`actual_displacement_residual_t`、`actual_lcb_residual_m`，并返回
`hydrostatic_targets_within_native_tolerance`。SAC 收敛不保证这个复核标志为真。
应依据自己的目标精度检查这两项结果；程序不暗中追加缩放或放宽收敛阈值。

The optional `block_coefficient` is a compatibility constraint, defined here as
raw target volume divided by **stored project L×B×T**. It must agree with the target
displacement, density and appendage coefficient within 1e-4. It is not silently
substituted for FreeShip's configurable `fcActualData` coefficient reference.

## Precision, sections and output

The upstream scalar type is IEEE-754 single. Model precision/subdivision settings
are preserved. API JSON uses numeric values without report rounding; XLSX stores
numbers with spreadsheet serialization precision and uses number formats for display.

交线采用原生曲面求交，型线图使用上游 DXF 导出方式中的 100 个采样点及折角参数。
横剖线位置 x、水线位置 z、纵剖线位置 y 均由调用者提供。明确请求的空端点站位仍保留，
但不伪造交线。`stations` 与 DXF 中非空站位数量因此可能不同。

Validation reports native leak candidates, nonmanifold edges and inconsistent
adjacent normals. It does not repair the model automatically or prove the absence
of global self-intersections. Open deck edges above the requested waterplane can be valid.

## JSON transport and file paths

Native requests and responses use UTF-8 JSON. Literal Unicode characters and
JSON `\uXXXX` escape sequences represent the same path. Model paths support
Unicode directory and file names; they are independent of the legacy FBM text
encoding setting. Version 0.3.1 fixes truncation of consecutive Unicode escapes
in the pinned FPC scanner; update the bundled native engine with the server.
