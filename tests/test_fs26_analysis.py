import asyncio
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

from freeship_mcp.fs26 import FS26Engine
from test_fs26 import ROOT, call, create_sample, fs26_service, fs26_session, model_sha


def loading_example():
    tank = {"kind": "tanks", "name": "Water", "x": 10, "y": 0, "z": .5,
            "length": 2, "width": 1, "height": 1, "fill": 50, "density": 1}
    return {
        "shared_items": [{"kind": "fixed", "name": "Lightship", "mass": 36, "x": 9.52, "y": 0, "z": 1.5}],
        "cases": [
            {"name": name, "items": [{"kind": "fixed", "name": "Engine", "mass": 1, "x": x, "y": 0, "z": 1.15}, tank]}
            for name, x in (("Baseline", 8), ("Shifted", 7.2))
        ],
        "criteria": [[20, .1]],
    }


def test_fs26_workbook_roundtrip_and_intact_stability(tmp_path, fs26_service):
    async def workflow():
        async with fs26_session(tmp_path, fs26_service) as client:
            created = await create_sample(client, "hull.fbm")
            original = (tmp_path / "hull.fbm").read_bytes()
            before = await call(client, "inspect_model", model_path="hull.fbm", include_control_net=True)
            assert (await call(client, "inspect_loading_book", model_path="hull.fbm"))["loading_book"] is None
            book = loading_example()
            result = await call(client, "save_loading_book", model_path="hull.fbm", output_path="loaded.fbm",
                                expected_model_sha256=created["provenance"]["output_model"]["sha256"], loading_book=book)
            assert result["reload_verified"] and result["changed"]
            saved = await call(client, "inspect_loading_book", model_path="loaded.fbm")
            assert saved["uses_loading_book"]
            assert saved["loading_book"] == {
                "version": 4, "shared_items": book["shared_items"], "criteria": book["criteria"],
                "cases": [[case["name"], case["items"]] for case in book["cases"]],
            }
            after = await call(client, "inspect_model", model_path="loaded.fbm", include_control_net=True)
            for key in ("settings", "control_points", "control_edges", "control_faces"):
                assert before[key] == after[key]
            params = dict(heel_angles_degrees=[0, 10, 30], free_trim=True)
            report = await call(client, "calculate_stability", model_path="loaded.fbm", **params)
            assert report["status"] == "complete" and report["successful_rows"] == 8
            assert report["provenance"]["model"]["sha256"] == model_sha(after)
            rows = {(row["case_name"], row["heel"]): row for row in report["rows"]}
            a, b = rows["Baseline", 0], rows["Shifted", 0]
            assert a["target_displacement"] == b["target_displacement"] == 38
            assert a["displacement"] == pytest.approx(38, abs=.001)
            assert b["displacement"] == pytest.approx(38, abs=.001)
            assert a["lcg"] == pytest.approx((36 * 9.52 + 8 + 10) / 38)
            assert a["vcg"] == pytest.approx((36 * 1.5 + 1.15 + .75) / 38)
            assert (b["lcg"] - a["lcg"]) * 38 == pytest.approx(-.8)
            assert a["gg0"] == pytest.approx((2 * 1**3 / 12) / 38)
            assert b["trim"] != a["trim"]
            assert rows["Baseline", 20]["gz_margin"] == pytest.approx(rows["Baseline", 20]["gz"] - .1)
            assert rows["Baseline", 30]["gz"] != rows["Shifted", 30]["gz"]

            engine = FS26Engine(tmp_path, Path(fs26_service))
            async with engine._source("loaded.fbm") as (service, _, __):
                response = await service.current(
                    "hydrostatics", mode="cross", angles=params["heel_angles_degrees"], trim=0,
                    free_trim=True, use_loading_book=True, loading_book=saved["loading_book"],
                )
                assert service.artifact_json(response, "hydro")["rows"] == report["rows"]

            invalid = deepcopy(book)
            invalid["cases"][0]["items"][1]["fill"] = 101
            error = await client.call_tool("save_loading_book", {
                "model_path": "hull.fbm", "output_path": "invalid.fbm",
                "expected_model_sha256": model_sha(before), "loading_book": invalid,
            })
            assert error.is_error and not (tmp_path / "invalid.fbm").exists()
            impossible = deepcopy(book)
            impossible["cases"][1]["items"][0]["mass"] = 10000
            partial = await call(client, "calculate_stability", model_path="hull.fbm", loading_book=impossible,
                                 **params)
            assert partial["status"] == "partial" and partial["failed_rows"] == 4
            assert all(row.get("message") and "gz" not in row
                       for row in partial["rows"] if row["status"] == "error")
            assert (tmp_path / "hull.fbm").read_bytes() == original

    asyncio.run(workflow())


FUNG_SPEEDS = {"start_kn": 6, "design_kn": 8, "end_kn": 10}
FUNG_PARAMS = {"NpBox": 1, "DpBox": 3}
MATCH_PARAMS = {"Edit2": 130, "Edit3": 200, "Edit12": 1, "Edit13": 4, "Edit14": .6}


async def prepare_performance_hulls(client, directory):
    shutil.copyfile(ROOT / "examples" / "synthetic-hull.fbm", directory / "reference.fbm")
    model = await call(client, "inspect_model", model_path="reference.fbm", include_control_net=True)
    point = min((p for p in model["control_points"] if p["batch_movable"] and p["p"][1] > 0 and p["p"][2] < 3),
                key=lambda p: abs(p["p"][0] - 20))
    x, y, z = point["p"]
    return await call(client, "edit_control_net", model_path="reference.fbm", output_path="variant.fbm",
                      expected_model_sha256=model_sha(model), edit={
                          "action": "move_points", "moves": [{"point_id": point["id"], "position": [x, y + .05, z]}],
                      })


