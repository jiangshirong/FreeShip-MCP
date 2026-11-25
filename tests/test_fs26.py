import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys

import ezdxf
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest
from freeship_mcp.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fs26_service():
    service = os.environ.get("FREESHIP_MCP_TEST_FS26_SERVICE")
    if not service:
        pytest.skip("Set FREESHIP_MCP_TEST_FS26_SERVICE to the native FS26 document service")
    return service


@asynccontextmanager
async def fs26_session(workspace, service):
    params = StdioServerParameters(command=sys.executable, args=[
        "-m", "freeship_mcp.server", "--workspace", str(workspace), "--fs26-service", service,
    ])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            yield client


async def call(client, name, **arguments):
    result = await client.call_tool(name, arguments)
    assert not result.is_error, result
    return json.loads(result.content[0].text)


def model_sha(snapshot):
    return snapshot["provenance"]["model"]["sha256"]


async def create_sample(client, filename):
    return await call(client, "create_hull", output_path=filename, length=20, beam=5, draft=1.6, columns=7, rows=5)


def test_fs26_stdio_model_reads(tmp_path, fs26_service):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model = workspace / "\u7bb1\u4f53.fbm"
    shutil.copyfile(ROOT / "examples/box.fbm", model)
    shutil.copyfile(model, tmp_path / "outside.fbm")
    (workspace / "invalid.fbm").write_bytes(b"invalid FreeShip model")
    legacy = Engine(workspace)
    asyncio.run(legacy.call("save_model", model.name, output_path="box.ftm", output_version=335))
    asyncio.run(legacy.raw({
        "operation": "create_box", "output_path": str(workspace / "imperial.fbm"), "imperial_storage": True,
    }))
    files_before = {path.name: path.read_bytes() for path in workspace.iterdir()}
    async def workflow():
        async with fs26_session(workspace, fs26_service) as client:
            tools = await client.list_tools()
            expected_tools = {
                "engine_info", "inspect_model", "validate_model", "calculate_hydrostatics",
                "create_hull", "edit_control_net", "save_model", "rebuild_hull", "export_linesplan_dxf",
                "inspect_loading_book", "save_loading_book", "calculate_stability",
                "inspect_performance_inputs", "calculate_performance", "calculate_propulsion_chain", "compare_resistance",
                "run_design_brief",
            }
            assert {tool.name for tool in tools.tools} == expected_tools
            info = await call(client, "engine_info")
            assert info["backend"] == "fs26"
            assert not info["read_only"]
            assert info["adapter_api_version"] == 1
            assert set(info["tools"]) == expected_tools

            summary = await call(client, "inspect_model", model_path=model.name)
            assert summary["units"] == "metric"
            assert "control_points" not in summary
            snapshot = await call(client, "inspect_model", model_path=model.name, include_control_net=True)
            assert len(snapshot["control_points"]) == summary["counts"]["control_points"] > 0
            checked = await call(client, "validate_model", model_path=model.name)
            assert checked["loaded"]
            assert checked["native_document"]["version_name"] == "4.6.2"

            hydrostatics = await call(client, "calculate_hydrostatics", model_path=model.name, draft=4)
            assert hydrostatics["engine"] == "cpp-hydrostatics"
            row, = hydrostatics["rows"]
            assert row["volume"] == pytest.approx(20 * 6 * 4, rel=2e-6)
            assert row["waterplane_area"] == pytest.approx(20 * 6, rel=1e-4)
            assert row["buoyancy"] == pytest.approx([10, 0, 2], abs=1e-4)
            assert hydrostatics["provenance"]["model"] == summary["provenance"]["model"]
            assert hydrostatics["provenance"]["engine"] == info["engine"]

            text_model = await call(client, "calculate_hydrostatics", model_path="box.ftm", draft=4)
            assert text_model["rows"][0]["volume"] == pytest.approx(480, rel=2e-6)
            imperial = await call(client, "calculate_hydrostatics", model_path="imperial.fbm", draft=4 / 0.3048)
            assert imperial["units"] == "imperial"
            assert imperial["rows"][0]["volume"] * 0.3048**3 == pytest.approx(480, rel=2e-6)

            for name, arguments in [
                ("inspect_model", {"model_path": "../outside.fbm"}),
                ("validate_model", {"model_path": "invalid.fbm"}),
                ("calculate_hydrostatics", {"model_path": model.name, "draft": 0}),
            ]:
                result = await client.call_tool(name, arguments)
                assert result.is_error, result
            converted = await call(client, "save_model", model_path="box.ftm", output_path="converted.fbm",
                                   expected_model_sha256=model_sha(text_model))
            assert converted["reload_verified"]
            reopened = await call(client, "calculate_hydrostatics", model_path="converted.fbm", draft=4)
            assert reopened["rows"][0]["volume"] == pytest.approx(480, rel=2e-6)

    asyncio.run(workflow())
    assert {path.name for path in workspace.iterdir()} == {*files_before, "converted.fbm"}
    assert all((workspace / filename).read_bytes() == content for filename, content in files_before.items())


