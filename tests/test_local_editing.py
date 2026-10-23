"""Public synthetic-model regression tests for explicit editing and drawing."""
import asyncio
import math
import shutil
from pathlib import Path
import ezdxf
import pytest
from pydantic import TypeAdapter, ValidationError
from freeship_mcp.engine import Engine,EngineError
from freeship_mcp.editing import LocalEdit
from freeship_mcp.quality import curve_metrics, analyze_geometry, AlignmentRule
from freeship_mcp.linesplan import linesplan_dxf, LinesplanOptions

ROOT=Path(__file__).resolve().parents[1]
def run(coro):return asyncio.run(coro)
@pytest.fixture
def engine(tmp_path):
    shutil.copy2(ROOT/'examples/box.fbm',tmp_path/'box.fbm')
    return Engine(tmp_path)
def inspect(engine,path='box.fbm'):
    return run(engine.call('inspect_model',path,include_control_net=True))
def edit(engine,data,source='box.fbm',target='edited.fbm'):
    typed=TypeAdapter(LocalEdit).validate_python(data)
    info=inspect(engine,source)
    return run(engine.call('edit_control_net',source,output_path=target,
        expected_model_sha256=info['provenance']['model']['sha256'],edit=typed.model_dump(exclude_none=True)))

def test_align_and_translate_only_selected(engine):
    info=inspect(engine);original=(engine.workspace/'box.fbm').read_bytes()
    selected=[p['index'] for p in info['control_net_points'] if p['coordinate_m'][1]>0]
    r=edit(engine,dict(action='align_points',point_indices=selected,axis='y',value_m=2.5))
    assert {p['index'] for p in r['changed_points']}==set(selected)
    assert r['maximum_point_movement_m']==pytest.approx(.5)
    assert r['topology']['integrity']
    h=run(engine.call('calculate_hydrostatics','edited.fbm',draft_m=4))
    assert h['volume_geometry_m3']==pytest.approx(400,rel=2e-6)
    moved=edit(engine,dict(action='translate_points',point_indices=list(range(8)),dx_m=1),source='edited.fbm',target='moved.fbm')
    assert all(a['coordinate_m'][0]+1==b['coordinate_m'][0] for a,b in zip(r['control_net_points'],moved['control_net_points']))
    assert (engine.workspace/'box.fbm').read_bytes()==original

def test_move_split_edge_and_face(engine):
    info=inspect(engine);edge=info['control_net_edges'][0];a,b=[info['control_net_points'][i]['coordinate_m'] for i in edge['point_indices']]
    result=edit(engine,dict(action='split_edge',edge_index=0,fraction=.25))
    assert len(result['control_net_points'])==9
    p=result['control_net_points'][result['created_point_index']]['coordinate_m']
    assert p==pytest.approx([x+.25*(y-x) for x,y in zip(a,b)])
    face=info['control_net_faces'][0]
    split=edit(engine,dict(action='split_face',face_index=0,point_indices=face['point_indices'][::2]),target='split.fbm')
    assert len(split['control_net_faces'])==len(info['control_net_faces'])+1
    update=edit(engine,dict(action='move_points',points=[{'index':0,'x_m':-.25}]),target='move.fbm')
    assert update['changed_points'][0]['after_m'][0]==-.25

def test_face_delete_restore_and_crease(engine):
    info=inspect(engine);f=info['control_net_faces'][0]
    removed=edit(engine,dict(action='delete_face',face_index=0))
    assert len(removed['control_net_faces'])==3
    restored=edit(engine,dict(action='add_face',point_indices=f['point_indices'],layer_index=f['layer_index']),
        source='edited.fbm',target='restored.fbm')
    assert len(restored['control_net_faces'])==4
    h=run(engine.call('calculate_hydrostatics','restored.fbm',draft_m=4))
    assert h['volume_geometry_m3']==pytest.approx(480,rel=2e-6)
    creased=edit(engine,dict(action='set_edge_crease',edge_index=0,crease=False),target='crease.fbm')
    assert creased['control_net_edges'][0]['crease'] is False

