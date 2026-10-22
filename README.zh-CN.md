# FreeShip MCP

[English](README.md)

Windows x64 本地 MCP，提供 FreeShip 模型读写、Lackenby 船型变换、求交、静水力计算、
DXF 型线图和 CSV/Excel 导出。计算使用原生 FreeShip 算法，全程不控制桌面。

简单说，它让 AI 能够调用船舶计算工具。把自己的船体模型和设计参数交给 AI，
就能让它读取模型、调整船型、计算静水力，并导出型线图和数据表。
它需要配合支持本地 MCP 的 AI 客户端使用，下载包本身不包含 AI 模型或聊天软件。

## 安装与连接

从 [v0.2.0 下载页](https://github.com/jiangshirong/FreeShip-MCP/releases/tag/v0.2.0)
下载 `FreeShip-MCP-Windows-x64.zip`，适用于 Windows 10/11 x64。
不需要安装 FreeShip、Python 或 Pascal 编译器。解压后，把 MCP 配置中的
`command` 指向其中的 `freeship-mcp.exe`，参数同样是 `--workspace` 和工作目录。
独立包同时包含 Python 运行环境和原生计算引擎。

例如，将程序包解压到 `C:\MCP\freeship-mcp`，新建 `C:\HullWork` 作为模型工作目录。
在 AI 客户端中添加以下 MCP 配置，然后把自己的模型放进工作目录：

```json
{
  "mcpServers": {
    "freeship": {
      "command": "C:\\MCP\\freeship-mcp\\freeship-mcp.exe",
      "args": ["--workspace", "C:\\HullWork", "--timeout", "120"]
    }
  }
}
```

连接后，可以先对 AI 说：

> 检查 FreeShip MCP 是否可用，读取工作目录中的 box.fbm，计算吃水 4 米、无纵倾、无横倾时的静水力，导出 Excel。先不要修改原模型。

试用模型可从仓库的 [examples](examples) 下载。使用自己的模型时，更换文件名、吃水等参数。

如果已经安装 Python 3.11 以上，也可安装下载页中的 Windows wheel：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install .\freeship_mcp-0.2.0-py3-none-win_amd64.whl
.venv\Scripts\freeship-mcp --workspace C:\HullWork --check
```

Python 安装方式的 MCP 配置示例：

```json
{
  "mcpServers": {
    "freeship": {
      "command": "C:\\MCP\\venv\\Scripts\\freeship-mcp.exe",
      "args": ["--workspace", "C:\\HullWork", "--timeout", "120"]
    }
  }
}
```

工作目录内的相对路径和绝对路径均可；解析后的目录联接目标也必须在工作目录内。
所有输出使用新文件名，不覆盖原模型。通信使用标准输入输出，诊断写入标准错误流。

## 使用顺序

1. `engine_info` 检查引擎；`inspect_model` 读取模型；`validate_model` 检查拓扑、相邻法向和破口候选点。
2. `scale_model` 缩放控制网格和项目尺度。旧交线的位置不会随之移动，需要下一步明确重建。

   可选 `project_length_m`、`project_beam_m`、`project_draft_m` 在几何缩放后明确设置设计尺度；
   `x_offset_m` 对缩放后的控制网格沿纵向平移。静水力结果另行返回实际水线范围，不能用设计尺度代替。
   控制点坐标、上部平面高度变换、甲板开口边界及单独的项目基准系数见
   [数值含义补充](docs/numerics.md#volume-mass-and-imperial-models)。
3. `rebuild_hull` 输入目标排水量、浮心坐标及基准、参与变换的图层索引。程序不选择经验值。
4. 查看 Lackenby 剖面积分残差及实际三维静水力残差，再决定是否采用。
5. `generate_sections` 输入横剖线、水线、纵剖线的位置。11 个理论站位可取 `L*i/10`，`i=0..10`。
6. `calculate_hydrostatics` 或 `calculate_hydrostatics_series` 计算指定吃水。
7. `export_linesplan_dxf` 导出三视图；`export_hydrostatics` 导出 CSV 或带 8 张曲线图的 Excel。
8. `save_model` 可转换 `.fbm`/`.ftm`，版本可保留或明确选取 335/462；不支持的降级会失败。

对外单位统一为米、吨、平方米、立方米和度；模型的原单位另行报告。
旧 FBM 的文字编码可选 `cp1252`、`cp1251` 或 `utf8`。数值字段不提前舍入；
Excel 的小数位设置只影响显示。

交线及静水力序列也支持 `[起点, 终点, 间距]`，单位为米；终点恰在网格上时会包含终点，
否则按间距停在终点之前，不额外补点。

浮心可选距艉垂线的米数 `aft_perpendicular_m`，或相对船中、向艏为正的船长比例
`midship_forward_fraction`。例如比例 `0.02` 表示船中前方 `0.02L`。

矩形箱体和合成船型由 `scripts/create_examples.py` 生成，可用于测试和熟悉接口。
阻力、推进、螺旋桨及大倾角稳性不在本版范围内。

## 当前版本

0.2.0 新增统一目标验收和导出来源核对，现有 13 个工具。详见
[目标验收与导出清单](docs/target-verification.md)。导出成果的 `.manifest.json`
应一并保留；服务与引擎需要同时更新到协议 2。

本版为预览版，已进行合成模型数值测试和本机 Windows 集成测试，实际船型的验证仍在继续。
使用变换结果前，要检查实际尺度、系数的计算基准和返回的残差。
目标参数及容差由调用者明确提供，程序不会代为选取。

## 开发资料

- [构建与打包](docs/development.zh-CN.md)
- [单位、系数及数值含义](docs/numerics.zh-CN.md)
- [验证范围](docs/verification.zh-CN.md)

新代码使用 GPL-3.0-or-later，上游原始版权声明及许可证保留。项目是独立适配器，
并非官方 FreeShip 发行版。
