"""FS26 model files, native calculations and verified copy-on-write edits."""
from __future__ import annotations

from contextlib import ExitStack, asynccontextmanager
from hashlib import sha256
from math import isfinite
import os
from pathlib import Path
import re
import shutil
import tempfile

from .engine import EngineError, LocalEngine, MAX_MODEL_BYTES, file_identity, finite
from .fs26_analysis import DIAGRAM_FIELD, NATIVE_FIELDS, PerformanceMethod, ResistanceMethod, SpeedRange, Values, native_values
from .fs26_editing import FS26Edit, Lackenby, edit_request
from .fs26_service import DocumentService, run_document_service

API_VERSION = 1
SNAPSHOT_VERSION = 1
HYDROSTATICS_SCHEMA = 1
TOOLS = (
    "engine_info", "inspect_model", "validate_model", "calculate_hydrostatics",
    "create_hull", "edit_control_net", "save_model", "rebuild_hull", "export_linesplan_dxf",
    "inspect_loading_book", "save_loading_book", "calculate_stability",
    "inspect_performance_inputs", "calculate_performance", "calculate_propulsion_chain", "compare_resistance",
    "run_design_brief",
)
CONTROL_NET = ("control_points", "control_edges", "control_faces")
# Geometry fields populated separately by the native extract operation.
EXTRACTED_RESISTANCE = {
    "LwlBox", "BwlBox", "DraftTotalBox", "DraftBox", "WettedSurfacebox", "Losbox", "DisplacementBox",
    "LCBBox", "CpBox", "KBulbBox", "BABox", "ZBulbBox", "FungCwp", "FungTransomDraftRatio",
}


def report_number(report: dict, key: str) -> float:
    value = report.get(key)
    if type(value) not in (float, int) or not isfinite(value):
        raise EngineError(f"FS26 result lacks a finite {key}")
    return value