def test_relax_requires_explicit_feature_opt_in(engine):
    with pytest.raises(EngineError,match='boundary|crease'):
        edit(engine,dict(action='relax_points',point_indices=[0],relaxation=.1))
    assert not (engine.workspace/'edited.fbm').exists()
    r=edit(engine,dict(action='relax_points',point_indices=[0],relaxation=.1,preserve_boundary=False,preserve_creases=False))
    assert r['maximum_point_movement_m']>0

def test_snapshot_and_topology_failure_cleanup(engine):
    with pytest.raises(EngineError,match='snapshot'):
        run(engine.call('edit_control_net','box.fbm',output_path='bad.fbm',expected_model_sha256='0'*64,
                       edit=dict(action='delete_face',face_index=0)))
    info=inspect(engine);f=info['control_net_faces'][0]
    with pytest.raises(EngineError):
        edit(engine,dict(action='add_face',point_indices=f['point_indices'],layer_index=0),target='bad.fbm')
    assert not (engine.workspace/'bad.fbm').exists()
    assert not list(engine.workspace.glob('.freeship-*'))

@pytest.mark.parametrize('data',[
    {'action':'move_points','points':[{'index':0}]},
    {'action':'align_points','point_indices':[0,0],'axis':'y','value_m':2},
    {'action':'split_edge','edge_index':0,'fraction':0},
    {'action':'move_points','points':[{'index':0,'x_m':float('nan')}]},
    {'action':'relax_points','point_indices':[0],'relaxation':2},
])
def test_edit_schema_rejects_invalid(data):
    with pytest.raises(ValidationError):TypeAdapter(LocalEdit).validate_python(data)

def curve(points,kind='waterline'):
    return dict(kind=kind,section_index=0,distance_m=0,points_m=points)
def test_quality_circle_and_kink():
    radius=4
    c=curve([[radius*math.cos(i*.01),radius*math.sin(i*.01),0] for i in range(101)])
    result=curve_metrics(c)
    assert result['maxima']['curvature_per_m']==pytest.approx(1/radius,rel=1e-9)
    assert result['maxima']['turn_degrees']==pytest.approx(math.degrees(.01),rel=1e-9)
    kink=curve([[0,0,0],[1,0,0],[1,1,0]]);kink['knuckle_points_m']=[[1,0,0]]
    result=curve_metrics(kink,max_turn_degrees=45)
    assert result['finding_count']==1 and result['findings'][0]['native_knuckle']
    assert curve_metrics(curve([[0,0,0],[0,0,0],[1,0,0],[2,0,0]]))['maxima']['turn_degrees']==0

def test_quality_constraints_and_unchecked(engine):
    model=inspect(engine);topology=run(engine.call('validate_model','box.fbm'))
    args=dict(geometry={'curves':[]},model=model,topology=topology)
    assert analyze_geometry(**args)['status']=='measured'
    assert analyze_geometry(**args,max_turn_degrees=20)['status']=='incomplete'
    rule=AlignmentRule(point_indices=[0],axis='y',value_m=99,tolerance_m=.001)
    assert analyze_geometry(**args,alignment_rules=[rule])['status']=='issues_found'

def test_complete_dxf_actual_boundaries_grids_and_sections(engine):
    original=(engine.workspace/'box.fbm').read_bytes()
    g=run(engine.call('linesplan_geometry','box.fbm',stations_m=[2,10,18,30],waterlines_m=[2,4],buttocks_m=[1,2]))
    assert any(g['silhouette_segments_m'].values())
    options=LinesplanOptions(stations_m=[2,10,18,30],waterlines_m=[2,4],buttocks_m=[1,2])
    result=linesplan_dxf(engine.workspace/'lines.dxf',g,options)
    assert all(v>0 for v in result['boundary_entities'].values())
    assert all(v>0 for v in result['grid_entities'].values())
    assert result['nonempty_sections']['station']==3 and result['empty_sections']['station']==[30]
    doc=ezdxf.readfile(engine.workspace/'lines.dxf');assert not doc.audit().has_errors
    grid=list(doc.modelspace().query('LINE[layer=="BODY_GRID"]'))
    assert any(e.dxf.start.x==e.dxf.end.x for e in grid)
    assert any(e.dxf.start.y==e.dxf.end.y for e in grid)
    assert doc.modelspace().query('TEXT[layer=="BODY_LABELS"]')
    top=[e for e in doc.modelspace().query('LINE[layer=="PROFILE_BOUNDARY"]')
         if e.dxf.start.y==pytest.approx(8) and e.dxf.end.y==pytest.approx(8)]
    assert sum(e.dxf.start.distance(e.dxf.end) for e in top)==pytest.approx(20,rel=1e-5)
    assert (engine.workspace/'box.fbm').read_bytes()==original

