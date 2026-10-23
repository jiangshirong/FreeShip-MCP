# Development and packaging / 开发与打包

## Build

Windows x64, Python 3.11, Lazarus 3.2 and FPC 3.2.2. Source and toolchain are separated.
`bootstrap-toolchain.ps1` downloads the pinned official installer, verifies its SHA-256
and installs into ignored `.toolchain`. It does not open the IDE or FreeShip.

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

PowerShell execution policy may require invoking your shell with `-ExecutionPolicy Bypass`
for these local build scripts. The compiler uses `nogui`; no GUI form is constructed by
the calculation path. The build script uses ASCII temporary directory junctions because
Lazarus 3.2's command-line path checks can fail on Chinese project paths. It never moves
or deletes the original project.

已有 Lazarus 时，可用 `build-engine.ps1 -LazarusDir C:\Lazarus`。编译器及 Lazarus 必须是
规定版本。依赖锁文件是 Windows x64 / Python 3.11 的已测版本快照；更新后应重跑完整测试。
普通使用者安装预编译 wheel 或独立程序，无需上述工具链。

## Outputs

- `dist/freeship_mcp-0.3.0-py3-none-win_amd64.whl`: Python MCP package with engine and notices.
- `dist/freeship_mcp-0.3.0.tar.gz`: matching application source, vendored FreeShip and build scripts.
- `dist/FreeShip-MCP-Windows-x64.zip`: standalone program, bundled Python runtime and native engine.
- `dist/standalone/freeship-mcp/freeship-mcp.exe`: unpacked standalone entry point.
- `dist/FreeShip-MCP-corresponding-source.tar.gz`: matching application archive plus the
  Lazarus/LCL and FPC RTL/package sources used by the binary build.

独立包解压后可直接配置 MCP，不需要 Python。也可从解压目录运行 `install.ps1`，
安装到当前用户目录；安装器只复制文件，不修改系统 PATH、注册表或 MCP 客户端配置。
它拒绝覆盖已有安装目录。

Application source is GPL-3.0-or-later. Preserve upstream per-file notices. Compiler/LCL
and dependency licenses are included in the binary package. The exact Lazarus installer
(which includes sources) is pinned by URL/hash in `scripts/bootstrap-toolchain.ps1`.
See `NOTICE`, `vendor/freeship/copyright` and `src/freeship_mcp/licenses`.

## Source maintenance

`UPSTREAM.json` identifies the base commit. `vendor-manifest.json` records original and
modified source hashes. `docs/upstream-changes.md` explains modifications.
`scripts/extract_lackenby.py` regenerates `engine/HeadlessLackenby.pas` from the pinned
vendored form source. Review its diff and rerun numerical regression tests after an update.

New tools belong in `server.py`; model mathematics belongs in the Pascal adapter.
`engine.py` confines paths, runs one subprocess per call and publishes outputs only after
successful native reload. Timeout, cancellation and failed iterations remove temporary outputs.

The public source allowlist is checked by `scripts/audit_public.py`. Local model data,
private reports, build logs, toolchains and release packages are excluded from the source
repository. Inspect the staged allowlist before publishing.

## Troubleshooting / 故障排查

- **Missing/incompatible engine**: install a matching Windows wheel or rebuild the engine.
- **Output exists**: choose a new output name. Existing files are protected.
- **Wrong model names**: pass the correct legacy encoding, usually cp1251 for Cyrillic FBM.
- **Lackenby fails**: check displacement/LCB feasibility, layer selection and residuals. An explicit
  larger iteration limit may help; it does not change the stopping rule.
- **Native save is not byte-identical**: no output is published. Preserve the source and inspect
  the model/version; do not bypass the check by copying bytes over a failed serialization.
- **No curves**: generate sections first; positions outside the hull can legitimately be empty.
- **Hydrostatic leak**: inspect open-boundary points and hydrostatic layers at that waterplane.
