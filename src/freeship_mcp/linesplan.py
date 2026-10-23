"""Metre-based three-view drawing of native curves and subdivided surface outlines."""
from __future__ import annotations
import math
from pathlib import Path
import ezdxf
from pydantic import Field, field_validator
from .editing import StrictModel


class LinesplanOptions(StrictModel):
    include_boundaries: bool = True
    include_silhouettes: bool = True
    include_creases: bool = True
    include_grid: bool = True
    include_labels: bool = True
    title: str = Field(default="Lines plan", max_length=120)
    stations_m: list[float] | None = Field(default=None, max_length=1000)
    waterlines_m: list[float] | None = Field(default=None, max_length=1000)
    buttocks_m: list[float] | None = Field(default=None, max_length=1000)
    body_split_x_m: float | None = None
    gap_m: float | None = Field(default=None, gt=0)
    text_height_m: float | None = Field(default=None, gt=0)

    @field_validator('title')
    @classmethod
    def plain_title(cls, value):
        if any(ord(c)<32 for c in value):raise ValueError('Title must be a single plain-text line')
        return value

    @field_validator('stations_m','waterlines_m','buttocks_m')
    @classmethod
    def finite_grid(cls, values):
        if values is not None and (len(set(values))!=len(values) or any(not math.isfinite(v) for v in values)):
            raise ValueError('Grid positions must be unique and finite')
        return values


