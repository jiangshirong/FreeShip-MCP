# 局部编辑、线型检查和型线图导出（0.3.0）

[English](local-editing.md)

服务和原生引擎须一起更新到协议 3。工具不预设某种船型的尺度、站数、浮心或验收标准。
局部编辑使用模型坐标，单位为米；它与有纵倾、横倾时的静水力坐标系有所区别。

## 操作顺序

1. 用 `inspect_model`，设置 `include_control_net: true`，读取点、边、面索引及
   `provenance.model.sha256`。
2. 明确选择索引和一种操作，把这个哈希传入 `expected_model_sha256`。
   模型已改变时，旧索引会被拒绝。
3. 指定新的 FBM/FTM 文件名。原生引擎编辑后重建、检查拓扑、保存、重新加载，
   比较完整点边面数据；失败不生成成功文件，也不覆盖输入。
4. 再次编辑前读取新文件。增删点边面可能重新编号。坐标修改的 `changed_points`
   对应输入索引；输出控制网格表对应保存后的索引。
   新文件哈希位于 `provenance.output_model.sha256`。
5. 明确吃水、纵倾、横倾，重算静水力，并用自己的目标和容差调用 `verify_model_targets`。
   局部编辑不会自动修改项目尺度、移动站位，也不会自动做全船 Lackenby 变换。

例如，把选定点对齐到调用者指定的半宽；哈希和索引必须换成检查结果：

```json
{
  "model_path": "hull.fbm",
  "output_path": "aligned.fbm",
  "expected_model_sha256": "<inspect_model 返回的 SHA-256>",
  "edit": {"action": "align_points", "point_indices": [1, 2], "axis": "y", "value_m": 2.5}
}
```

上面的坐标只是接口示例，不是设计采用值。

## 局部编辑操作

| action | 参数 | 作用 |
|---|---|---|
| `move_points` | `points: [{index, x_m?, y_m?, z_m?}]` | 修改指定坐标分量 |
| `translate_points` | `point_indices`，可选 `dx_m/dy_m/dz_m` | 平移选定点 |
| `align_points` | `point_indices`、`axis`、`value_m` | 将一个坐标对齐 |
| `relax_points` | `point_indices`、`relaxation` | 对选定点按相邻点同步平均；迭代次数默认 1 |
| `split_edge` | `edge_index`，可选 `fraction` | 用原生方法插点；位置比例默认 0.5 |
| `set_edge_crease` | `edge_index`、`crease` | 设置硬边标志 |
| `split_face` | `face_index`、两个 `point_indices` | 连接面上两个不相邻顶点以拆面 |
| `add_face` | 有顺序的 `point_indices`、`layer_index` | 用已有顶点补面；顺序决定法向 |
| `delete_face` | `face_index` | 删除指定面，可用于明确要求的开口 |

锁定点默认拒绝；明确设置 `allow_locked: true` 才能操作，完成后保留锁定状态。
带桌面锚定或直线约束的点会被标出并拒绝，避免绕过原有约束。
发生未选中点的坐标移动、非流形边、相邻面法向不一致或退化面时，不发布输出。
水面以上的开口可能合理；是否在给定水线漏水，仍需静水力计算确认。

`relax_points` 是邻点平均，不是自动设计优化。它可能使船体收缩或改变排水量。
边界点及硬边端点默认保护；必须明确关闭 `preserve_boundary`、`preserve_creases`
才会移动相应点。参与点、平均权重、迭代次数均由调用者选择。

## `analyze_hull_quality` 线型检查

只读，不修改船型。可指定横剖线、水线、纵剖线位置，临时重建对应类别；
未指定的类别保留原文件站位。每条原生曲线默认取 201 个参数采样点，支持 21～1001，
并保留原生折角采样点。

返回每条曲线的端点、长度估计、转角、离散曲率、相邻曲率差、最大值及坐标、投影曲率变号次数；
同时检查拓扑。`alignment_rules` 可检查一组选定点是否满足明确坐标与容差。

```json
{
  "model_path": "aligned.fbm",
  "stations_m": [5, 10, 15], "waterlines_m": [1, 2, 3],
  "max_turn_degrees": 20,
  "alignment_rules": [{"point_indices": [1, 2], "axis": "y", "value_m": 2.5, "tolerance_m": 0.001}]
}
```

可选阈值为 `max_turn_degrees`、`max_curvature_per_m`、`max_curvature_step_per_m`。
不指定验收阈值时返回 `measured`，不是“船型合格”。`issues_found` 表示有待检查的位置；
`no_requested_issues_found` 只表示指定检查未发现问题。
要求检查曲线却没有曲线时为 `incomplete`，并标记 `curve_checks: not_checked`。
原生折角可能是刻意设计，需结合具体用途判断。
每条曲线最多返回 20 个详细提示，同时保留全部提示数量。

对三个连续点 A、B、C：转角由 AB、BC 的夹角求得，曲率估计为
2|AB×BC|/(|AB||BC||AC|)。相邻曲率差是两个采样估计值之差的绝对值，不是对弧长的导数。
采样密度会影响结果，比较时应保持一致。数值重复点过滤不是设计容差。
该检查不能证明曲面完全光顺或没有自相交，也不会自动修船。

## `export_linesplan_dxf` 完整型线图

默认输出纵剖、水线、横剖三视图，包含原生交线、真实曲面边界、硬边、视向轮廓、
横竖网格、基线、中心线、坐标和站号。轮廓只使用开启型线图显示的图层。
视图用平移排布，横剖图按指定分界位置左右分置；坐标、视图间距和文字高度均以米计。

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

options 中的位置同时用于临时生成交线和网格，不改动原模型；空数组移除该类别，
省略则使用原文件位置。横剖分界位置默认读取项目设置，不根据浮心目标猜测。

`include_boundaries`、`include_creases`、`include_silhouettes`、`include_grid`、
`include_labels` 默认开启；`gap_m`、`text_height_m` 可调整排布。
横剖图重合端点合并标注，邻近标注通过引线错开。

交线保持为独立折线，边界与轮廓来自实际细分网格边；不会跨越空缺强行闭合。
视向轮廓为网格近似，没有隐藏线消除。闭合曲面即使没有开口边，仍可导出视向轮廓。

结果分别报告曲线、边界、硬边、轮廓、网格数量，以及 `empty_sections`。
位于尖艏等处的理论站位可能没有有效交线；工具不会伪造这一站。
只导出轮廓时也会如实报告交线数量为零，不能把它当成完整站位的验收。
DXF 会由 ezdxf 重新读取审计；旁边的 manifest 记录模型哈希、原生请求和全部导出设置。
保留该清单，模型修改后用 `check_export_source` 检查成果是否过期。

指定站位缺少交线时，会列入 `empty_sections`。其他交线存在也只标为 `curve_checks: partial`；
在要求检查曲线阈值的情况下，整体不会报告检查完整通过。尖艏等处的空站位仍可能合理。
