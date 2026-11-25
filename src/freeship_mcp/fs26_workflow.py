"""Run a bounded FS26 preliminary design brief and publish its verified artifacts."""
from collections.abc import Awaitable, Callable
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Annotated
from pydantic import AfterValidator, Field, StringConstraints, model_validator

from .engine import EngineError, file_identity
from .fs26 import FS26Engine, report_number
from .fs26_analysis import AnalysisInput, Angles, Coordinate, LoadingBook, Name, Nonnegative, Positive, SpeedRange, Values
from .fs26_editing import FS26Edit


class Variant(AnalysisInput):
    name: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")]
    edit: FS26Edit | None = None


class Acceptance(AnalysisInput):
    max_upright_immersion_m: Positive
    max_performance_trim_m: Nonnegative
    max_performance_upright_gz_m: Nonnegative
    max_design_resistance_kn: Positive
    min_matched_speed_kn: Positive


def ordered_sections(values: list[float]) -> list[float]:
    if sorted(set(values)) != values:
        raise ValueError("Section positions must be strictly increasing")
    return values


SectionPositions = Annotated[list[Coordinate], Field(min_length=1, max_length=512), AfterValidator(ordered_sections)]


class DrawingSections(AnalysisInput):
    stations_m: SectionPositions
    waterlines_m: SectionPositions
    buttocks_m: SectionPositions

    def native(self) -> dict:
        return {1: self.stations_m, 2: self.buttocks_m, 3: self.waterlines_m}


class DesignBrief(AnalysisInput):
    title: Name
    vessel_type: Name
    seed_model_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    variants: Annotated[list[Variant], Field(min_length=1, max_length=8)]
    loading_book: LoadingBook
    heel_angles_degrees: Angles
    performance_case: Name
    speeds: SpeedRange
    resistance_values: Values
    propeller_values: Values
    acceptance: Acceptance
    drawing_sections: DrawingSections | None = None

    @model_validator(mode="after")
    def check_inputs(self):
        if len({item.name.lower() for item in self.variants}) != len(self.variants):
            raise ValueError("Variant names must be unique")
        if self.performance_case not in {case.name for case in self.loading_book.cases}:
            raise ValueError("The performance case must name a case in the loading book")
        if not self.loading_book.criteria:
            raise ValueError("Supply at least one design-brief GZ criterion")
        if self.speeds.end_kn <= self.acceptance.min_matched_speed_kn:
            raise ValueError("The speed range must extend beyond the minimum matched speed")
        if not {"FungWake", "FungDeduction", "FungEtaR", "NpBox", "DpBox"} <= self.resistance_values.keys():
            raise ValueError("Supply propeller count, diameter limit, wake, thrust deduction and relative rotative efficiency")
        if self.resistance_values.keys() & {"DraftTotalBox", "StartSpeedBox", "EndSpeedBox", "StepSpeedBox", "DraftBox"}:
            raise ValueError("Set speeds in speeds; the performance draft and trim come from the specified load case")
        if not {"Edit2", "Edit3", "Edit12", "Edit13", "Edit14"} <= self.propeller_values.keys():
            raise ValueError("Supply shaft rotation speed, available engine power and propeller series inputs")
        return self


def check(name: str, actual: float, limit: float, unit: str, *, minimum: bool = False, **context) -> dict:
    passed = actual >= limit if minimum else actual <= limit
    return {"name": name, "actual": actual, "limit": limit, "unit": unit,
            "operator": ">=" if minimum else "<=", "status": "pass" if passed else "fail", **context}


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


async def evaluate_variant(engine: FS26Engine, seed: str, brief: DesignBrief, variant: Variant) -> dict:
    model = f"hull-{variant.name}.fbm"
    result = {"name": variant.name, "status": "blocked", "checks": []}
    checks = result["checks"]
    stage = "model"
    try:
        saved = await engine.write_model(model, model_path=seed, expected_model_sha256=brief.seed_model_sha256,
                                         edit=variant.edit, loading_book=brief.loading_book.native(),
                                         sections=brief.drawing_sections.native() if brief.drawing_sections else None)
        result["model"] = saved["provenance"]["output_model"]
        stage = "stability"
        stability = await engine.stability(model, brief.heel_angles_degrees, 0, True, None)
        result["stability"] = stability
        for row in stability["rows"]:
            case, heel = row["case_name"], row["heel"]
            if row["status"] != "ok":
                checks.append({"name": "equilibrium", "status": "blocked", "case": case, "heel_degrees": heel,
                               "reason": row["message"]})
                continue
            if heel == 0:
                checks.append(check("upright_immersion", report_number(row, "absolute_draft"),
                                    brief.acceptance.max_upright_immersion_m, "m", case=case))
            if "required_gz" in row:
                checks.append(check("minimum_gz", report_number(row, "gz"), report_number(row, "required_gz"),
                                    "m", minimum=True, case=case, heel_degrees=heel))
        if stability["status"] != "complete":
            return result

        stage = "resistance_applicability"
        upright = next(row for row in stability["rows"]
                       if row["case_name"] == brief.performance_case and row["heel"] == 0)
        trim = check("performance_absolute_trim", abs(report_number(upright, "trim")),
                     brief.acceptance.max_performance_trim_m, "m", case=brief.performance_case)
        upright_gz = check("performance_absolute_upright_gz", abs(report_number(upright, "gz")),
                           brief.acceptance.max_performance_upright_gz_m, "m", case=brief.performance_case)
        checks.extend((trim, upright_gz))
        if any(row["status"] == "fail" for row in (trim, upright_gz)):
            result.update(status="fail", blocked_stage="propulsion", reason="Even-keel performance conditions exceeded")
            return result

        # Use the same upright waterplane datum as the native equilibrium workflow.
        a, _, c, d = upright["plane"]
        midship = .5 * report_number(saved["model"]["settings"], "length")
        if c <= 0:
            raise EngineError("Invalid upright waterplane")
        draft = (-d - a * midship) / c - report_number(upright, "keel_z")
        if draft <= 0:
            raise EngineError("Non-positive upright draft")
        result["performance_condition"] = {"case": brief.performance_case, "draft_m": draft, "heel_degrees": 0,
                                           "trim_m": 0, "equilibrium_trim_m": upright["trim"]}
        stage = "propulsion"
        performance = await engine.propulsion_chain(
            model, "fung", brief.speeds, {**brief.resistance_values, "DraftTotalBox": draft}, brief.propeller_values, {}, True,
        )
        result["performance"] = performance
        if abs(report_number(performance["resistance"]["effective_values"], "DraftTotalBox") - draft) > 1e-5:
            raise EngineError("The native resistance calculation used a different draft")
        design = performance["resistance"]["result"]["design"]
        checks.append(check("design_resistance", report_number(design, "total_kn"),
                            brief.acceptance.max_design_resistance_kn, "kN", speed_kn=brief.speeds.design_kn))
        matching = performance["propeller_design"]["result"]
        if matching.get("table_limited") is not False:
            checks.append({"name": "matched_speed", "status": "blocked",
                           "reason": "The resistance table did not bracket a power balance"})
            return result
        checks.append(check("matched_speed", report_number(matching["matched"], "speed_kn"),
                            brief.acceptance.min_matched_speed_kn, "kn", minimum=True))
        result["status"] = "pass" if all(row["status"] == "pass" for row in checks) else "fail"
    except (EngineError, ValueError) as exc:
        result.update(blocked_stage=stage, reason=str(exc))
    return result


