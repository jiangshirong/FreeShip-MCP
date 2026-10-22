import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from freeship_mcp.engine import Engine, EngineError

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "src/freeship_mcp/bin/freeship-engine.exe"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def engine(tmp_path):
    shutil.copy2(ROOT / "examples/box.fbm", tmp_path / "箱体-Корпус.fbm")
    shutil.copy2(ROOT / "examples/synthetic-hull.fbm", tmp_path / "hull.fbm")
    return Engine(tmp_path)


def test_analytic_box(engine):
    h = run(engine.call("calculate_hydrostatics", "箱体-Корпус.fbm", draft_m=4))
    assert h["volume_geometry_m3"] == pytest.approx(20 * 6 * 4, rel=2e-6)
    assert h["lcb_ap_m"] == pytest.approx(10, abs=1e-4)
    assert h["vcb_m"] == pytest.approx(2, abs=1e-4)
    assert h["tcb_m"] == pytest.approx(0, abs=1e-6)
    assert h["waterplane_area_m2"] == pytest.approx(120, rel=1e-4)
    assert h["bm_transverse_m"] == pytest.approx(6**2 / (12 * 4), rel=1e-4)
    assert h["bm_longitudinal_m"] == pytest.approx(20**2 / (12 * 4), rel=1e-4)


def test_native_roundtrip_and_binary_identity(engine):
    original = engine.workspace / "箱体-Корпус.fbm"
    result = run(engine.call("save_model", original.name, output_path="identity.fbm"))
    assert result["byte_identical_native_roundtrip"]
    assert original.read_bytes() == (engine.workspace / "identity.fbm").read_bytes()
    for version in (335, 462):
        name = f"box-{version}.ftm"
        run(engine.call("save_model", original.name, output_path=name, output_version=version))
        run(engine.call("save_model", name, output_path=f"box-{version}.fbm"))
        for saved in (name, f"box-{version}.fbm"):
            h = run(engine.call("calculate_hydrostatics", saved, draft_m=4))
            assert h["volume_geometry_m3"] == pytest.approx(480, rel=2e-6)


def test_scale_invariants_and_layers(engine):
    run(engine.call("scale_model", "箱体-Корпус.fbm", output_path="scaled.fbm",
                    x_factor=2, y_factor=2, z_factor=2))
    h = run(engine.call("calculate_hydrostatics", "scaled.fbm", draft_m=8))
    assert h["volume_geometry_m3"] == pytest.approx(480 * 8, rel=2e-6)
    assert h["waterplane_area_m2"] == pytest.approx(120 * 4, rel=1e-4)
    assert h["bm_transverse_m"] == pytest.approx(1.5, rel=1e-4)
    info = run(engine.call("inspect_model", "scaled.fbm"))
    assert info["length_m"] == 40
    assert info["layers"][0]["faces"] == 4
    v = run(engine.call("validate_model", "scaled.fbm"))
    assert v["integrity"] and v["inconsistent_normal_edges"] == 0
    assert v["nonmanifold_edges"] == 0


def test_explicit_project_dimensions_after_scale(engine):
    run(engine.call("scale_model", "箱体-Корпус.fbm", output_path="settings.fbm",
                    x_factor=1.5, y_factor=1, z_factor=2,
                    project_length_m=20, project_beam_m=6, project_draft_m=4, x_offset_m=3))
    info = run(engine.call("inspect_model", "settings.fbm"))
    assert (info["length_m"], info["beam_m"], info["draft_m"]) == (20, 6, 4)
    h = run(engine.call("calculate_hydrostatics", "settings.fbm", draft_m=4))
    assert h["volume_geometry_m3"] == pytest.approx(30 * 6 * 4, rel=2e-6)
    assert h["lcb_ap_m"] == pytest.approx(18, abs=2e-4)
    assert h["waterline_min_m"][0] == pytest.approx(3, abs=2e-4)
    assert h["waterline_max_m"][0] == pytest.approx(33, abs=2e-4)


def test_appendage_and_imperial_conversion(engine):
    for imperial in (False, True):
        path = engine.workspace / f"units-{imperial}.fbm"
        run(engine.raw(dict(operation="create_box", output_path=str(path), appendage_coefficient=1.005,
                            imperial_storage=imperial)))
        h = run(engine.call("calculate_hydrostatics", path.name, draft_m=4))
        assert h["volume_geometry_m3"] == pytest.approx(480, rel=5e-6)
        assert h["volume_corrected_m3"] == pytest.approx(480 * 1.005, rel=5e-6)
        assert h["displacement_t"] == pytest.approx(480 * 1.005 * 1.025, rel=5e-6)


def test_dry_and_invalid_inputs(engine):
    h = run(engine.call("calculate_hydrostatics", "箱体-Корпус.fbm", draft_m=-1))
    assert h["no_immersion"] and h["displacement_t"] == 0
    (engine.workspace / "broken.fbm").write_bytes(b"not a model")
    with pytest.raises(EngineError):
        run(engine.call("inspect_model", "broken.fbm"))
    with pytest.raises(ValueError):
        engine.path("../outside.fbm", output=True)
    with pytest.raises(FileExistsError):
        engine.path("箱体-Корпус.fbm", output=True)


def test_lackenby_and_no_false_output(engine):
    h = run(engine.call("calculate_hydrostatics", "hull.fbm", draft_m=3))
    r = run(engine.call("rebuild_hull", "hull.fbm", output_path="rebuilt.fbm",
                        displacement_t=h["displacement_t"] * 1.01, lcb_ap_m=h["lcb_ap_m"],
                        layer_indices=[0], max_iterations=15))
    assert r["iterations"] <= 15
    assert r["sac_displacement_relative_residual"] <= 1e-4
    assert r["sac_lcb_length_relative_residual"] <= 5e-5
    reloaded = run(engine.call("calculate_hydrostatics", "rebuilt.fbm", draft_m=3))
    assert reloaded["displacement_t"] == r["hydrostatics"]["displacement_t"]
    assert abs(r["actual_displacement_residual_t"]) / h["displacement_t"] < 0.002
    with pytest.raises(EngineError):
        run(engine.call("rebuild_hull", "hull.fbm", output_path="failed.fbm",
                        displacement_t=h["displacement_t"] * 100, lcb_ap_m=20,
                        layer_indices=[0], max_iterations=1))
    assert not (engine.workspace / "failed.fbm").exists()
    assert not list(engine.workspace.glob(".freeship-*"))


def test_timeout_and_cancel_cleanup(engine):
    engine.timeout = 1e-6
    with pytest.raises(EngineError, match="exceeded"):
        run(engine.call("save_model", "hull.fbm", output_path="timeout.fbm"))
    assert not (engine.workspace / "timeout.fbm").exists()
    assert not list(engine.workspace.glob(".freeship-*"))

    async def cancel():
        engine.timeout = 120
        task = asyncio.create_task(engine.call("rebuild_hull", "hull.fbm", output_path="cancelled.fbm",
            displacement_t=500, lcb_ap_m=20, layer_indices=[0], max_iterations=200))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    run(cancel())
    assert not (engine.workspace / "cancelled.fbm").exists()
    assert not list(engine.workspace.glob(".freeship-*"))