def test_fs26_resistance_comparison_and_propulsion_chain(tmp_path, fs26_service):
    async def workflow():
        async with fs26_session(tmp_path, fs26_service) as client:
            edited = await prepare_performance_hulls(client, tmp_path)
            schema = await call(client, "inspect_performance_inputs", model_path="reference.fbm",
                                calculator="fung", extract=True)
            assert schema["effective_values"]["LwlBox"] > 39
            comparison = await call(client, "compare_resistance", baseline_path="reference.fbm",
                                    candidate_path="variant.fbm", calculator="fung",
                                    speeds=FUNG_SPEEDS, values=FUNG_PARAMS)
            baseline, variant = (comparison[key] for key in ("baseline", "candidate"))
            assert model_sha(baseline) != model_sha(variant) == edited["provenance"]["output_model"]["sha256"]
            ref, other = (item["result"]["design"] for item in (baseline, variant))
            assert ref["knots"] == other["knots"] == 8
            assert ref["total_kn"] == pytest.approx(12.65313, abs=.0001)
            assert ref["total_kn"] != other["total_kn"]
            assert comparison["candidate_minus_baseline"]["total_kn"] == pytest.approx(other["total_kn"] - ref["total_kn"])
            assert ref["power_kw"] == pytest.approx(ref["total_kn"] * 8 * 1852 / 3600)

            chain = await call(client, "calculate_propulsion_chain", model_path="reference.fbm", resistance="fung",
                               speeds=FUNG_SPEEDS, resistance_values=FUNG_PARAMS, propeller_values=MATCH_PARAMS)
            assert chain["resistance"]["result"]["design"] == ref
            design = chain["propeller_design"]["result"]
            matched = design["matched"]
            assert 0 < matched["diameter_m"] <= FUNG_PARAMS["DpBox"]
            assert abs(matched["thrust_residual_kn"]) < 1e-5
            assert matched["rpm"] == MATCH_PARAMS["Edit3"]
            assert design["table_limited"] is False
            assert FUNG_SPEEDS["start_kn"] < matched["speed_kn"] < FUNG_SPEEDS["end_kn"]
            assert matched["engine_power_kw"] == pytest.approx(MATCH_PARAMS["Edit2"], abs=1e-5)
            passport = chain["propulsion_passport"]["result"]
            assert passport["points"] and passport["extrapolated"] is False
            assert model_sha(chain) == model_sha(baseline)

            await create_sample(client, "out-of-domain.fbm")
            invalid = await client.call_tool("compare_resistance", {
                "baseline_path": "reference.fbm", "candidate_path": "out-of-domain.fbm", "calculator": "fung",
                "speeds": FUNG_SPEEDS, "values": FUNG_PARAMS,
            })
            assert invalid.is_error

    asyncio.run(workflow())


@pytest.mark.parametrize("calculator,values,expected", [
    ("oortmerssen", {
        "StartSpeedBox": 3, "EndSpeedBox": 13, "StepSpeedBox": 14, "LwlBox": 30.5, "OortLpp": 27.5,
        "BwlBox": 29 / 3.45, "DraftTotalBox": (29 / 3.45) / 2.85, "DraftBox": 0, "DisplacementBox": 376,
        "WettedSurfacebox": 284, "CpBox": .609 * 29 / 30.5, "LCBBox": (-.0255 * 29 + .75) / 30.5 * 100,
        "KBulbBox": 23, "DensityBox": 1.025, "ViscosityBox": 1.18831, "KeBox": 1, "OortCorrelation": .00051,
    }, "design"),
    ("hollenbach", {
        "StartSpeedBox": 11, "EndSpeedBox": 16, "StepSpeedBox": 18, "HolCondition": 0, "HolBulb": 0,
        "HolLpp": 120, "LwlBox": 123, "Losbox": 126, "BwlBox": 20, "DraftTotalBox": 6.5, "DraftBox": 0,
        "DisplacementBox": 10608, "DpBox": 4.5, "WettedSurfacebox": 2800, "DensityBox": 1.025, "ViscosityBox": 1.189,
    }, "design"),
    ("propeller5", {"ComboBox1": 0, "Edit2": 200, "Edit3": .7, "Edit4": 1, "Edit5": 4, "Edit6": 3, "Edit7": 4}, "working"),
    ("propeller1", {
        "Edit2": 10, "Edit3": 30, "Edit4": 1, "Edit5": 3, "Edit6": .1, "Edit7": 1025, "Edit8": .1, "Edit9": .1,
        "Edit10": 1, "Edit11": 1, "Edit12": .98, "Edit13": .98, "Edit14": 1, "Edit15": 4, "Edit16": .6,
    }, "candidates"),
])
def test_fs26_additional_native_performance_methods(tmp_path, fs26_service, calculator, values, expected):
    shutil.copyfile(ROOT / "examples" / "synthetic-hull.fbm", tmp_path / "hull.fbm")

    async def workflow():
        async with fs26_session(tmp_path, fs26_service) as client:
            report = await call(client, "calculate_performance", model_path="hull.fbm",
                                calculator=calculator, values=values)
            result = report["result"][expected]
            if calculator == "propeller5":
                assert result["j"] == pytest.approx(.4)
                assert 0 < result["efficiency"] < 1
            elif calculator == "propeller1":
                assert len(result) == 5 and result[0]["requested_diameter_m"] == 3
                solutions = [item["solution"] for item in result if item["solution"] is not None]
                assert solutions and all(abs(item["thrust_residual_kn"]) < 1e-5 for item in solutions)
            else:
                assert result["knots"] == values["EndSpeedBox"]
                assert result["total_kn"] > 0

    asyncio.run(workflow())
