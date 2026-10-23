{ Explicit local control-net edits. GPL-3.0-or-later. Native topology methods retained. }
unit HeadlessEditing;
{$mode objfpc}{$H+}
interface
uses SysUtils,Classes,Math,fpjson,FreeShipUnit,FreeGeometry,FreeTypes;
function EditControlNet(M:TFreeShip; R:TJSONObject):TJSONObject;
procedure AddControlNet(M:TFreeShip; O:TJSONObject);
implementation
function Factor(M:TFreeShip):Double;
begin if M.ProjectSettings.ProjectUnits=fuImperial then Result:=0.3048 else Result:=1; end;
function PointAt(M:TFreeShip; I:Integer; AllowLocked:Boolean):TFreeSubdivisionControlPoint;
begin
 if (I<0) or (I>=M.Surface.NumberOfControlPoints) then raise Exception.Create('Point index out of range');
 Result:=M.Surface.ControlPoint[I];
 if Result.Locked and not AllowLocked then raise Exception.Create('Selected point is locked');
 if (Result.AnchorPoint<>nil) or (Result.LinearConstraintPointA<>nil) or (Result.LinearConstraintPointB<>nil) then
  raise Exception.Create('Selected point has a desktop anchor or linear constraint; raw local editing is unsupported');
end;
procedure AssignCoordinate(P:TFreeSubdivisionControlPoint; V:T3DCoordinate; AllowLocked:Boolean);
var WasLocked:Boolean;
begin
 WasLocked:=P.Locked;
 if WasLocked and not AllowLocked then raise Exception.Create('Selected point is locked');
 try P.Locked:=False;P.Coordinate:=V;finally P.Locked:=WasLocked;end;
end;
procedure AddControlNet(M:TFreeShip; O:TJSONObject);
var I,J:Integer; A,B,C:TJSONArray; P:T3DCoordinate; V:TJSONObject; E:TFreeSubdivisionControlEdge; F:TFreeSubdivisionControlFace;
begin
 A:=TJSONArray.Create;B:=TJSONArray.Create;C:=TJSONArray.Create;
 for I:=0 to M.Surface.NumberOfControlPoints-1 do
 begin
  V:=TJSONObject.Create;V.Add('index',I);P:=M.Surface.ControlPoint[I].Coordinate;
  V.Add('coordinate_m',TJSONArray.Create([P.X*Factor(M),P.Y*Factor(M),P.Z*Factor(M)]));
  V.Add('locked',M.Surface.ControlPoint[I].Locked);
  V.Add('boundary',M.Surface.ControlPoint[I].IsBoundaryVertex);
  V.Add('has_desktop_constraint',(M.Surface.ControlPoint[I].AnchorPoint<>nil) or
    (M.Surface.ControlPoint[I].LinearConstraintPointA<>nil) or (M.Surface.ControlPoint[I].LinearConstraintPointB<>nil));
  V.Add('vertex_type',Ord(M.Surface.ControlPoint[I].VertexType));A.Add(V);
 end;
 for I:=0 to M.Surface.NumberOfControlEdges-1 do
 begin
  E:=M.Surface.ControlEdge[I];V:=TJSONObject.Create;V.Add('index',I);
  V.Add('point_indices',TJSONArray.Create([E.StartPoint.VertexIndex,E.EndPoint.VertexIndex]));
  V.Add('crease',E.Crease);V.Add('adjacent_faces',E.NumberOfFaces);B.Add(V);
 end;
 for I:=0 to M.Surface.NumberOfControlFaces-1 do
 begin
  F:=M.Surface.ControlFace[I];V:=TJSONObject.Create;V.Add('index',I);V.Add('layer_index',F.Layer.LayerIndex);
  V.Add('point_indices',TJSONArray.Create);
  for J:=0 to F.NumberOfPoints-1 do V.Arrays['point_indices'].Add(F.Point[J].VertexIndex);
  C.Add(V);
 end;
 O.Add('control_net_points',A);O.Add('control_net_edges',B);O.Add('control_net_faces',C);
end;
function EditControlNet(M:TFreeShip; R:TJSONObject):TJSONObject;
var A:TJSONObject;Kind,Axis:String;Ids,Updates:TJSONArray;I,J,K,N,Iterations:Integer;
 AllowLocked,Deleted,PreserveBoundary:Boolean;F,Ratio,Weight:Double;P,Q:TFreeSubdivisionControlPoint;
 Edge:TFreeSubdivisionControlEdge;Face:TFreeSubdivisionControlFace;List:TList;
 V,Mean:T3DCoordinate; Before:array of T3DCoordinate;Chosen:array of Boolean;Changed:TJSONArray;Change:TJSONObject;MaxMove,Distance:Double; Dest:array of T3DCoordinate;Touched:array of TFreeSubdivisionControlPoint;