def linesplan_dxf(path: Path, geometry: dict, options: LinesplanOptions | None = None) -> dict:
    options=options or LinesplanOptions()
    curves=geometry['curves'];boundaries=geometry.get('boundary_segments_m',[])
    silhouettes=geometry.get('silhouette_segments_m',{});creases=geometry.get('crease_segments_m',[])
    if not curves and not (options.include_boundaries and boundaries) and not (options.include_silhouettes and any(silhouettes.values())) and not (options.include_creases and creases):
        raise ValueError('No drawable native geometry; generate sections or enable surface outlines')
    doc=ezdxf.new('R2010');doc.units=ezdxf.units.M;space=doc.modelspace()
    minimum=geometry['geometry_min_m'];maximum=geometry['geometry_max_m']
    xmin,xmax=minimum[0],maximum[0];zmin,zmax=minimum[2],maximum[2]
    half=max(abs(minimum[1]),abs(maximum[1]),geometry['beam_m']/2)
    if half<=0 or xmax<=xmin or zmax<=zmin:raise ValueError('Degenerate view bounds')
    gap=options.gap_m or max(half,1.);text=options.text_height_m or max(xmax-xmin,half*2)/140
    split=geometry['split_section_m'] if options.body_split_x_m is None else options.body_split_x_m
    plan_y=zmin-gap-half
    body_x=xmax+gap+half
    counts={v:0 for v in ('PROFILE','PLAN','BODY')};boundary_counts=dict.fromkeys(counts,0);silhouette_counts=dict.fromkeys(counts,0)
    crease_counts=dict.fromkeys(counts,0);body_labels=[]
    grid_counts=dict.fromkeys(counts,0);sections={k:set() for k in ('station','waterline','buttock')}
    locations={k:sorted(geometry.get('section_positions_m',{}).get(k,{c['distance_m'] for c in curves if c['kind']==k})) for k in sections}
    grids={k:locations[k] if getattr(options,a) is None else sorted(getattr(options,a))
           for k,a in [('station','stations_m'),('waterline','waterlines_m'),('buttock','buttocks_m')]}
    def layer(name,color):
        if name not in doc.layers:doc.layers.add(name,color=color)
        return {'layer':name}
    def line(a,b,name,color):
        if math.dist(a,b)<=1e-9:return False
        space.add_line(a,b,dxfattribs=layer(name,color));return True
    def label(value,point,name='LABELS'):
        if options.include_labels:
            space.add_text(str(value),dxfattribs={**layer(name,7),'height':text,'insert':point})
    def project(p,view,side=1):
        x,y,z=p
        return (x,z) if view=='PROFILE' else (x,plan_y+y) if view=='PLAN' else (body_x+side*y,z)
    for c in curves:
        kind=c['kind'];sections[kind].add(c['section_index']);points=c['points_m']
        if len(points)<2:continue
        views=['PROFILE','PLAN']+(['BODY'] if kind=='station' else [])
        for view in views:
            side=-1 if c['distance_m']<=split else 1
            projected=[project(p,view,side) for p in points]
            if all(math.dist(projected[0],p)<1e-9 for p in projected):continue
            space.add_lwpolyline(projected,dxfattribs=layer(f"{view}_{kind.upper()}_{c['section_index']:03}",{'station':3,'waterline':5,'buttock':1}[kind]))
            counts[view]+=1
            if view=='BODY':body_labels.append((projected[-1],c['section_index'],side))
    # Group coincident section endpoints; stack nearby labels with real endpoint leaders.
    if options.include_labels:
        groups=[]
        for point,index,side in body_labels:
            match=next((g for g in groups if g['side']==side and math.dist(g['point'],point)<text*.5),None)
            if match is None:groups.append({'point':point,'ids':{index},'side':side})
            else:match['ids'].add(index)
        previous=zmin-text*2
        for group in sorted(groups,key=lambda g:(g['point'][1],g['side'])):
            target=(body_x+half+text*10,max(group['point'][1],previous+text*1.5));previous=target[1]
            label('S'+','.join(map(str,sorted(group['ids']))),target,'BODY_LABELS')
            line(group['point'],target,'BODY_LABEL_LEADERS',8)
    # Independent native edge segments are never joined across a missing intersection.
    # Clip body outline edges at the split plane before reflecting the aft/fore halves.
    def outline(segment,view,name,color):
        a,b=segment
        if view!='BODY':return int(line(project(a,view),project(b,view),name,color))
        pieces=[(a,b)]
        if (a[0]-split)*(b[0]-split)<0:
            t=(split-a[0])/(b[0]-a[0]);p=[x+t*(y-x) for x,y in zip(a,b)];pieces=[(a,p),(p,b)]
        total=0
        for p,q in pieces:
            side=-1 if (p[0]+q[0])/2<=split else 1
            total+=line(project(p,view,side),project(q,view,side),name,color)
        return total
    for view in counts:
        if options.include_boundaries:
            for segment in boundaries:boundary_counts[view]+=outline(segment,view,view+'_BOUNDARY',7)
        if options.include_creases:
            for segment in creases:crease_counts[view]+=outline(segment,view,view+'_CREASE',7)
        if options.include_silhouettes:
            for segment in silhouettes.get(view,[]):silhouette_counts[view]+=outline(segment,view,view+'_SILHOUETTE',7)
    if options.include_grid:
        for i,x in enumerate(grids['station']):
            grid_counts['PROFILE']+=line((x,zmin),(x,zmax),'PROFILE_GRID',8)
            grid_counts['PLAN']+=line((x,plan_y-half),(x,plan_y+half),'PLAN_GRID',8)
            label(f'x={x:g}',(x,zmin-text*1.5),'PROFILE_GRID_LABELS')
        for z in sorted(set(grids['waterline']+[zmin])):
            grid_counts['PROFILE']+=line((xmin,z),(xmax,z),'PROFILE_GRID',8)
            grid_counts['BODY']+=line((body_x-half,z),(body_x+half,z),'BODY_GRID',8)
            label(f'z={z:g}',(body_x+half+text,z),'BODY_GRID_LABELS')
        for y in sorted(set([0]+[s*abs(v) for v in grids['buttock'] for s in (-1,1)])):
            grid_counts['PLAN']+=line((xmin,plan_y+y),(xmax,plan_y+y),'PLAN_GRID',8)
            grid_counts['BODY']+=line((body_x+y,zmin),(body_x+y,zmax),'BODY_GRID',8)
            label(f'y={y:g}',(body_x+y,zmin-text*1.5),'BODY_GRID_LABELS')
        for view,a,b in [('PROFILE',(xmin,zmin),(xmax,zmin)),('BODY',(body_x-half,zmin),(body_x+half,zmin)),
                         ('BODY',(body_x,zmin),(body_x,zmax)),('PLAN',(xmin,plan_y),(xmax,plan_y))]:
            line(a,b,view+'_DATUM',7)
    label(options.title,(xmin,zmax+text*5))
    for title,point in [('PROFILE',(xmin,zmax+text*2)),('PLAN',(xmin,plan_y+half+text*2)),('BODY',(body_x-half,zmax+text*2))]:label(title,point)
    doc.saveas(path)
    check=ezdxf.readfile(path)
    if check.audit().has_errors:raise ValueError('Exported DXF failed independent audit')
    return {'views':counts,'boundary_entities':boundary_counts,'silhouette_entities':silhouette_counts,
            'grid_entities':grid_counts,'crease_entities':crease_counts,'nonempty_sections':{k:len(v) for k,v in sections.items()},
            'empty_sections':{k:[v for v in grids[k] if not any(abs(c['distance_m']-v)<1e-7 for c in curves if c['kind']==k)] for k in sections},
            'units':'m','entities':len(check.modelspace()),'options':options.model_dump(),
            'layout':{'plan_y_m':plan_y,'body_center_x_m':body_x,'body_split_x_m':split},
            'curve_sampling':'native spline parameter samples plus original knuckles',
            'outline_sampling':'actual subdivided mesh edges; no invented curve closure; no hidden-line removal'}
