# FreeShip MCP

[English](README.md)

面向 Windows 的 FreeShip MCP 服务，提供模型读取、控制网格编辑、船型变换、几何诊断和工程文件导出，使用原生 FreeShip Plus 计算引擎。

## 功能

- 读写 FBM/FTM 模型，支持 fv335、fv462 格式。
- 编辑控制点、边和面，缩放几何，执行 Lackenby 船型变换。
- 按指定位置生成横剖线、水线和纵剖线。
- 检查拓扑、采样曲线质量和坐标约束。
- 按指定吃水或吃水范围计算静水力。
- 导出三视图 DXF 型线图及 CSV/XLSX 报告，并记录成果来源。

## 安装

**平台：** Windows 10/11 x64。**通信方式：** stdio。

从 [Releases](https://github.com/jiangshirong/FreeShip-MCP/releases) 下载并解压 `FreeShip-MCP-Windows-x64.zip`。独立包包含运行环境和计算引擎。

也可使用 Python 3.11 及以上版本安装 Windows wheel：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install .\freeship_mcp-0.3.1-py3-none-win_amd64.whl
```

## 配置

创建工作目录，在 MCP 客户端配置中添加：

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

使用 wheel 安装时，将 command 改为 `.venv\Scripts\freeship-mcp.exe` 的绝对路径。

| 参数 | 说明 |
|---|---|
| `--workspace` | 必填，已存在的模型及输出工作目录 |
| `--timeout` | 原生操作超时秒数，默认 `120` |
| `--engine` | 可选，兼容计算引擎的路径 |
| `--check` | 检查引擎兼容性后退出 |

文件访问限定在工作目录内，输出使用新文件名。日志写入标准错误流。

## 工具

| 工具 | 说明 |
|---|---|
| `engine_info` | 获取引擎版本、上游源码版本和功能 |
| `inspect_model` | 读取项目设置、几何范围、图层、单位和控制网格索引 |
| `validate_model` | 检查拓扑、相邻面法向和开口边界 |
| `edit_control_net` | 移动、对齐、局部平滑控制点，拆边拆面、增删面及设置硬边 |
| `analyze_hull_quality` | 检查采样曲线质量和指定坐标约束 |
| `verify_model_targets` | 按指定目标与容差核对模型测量值 |
| `check_export_source` | 核对导出文件及源模型哈希 |
| `save_model` | 保存或转换 FBM/FTM 模型 |
| `scale_model` | 缩放几何与项目尺度 |
| `rebuild_hull` | 对选定图层执行 Lackenby 变换 |
| `generate_sections` | 生成横剖线、水线和纵剖线 |
| `calculate_hydrostatics` | 按指定吃水、纵倾和横倾计算静水力 |
| `calculate_hydrostatics_series` | 按吃水列表或范围批量计算 |
| `export_linesplan_dxf` | 导出纵剖、水线、横剖视图及轮廓、网格和标注 |
| `export_hydrostatics` | 导出 CSV 或带数据与图表的 XLSX |

接口物理量使用米、吨和度，面积与体积使用平方米和立方米。旧 FBM 文本编码支持 `cp1252`、`cp1251`、`utf8`。

局部编辑须携带模型检查返回的 SHA-256。目标值和容差由调用参数指定。0.3.1 使用原生协议 3，服务与引擎须配套更新。

## 文档

- [局部编辑、线型诊断与 DXF 参数](docs/local-editing.zh-CN.md)
- [单位与数值含义](docs/numerics.zh-CN.md)
- [目标核验与导出清单](docs/target-verification.md)
- [构建与打包](docs/development.zh-CN.md)
- [测试与验证范围](docs/verification.zh-CN.md)
- [合成测试模型](examples)

## 开发

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
scripts\bootstrap-toolchain.ps1
scripts\build-engine.ps1
.venv\Scripts\python -m pytest -q
scripts\package-windows.ps1
```

构建使用 Free Pascal 3.2.2 和 Lazarus 3.2。仓库包含固定版本的上游源码及构建说明，见 [UPSTREAM.json](UPSTREAM.json) 和[上游修改记录](docs/upstream-changes.md)。

## 许可证

[GPL-3.0-or-later](LICENSE)。原 FreeShip 及依赖组件的版权声明保留在 [NOTICE](NOTICE) 中。本项目为独立 FreeShip 适配器。
