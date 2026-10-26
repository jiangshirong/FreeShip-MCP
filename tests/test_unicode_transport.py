"""Native JSON Unicode paths: literal UTF-8 and escaped input must be equivalent."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(params=['local','standalone'])
def native_engine(request):
    binary=(ROOT/'src/freeship_mcp/bin/freeship-engine.exe' if request.param=='local' else
            ROOT/'dist/standalone/freeship-mcp/_internal/freeship_mcp/bin/freeship-engine.exe')
    if not binary.exists():pytest.skip('Build the standalone package first')
    return binary


def native(binary,workspace,request,escaped):
    p=subprocess.run([str(binary)],input=(json.dumps(request,ensure_ascii=escaped)+'\n').encode('utf-8'),
        cwd=workspace,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    result=json.loads(p.stdout)
    assert p.returncode==0 and result.get('ok'),result
    return result


@pytest.mark.parametrize('escaped',[False,True],ids=['literal-utf8','unicode-escaped'])
@pytest.mark.parametrize('absolute',[False,True],ids=['relative','absolute'])
@pytest.mark.parametrize('filename',['model.fbm','中文模型.fbm','模型-🚢-Ł.fbm'],ids=['ascii','cjk','supplementary'])
def test_json_unicode_input_and_output_paths(tmp_path,native_engine,escaped,absolute,filename):
    workspace=tmp_path/'中文目录'/'繁體資料'/'русский-Ł';workspace.mkdir(parents=True)
    source=workspace/filename;shutil.copy2(ROOT/'examples/box.fbm',source)
    target=workspace/('另存-🚢-'+filename)
    request=dict(operation='save_model',model_path=str(source) if absolute else source.name,
                 output_path=str(target) if absolute else target.name,output_version=0)
    native(native_engine,workspace,request,escaped)
    assert target.read_bytes()==source.read_bytes()
    h=native(native_engine,workspace,dict(operation='calculate_hydrostatics',model_path=str(target) if absolute else target.name,draft_m=4),escaped)
    assert h['volume_geometry_m3']==pytest.approx(480,rel=2e-6)


def test_escaped_unicode_model_text_is_not_truncated(tmp_path,native_engine):
    shutil.copy2(ROOT/'examples/box.fbm',tmp_path/'model.fbm')
    title='中文繁體-🚢-Ł-русский'
    native(native_engine,tmp_path,dict(operation='scale_model',model_path='model.fbm',output_path='saved.fbm',
        x_factor=1,y_factor=1,z_factor=1,project_name=title,encoding='utf8'),True)
    result=native(native_engine,tmp_path,dict(operation='inspect_model',model_path='saved.fbm',encoding='utf8'),True)
    assert result['project_name']==title
