import asyncio
from pathlib import Path
import shutil
import pytest
from freeship_mcp.engine import Engine,EngineError

ROOT=Path(__file__).resolve().parents[1]
def run(coro):return asyncio.run(coro)
@pytest.fixture
def engine(tmp_path):
    for name in ['box.fbm','synthetic-hull.fbm']:shutil.copy2(ROOT/'examples'/name,tmp_path/name)
    return Engine(tmp_path)

@pytest.mark.parametrize('operation',['save_model','scale_model','edit_control_net','generate_sections','rebuild_hull'])
def test_default_fv335_and_exact_filename(engine,operation):
    source='box.fbm';params={}
    if operation=='scale_model':params=dict(x_factor=1,y_factor=1,z_factor=1)
    elif operation=='edit_control_net':
        info=run(engine.call('inspect_model',source,include_control_net=True))
        params=dict(expected_model_sha256=info['provenance']['model']['sha256'],edit=dict(action='move_points',points=[{'index':0,'x_m':-.01}]))
    elif operation=='generate_sections':params=dict(stations_m=[5,10,15])
    elif operation=='rebuild_hull':
        source='synthetic-hull.fbm';h=run(engine.call('calculate_hydrostatics',source,draft_m=3))
        params=dict(displacement_t=h['displacement_t']*1.01,lcb_ap_m=h['lcb_ap_m'],layer_indices=[0],max_iterations=15)
    result=run(engine.call(operation,source,output_path='chosen.fbm',**params))
    assert result['output_format_version']=='fv335'
    assert Path(result['output_path']).name=='chosen.fbm'
    assert run(engine.call('inspect_model','chosen.fbm'))['format_version']=='fv335'
    assert not list(engine.workspace.glob('*fv335*'))

@pytest.mark.parametrize('version,expected',[(0,'fv462'),(335,'fv335'),(462,'fv462')])
def test_output_version_override(engine,version,expected):
    result=run(engine.call('save_model','box.fbm',output_path='output.fbm',output_version=version))
    assert result['output_format_version']==expected
    h=run(engine.call('calculate_hydrostatics','output.fbm',draft_m=4))
    assert h['volume_geometry_m3']==pytest.approx(480,rel=2e-6)
    if version==0:assert result['byte_identical_native_roundtrip']


def test_native_default_and_incompatible_downgrade(engine):
    run(engine.raw(dict(operation='save_model',model_path=str(engine.workspace/'box.fbm'),output_path=str(engine.workspace/'native.fbm'))))
    assert run(engine.call('inspect_model','native.fbm'))['format_version']=='fv335'
    run(engine.raw(dict(operation='create_mesh',output_path=str(engine.workspace/'named.fbm'),
        points_m=[[0,0,0],[2,0,0],[2,2,0],[0,2,0]],faces=[[0,1,2,3]],point_names=['named point','','',''],
        length_m=2,beam_m=4,draft_m=1)))
    with pytest.raises(EngineError,match='cannot represent'):
        run(engine.call('save_model','named.fbm',output_path='rejected.fbm'))
    assert not (engine.workspace/'rejected.fbm').exists()
    result=run(engine.call('save_model','named.fbm',output_path='preserved.fbm',output_version=0))
    assert result['byte_identical_native_roundtrip']
