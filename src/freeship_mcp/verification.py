"""Explicit target checks. Settings are never substituted for geometry measurements."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .engine import Engine, EngineError, finite, file_identity

Metric = Literal[
    "project_length_m", "project_beam_m", "project_draft_m", "draft_m",
    "waterline_length_m", "waterline_beam_m", "displacement_t", "lcb_ap_m",
    "lcb_midship_fraction", "block_coefficient_project_geometry",
    "waterplane_coefficient_project", "block_coefficient_native", "waterplane_coefficient_native",
    "section_top_above_keel_m", "minimum_freeboard_m",
]


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    metric: Metric
    expected: float
    absolute_tolerance: float = Field(ge=0)
    section_x_m: float | None = None


async def verify_targets(engine: Engine, model_path: str, draft_m: float, targets: list[Target],
                         trim_m: float = 0, heel_degrees: float = 0, encoding: str = "cp1252") -> dict:
    for name, value in (("draft_m", draft_m), ("trim_m", trim_m), ("heel_degrees", heel_degrees)):
        finite(value, name)
    if not 1 <= len(targets) <= 100:
        raise ValueError("Provide 1 to 100 explicit targets with absolute tolerances")
    keys = [(t.metric, t.section_x_m) for t in targets]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate target metric/section")
    for t in targets:
        if t.metric == "section_top_above_keel_m" and t.section_x_m is None:
            raise ValueError("section_top_above_keel_m requires an explicit section_x_m")
        if t.metric != "section_top_above_keel_m" and t.section_x_m is not None:
            raise ValueError("section_x_m is only valid for section_top_above_keel_m")
    model = await engine.call("inspect_model", model_path, encoding=encoding)
    identity = model["provenance"]["model"]
    evidence = [model["provenance"]]

    def stable(result):
        if result["provenance"]["model"] != identity:
            raise EngineError("Model changed between verification measurements; retry")
        evidence.append(result["provenance"])
        return result

    hydro, hydro_error = {}, None
    # Section/settings checks still run when hydrostatics cannot be calculated.
    try:
        hydro = stable(await engine.call("calculate_hydrostatics", model_path, draft_m=draft_m,
            trim_m=trim_m, heel_degrees=heel_degrees, encoding=encoding))
    except EngineError as exc:
        if "changed" in str(exc):
            raise
        hydro_error = str(exc)
    checks = []
    sections = {}
    for t in targets:
        metric = t.metric
        basis = {"kind": "hydrostatics", "reference": hydro.get("centres_reference")}
        reason = None
        value = None
        if metric.startswith("project_"):
            value = model[metric.removeprefix("project_")]
            basis = {"kind": "project_setting", "geometry_verified": False}
        elif metric == "section_top_above_keel_m":
            if t.section_x_m not in sections:
                sections[t.section_x_m] = stable(await engine.call("measure_section", model_path,
                    section_x_m=t.section_x_m, encoding=encoding))
            section = sections[t.section_x_m]
            value = section.get(metric)
            reason = "No intersection on hydrostatics-enabled surfaces" if value is None else None
            basis = {"kind": "section_geometry", "section_x_m": t.section_x_m,
                     "scope": section["scope"], "curve_count": section["curve_count"]}
        else:
            key = metric.removesuffix("_native") if metric.endswith("_native") else metric
            value = hydro.get(key)
            if metric.startswith(("block_coefficient", "waterplane_coefficient")):
                basis = hydro.get("coefficient_basis", {}).get(
                    "native" if metric.endswith("_native") else "project_geometry", {})
            if value is None:
                reason = hydro_error or "Metric undefined at the requested waterplane"
            elif metric == "minimum_freeboard_m" and (trim_m != 0 or heel_degrees != 0):
                value = None
                reason = "Vertical clearance only; minimum inclined-waterplane clearance is not measured"
            elif draft_m <= 0 or hydro.get("no_immersion"):
                value = None
                reason = "No positive immersed draft; hydrostatic target not checked"
        unit = "t" if metric == "displacement_t" else "1" if "coefficient" in metric or metric.endswith("fraction") else "m"
        residual = None if value is None else value-t.expected
        status = "not_checked" if residual is None else "passed" if abs(residual) <= t.absolute_tolerance else "failed"
        checks.append({**t.model_dump(exclude_none=True), "unit": unit, "measured": value,
                       "residual": residual, "status": status, "basis": basis, "reason": reason})
    counts = {s: sum(c["status"] == s for c in checks) for s in ("passed", "failed", "not_checked")}
    if file_identity(engine.path(model_path)) != identity:
        raise EngineError("Model changed during target verification; retry")
    return {"ok": True, "status": "failed" if counts["failed"] else "incomplete" if counts["not_checked"] else "passed",
            "scope": "Only explicitly requested targets; passing settings does not verify hull geometry or unrequested properties",
            "summary": counts, "checks": checks, "coefficient_basis": hydro.get("coefficient_basis"),
            "provenance": {**model["provenance"], "measurements": evidence,
                           "conditions": {"draft_m": draft_m, "trim_m": trim_m, "heel_degrees": heel_degrees}}}
