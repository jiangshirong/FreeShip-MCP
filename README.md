# FreeShip MCP

[简体中文](README.zh-CN.md)

Local Windows x64 MCP server for FreeShip model I/O, native Lackenby transformation,
intersections, hydrostatics, DXF linesplans and CSV/XLSX reports. No desktop automation.

The calculation engine is built from FreeShip Plus commit
`1de17e99fb2b1cc559cdf27c5cafb595a627a641`. It uses the original subdivision surface,
intersection, hydrostatic and Lackenby mathematics with a nonvisual entry point.

## Installation

**Preview release:** [v0.1.0 downloads](https://github.com/jiangshirong/FreeShip-MCP/releases/tag/v0.1.0).
The standalone `FreeShip-MCP-Windows-x64.zip` needs no Python installation. Extract it,
point your MCP `command` at `freeship-mcp.exe` and pass `--workspace C:\HullWork`.
It includes the Python runtime and native engine.

Alternatively, on Windows 10/11 x64 with Python 3.11+, install the **Windows wheel containing
the engine** from a release or a local build:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install .\freeship_mcp-0.1.0-py3-none-win_amd64.whl
.venv\Scripts\freeship-mcp --workspace C:\HullWork --check
```

The workspace must exist. FreeShip desktop and Pascal are not runtime requirements.
For a standalone Windows package, see [development and packaging](docs/development.md).

Use an AI client that supports local MCP servers over stdio. This download provides
the calculation tools; it does not include an AI model or a chat application.

## MCP configuration

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

The server uses stdio. Diagnostics go to stderr. Paths may be relative to the configured
workspace or absolute inside it. Existing files are never overwritten. Input models and
all output files must remain inside that workspace, including resolved junction targets.

## Tools

| Tool | Purpose |
|---|---|
| `engine_info` | Check engine version and capabilities |
| `inspect_model` | Stored dimensions, actual geometry bounds, layers, units and sections |
| `validate_model` | Topology, adjacent face normals and native leak candidates |
| `save_model` | New FBM/FTM; preserve version or explicitly select 335/462 |
| `scale_model` | Native XYZ mesh and project scaling |
| `rebuild_hull` | Lackenby with explicit displacement, LCB and selected layer indices |
| `generate_sections` | Native stations, waterlines and buttocks at explicit positions |
| `calculate_hydrostatics` | One specified draft, trim and heel |
| `calculate_hydrostatics_series` | Explicit draft list |
| `export_linesplan_dxf` | Profile, plan and body views in metres |
| `export_hydrostatics` | CSV or XLSX with numeric data and eight curves |

Physical API values use **metres, metric tonnes, m², m³ and degrees**, even for imperial
models. Legacy model text encoding is explicit (`cp1252`, `cp1251` or `utf8`).
See [units and numerical semantics](docs/numerics.md) before setting transform targets.

## Example workflow

Generate the original synthetic examples with `python scripts/create_examples.py --output-dir C:\HullWork`
after building the engine. Example model data are self-created; no course or private model is included.

1. Inspect and validate a model.
2. Scale its actual mesh to desired dimensions; regenerate section positions afterward.
3. Supply displacement, LCB coordinate reference and layer indices to `rebuild_hull`.
4. Check **both** SAC convergence and actual 3D hydrostatic residuals.
5. Generate sections; for 11 theory stations use `L * i / 10`, `i = 0..10`.
6. Export DXF and hydrostatic series. A station exactly at a point stem may have no curve;
   the saved station count and nonempty curve count are reported separately.

Section and hydrostatic-series tools also accept ranges `[start_m, end_m, step_m]`.
The endpoint is included when the step lands on it; an off-grid endpoint is not appended.

## Scope

This is an early preview. Synthetic numerical tests and local Windows integration tests
are provided; broader real-hull validation is ongoing. Review dimensions, coefficient
references and both sets of residuals before using a transformed hull.

No resistance, propulsion, propeller or large-angle stability tools. Empirical targets
are supplied by the caller. Validation does not prove the absence of all surface
self-intersections. A successful Lackenby SAC iteration is not a promise that a different
3D integration method has identical residuals. See [verification](docs/verification.md).

## License

New integration code: GPL-3.0-or-later. Original FreeShip notices and licenses remain in
`vendor/freeship`, [NOTICE](NOTICE) and [LICENSE](LICENSE). This is an independent adapter,
not an official FreeShip release. Bundled binaries must be distributed with corresponding
source and third-party notices; see [development](docs/development.md).