async def run_design_brief(engine: FS26Engine, model_path: str, output_directory: str, brief: DesignBrief,
                           progress: Callable[..., Awaitable[None]]) -> dict:
    source = engine.path(model_path)
    target = engine.path(output_directory, output=True, suffixes=None)
    source_id = file_identity(source)
    executable = file_identity(engine.executable)
    if source_id["sha256"] != brief.seed_model_sha256:
        raise EngineError("Model snapshot hash mismatch; inspect the current seed before running the brief")
    with tempfile.TemporaryDirectory(prefix=".freeship-design-", dir=target.parent) as scratch:
        workspace = Path(scratch)
        deliverables = workspace / "delivery"
        deliverables.mkdir()
        staged_engine = FS26Engine(deliverables, engine.executable, engine.timeout)
        # Keep the exact seed alongside the brief so candidate generation is reproducible.
        seed_name = "seed" + source.suffix.lower()
        seed, identity = engine._copy_model(source, workspace)
        if identity != source_id:
            raise EngineError("Source changed while preparing the brief")
        seed.rename(deliverables / seed_name)
        if (await staged_engine.inspect(seed_name, False))["units"] != "metric":
            raise ValueError("This design brief workflow requires a metric seed model")

        candidates = []
        for index, variant in enumerate(brief.variants):
            await progress(index, total=len(brief.variants), message=f"Evaluating {variant.name}")
            candidates.append(await evaluate_variant(staged_engine, seed_name, brief, variant))
        eligible = [item for item in candidates if item["status"] == "pass"]
        selected = min(eligible, key=lambda item: item["performance"]["resistance"]["result"]["design"]["total_kn"],
                       default=None)
        result = {"schema": 1, "title": brief.title, "vessel_type": brief.vessel_type,
                  "basis": "preliminary_design_brief", "seed": {**source_id, "file_name": seed_name},
                  "engine": executable, "selection": "lowest_design_resistance_among_passing_variants",
                  "status": "selected" if selected else "no_passing_variant",
                  "selected": selected["name"] if selected else None, "candidates": candidates}
        files = {"brief": "brief.json", "assessment": "assessment.json"}
        if selected:
            files["selected_model"] = selected["model"]["file_name"]
            drawing, provenance = await staged_engine.linesplan(files["selected_model"])
            if provenance["model"] != selected["model"] or provenance["engine"] != executable:
                raise EngineError("Selected drawing does not match the evaluated model")
            files["selected_drawing"] = "selected.dxf"
            (deliverables / files["selected_drawing"]).write_bytes(drawing)
            result["drawing"] = {"file_name": files["selected_drawing"], "sha256": sha256(drawing).hexdigest(),
                                 "provenance": provenance}
        for item in candidates:
            for stage in ("stability", "performance"):
                if stage in item and (item[stage]["provenance"]["engine"] != executable
                                      or item[stage]["provenance"]["model"] != item["model"]):
                    raise EngineError("A calculation used a different engine or candidate revision")
        write_json(deliverables / files["brief"], brief.model_dump(mode="json"))
        write_json(deliverables / files["assessment"], result)
        await progress(len(brief.variants), total=len(brief.variants), message="Publishing design assessment")
        engine._verify_inputs(source, source_id, executable)
        if engine.path(output_directory, output=True, suffixes=None) != target:
            raise EngineError("Output directory changed during the request")
        deliverables.rename(target)
    return {
        "status": result["status"], "selected": result["selected"], "output_directory": str(target), "files": files,
        "candidates": [{key: item[key] for key in ("name", "status", "checks", "reason") if key in item}
                       for item in candidates],
    }
