"""Sample-based curve diagnostics, with caller-selected thresholds; never an automatic hull approval."""
import math
from typing import Literal
from pydantic import Field
from .editing import StrictModel, Indices


class AlignmentRule(StrictModel):
    point_indices: Indices
    axis: Literal["x", "y", "z"]
    value_m: float
    tolerance_m: float = Field(ge=0)


def sub(a, b):return [x-y for x,y in zip(a,b)]
def norm(a):return math.sqrt(sum(x*x for x in a))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def curve_metrics(curve, max_turn_degrees=None, max_curvature_per_m=None,
                  max_curvature_step_per_m=None):
    pts=[]
    for p in curve["points_m"]:
        if not pts or math.dist(p,pts[-1])>1e-9:pts.append(p)
    extrema={"turn_degrees":0.,"curvature_per_m":0.,"curvature_step_per_m":0.}
    locations={};findings=[];previous=None;signs=[]
    normal_axis={"station":0,"waterline":2,"buttock":1}[curve['kind']]
    for i in range(1,len(pts)-1):
        u=sub(pts[i],pts[i-1]);v=sub(pts[i+1],pts[i]);w=sub(pts[i+1],pts[i-1])
        lu,lv,lw=norm(u),norm(v),norm(w)
        if min(lu,lv,lw)<1e-12:continue
        c=cross(u,v);turn=math.degrees(math.atan2(norm(c),sum(x*y for x,y in zip(u,v))))
        curvature=2*norm(c)/(lu*lv*lw)
        step=0 if previous is None else abs(curvature-previous);previous=curvature
        if abs(c[normal_axis])>1e-12:signs.append(1 if c[normal_axis]>0 else -1)
        at_knuckle=any(math.dist(pts[i],k)<1e-7 for k in curve.get('knuckle_points_m',[]))
        for key,value,limit in [('turn_degrees',turn,max_turn_degrees),('curvature_per_m',curvature,max_curvature_per_m),
                                ('curvature_step_per_m',step,max_curvature_step_per_m)]:
            if value>extrema[key]:extrema[key]=value;locations[key]=pts[i]
            if limit is not None and value>limit:
                findings.append({'metric':key,'value':value,'threshold':limit,'coordinate_m':pts[i],
                                 'native_knuckle':at_knuckle})
    return {"kind":curve['kind'],"section_index":curve['section_index'],"distance_m":curve['distance_m'],
            'samples':len(pts),'endpoints_m':([pts[0],pts[-1]] if pts else []),'polyline_length_m':sum(math.dist(a,b) for a,b in zip(pts,pts[1:])),
            'maxima':extrema,'maximum_locations_m':locations,
            'projected_curvature_sign_changes':sum(a!=b for a,b in zip(signs,signs[1:])),
            'finding_count':len(findings),'findings':findings[:20]}


def analyze_geometry(geometry, model, topology, alignment_rules=(), max_turn_degrees=None,
                     max_curvature_per_m=None, max_curvature_step_per_m=None):
    curves=[curve_metrics(c,max_turn_degrees,max_curvature_per_m,max_curvature_step_per_m) for c in geometry['curves']]
    points={p['index']:p['coordinate_m'] for p in model['control_net_points']}
    checks=[]
    for rule in alignment_rules:
        axis='xyz'.index(rule.axis)
        for index in rule.point_indices:
            if index not in points:raise ValueError('Alignment point index out of range')
            residual=points[index][axis]-rule.value_m
            checks.append({'point_index':index,'coordinate_m':points[index],'axis':rule.axis,
                           'expected_m':rule.value_m,'residual_m':residual,'tolerance_m':rule.tolerance_m,
                           'status':'passed' if abs(residual)<=rule.tolerance_m else 'failed'})
    expected=geometry.get('section_positions_m',{})
    missing={kind:[position for position in values if not any(c['kind']==kind and abs(c['distance_m']-position)<1e-7 for c in curves)]
             for kind,values in expected.items()}
    curve_limits=any(t is not None for t in (max_turn_degrees,max_curvature_per_m,max_curvature_step_per_m))
    incomplete=not curves or any(missing.values())
    flags=sum(c['finding_count'] for c in curves)
    topo_bad=not topology['integrity'] or any(topology[k]>0 for k in ('nonmanifold_edges','inconsistent_normal_edges','degenerate_faces'))
    requested=bool(alignment_rules) or any(t is not None for t in (max_turn_degrees,max_curvature_per_m,max_curvature_step_per_m))
    issues=topo_bad or flags>0 or any(c['status']=='failed' for c in checks)
    return {'ok':True,'status':'issues_found' if issues else 'measured' if not requested else
            'incomplete' if incomplete and curve_limits else 'no_requested_issues_found',
            'scope':'Discrete sampled-curve estimates and explicit control-point constraints; not a proof of fairness, self-intersection absence or design compliance. Native knuckles may be intentional.',
            'curve_count':len(curves),'curve_diagnostics':curves,'finding_count':flags,
            'alignment_checks':checks,'topology':topology,
            'curve_checks':'not_checked' if not curves else 'partial' if any(missing.values()) else 'measured',
            'section_positions_m':expected,'empty_sections':missing,
            'thresholds':{'max_turn_degrees':max_turn_degrees,'max_curvature_per_m':max_curvature_per_m,
                          'max_curvature_step_per_m':max_curvature_step_per_m}}