begin
 Result:=TJSONObject.Create;A:=R.Objects['edit'];Kind:=A.Get('action','');F:=Factor(M);
 AllowLocked:=R.Get('allow_locked',False);M.Surface.ClearMesh;
 SetLength(Before,M.Surface.NumberOfControlPoints);SetLength(Chosen,Length(Before));
 for I:=0 to High(Before) do Before[I]:=M.Surface.ControlPoint[I].Coordinate;
 if Kind='move_points' then begin
  Updates:=A.Arrays['points'];for I:=0 to Updates.Count-1 do begin
   J:=Updates.Objects[I].Get('index',-1);PointAt(M,J,AllowLocked);Chosen[J]:=True;end;
 end else if (Kind='translate_points') or (Kind='align_points') or (Kind='relax_points') then begin
  Ids:=A.Arrays['point_indices'];for I:=0 to Ids.Count-1 do begin
   J:=Ids.Integers[I];PointAt(M,J,AllowLocked);Chosen[J]:=True;end;
 end;
 if Kind='move_points' then
 begin
  Updates:=A.Arrays['points'];
  for I:=0 to Updates.Count-1 do
  begin
   P:=PointAt(M,Updates.Objects[I].Get('index',-1),AllowLocked);V:=P.Coordinate;
   if Updates.Objects[I].Find('x_m')<>nil then V.X:=Updates.Objects[I].Get('x_m',0.0)/F;
   if Updates.Objects[I].Find('y_m')<>nil then V.Y:=Updates.Objects[I].Get('y_m',0.0)/F;
   if Updates.Objects[I].Find('z_m')<>nil then V.Z:=Updates.Objects[I].Get('z_m',0.0)/F;
   AssignCoordinate(P,V,AllowLocked);
  end;
 end else if (Kind='translate_points') or (Kind='align_points') or (Kind='relax_points') then
 begin
  Ids:=A.Arrays['point_indices'];SetLength(Touched,Ids.Count);SetLength(Dest,Ids.Count);
  for I:=0 to Ids.Count-1 do Touched[I]:=PointAt(M,Ids.Integers[I],AllowLocked);
  Iterations:=1;if Kind='relax_points' then Iterations:=A.Get('iterations',1);
  for K:=1 to Iterations do
  begin
   for I:=0 to High(Touched) do
   begin
    P:=Touched[I];V:=P.Coordinate;
    if Kind='translate_points' then
    begin
     V.X:=V.X+A.Get('dx_m',0.0)/F;V.Y:=V.Y+A.Get('dy_m',0.0)/F;V.Z:=V.Z+A.Get('dz_m',0.0)/F;
    end else if Kind='align_points' then
    begin
     Axis:=A.Get('axis','');
     if Axis='x' then V.X:=A.Get('value_m',0.0)/F
     else if Axis='y' then V.Y:=A.Get('value_m',0.0)/F
     else if Axis='z' then V.Z:=A.Get('value_m',0.0)/F
     else raise Exception.Create('Invalid alignment axis');
    end else begin
     PreserveBoundary:=A.Get('preserve_boundary',True);
     if PreserveBoundary and P.IsBoundaryVertex then raise Exception.Create('Relaxation would move a boundary point; explicit opt-in required');
     Mean:=SetPoint(0,0,0);N:=0;
     for J:=0 to P.NumberOfEdges-1 do
     begin
      if P.Edge[J].Crease and A.Get('preserve_creases',True) then raise Exception.Create('Relaxation would move a crease endpoint; explicit opt-in required');
      if P.Edge[J].StartPoint=P then Q:=TFreeSubdivisionControlPoint(P.Edge[J].EndPoint)
      else Q:=TFreeSubdivisionControlPoint(P.Edge[J].StartPoint);
      Mean.X:=Mean.X+Q.Coordinate.X;Mean.Y:=Mean.Y+Q.Coordinate.Y;Mean.Z:=Mean.Z+Q.Coordinate.Z;Inc(N);
     end;
     if N=0 then raise Exception.Create('Isolated point cannot be relaxed');
     Weight:=A.Get('relaxation',0.0);
     V.X:=V.X+Weight*(Mean.X/N-V.X);V.Y:=V.Y+Weight*(Mean.Y/N-V.Y);V.Z:=V.Z+Weight*(Mean.Z/N-V.Z);
    end;
    Dest[I]:=V;
   end;
   for I:=0 to High(Touched) do AssignCoordinate(Touched[I],Dest[I],AllowLocked);
  end;
 end else if (Kind='split_edge') or (Kind='set_edge_crease') then
 begin
  I:=A.Get('edge_index',-1);
  if (I<0) or (I>=M.Surface.NumberOfControlEdges) then raise Exception.Create('Edge index out of range');
  Edge:=M.Surface.ControlEdge[I];PointAt(M,Edge.StartPoint.VertexIndex,AllowLocked);PointAt(M,Edge.EndPoint.VertexIndex,AllowLocked);
  if Kind='set_edge_crease' then Edge.Crease:=A.Get('crease',False)
  else begin
   Ratio:=A.Get('fraction',0.5);
   if (Ratio<=0) or (Ratio>=1) then raise Exception.Create('Split fraction must be inside (0,1)');
   V:=Edge.StartPoint.Coordinate;Mean:=Edge.EndPoint.Coordinate;
   V:=SetPoint(V.X+(Mean.X-V.X)*Ratio,V.Y+(Mean.Y-V.Y)*Ratio,V.Z+(Mean.Z-V.Z)*Ratio);
   P:=Edge.InsertControlPoint(V);if P=nil then raise Exception.Create('Native edge split failed');
   Result.Add('created_point_index',P.VertexIndex);
  end;
 end else if (Kind='split_face') or (Kind='delete_face') then
 begin
  I:=A.Get('face_index',-1);
  if (I<0) or (I>=M.Surface.NumberOfControlFaces) then raise Exception.Create('Face index out of range');
  Face:=M.Surface.ControlFace[I];
  for J:=0 to Face.NumberOfPoints-1 do PointAt(M,Face.Point[J].VertexIndex,AllowLocked);
  if Kind='delete_face' then Face.Delete
  else begin
   Ids:=A.Arrays['point_indices'];P:=PointAt(M,Ids.Integers[0],AllowLocked);Q:=PointAt(M,Ids.Integers[1],AllowLocked);
   Edge:=Face.InsertEdge(P,Q,Deleted);if Edge=nil then raise Exception.Create('Split needs two nonadjacent vertices of the selected face');
  end;
 end else if Kind='add_face' then
 begin
  I:=A.Get('layer_index',-1);if (I<0) or (I>=M.NumberOfLayers) then raise Exception.Create('Layer index out of range');
  List:=TList.Create;
  try
   Ids:=A.Arrays['point_indices'];for J:=0 to Ids.Count-1 do List.Add(PointAt(M,Ids.Integers[J],AllowLocked));
   Face:=M.Surface.AddControlFace(List,True);if Face=nil then raise Exception.Create('Native face creation failed');
   Face.Layer:=M.Layer[I];Result.Add('created_face_index',Face.FaceIndex);
  finally List.Free;end;
 end else raise Exception.Create('Unknown local edit');
 M.Built:=False;M.Surface.Rebuild;Result.Add('action',Kind);
 if (Kind='move_points') or (Kind='translate_points') or (Kind='align_points') or (Kind='relax_points') then begin
  Changed:=TJSONArray.Create;Result.Add('changed_points',Changed);MaxMove:=0;
  for I:=0 to High(Before) do begin
   V:=M.Surface.ControlPoint[I].Coordinate;Mean:=Before[I];
   Distance:=Sqrt(Sqr(V.X-Mean.X)+Sqr(V.Y-Mean.Y)+Sqr(V.Z-Mean.Z))*F;
   if Distance=0 then Continue;
   if not Chosen[I] then raise Exception.Create('Native point constraints moved an unselected point; select linked points explicitly');
   Change:=TJSONObject.Create;Change.Add('index',I);
   Change.Add('before_m',TJSONArray.Create([Mean.X*F,Mean.Y*F,Mean.Z*F]));
   Change.Add('after_m',TJSONArray.Create([V.X*F,V.Y*F,V.Z*F]));
   Change.Add('movement_m',Distance);Changed.Add(Change);MaxMove:=Max(MaxMove,Distance);
  end;
  Result.Add('maximum_point_movement_m',MaxMove);
 end;
 Result.Add('indices_scope','Input model snapshot; inspect the output before the next edit');
end;
end.
