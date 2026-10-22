import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
import pytest
from freeship_mcp.engine import Engine
from freeship_mcp.engine import positions

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("example_source", ROOT/"scripts/create_examples.py")
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


def test_translation_symmetry_and_native_reload(tmp_path):
    async def check():
        engine = Engine(tmp_path)
        request = examples.hull_request(tmp_path/"original.fbm")
        await engine.raw(request)
        original = await engine.call("calculate_hydrostatics", "original.fbm", draft_m=3)
        request["output_path"] = str(tmp_path/"translated.fbm")
        request["points_m"] = [[x+7,y,z+5] for x,y,z in request["points_m"]]
        await engine.raw(request)
        moved = await engine.call("calculate_hydrostatics", "translated.fbm", draft_m=3)
        assert moved["volume_geometry_m3"] == pytest.approx(original["volume_geometry_m3"], rel=2e-5)
        assert moved["lcb_ap_m"] == pytest.approx(original["lcb_ap_m"]+7, abs=2e-4)
        assert moved["vcb_m"] == pytest.approx(original["vcb_m"], abs=2e-4)
        assert moved["keel_model_z_m"] == pytest.approx(original["keel_model_z_m"]+5, abs=2e-4)
        assert moved["tcb_m"] == pytest.approx(0, abs=1e-6)
        assert moved["waterplane_area_m2"] == pytest.approx(original["waterplane_area_m2"], rel=2e-5)
        await engine.call("generate_sections", "original.fbm", output_path="sections.fbm",
            stations_m=[4,8,12,16,20,24,28,32,36], waterlines_m=[1,2,3], buttocks_m=[1,2])
        geometry = await engine.call("linesplan_geometry", "sections.fbm")
        assert len({c["section_index"] for c in geometry["curves"] if c["kind"]=="station"}) == 9
        # Add-existing is idempotent and retains no duplicate native section positions.
        result = await engine.call("generate_sections", "sections.fbm", output_path="sections-2.fbm",
            stations_m=[4,8,12,16,20,24,28,32,36], waterlines_m=[1,2,3], buttocks_m=[1,2], replace_existing=False)
        assert result["stations"]==9 and result["waterlines"]==3 and result["buttocks"]==2
    asyncio.run(check())


def test_progress_is_intermediate_and_monotone(tmp_path):
    async def check():
        engine = Engine(tmp_path)
        await engine.raw(dict(operation="create_box",output_path=str(tmp_path/"box.fbm")))
        progress = []
        async def report(value, message):
            progress.append((value, message))
        await engine.call("calculate_hydrostatics_series","box.fbm",drafts_m=[1,2,3,4],progress=report)
        assert progress[0][0]==0 and progress[-1][0]==1
        assert any(0<value<1 for value,_ in progress)
        assert sorted(value for value,_ in progress)==[value for value,_ in progress]
    asyncio.run(check())


def test_original_numerical_sources():
    subprocess.run([sys.executable, str(ROOT/"scripts/verify_upstream.py")],check=True)
    original = (ROOT/"vendor/freeship/Forms/FreeLackenbyDlg.pas").read_text(encoding="utf-8-sig")
    adapter = (ROOT/"engine/HeadlessLackenby.pas").read_text(encoding="utf-8")
    # Numerical integration and point-transform expressions remain literal upstream
    # method bodies; only the enclosing UI bindings and drawing scale differ.
    for start, end in (("  procedure InitializeData", "  end;{InitializeData}"),
                       ("          // Make all data dimensionless", "          Modified := True;")):
        expected = original[original.index(start):original.index(end,original.index(start))+len(end)]
        actual = adapter[adapter.index(start):adapter.index(end,adapter.index(start))+len(end)]
        assert actual == expected


def test_explicit_range_semantics():
    assert positions(None,[0,10,1],"drafts")==list(range(11))
    assert positions(None,[0,2.5,1],"drafts")==[0,1,2]
    with pytest.raises(ValueError): positions([0,1],[0,1,1],"drafts")
    with pytest.raises(ValueError): positions(None,[0,1,0],"drafts")
    with pytest.raises(ValueError): positions(None,[0,10000,1],"drafts")
