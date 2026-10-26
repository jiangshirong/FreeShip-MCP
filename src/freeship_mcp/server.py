"""Windows stdio MCP; all model calculations go through the native subprocess."""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
import sys
import tempfile
from functools import wraps
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from .engine import Engine, EngineError, finite, positions
from .exporters import hydrostatics_report, linesplan_dxf
from .verification import Target, verify_targets
from .editing import LocalEdit
from .quality import AlignmentRule, analyze_geometry
from .linesplan import LinesplanOptions
from .engine import file_identity


def create_server(engine: Engine) -> MCPServer:
    mcp = MCPServer("FreeShip MCP", version="0.3.2", instructions=(
        "Native FreeShip geometry and hydrostatics on Windows. All public physical inputs use metres, "
        "metric tonnes and degrees. All paths are confined to the configured workspace. "
        "Do not infer empirical values or LCB targets. Model outputs default to fv335. Output filenames are exactly those specified by output_path; do not append version labels. Outputs never overwrite existing files."))

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
    async def inspect_model(model_path: str, encoding: str = "cp1252", include_control_net: bool = False) -> dict:
        """Read FBM/FTM. Separate project dimensions, geometry bounds and layer flags. include_control_net returns point/edge/face indices. encoding affects legacy FBM text."""
        return await engine.call("inspect_model", model_path, encoding=encoding, include_control_net=include_control_net)

    @safe_tool()
    async def validate_model(model_path: str, encoding: str = "cp1252") -> dict:
        """Check topology, adjacent normals and native open-boundary leak candidates. Open deck above water is not automatically a defect."""
        return await engine.call("validate_model", model_path, encoding=encoding)

    @safe_tool()
    async def edit_control_net(model_path: str, output_path: str, expected_model_sha256: str,
                               edit: LocalEdit, allow_locked: bool = False, encoding: str = "cp1252", output_version: int = 335) -> dict:
        """Apply one explicit local native edit to a new model, then validate and reload it.
        Inspect include_control_net first; use its provenance.model.sha256 and current point/edge/face indices.
        Supports point movement/alignment/relaxation, edge split/crease and face split/add/delete.
        Relaxation is a selected-neighbour averaging operation, not automatic hull fairing.
        Stored project dimensions are not inferred from edits. Recalculate hydrostatics and sections explicitly.
        """
        if not re.fullmatch(r"[0-9a-f]{64}",expected_model_sha256):
            raise ValueError("expected_model_sha256 must be the lowercase SHA-256 from inspect_model")
        return await engine.call("edit_control_net", model_path, output_path=output_path,
            expected_model_sha256=expected_model_sha256, output_version=output_version, edit=edit.model_dump(exclude_none=True),
            allow_locked=allow_locked, encoding=encoding)

    @safe_tool()
    async def analyze_hull_quality(model_path: str, stations_m: list[float] | None = None,
                                   waterlines_m: list[float] | None = None, buttocks_m: list[float] | None = None,
                                   alignment_rules: list[AlignmentRule] | None = None,
                                   max_turn_degrees: float | None = None, max_curvature_per_m: float | None = None,
                                   max_curvature_step_per_m: float | None = None,
                                   sample_count: int = 201, encoding: str = "cp1252") -> dict:
        """Read-only native section diagnostics: sampled turning, curvature, changes and explicit point constraints.
        No default acceptance limits. Returns suspicious coordinates, native knuckles and topology diagnostics.
        No self-intersection proof or automatic design approval. Up to 20 finding details per curve; total count retained.
        Optional section positions are calculated in memory and never saved to the source.
        """
        if not 21 <= sample_count <= 1001:raise ValueError("sample_count must be 21..1001")
        for name,value in (("max_turn_degrees",max_turn_degrees),("max_curvature_per_m",max_curvature_per_m),
                           ("max_curvature_step_per_m",max_curvature_step_per_m)):
            if value is not None:
                finite(value,name)
                if value<0:raise ValueError(f"{name} must be nonnegative")
        if max_turn_degrees is not None and max_turn_degrees>180:raise ValueError("Turning limit must be <=180 degrees")
        if alignment_rules is not None and len(alignment_rules)>1000:raise ValueError("At most 1000 alignment rules")
        section_args={key:positions(value,None,key) for key,value in
                      (("stations_m",stations_m),("waterlines_m",waterlines_m),("buttocks_m",buttocks_m)) if value is not None}
        model=await engine.call("inspect_model",model_path,include_control_net=True,encoding=encoding)
        topology=await engine.call("validate_model",model_path,encoding=encoding)
        geometry=await engine.call("linesplan_geometry",model_path,sample_count=sample_count,encoding=encoding,**section_args)
        identities=[r['provenance']['model']['sha256'] for r in (model,topology,geometry)]
        if len(set(identities))!=1:raise EngineError("Model changed between diagnostic measurements")
        result=analyze_geometry(geometry,model,topology,alignment_rules or [],max_turn_degrees,
                                max_curvature_per_m,max_curvature_step_per_m)
        result['provenance']=geometry['provenance']
        result['alignment_rules']=[r.model_dump() for r in alignment_rules or []]
        result['sample_count']=sample_count
        return result

    @safe_tool()
    async def verify_model_targets(model_path: str, draft_m: float, targets: list[Target],
                                   trim_m: float = 0, heel_degrees: float = 0,
                                   encoding: str = "cp1252") -> dict:
        """Check explicit targets and absolute tolerances: passed/failed/not_checked.
        Project settings do not verify geometry. Coefficient metrics explicitly select native or project basis.
        section_top_above_keel_m requires section_x_m; it is the highest point on hydrostatics surfaces,
        not automatic main-deck identification. Does not alter the model or infer missing targets.
        """
        return await verify_targets(engine, model_path, draft_m, targets, trim_m, heel_degrees, encoding)

    @safe_tool()
    async def check_export_source(model_path: str, export_path: str) -> dict:
        """Compare an export's manifest hashes with the current model and artifact. Missing manifest is unverified."""
        model = engine.path(model_path)
        artifact = engine.path(export_path, suffixes=(".dxf", ".xlsx", ".csv"))
        sidecar = engine.path(str(artifact)+".manifest.json", output=False, suffixes=(".json",)) if Path(str(artifact)+".manifest.json").exists() else None
        if sidecar is None:
            return {"ok": True, "status": "unverified", "reason": "No provenance manifest; regenerate the export"}
        if sidecar.stat().st_size > 16*1024*1024:
            raise ValueError("Manifest exceeds 16 MiB")
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        try:
            model_match = manifest["provenance"]["model"]["sha256"] == file_identity(model)["sha256"]
            artifact_match = manifest["artifact"]["sha256"] == file_identity(artifact)["sha256"]
        except (KeyError, TypeError):
            raise ValueError("Invalid provenance manifest; regenerate the export")
        return {"ok": True, "status": "current" if model_match and artifact_match else "stale_or_modified",
                "model_matches": model_match, "artifact_matches": artifact_match,
                "provenance": manifest["provenance"],
                "scope": "Hash consistency only; not proof of geometry validity or manifest authenticity"}

    @safe_tool()
    async def save_model(model_path: str, output_path: str, output_version: int = 335, encoding: str = "cp1252") -> dict:
        """Save/reload a new model. Default format is fv335; output_path determines the filename and FBM/FTM extension. Explicit output_version=0 preserves, 462 selects fv462. Unsupported downgrade fails."""
        return await engine.call("save_model", model_path, output_path=output_path, output_version=output_version, encoding=encoding)

    @safe_tool()
    async def scale_model(model_path: str, output_path: str, x_factor: float, y_factor: float,
                          z_factor: float, allow_locked: bool = False, scale_markers: bool = True,
                          encoding: str = "cp1252", project_length_m: float | None = None,
                          project_beam_m: float | None = None, project_draft_m: float | None = None,
                          x_offset_m: float = 0, z_cut_m: float | None = None,
                          z_above_factor: float | None = None, project_name: str | None = None,
                          project_designer: str | None = None, project_comment: str | None = None,
                          point_updates: list[dict] | None = None, output_version: int = 335) -> dict:
        """Native XYZ scaling. Optional project dimensions explicitly set design metadata after geometry scaling.
        Otherwise stored dimensions scale with the mesh. x_offset_m translates the scaled mesh along x.
        Existing sections remain fixed; regenerate explicitly.
        Optional z_cut_m/z_above_factor scale control-point heights above an explicit plane.
        This edits geometry; all hydrostatics must be recalculated. Native coefficients remain unchanged.
        """
        for name, value in (("x", x_factor), ("y", y_factor), ("z", z_factor)):
            finite(value, name, positive=True)
        settings = {key: value for key, value in (("project_length_m", project_length_m),
                    ("project_beam_m", project_beam_m), ("project_draft_m", project_draft_m)) if value is not None}
        for name, value in settings.items():
            finite(value, name, positive=True)
        finite(x_offset_m, "x_offset_m")
        if (z_cut_m is None) != (z_above_factor is None):
            raise ValueError("Provide z_cut_m and z_above_factor together")
        if z_above_factor is not None:
            finite(z_cut_m, "z_cut_m"); finite(z_above_factor, "z_above_factor", positive=True)
            settings.update(z_cut_m=z_cut_m, z_above_factor=z_above_factor)
        for name, value in (("project_name", project_name), ("project_designer", project_designer),
                            ("project_comment", project_comment)):
            if value is not None:
                if "\x00" in value or len(value)>4096:
                    raise ValueError(f"Invalid {name}")
                settings[name]=value
        if point_updates is not None:
            if len(point_updates)>100000:
                raise ValueError("Too many point updates")
            seen=set()
            for point in point_updates:
                if set(point)-{"index","x_m","y_m","z_m"} or "index" not in point:
                    raise ValueError("Point updates require index and explicit x_m/y_m/z_m coordinates")
                index=point["index"]
                if type(index) is not int or index<0 or index in seen:
                    raise ValueError("Point indices must be unique nonnegative integers")
                seen.add(index)
                for key,value in point.items():
                    if key!="index":finite(value,key)
            settings["point_updates"]=point_updates
        return await engine.call("scale_model", model_path, output_path=output_path,
                                 x_factor=x_factor, y_factor=y_factor, z_factor=z_factor, output_version=output_version,
                                 allow_locked=allow_locked, scale_markers=scale_markers, encoding=encoding,
                                 x_offset_m=x_offset_m, **settings)

    @safe_tool()
    async def rebuild_hull(model_path: str, output_path: str, displacement_t: float, lcb_value: float,
                           lcb_reference: str, layer_indices: list[int], ctx: Context,
                           block_coefficient: float | None = None, max_iterations: int = 15,
                           allow_locked: bool = False, encoding: str = "cp1252", output_version: int = 335) -> dict:
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
                                 max_iterations=max_iterations, allow_locked=allow_locked, output_version=output_version, encoding=encoding,
                                 progress=lambda f, m: progress(ctx, f, m))

    @safe_tool()
    async def generate_sections(model_path: str, output_path: str, stations_m: list[float] | None = None,
                                waterlines_m: list[float] | None = None, buttocks_m: list[float] | None = None,
                                station_range_m: list[float] | None = None,
                                waterline_range_m: list[float] | None = None,
                                buttock_range_m: list[float] | None = None,
                                replace_existing: bool = True, encoding: str = "cp1252", output_version: int = 335) -> dict:
        """Native sections at x/z/y positions, or [start,end,step] ranges in metres. A range includes its end only if the grid hits it."""
        stations_m = positions(stations_m, station_range_m, "stations")
        waterlines_m = positions(waterlines_m, waterline_range_m, "waterlines")
        buttocks_m = positions(buttocks_m, buttock_range_m, "buttocks")
        if not any((stations_m, waterlines_m, buttocks_m)):
            raise ValueError("Provide at least one section position")
        return await engine.call("generate_sections", model_path, output_path=output_path,
                                 stations_m=stations_m, waterlines_m=waterlines_m, buttocks_m=buttocks_m,
                                 replace_existing=replace_existing, output_version=output_version, encoding=encoding)

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
    async def export_linesplan_dxf(model_path: str, output_path: str, encoding: str = "cp1252",
                                   options: LinesplanOptions | None = None) -> dict:
        """Export three views with native curves, true surface boundaries, mesh silhouettes, grids and labels.
        Optional grid positions also generate temporary native sections. They do not change the source model.
        Surface outlines are mesh segments; disconnected splines remain separate. No hidden-line removal.
        """
        target = engine.path(output_path, output=True, suffixes=(".dxf",))
        options=options or LinesplanOptions()
        section_args={key:getattr(options,key) for key in ('stations_m','waterlines_m','buttocks_m') if getattr(options,key) is not None}
        geometry = await engine.call("linesplan_geometry", model_path, encoding=encoding, **section_args)
        provenance={**geometry['provenance'],'export':{'format':'.dxf','options':options.model_dump()}}
        return await write_export(target, lambda p: linesplan_dxf(p, geometry, options), provenance)

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
        provenance = {**result["provenance"], "export": {"format": target.suffix.lower(), "display_decimals": display_decimals},
            "coefficient_basis_by_draft": [{"draft_m": row["draft_m"], "basis": row["coefficient_basis"]} for row in result["rows"]]}
        return await write_export(target, lambda p: hydrostatics_report(p, result["rows"], display_decimals, provenance), provenance)

    return mcp


async def write_export(target: Path, writer, provenance: dict) -> dict:
    sidecar = Path(str(target)+".manifest.json")
    if sidecar.exists():
        raise FileExistsError("Export manifest exists; choose a new filename")
    fd, name = tempfile.mkstemp(prefix=".freeship-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    manifest_temp = None
    published = False
    try:
        # Writers are finite local serialization; native calculation has already completed.
        result = writer(temporary)
        manifest = {"schema_version": 1, "provenance": provenance,
                    "artifact": {**file_identity(temporary), "file_name": target.name}}
        fd, manifest_name = tempfile.mkstemp(prefix=".freeship-", suffix=".json", dir=target.parent)
        os.close(fd)
        manifest_temp = Path(manifest_name)
        manifest_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.rename(target)
        published = True
        manifest_temp.rename(sidecar)
        return {"ok": True, "output_path": str(target), "manifest_path": str(sidecar), "provenance": provenance, **result}
    except BaseException:
        if published:
            target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)


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
