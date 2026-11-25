import asyncio
from hashlib import sha256
import json
from pathlib import Path
import shutil

import ezdxf
import pytest

from test_fs26 import ROOT, call, fs26_service, fs26_session
from test_fs26_analysis import FUNG_SPEEDS, MATCH_PARAMS


def sample_brief(seed_sha256):
    return {
        "title": "40 m workboat preliminary study",
        "vessel_type": "Displacement workboat",
        "seed_model_sha256": seed_sha256,
        "variants": [
            {"name": "baseline"},
            {"name": "widened", "edit": {"action": "move_points", "moves": [
                {"point_id": 31, "position": [20, 2.85, 0]},
            ]}},
        ],
        "loading_book": {
            "shared_items": [{"kind": "fixed", "name": "Lightship", "mass": 400, "x": 20, "y": 0, "z": 2.1}],
            "cases": [
                {"name": "Design load", "items": [{"kind": "fixed", "name": "Cargo", "mass": 60, "x": 20, "y": 0, "z": 2.6}]},
                {"name": "Reduced load", "items": [{"kind": "fixed", "name": "Cargo", "mass": 30, "x": 20.15, "y": 0, "z": 2.6}]},
            ],
            "criteria": [[20, .15], [30, .25]],
        },
        "heel_angles_degrees": [0, 10, 20, 30],
        "performance_case": "Design load",
        "speeds": FUNG_SPEEDS,
        "resistance_values": {
            "NpBox": 1, "DpBox": 3, "FungWake": .1, "FungDeduction": .1, "FungEtaR": 1,
            "FungTransomDraftRatio": 0,
        },
        "propeller_values": MATCH_PARAMS,
        "drawing_sections": {
            "stations_m": [x for x in range(4, 40, 4)], "waterlines_m": [1, 2, 3, 4], "buttocks_m": [1, 2, 3],
        },
        "acceptance": {
            "max_upright_immersion_m": 3.08, "max_performance_trim_m": .05, "max_performance_upright_gz_m": .005,
            "max_design_resistance_kn": 12.55, "min_matched_speed_kn": 9,
        },
    }


def test_fs26_design_brief_selects_and_publishes_consistent_artifacts(tmp_path, fs26_service):
    seed = tmp_path / "input.fbm"
    shutil.copyfile(ROOT / "examples" / "synthetic-hull.fbm", seed)
    seed_sha256 = sha256(seed.read_bytes()).hexdigest()
    brief = sample_brief(seed_sha256)
    brief["variants"].append({"name": "invalid", "edit": {"action": "split_edge", "edge_id": 9999}})

    async def workflow():
        async with fs26_session(tmp_path, fs26_service) as client:
            delivery = await call(client, "run_design_brief", model_path=seed.name, output_directory="study", brief=brief)
            assert delivery["status"] == "selected" and delivery["selected"] == "widened"
            folder = Path(delivery["output_directory"])
            files = delivery["files"]
            assessment = json.loads((folder / files["assessment"]).read_bytes())
            a, b, c = assessment["candidates"]
            assert [a["status"], b["status"], c["status"]] == ["fail", "pass", "blocked"]
            reasons = [x["name"] for x in a["checks"] if x["status"] != "pass"]
            assert reasons == ["design_resistance"]
            assert c["blocked_stage"] == "model"
            assert a["stability"]["successful_rows"] == b["stability"]["successful_rows"] == 8
            assert b["performance"]["resistance"]["effective_values"]["DraftTotalBox"] == pytest.approx(
                b["performance_condition"]["draft_m"], abs=1e-6)
            assert assessment["basis"] == "preliminary_design_brief"
            drawing = folder / files["selected_drawing"]
            assert assessment["drawing"]["sha256"] == sha256(drawing.read_bytes()).hexdigest()
            doc = ezdxf.readfile(drawing, encoding="utf-8")
            assert not doc.audit().has_errors
            assert {e.dxf.layer for e in doc.modelspace().query("POLYLINE")} >= {"stations", "waterlines", "buttocks"}
            model_sha256 = sha256((folder / files["selected_model"]).read_bytes()).hexdigest()
            for evidence in (b["stability"], b["performance"], assessment["drawing"]):
                assert evidence["provenance"]["model"]["sha256"] == model_sha256
            assert sha256((folder / assessment["seed"]["file_name"]).read_bytes()).hexdigest() == seed_sha256
            assert sha256(seed.read_bytes()).hexdigest() == seed_sha256
            retry = await client.call_tool("run_design_brief", {
                "model_path": seed.name, "output_directory": "study", "brief": brief,
            })
            assert retry.is_error
            stale = await client.call_tool("run_design_brief", {
                "model_path": seed.name, "output_directory": "stale", "brief": {**brief, "seed_model_sha256": "0" * 64},
            })
            assert stale.is_error and not (tmp_path / "stale").exists()
            assert not list(tmp_path.glob(".freeship-design-*"))

    asyncio.run(workflow())