def test_fs26_stdio_hull_edit_calculation_and_export(tmp_path, fs26_service):
    async def workflow():
        async with fs26_session(tmp_path, fs26_service) as client:
            created = await create_sample(client, "hull.fbm")
            assert created["reload_verified"]
            original = (tmp_path / "hull.fbm").read_bytes()
            before = await call(client, "inspect_model", model_path="hull.fbm",
                                include_control_net=True, include_lackenby_reference=True)
            assert before["counts"] == {"control_points": 35, "control_edges": 58, "control_faces": 24}
            assert created["provenance"]["output_model"]["sha256"] == model_sha(before)
            point = next(p for p in before["control_points"] if p["id"] == 11)
            x, y, z = point["p"]
            move = {"action": "move_points", "moves": [{"point_id": point["id"], "position": [x, y + .2, z]}]}
            edited = await call(client, "edit_control_net", model_path="hull.fbm", output_path="widened.fbm",
                                expected_model_sha256=model_sha(before), edit=move)
            assert edited["reload_verified"] and edited["changed"]
            assert edited["provenance"]["revision"] == 2
            assert edited["edit_engine"] == "cpp-points"
            after = await call(client, "inspect_model", model_path="widened.fbm", include_control_net=True)
            assert after["counts"] == before["counts"]
            for previous, current in zip(before["control_points"], after["control_points"]):
                assert current["id"] == previous["id"]
                expected = [x, y + .2, z] if current["id"] == point["id"] else previous["p"]
                assert current["p"] == pytest.approx(expected, abs=2e-7)
            assert after["control_edges"] == before["control_edges"]
            assert after["control_faces"] == before["control_faces"]
            assert model_sha(after) == edited["provenance"]["output_model"]["sha256"]

            async def measure(name):
                statics = await call(client, "calculate_hydrostatics", model_path=f"{name}.fbm", draft=1.6)
                exported = await call(client, "export_linesplan_dxf", model_path=f"{name}.fbm", output_path=f"{name}.dxf")
                path = tmp_path / f"{name}.dxf"
                manifest = json.loads((tmp_path / f"{name}.dxf.manifest.json").read_bytes())
                assert exported["provenance"]["model"] == statics["provenance"]["model"]
                assert manifest["provenance"]["export"]["engine"] == "cpp-native"
                assert manifest["artifact"]["sha256"] == sha256(path.read_bytes()).hexdigest()
                drawing = ezdxf.readfile(path, encoding="utf-8")
                assert not drawing.audit().has_errors
                sections = [list(polyline.points()) for polyline in drawing.modelspace().query('POLYLINE[layer=="stations"]')]
                assert sections
                return statics["rows"][0], sections

            start, sections_before = await measure("hull")
            widened, sections_after = await measure("widened")
            assert len(sections_before) == len(sections_after)
            assert sections_after != sections_before
            assert widened["volume"] > start["volume"]
            assert widened["waterplane_area"] > start["waterplane_area"]

            baseline = before["lackenby_reference"]
            target = baseline["displacement"] * 1.01
            rebuilt = await call(client, "rebuild_hull", model_path="hull.fbm", output_path="transformed.fbm",
                                 expected_model_sha256=model_sha(before), displacement=target, lcb=baseline["lcb"],
                                 layer_ids=[layer["id"] for layer in before["layers"]])
            assert rebuilt["edit_engine"] == "cpp-lackenby" and rebuilt["reload_verified"]
            assert rebuilt["lackenby_reference"]["displacement"] == pytest.approx(target, rel=1e-4)
            assert rebuilt["lackenby_reference"]["lcb"] == pytest.approx(baseline["lcb"], abs=.002)

            stale = await client.call_tool("edit_control_net", {
                "model_path": "widened.fbm", "output_path": "stale.fbm", "expected_model_sha256": model_sha(before),
                "edit": move,
            })
            assert stale.is_error and "hash mismatch" in stale.content[0].text
            assert not (tmp_path / "stale.fbm").exists()

            def save_copy():
                return client.call_tool("save_model", {
                    "model_path": "hull.fbm", "output_path": "copy.fbm", "expected_model_sha256": model_sha(before),
                })
            results = await asyncio.gather(save_copy(), save_copy())
            assert sum(result.is_error for result in results) == 1
            assert (tmp_path / "copy.fbm").read_bytes() == original
            assert (tmp_path / "hull.fbm").read_bytes() == original
            assert not list(tmp_path.glob(".freeship-*"))

    asyncio.run(workflow())


