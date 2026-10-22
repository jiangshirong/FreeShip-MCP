# 开发、打包与故障排查

[English](development.md)

## 从源码构建

需要 Windows x64、Python 3.11、Free Pascal 3.2.2 和 Lazarus 3.2。
上游版本固定在 `UPSTREAM.json`，源码保存在 `vendor/freeship`。

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
scripts\bootstrap-toolchain.ps1
scripts\build-engine.ps1
.venv\Scripts\python scripts\create_examples.py --output-dir examples
.venv\Scripts\python -m pytest -q
scripts\package-windows.ps1
```

工具链下载后会检查 SHA-256，安装在忽略目录 `.toolchain`。已有相应版本时，可以使用
`build-engine.ps1 -LazarusDir C:\Lazarus`。构建不启动 Lazarus IDE 或 FreeShip 窗口。
如果本机 PowerShell 禁止执行脚本，可在调用构建脚本的终端设置 `-ExecutionPolicy Bypass`。

Lazarus 3.2 在部分 Windows 中文路径下会误判目录不存在，构建脚本会在临时目录创建
ASCII 路径的目录联接，实际源码仍在原项目中，不移动原文件。

## 发布产物

| 文件 | 内容 |
|---|---|
| `dist/freeship_mcp-0.1.0-py3-none-win_amd64.whl` | Python MCP 包、原生引擎和许可证 |
| `dist/freeship_mcp-0.1.0.tar.gz` | 对应应用源码、上游源码及构建脚本 |
| `dist/FreeShip-MCP-Windows-x64.zip` | 可直接运行的程序，包含 Python 运行环境及引擎 |
| `dist/FreeShip-MCP-corresponding-source.tar.gz` | 应用源码及构建所用 Lazarus/LCL、FPC 运行库与包源码 |

独立包解压即可配置 MCP。也可以从解压目录运行 `install.ps1`，复制到当前用户的
`LOCALAPPDATA\Programs\FreeShip-MCP`。安装脚本不修改系统 PATH、注册表或客户端设置，
已有目标目录时会拒绝覆盖。普通使用者不需要安装 Python、FreeShip 或 Pascal。

新代码使用 GPL-3.0-or-later。保留上游每个文件的原有版权声明；发布二进制时一并提供
对应源码包和第三方许可证。固定版本及源码来源见 `NOTICE`、`UPSTREAM.json`、
`vendor/freeship/copyright` 与 `src/freeship_mcp/licenses`。

## 修改代码

- `src/freeship_mcp/server.py`：MCP 工具参数、调用顺序和错误返回。
- `src/freeship_mcp/engine.py`：工作目录限制、子进程、进度、取消、超时和输出提交。
- `src/freeship_mcp/exporters.py`：使用引擎结果生成 DXF、CSV、Excel。
- `engine/HeadlessModel.pas`：原生模型、静水力、缩放和求交的无窗口入口。
- `engine/HeadlessLackenby.pas`：从上游提取的变换算法。
- `scripts/extract_lackenby.py`：重新生成上述变换适配单元。
- `vendor-manifest.json`：上游原始文件与修改文件的哈希记录。

更新上游时，应检查生成代码的差异并重跑测试。不要以 Python 简化公式替换原生船型算法，
也不要通过窗口控制实现缺少的功能。每次调用独立加载模型，失败或取消时删除临时输出，
只有保存后通过原生重读检查的模型才能提交到最终文件名。

## 准备公开仓库

运行 `python scripts/audit_public.py --write-manifest` 生成公开清单，检查后使用
`--stage` 只暂存清单中的文件。课程模型、私人结果、构建日志和工具链不进入源码仓库。
脚本不创建远程仓库，也不上传或推送。CI 定义保存在 `.github/workflows/windows.yml`，
但只有在 GitHub 实际运行后才能作为远程构建通过的证据。

## 常见问题

- **找不到引擎或版本不符**：安装配套 Windows wheel，或按固定版本重新构建。
- **输出已存在**：使用新文件名，程序不覆盖已有成果。
- **俄语名称乱码**：检查 FBM 的编码参数，俄语旧文件通常使用 `cp1251`。
- **Lackenby 未收敛**：核对目标、图层和残差；可以明确增加迭代上限，不改变收敛判据。
- **原生写回不满足字节一致性**：不提交输出，保留原文件检查格式与数据；不以复制原文件掩盖写回失败。
- **没有型线**：先生成交线；位于船体之外或尖端的站位可能没有实际曲线。
- **静水力计算出现破口**：结合指定水面、破口候选点和参与计算的图层检查模型。
