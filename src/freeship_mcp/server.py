"""Windows stdio MCP; all model calculations go through the native subprocess."""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from functools import wraps
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from .engine import Engine, EngineError, finite, positions
from .exporters import hydrostatics_report, linesplan_dxf


def create_server(engine: Engine) -> MCPServer:
    mcp = MCPServer("FreeShip MCP", version="0.1.0", instructions=(
        "Native FreeShip geometry and hydrostatics on Windows. All public physical inputs use metres, "
        "metric tonnes and degrees. All paths are confined to the configured workspace. "
        "Do not infer empirical values or LCB targets. Outputs never overwrite existing files."))

    async def progress(ctx: Context, fraction: float, message: str):
        await ctx.report_progress(fraction, total=1, message=message)

    def safe_tool():
        def register(function):
            @wraps(function)
            async def guarded(*args, **kwargs):
                try:
                    return await function(*args, **kwargs)
                except (ValueError, OSError, EngineError) as exc:
                    raise ToolError(str(exc)) from exc
            return mcp.tool()(guarded)
        return register

    @safe_tool()
    async def engine_info() -> dict:
        """Return native engine version, pinned upstream revision and capabilities."""
        return await engine.check()

    @safe_tool()
    async def inspect_model(model_path: str, encoding: str = "cp1252") -> dict:
        """Read FBM/FTM. Separate project dimensions, geometry bounds and layer flags. encoding affects legacy FBM text."""
        return await engine.call("inspect_model", model_path, encoding=encoding)

    @safe_tool()
    async def validate_model(model_path: str, encoding: str = "cp1252") -> dict:
        """Check topology, adjacent normals and native open-boundary leak candidates. Open deck above water is not automatically a defect."""
        return await engine.call("validate_model", model_path, encoding=encoding)

    @safe_tool()
    async def save_model(model_path: str, output_path: str, output_version: int = 0, encoding: str = "cp1252") -> dict:
        """Save/reload a new FBM or FTM. Version 0 preserves; 335/462 are explicit. Unsupported downgrade fails."""
        return await engine.call("save_model", model_path, output_path=output_path, output_version=output_version, encoding=encoding)

    @safe_tool()
    async def scale_model(model_path: str, output_path: str, x_factor: float, y_factor: float,
                          z_factor: float, allow_locked: bool = False, scale_markers: bool = True,
                          encoding: str = "cp1252", project_length_m: float | None = None,
                          project_beam_m: float | None = None, project_draft_m: float | None = None) -> dict:
        """Native XYZ scaling. Optional project dimensions explicitly set design metadata after geometry scaling.
        Otherwise stored dimensions scale with the mesh. Existing sections remain fixed; regenerate explicitly.
        """
        for name, value in (("x", x_factor), ("y", y_factor), ("z", z_factor)):
            finite(value, name, positive=True)
        settings = {key: value for key, value in (("project_length_m", project_length_m),
                    ("project_beam_m", project_beam_m), ("project_draft_m", project_draft_m)) if value is not None}
        for name, value in settings.items():
            finite(value, name, positive=True)
        return await engine.call("scale_model", model_path, output_path=output_path,
                                 x_factor=x_factor, y_factor=y_factor, z_factor=z_factor,
                                 allow_locked=allow_locked, scale_markers=scale_markers, encoding=encoding, **settings)

    @safe_tool()
    async def rebuild_hull(model_path: str, output_path: str, displacement_t: float, lcb_value: float,
                           lcb_reference: str, layer_indices: list[int], ctx: Context,
                           block_coefficient: float | None = None, max_iterations: int = 15,
                           allow_locked: bool = False, encoding: str = "cp1252") -> dict:
        """Native Lackenby transform. lcb_reference is aft_perpendicular_m or midship_forward_fraction.
        Select layers explicitly. Optional Cb must agree with target raw volume / stored LBT.
        Reports native SAC convergence separately from recalculated 3D hydrostatic residuals.
        """
        finite(displacement_t, "displacement_t", positive=True); finite(lcb_value, "lcb_value")
        if not layer_indices or any(i < 0 for i in layer_indices):
            raise ValueError("Provide nonnegative layer_indices explicitly")
        if not 1 <= max_iterations <= 200:
            raise ValueError("max_iterations must be between 1 and 200")
        info = await engine.call("inspect_model", model_path, encoding=encoding)
        if lcb_reference == "aft_perpendicular_m":
            lcb_m = lcb_value
        elif lcb_reference == "midship_forward_fraction":
            lcb_m = (0.5 + lcb_value) * info["length_m"]
        else:
            raise ValueError("Unknown lcb_reference")
        if block_coefficient is not None:
            finite(block_coefficient, "block_coefficient", positive=True)
            density = info["density_model_units"]
            if info["model_units"] == "fuImperial":
                density *= 0.00045359237 / 0.3048**3
            implied = displacement_t / (density * info["appendage_coefficient"] * info["length_m"] * info["beam_m"] * info["draft_m"])
            if abs(implied - block_coefficient) > 1e-4:
                raise ValueError(f"Conflicting targets: target displacement implies stored-dimension Cb={implied:.8g}")
        return await engine.call("rebuild_hull", model_path, output_path=output_path,
                                 displacement_t=displacement_t, lcb_ap_m=lcb_m, layer_indices=layer_indices,
                                 max_iterations=max_iterations, allow_locked=allow_locked, encoding=encoding,
                                 progress=lambda f, m: progress(ctx, f, m))

    @safe_tool()
    async def generate_sections(model_path: str, output_path: str, stations_m: list[float] | None = None,
                                waterlines_m: list[float] | None = None, buttocks_m: list[float] | None = None,
                                station_range_m: list[float] | None = None,
                                waterline_range_m: list[float] | None = None,
                                buttock_range_m: list[float] | None = None,
                                replace_existing: bool = True, encoding: str = "cp1252") -> dict:
        """Native sections at x/z/y positions, or [start,end,step] ranges in metres. A range includes its end only if the grid hits it."""
        stations_m = positions(stations_m, station_range_m, "stations")
        waterlines_m = positions(waterlines_m, waterline_range_m, "waterlines")
        buttocks_m = positions(buttocks_m, buttock_range_m, "buttocks")
        if not any((stations_m, waterlines_m, buttocks_m)):
            raise ValueError("Provide at least one section position")
        return await engine.call("generate_sections", model_path, output_path=output_path,
                                 stations_m=stations_m, waterlines_m=waterlines_m, buttocks_m=buttocks_m,
                                 replace_existing=replace_existing, encoding=encoding)

    @safe_tool()
    async def calculate_hydrostatics(model_path: str, draft_m: float, trim_m: float = 0,
                                     heel_degrees: float = 0, encoding: str = "cp1252") -> dict:
        """Calculate native hydrostatics. Draft is above the hull's lowest hydrostatic point; trim is fore-aft draft difference, positive bow down."""
        finite(draft_m, "draft_m"); finite(trim_m, "trim_m"); finite(heel_degrees, "heel_degrees")
        return await engine.call("calculate_hydrostatics", model_path, draft_m=draft_m,
                                 trim_m=trim_m, heel_degrees=heel_degrees, encoding=encoding)

    @safe_tool()
    async def calculate_hydrostatics_series(model_path: str, ctx: Context,
                                            drafts_m: list[float] | None = None,
                                            draft_range_m: list[float] | None = None,
                                            trim_m: float = 0, heel_degrees: float = 0,
                                            encoding: str = "cp1252") -> dict:
        """Calculate up to 1000 drafts: a list or [start,end,step] range in metres. Values are not rounded."""
        drafts_m = positions(drafts_m, draft_range_m, "drafts")
        if not 1 <= len(drafts_m) <= 1000:
            raise ValueError("Provide 1 to 1000 drafts")
        for draft in drafts_m:
            finite(draft, "draft_m")
        finite(trim_m, "trim_m"); finite(heel_degrees, "heel_degrees")
        return await engine.call("calculate_hydrostatics_series", model_path, drafts_m=drafts_m,
                                 trim_m=trim_m, heel_degrees=heel_degrees, encoding=encoding,
                                 progress=lambda f, m: progress(ctx, f, m))

    @safe_tool()
    async def export_linesplan_dxf(model_path: str, output_path: str, encoding: str = "cp1252") -> dict:
        """Export metre-based 2D profile/plan/body views of native intersection splines, sampled exactly as the upstream DXF exporter."""
        target = engine.path(output_path, output=True, suffixes=(".dxf",))
        geometry = await engine.call("linesplan_geometry", model_path, encoding=encoding)
        return await write_export(target, lambda p: linesplan_dxf(p, geometry))

    @safe_tool()
    async def export_hydrostatics(model_path: str, output_path: str, ctx: Context,
                                 drafts_m: list[float] | None = None,
                                 draft_range_m: list[float] | None = None,
                                 trim_m: float = 0, heel_degrees: float = 0,
                                 display_decimals: int = 2, encoding: str = "cp1252") -> dict:
        """Recalculate and export CSV or XLSX with raw numeric data and eight charts. Formatting does not round stored results."""
        target = engine.path(output_path, output=True, suffixes=(".csv", ".xlsx"))
        result = await calculate_hydrostatics_series(model_path, ctx=ctx, drafts_m=drafts_m,
            draft_range_m=draft_range_m, trim_m=trim_m, heel_degrees=heel_degrees, encoding=encoding)
        return await write_export(target, lambda p: hydrostatics_report(p, result["rows"], display_decimals))

    return mcp


async def write_export(target: Path, writer) -> dict:
    fd, name = tempfile.mkstemp(prefix=".freeship-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        # Writers are finite local serialization; native calculation has already completed.
        result = writer(temporary)
        temporary.rename(target)
        return {"ok": True, "output_path": str(target), **result}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Windows local FreeShip MCP (stdio)")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--check", action="store_true", help="Print engine compatibility check and exit")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("This release supports Windows x64 only")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        engine = Engine(args.workspace, args.engine, args.timeout)
        info = asyncio.run(engine.check())
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"FreeShip engine startup failed: {exc}. Install the matching Windows wheel.\n")
    if args.check:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return
    create_server(engine).run(transport="stdio")


if __name__ == "__main__":
    main()
