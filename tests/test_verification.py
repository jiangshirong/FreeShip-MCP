import asyncio
import hashlib
import json
import shutil
from pathlib import Path
import pytest
from pydantic import ValidationError
from freeship_mcp.engine import Engine, EngineError
from freeship_mcp.verification import Target, verify_targets
from freeship_mcp.server import write_export

ROOT=Path(__file__).resolve().parents[1]


def run(task):return asyncio.run(task)


@pytest.fixture
def engine(tmp_path):
    shutil.copy2(ROOT/'examples/box.fbm',tmp_path/'box.fbm')
    return Engine(tmp_path)


def target(metric,value,tol=.001,**kwargs):
    return Target(metric=metric,expected=value,absolute_tolerance=tol,**kwargs)


def test_height_is_geometry_not_metadata(engine):
    # Metadata all match while the upper hull is deliberately twice the required height.
    run(engine.call('scale_model','box.fbm',output_path='tall.fbm',x_factor=1,y_factor=1,z_factor=2,
        project_length_m=20,project_beam_m=6,project_draft_m=4))
    result=run(verify_targets(engine,'tall.fbm',4,[target('project_length_m',20),
        target('project_draft_m',4),target('section_top_above_keel_m',8,section_x_m=10)]))
    assert result['status']=='failed'
    assert result['summary']=={'passed':2,'failed':1,'not_checked':0}
    assert result['checks'][2]['measured']==pytest.approx(16)
    assert result['checks'][0]['basis']['geometry_verified'] is False
    assert hashlib.sha256((engine.workspace/'tall.fbm').read_bytes()).hexdigest()==result['provenance']['model']['sha256']


def test_coefficient_bases_and_explicit_tolerance(engine):
    # Actual box beam stays 6; metadata beam is 12. Native and project alpha differ.
    run(engine.call('scale_model','box.fbm',output_path='wide-setting.fbm',x_factor=1,y_factor=1,z_factor=1,
        project_beam_m=12))
    result=run(verify_targets(engine,'wide-setting.fbm',4,[
        target('waterplane_coefficient_project',.5,.0001),target('waterplane_coefficient_native',1,.0001)]))
    assert result['status']=='passed'
    native=result['checks'][1]['basis']; project=result['checks'][0]['basis']
    assert native['waterplane_beam_m']==pytest.approx(6)
    assert project['beam_m']==12
    h=run(engine.call('calculate_hydrostatics','wide-setting.fbm',draft_m=4))
    assert h['block_coefficient']==pytest.approx(native['volume_m3']/(native['length_m']*native['beam_m']*4),rel=2e-6)


def test_missing_section_and_dry_are_not_passes(engine):
    r=run(verify_targets(engine,'box.fbm',0,[target('displacement_t',0,1),
        target('section_top_above_keel_m',8,section_x_m=100)]))
    assert r['status']=='incomplete' and r['summary']['not_checked']==2
    assert all(c['measured'] is None for c in r['checks'])


def test_input_contract(engine):
    for payload in [dict(metric='H',expected=8,absolute_tolerance=.1),
                    dict(metric='displacement_t',expected=float('nan'),absolute_tolerance=1),
                    dict(metric='displacement_t',expected=1,absolute_tolerance=-1)]:
        with pytest.raises(ValidationError):Target(**payload)
    with pytest.raises(ValueError,match='explicit section'):
        run(verify_targets(engine,'box.fbm',4,[target('section_top_above_keel_m',8)]))
    with pytest.raises(ValueError,match='Duplicate'):
        run(verify_targets(engine,'box.fbm',4,[target('displacement_t',1),target('displacement_t',1)]))


def test_changed_input_rejected(engine,monkeypatch):
    original=engine.raw
    async def changing(*args,**kwargs):
        result=await original(*args,**kwargs)
        with (engine.workspace/'box.fbm').open('ab') as stream:stream.write(b'changed')
        return result
    monkeypatch.setattr(engine,'raw',changing)
    with pytest.raises(EngineError,match='changed during'):
        run(engine.call('inspect_model','box.fbm'))


def test_export_manifest_and_cleanup(tmp_path):
    path=tmp_path/'test.csv'; provenance={'model':{'sha256':'test'},'request':{'drafts_m':[1,2]}}
    def writer(p):p.write_text('valid');return {'rows':2}
    run(write_export(path,writer,provenance))
    manifest=json.loads(Path(str(path)+'.manifest.json').read_text())
    assert manifest['artifact']['sha256']==hashlib.sha256(b'valid').hexdigest()
    assert manifest['provenance']==provenance
    path2=tmp_path/'failed.csv'
    def failed(p):p.write_text('partial');raise ValueError('failed')
    with pytest.raises(ValueError):run(write_export(path2,failed,provenance))
    assert not path2.exists() and not Path(str(path2)+'.manifest.json').exists()
    assert not list(tmp_path.glob('.freeship-*'))