def test_dxf_no_sections_still_has_real_outlines(engine):
    g=run(engine.call('linesplan_geometry','box.fbm'))
    r=linesplan_dxf(engine.workspace/'outline.dxf',g)
    assert r['views']['BODY']==0 and r['boundary_entities']['BODY']>0
    assert r['nonempty_sections']['station']==0

def test_locked_point_requires_opt_in_and_remains_locked(engine):
    request=dict(operation='create_mesh',output_path=str(engine.workspace/'locked.fbm'),
        points_m=[[0,0,0],[2,0,0],[2,2,0],[0,2,0]],faces=[[0,1,2,3]],
        locked_point_indices=[0],length_m=2,beam_m=4,draft_m=1,crease_edges=True)
    run(engine.raw(request));info=inspect(engine,'locked.fbm')
    args=dict(action='move_points',points=[{'index':0,'x_m':-.1}])
    with pytest.raises(EngineError,match='locked'):edit(engine,args,source='locked.fbm')
    r=run(engine.call('edit_control_net','locked.fbm',output_path='unlocked-edit.fbm',allow_locked=True,
        expected_model_sha256=info['provenance']['model']['sha256'],edit=args))
    assert r['control_net_points'][0]['locked'] is True
    assert r['control_net_points'][0]['coordinate_m'][0]==pytest.approx(-.1)
    assert inspect(engine,'unlocked-edit.fbm')['control_net_points'][0]['locked'] is True


def test_closed_box_silhouettes_without_open_boundaries(engine):
    p=[[0,0,0],[2,0,0],[2,2,0],[0,2,0],[0,0,2],[2,0,2],[2,2,2],[0,2,2]]
    faces=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
    run(engine.raw(dict(operation='create_mesh',output_path=str(engine.workspace/'closed.fbm'),
        points_m=p,faces=faces,length_m=2,beam_m=4,draft_m=1,crease_edges=True)))
    g=run(engine.call('linesplan_geometry','closed.fbm'))
    assert not g['boundary_segments_m']
    assert all(g['silhouette_segments_m'][v] for v in ('PROFILE','PLAN','BODY'))
    r=linesplan_dxf(engine.workspace/'closed.dxf',g)
    assert all(n>0 for n in r['silhouette_entities'].values())
    assert all(n>0 for n in r['crease_entities'].values())


def test_explicit_local_edit_in_imperial_model(engine):
    run(engine.raw(dict(operation='create_box',output_path=str(engine.workspace/'imperial.fbm'),imperial_storage=True)))
    info=inspect(engine,'imperial.fbm');ids=[p['index'] for p in info['control_net_points'] if p['coordinate_m'][1]>0]
    edit(engine,dict(action='align_points',point_indices=ids,axis='y',value_m=2.5),source='imperial.fbm')
    result=run(engine.call('calculate_hydrostatics','edited.fbm',draft_m=4))
    assert result['waterline_beam_m']==pytest.approx(5,rel=2e-6)
    assert result['volume_geometry_m3']==pytest.approx(400,rel=5e-6)


def test_partial_curve_coverage_cannot_pass_requested_limits(engine):
    model=inspect(engine);topology=run(engine.call('validate_model','box.fbm'))
    geometry=run(engine.call('linesplan_geometry','box.fbm',stations_m=[10,30],waterlines_m=[4]))
    result=analyze_geometry(geometry,model,topology,max_turn_degrees=180)
    assert result['curve_count']>0
    assert result['empty_sections']['station']==[30]
    assert result['curve_checks']=='partial' and result['status']=='incomplete'
