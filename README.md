# FreeShip MCP

[简体中文](README.zh-CN.md)

A Windows MCP server for FreeShip model inspection, control-net editing, hull transformation, geometry diagnostics and engineering exports. Powered by the native FreeShip Plus engine.

## Features

- Read and write FBM/FTM models, including fv335 and fv462.
- Edit control points, edges and faces; scale geometry and apply Lackenby transformations.
- Generate stations, waterlines and buttocks at specified positions.
- Inspect topology, sampled curve quality and coordinate constraints.
- Calculate hydrostatics at individual drafts or across a draft range.
- Export three-view DXF linesplans and CSV/XLSX reports with source manifests.

## Installation

**Platform:** Windows 10/11 x64. **Transport:** stdio.

Download `FreeShip-MCP-Windows-x64.zip` from [Releases](https://github.com/jiangshirong/FreeShip-MCP/releases), then extract it. The standalone package includes the runtime and calculation engine.

Alternatively, install the Windows wheel with Python 3.11 or later:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install .\freeship_mcp-0.3.0-py3-none-win_amd64.whl
```

## Configuration

Create a workspace directory and add the server to your MCP client configuration:

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

For a wheel installation, use `.venv\Scripts\freeship-mcp.exe` as the command.

| Option | Description |
|---|---|
| `--workspace` | Required existing directory containing input models and outputs |
| `--timeout` | Native operation timeout in seconds; default `120` |
| `--engine` | Optional path to a compatible native engine |
| `--check` | Check engine compatibility and exit |

Paths are restricted to the configured workspace. Outputs use new filenames. Logs are written to stderr.

## Tools

| Tool | Description |
|---|---|
| `engine_info` | Engine version, upstream revision and capabilities |
| `inspect_model` | Project settings, geometry bounds, layers, units and control-net indices |
| `validate_model` | Topology, adjacent face orientation and open-boundary diagnostics |
| `edit_control_net` | Move, align or relax points; split edges/faces; add or delete faces; set creases |
| `analyze_hull_quality` | Sampled curve diagnostics and explicit coordinate checks |
| `verify_model_targets` | Compare model measurements with specified targets and tolerances |
| `check_export_source` | Verify export and source-model hashes |
| `save_model` | Save or convert FBM/FTM models |
| `scale_model` | Scale geometry and project dimensions |
| `rebuild_hull` | Apply a Lackenby transformation to selected layers |
| `generate_sections` | Generate stations, waterlines and buttocks |
| `calculate_hydrostatics` | Calculate at a specified draft, trim and heel |
| `calculate_hydrostatics_series` | Calculate for a draft list or range |
| `export_linesplan_dxf` | Export profile, plan and body views with outlines, grids and labels |
| `export_hydrostatics` | Export CSV or XLSX data and charts |

API physical units are metres, metric tonnes and degrees; areas and volumes use m² and m³. Legacy FBM text encoding supports `cp1252`, `cp1251` and `utf8`.

Local edits require the model SHA-256 returned by inspection. Target values and tolerances are explicit inputs. Version 0.3.0 uses native protocol 3; update the server and engine together.

## Documentation

- [Local editing, diagnostics and DXF options](docs/local-editing.md)
- [Units and numerical semantics](docs/numerics.md)
- [Target verification and export manifests](docs/target-verification.md)
- [Build and packaging](docs/development.md)
- [Tests and validation coverage](docs/verification.md)
- [Synthetic test models](examples)

## Development

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
scripts\bootstrap-toolchain.ps1
scripts\build-engine.ps1
.venv\Scripts\python -m pytest -q
scripts\package-windows.ps1
```

The build uses Free Pascal 3.2.2 and Lazarus 3.2. Pinned upstream sources and build instructions are included in the repository; see [UPSTREAM.json](UPSTREAM.json) and [upstream changes](docs/upstream-changes.md).

## License

[GPL-3.0-or-later](LICENSE). Original FreeShip and dependency notices are retained in [NOTICE](NOTICE). This project is an independent FreeShip adapter.