class FS26Engine(LocalEngine):
    def __init__(self, workspace: Path, executable: Path, timeout: float = 120):
        super().__init__(workspace, executable, timeout)

    async def check(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="freeship-mcp-fs26-") as temporary:
            async with run_document_service(self.executable, Path(temporary), self.timeout) as service:
                response = await service.request("document_context", colors=[])
        if response.get("preferences_engine") != "cpp-preferences":
            raise EngineError("Incompatible FS26 document context")
        return {
            "backend": "fs26",
            "document_engine": response["document_engine"],
            "adapter_api_version": API_VERSION,
            "required_artifact_schemas": {"model_snapshot": SNAPSHOT_VERSION, "hydrostatics": HYDROSTATICS_SCHEMA},
            "read_only": False,
            "tools": list(TOOLS),
            "input_formats": [".fbm", ".ftm"],
            "model_output_formats": [".fbm"],
            "length_units": {"metric": "m", "imperial": "ft"},
            "performance_methods": list(NATIVE_FIELDS),
            "engine": file_identity(self.executable),
        }

    async def inspect(self, model_path: str, include_control_net: bool, include_lackenby_reference: bool = False) -> dict:
        async with self._source(model_path) as (service, opened, provenance):
            snapshot = self._snapshot(service, opened)
            result = self._summary(snapshot)
            if include_control_net:
                result.update({key: snapshot[key] for key in CONTROL_NET})
            if include_lackenby_reference:
                result["lackenby_reference"] = await self._measure_lackenby(service)
        return {**result, "provenance": provenance}

    async def validate(self, model_path: str) -> dict:
        async with self._source(model_path) as (service, opened, provenance):
            self._snapshot(service, opened)
            response = await service.current("document_status")
        if not isinstance(response.get("fbm"), dict):
            raise EngineError("FS26 did not return document status")
        return {
            "loaded": True,
            "scope": ["file_parse", "document_load", "snapshot_structure"],
            "native_document": response["fbm"],
            "provenance": provenance,
        }

    async def hydrostatics(self, model_path: str, draft: float, trim: float, heel_degrees: float) -> dict:
        finite(draft, "draft")
        finite(trim, "trim")
        finite(heel_degrees, "heel_degrees")
        if draft < 0 or abs(heel_degrees) > 85:
            raise ValueError("Draft must be nonnegative and heel must be within [-85, 85] degrees")
        async with self._source(model_path) as (service, opened, provenance):
            snapshot = self._snapshot(service, opened)
            report = await self._hydro(service, snapshot["units"], mode="single", draft=draft, trim=trim, heel=heel_degrees)
        rows = report["rows"]
        if len(rows) != 1:
            raise EngineError("FS26 did not return one completed hydrostatics row")
        if rows[0].get("status") != "ok":
            raise EngineError(str(rows[0].get("message") or "FS26 hydrostatics failed"))
        return {**report, "provenance": provenance}

    @staticmethod
    async def _hydro(service: DocumentService, units: str, **request) -> dict:
        response = await service.current("hydrostatics", **request)
        report = service.artifact_json(response, "hydro")
        if (report.get("schema") != HYDROSTATICS_SCHEMA or report.get("units") != units
                or report.get("mode") != request["mode"] or report.get("cancelled") is not False):
            raise EngineError("Incomplete or incompatible FS26 hydrostatics report")
        rows = report.get("rows")
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or r.get("status") not in ("ok", "error") for r in rows):
            raise EngineError("Invalid FS26 hydrostatics rows")
        return report

    @staticmethod
    async def _loading_settings(service: DocumentService) -> dict:
        response = await service.current("hydro_defaults")
        analysis = response.get("analysis")
        if not isinstance(analysis, dict):
            raise EngineError("Missing FS26 hydrostatics setup")
        settings = analysis.get("saved_cross_inputs")
        if settings is None:
            return {}
        if not isinstance(settings, dict):
            raise EngineError("Invalid saved FS26 stability inputs")
        return settings

    async def inspect_loading(self, model_path: str) -> dict:
        async with self._source(model_path) as (service, _, provenance):
            settings = await self._loading_settings(service)
        return {
            "loading_book": settings.get("loading_book"), "uses_loading_book": bool(settings.get("use_loading_book")),
            "provenance": provenance,
        }

    async def stability(self, model_path: str, angles: list[float], trim: float, free_trim: bool,
                        book: dict | None) -> dict:
        finite(trim, "trim")
        async with self._source(model_path) as (service, opened, provenance):
            units = self._snapshot(service, opened)["units"]
            if book is None:
                book = (await self._loading_settings(service)).get("loading_book")
            if not book:
                raise ValueError("Supply a loading book or use an FBM with a saved loading book")
            report = await self._hydro(service, units, mode="cross", angles=angles, trim=trim, free_trim=free_trim,
                                       use_loading_book=True, loading_book=book)
        valid = sum(row["status"] == "ok" for row in report["rows"])
        return {
            **report, "status": "complete" if valid == len(report["rows"]) else "partial" if valid else "failed",
            "successful_rows": valid, "failed_rows": len(report["rows"]) - valid, "provenance": provenance,
        }

    @staticmethod
    async def _performance(service: DocumentService, calculator: PerformanceMethod, values: Values,
                           extract: bool, *, defaults: bool = False) -> dict:
        values = native_values(calculator, values)
        response = await service.current("performance_defaults", calculator=calculator, values=values, extract=extract)
        schema = service.artifact_json(response, "performance")
        fields = schema.get("fields")
        if schema.get("calculator") != calculator or not isinstance(fields, list):
            raise EngineError("Invalid FS26 performance input schema")
        applied = {field["key"]: field["value"] for field in fields}
        native_values(calculator, applied)
        if defaults:
            return {"calculator": calculator, "title": schema["title"], "fields": fields, "effective_values": applied}
        # Reapply explicit inputs and extract on the same document. This retains native
        # input precision and avoids passing disabled fields back as overrides.
        result = await service.current("performance", calculator=calculator, values=values, extract=extract)
        report = service.artifact_json(result, "performance")
        _, section = NATIVE_FIELDS[calculator]
        data = report.get(section)
        if report.get("calculator") != calculator or not isinstance(data, dict):
            raise EngineError(f"FS26 did not return a native {calculator} calculation")
        calculated_fields = report.get("parameters", {}).get("fields")
        if not isinstance(calculated_fields, list):
            raise EngineError("FS26 did not report the calculation inputs")
        return {
            "calculator": calculator, "engine": report["engine"],
            "effective_values": {field["key"]: field["value"] for field in calculated_fields},
            "warnings": report.get("warnings", []),
            "result": {key: value for key, value in data.items() if key != "plot"},
        }

    async def performance(self, model_path: str, calculator: PerformanceMethod, values: Values, extract: bool,
                          *, defaults: bool = False) -> dict:
        async with self._source(model_path) as (service, opened, provenance):
            units = self._snapshot(service, opened)["units"]
            result = await self._performance(service, calculator, values, extract, defaults=defaults)
        return {**result, "model_units": units, "extracted": extract, "provenance": provenance}

    async def propulsion_chain(self, model_path: str, resistance: ResistanceMethod, speeds: SpeedRange,
                               resistance_values: Values, propeller_values: Values, passport_values: Values,
                               extract_hull: bool) -> dict:
        async with self._source(model_path) as (service, opened, provenance):
            if self._snapshot(service, opened)["units"] != "metric":
                raise ValueError("The native propeller matching workflow requires a metric ship model")
            drag = await self._performance(service, resistance, {**resistance_values, **speeds.native()}, extract_hull)
            if drag["result"].get("cache_published") is not True:
                raise EngineError("FS26 did not publish these resistance results for propulsion matching")
            propeller = await self._performance(service, "propeller2", propeller_values, True)
            passport = await self._performance(service, "propeller3", passport_values, True)
        return {
            "resistance": drag, "propeller_design": propeller, "propulsion_passport": passport,
            "hull_geometry_extracted": extract_hull, "provenance": provenance,
        }

    async def compare_resistance(self, baseline_path: str, candidate_path: str, calculator: ResistanceMethod,
                                 speeds: SpeedRange, values: Values) -> dict:
        request = {**values, **speeds.native()}
        baseline = await self.performance(baseline_path, calculator, request, True)
        candidate = await self.performance(candidate_path, calculator, request, True)
        if baseline["model_units"] != candidate["model_units"] or baseline["provenance"]["engine"] != candidate["provenance"]["engine"]:
            raise ValueError("Comparison requires equal model units and the same FS26 executable")
        if {k: v for k, v in baseline["effective_values"].items() if k not in EXTRACTED_RESISTANCE} != {
                k: v for k, v in candidate["effective_values"].items() if k not in EXTRACTED_RESISTANCE}:
            raise ValueError("Effective non-geometry inputs differ; explicitly supply common calculation settings")
        a = baseline["result"].get("design", {})
        b = candidate["result"].get("design", {})
        if report_number(a, "knots") != report_number(b, "knots"):
            raise EngineError("FS26 returned different design speeds")
        deltas = {key: report_number(b, key) - report_number(a, key) for key in ("total_kn", "power_kw")}
        return {"baseline": baseline, "candidate": candidate, "candidate_minus_baseline": deltas}

    async def linesplan(self, model_path: str) -> tuple[bytes, dict]:
        async with self._source(model_path, include_drawing=True) as (service, opened, provenance):
            snapshot = self._snapshot(service, opened)
            report = service.artifact_json(opened, "native_report")
            drawing = service.artifact_path(opened, "dxf").read_bytes()
            if (report.get("engine") != "cpp-native" or report.get("status") != "pass"
                    or report.get("drawing_deferred") is not False
                    or report.get("dxf_sha256") != sha256(drawing).hexdigest()
                    or report.get("dxf_bytes") != len(drawing)):
                raise EngineError("Invalid FS26 lines plan publication")
        return drawing, {**provenance, "export": {"format": ".dxf", "engine": "cpp-native", "units": snapshot["units"]}}

    async def write_model(self, output_path: str, *, model_path: str | None = None,
                          expected_model_sha256: str | None = None, creation: dict | None = None,
                          edit: FS26Edit | Lackenby | None = None, loading_book: dict | None = None,
                          sections: dict[int, list[float]] | None = None) -> dict:
        target = self.path(output_path, output=True, suffixes=(".fbm",))
        source = self.path(model_path) if model_path is not None else None
        if source is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_model_sha256 or ""):
            raise ValueError("expected_model_sha256 must be the lowercase SHA-256 from inspect_model")
        engine = file_identity(self.executable)
        with ExitStack() as pending_output:
            with tempfile.TemporaryDirectory(prefix="freeship-mcp-fs26-") as temporary:
                directory = Path(temporary).resolve()
                identity = None
                if source is not None:
                    private_input, identity = self._copy_model(source, directory)
                    if identity["sha256"] != expected_model_sha256:
                        raise EngineError("Model snapshot hash mismatch; inspect the current model before editing or saving")

                async with run_document_service(self.executable, directory, self.timeout) as service:
                    if source is None:
                        state = await service.open_document("new", **creation)
                    else:
                        state = await service.open_document("load", path=str(private_input), defer_drawing=True)
                    snapshot = self._snapshot(service, state)
                    revision_before = service.revision
                    edit_engine = None
                    if edit is not None:
                        command = edit_request(edit, snapshot)
                        method = command.pop("method")
                        state = await service.current(method, edit=True, **command)
                        edit_engine = state["edit_engine"]
                    for kind, positions in (sections or {}).items():
                        state = await service.current("sections", edit=True, operation="add", kind=kind, positions=positions)
                    if edit is not None or sections:
                        snapshot = self._snapshot(service, state)

                    provenance = self._provenance(state, engine, identity)
                    changed = source is None or service.revision != revision_before
                    save_options = {}
                    if loading_book is not None:
                        settings = await self._loading_settings(service)
                        changed = changed or settings.get("loading_book") != loading_book or settings.get("use_loading_book") is not True
                        settings.update(loading_book=loading_book, use_loading_book=True)
                        settings.pop("gz_criteria", None)
                        save_options["calculation_drafts"] = {"hydro_cross": settings}
                    saved = await service.current("save", format="fbm", **save_options)
                    prepared = service.artifact_path(saved, "saved_file")
                    output_identity = file_identity(prepared)
                    self._check_save_receipt(saved, output_identity)

                    # Open the actual prepared bytes as a new document. IDs can change when an FBM is reopened.
                    reopened = await service.open_document("load", path=str(prepared), defer_drawing=True)
                    reopened_model = self._snapshot(service, reopened)
                    status = await service.current("document_status")
                    if status.get("fbm_sha256") != output_identity["sha256"]:
                        raise EngineError("FS26 reopened bytes differ from the save receipt")
                    if self._geometry(service, state, snapshot) != self._geometry(service, reopened, reopened_model):
                        raise EngineError("Control net or model settings changed during FBM save and reload")
                    if loading_book is not None:
                        restored = await self._loading_settings(service)
                        if restored.get("loading_book") != loading_book or restored.get("use_loading_book") is not True:
                            raise EngineError("Loading book was not retained in the reopened FBM")

                    result = {"ok": True, "output_path": str(target), "changed": changed, "reload_verified": True,
                              "model": self._summary(reopened_model)}
                    if edit_engine is not None:
                        result["edit_engine"] = edit_engine
                    if isinstance(edit, Lackenby):
                        result["lackenby_reference"] = await self._measure_lackenby(service)

                provenance["output_model"] = {**output_identity, "file_name": target.name}
                fd, temporary_output = tempfile.mkstemp(prefix=".freeship-", suffix=target.suffix, dir=target.parent)
                os.close(fd)
                staged = Path(temporary_output)
                pending_output.callback(staged.unlink, missing_ok=True)
                shutil.copyfile(prepared, staged)
                if file_identity(staged) != {**output_identity, "file_name": staged.name}:
                    raise EngineError("Staged FBM does not match the verified save")
            self._verify_inputs(source, identity, engine)
            if self.path(output_path, output=True, suffixes=(".fbm",)) != target:
                raise EngineError("Output location changed during the request")
            staged.rename(target)  # On Windows, this fails if another request created target.
        return {**result, "provenance": provenance}

    @asynccontextmanager
    async def _source(self, model_path: str, *, include_drawing: bool = False):
        model = self.path(model_path)
        engine = file_identity(self.executable)
        with tempfile.TemporaryDirectory(prefix="freeship-mcp-fs26-") as temporary:
            directory = Path(temporary).resolve()
            private_input, identity = self._copy_model(model, directory)
            async with run_document_service(self.executable, directory, self.timeout) as service:
                opened = await service.open_document("load", path=str(private_input), defer_drawing=not include_drawing)
                yield service, opened, self._provenance(opened, engine, identity)
        self._verify_inputs(model, identity, engine)

    @staticmethod
    def _copy_model(model: Path, directory: Path) -> tuple[Path, dict]:
        private_input = directory / ("input" + model.suffix.lower())
        with model.open("rb") as source:
            data = source.read(MAX_MODEL_BYTES + 1)
        if not data or len(data) > MAX_MODEL_BYTES:
            raise ValueError("Input model size must be between 1 byte and 256 MiB")
        private_input.write_bytes(data)
        return private_input, {"file_name": model.name, "sha256": sha256(data).hexdigest(), "size_bytes": len(data)}

    def _verify_inputs(self, model: Path | None, identity: dict | None, engine: dict):
        if model is not None and file_identity(model) != identity:
            raise EngineError("Input model changed during the FS26 request")
        if file_identity(self.executable) != engine:
            raise EngineError("FS26 executable changed during the request")

    @staticmethod
    def _provenance(response: dict, engine: dict, model: dict | None) -> dict:
        return {
            "backend": "fs26", "adapter_api_version": API_VERSION,
            "document_id": response["document_id"], "revision": response["revision"], "model": model, "engine": engine,
        }

    @staticmethod
    def _snapshot(service: DocumentService, response: dict) -> dict:
        snapshot = service.artifact_json(response, "model")
        if (snapshot.get("format") != "FreeShipModelSnapshot" or snapshot.get("version") != SNAPSHOT_VERSION
                or snapshot.get("units") not in {"metric", "imperial"}
                or not all(isinstance(snapshot.get(key), list) for key in (*CONTROL_NET, "layers", "sections"))
                or not all(isinstance(snapshot.get(key), dict) for key in ("settings", "bounds"))
                or not isinstance(snapshot.get("name"), str)):
            raise EngineError("Unsupported FS26 model snapshot schema")
        return snapshot

    @staticmethod
    def _summary(snapshot: dict) -> dict:
        keys = ("name", "units", "bounds", "settings", "layers")
        return {**{key: snapshot[key] for key in keys}, "counts": {key: len(snapshot[key]) for key in CONTROL_NET}}

    @staticmethod
    async def _measure_lackenby(service: DocumentService) -> dict:
        response = await service.current("inspect_modeling")
        values = response.get("analysis")
        if response.get("analysis_engine") != "cpp-lackenby" or not isinstance(values, dict):
            raise EngineError("Missing native Lackenby reference measurements")
        return values

    @staticmethod
    def _check_save_receipt(saved: dict, identity: dict):
        receipt = saved.get("save_receipt")
        if (not isinstance(receipt, dict) or receipt.get("version") != 1
                or receipt.get("document_id") != saved["document_id"] or receipt.get("revision") != saved["revision"]
                or receipt.get("bytes") != identity["size_bytes"] or receipt.get("sha256") != identity["sha256"]):
            raise EngineError("FS26 save receipt does not describe the prepared FBM")

    @staticmethod
    def _geometry(service: DocumentService, response: dict, model: dict) -> tuple:
        """Translate live IDs into FBM serialization order before comparing the control net."""
        bindings = service.artifact_json(response, "calculation_bindings")
        if bindings.get("format") != "FreeShipDocumentBindings" or bindings.get("version") != 1:
            raise EngineError("Unsupported FS26 document binding schema")
        try:
            groups = {}
            for key in ("points", "edges", "faces", "layers"):
                entities = model["layers" if key == "layers" else f"control_{key}"]
                by_id = {entity["id"]: entity for entity in entities}
                ids = bindings[key]
                if len(ids) != len(entities) or set(ids) != by_id.keys():
                    raise EngineError(f"FS26 has inconsistent {key} bindings")
                groups[key] = [by_id[entity_id] for entity_id in ids]

            point_index = {point["id"]: index for index, point in enumerate(groups["points"], start=1)}
            point_index[0] = 0
            layer_index = {layer["id"]: index for index, layer in enumerate(groups["layers"])}
            points = [(p["p"], p["locked"], p["vertex_type"], p.get("name", ""), p.get("hard_anchor", False),
                       tuple(point_index[p.get(key, 0)] for key in ("anchor", "line_a", "line_b")))
                      for p in groups["points"]]
            edges = [(sorted((point_index[e["a"]], point_index[e["b"]])), e["crease"]) for e in groups["edges"]]
            faces = [(layer_index[f["layer"]], [point_index[p] for p in f["points"]]) for f in groups["faces"]]
            layers = [{key: value for key, value in layer.items() if key != "id"} for layer in groups["layers"]]
        except (KeyError, TypeError) as exc:
            raise EngineError("Invalid FS26 control net bindings") from exc
        return model["units"], model["settings"], points, edges, faces, layers, model["sections"]