def test_fs26_stdio_topology_and_fairing(tmp_path, fs26_service):
    async def workflow():
        async with fs26_session(tmp_path, fs26_service) as client:
            await create_sample(client, "seed.fbm")

            async def inspect(filename):
                return await call(client, "inspect_model", model_path=filename, include_control_net=True)

            seed = await inspect("seed.fbm")

            async def edit(filename, arguments, model="seed.fbm", snapshot=seed):
                result = await call(client, "edit_control_net", model_path=model, output_path=filename,
                                    expected_model_sha256=model_sha(snapshot), edit=arguments)
                assert result["changed"] and result["reload_verified"]
                return await inspect(filename)

            points = {p["id"]: p["p"] for p in seed["control_points"]}
            with_point = await edit("point.fbm", {"action": "add_point", "position": [10, 1, 3]})
            assert with_point["counts"]["control_points"] == len(points) + 1
            assert any(p["p"] == [10, 1, 3] for p in with_point["control_points"] if p["id"] not in points)
            faired = await edit("fair.fbm", {"action": "relax_points", "point_ids": [11], "relaxation": .25})
            assert next(p["p"] for p in faired["control_points"] if p["id"] == 11) != points[11]
            assert {p["id"]: p["p"] for p in faired["control_points"] if p["id"] != 11} == {
                point_id: pos for point_id, pos in points.items() if point_id != 11
            }
            edge = next(edge for edge in seed["control_edges"] if not edge["crease"] and 11 in (edge["a"], edge["b"]))
            split = await edit("split-edge.fbm", {"action": "split_edge", "edge_id": edge["id"]})
            added = next(p for p in split["control_points"] if p["id"] not in points)
            assert added["p"] == pytest.approx([(a + b) / 2 for a, b in zip(points[edge["a"]], points[edge["b"]])])
            assert split["counts"]["control_faces"] == seed["counts"]["control_faces"]
            crease = await edit("crease.fbm", {"action": "set_edge_crease", "edge_id": edge["id"], "crease": True})
            assert next(e for e in crease["control_edges"] if e["id"] == edge["id"])["crease"]
            no_op = await call(client, "edit_control_net", model_path="crease.fbm", output_path="same-crease.fbm",
                               expected_model_sha256=model_sha(crease),
                               edit={"action": "set_edge_crease", "edge_id": edge["id"], "crease": True})
            assert not no_op["changed"] and no_op["provenance"]["revision"] == 1
            assert (tmp_path / "same-crease.fbm").read_bytes() == (tmp_path / "crease.fbm").read_bytes()

            face = seed["control_faces"][8]
            divided = await edit("split-face.fbm", {"action": "split_face", "face_id": face["id"],
                                                   "point_ids": face["points"][::2]})
            assert divided["counts"]["control_faces"] == seed["counts"]["control_faces"] + 1
            removed = await edit("deleted.fbm", {"action": "delete_face", "face_id": face["id"]})
            assert removed["counts"]["control_faces"] == seed["counts"]["control_faces"] - 1
            by_position = {tuple(p["p"]): p["id"] for p in removed["control_points"]}
            restored = await edit("restored.fbm", {"action": "add_face", "layer_id": removed["layers"][0]["id"],
                                                  "ids": [by_position[tuple(points[p])] for p in face["points"]]},
                                  model="deleted.fbm", snapshot=removed)
            assert restored["counts"]["control_faces"] == seed["counts"]["control_faces"]

            for invalid in [
                {"action": "relax_points", "point_ids": [1], "relaxation": .25},
                {"action": "split_edge", "edge_id": 999},
                {"action": "add_face", "layer_id": face["layer"], "ids": face["points"]},
            ]:
                failure = await client.call_tool("edit_control_net", {
                    "model_path": "seed.fbm", "output_path": "rejected.fbm", "expected_model_sha256": model_sha(seed),
                    "edit": invalid,
                })
                assert failure.is_error, failure
                assert not (tmp_path / "rejected.fbm").exists()

    asyncio.run(workflow())
