{ FreeShip MCP adapter, GPL-3.0-or-later. Native geometry/calculations remain upstream. }
unit HeadlessModel;
{$mode objfpc}{$H+}
interface
uses SysUtils, Classes, Math, TypInfo, fpjson, FreeShipUnit, FreeGeometry,
     FreeTypes, FreeVersionUnit, FreeFileBuffer, HeadlessLackenby;
function ExecuteRequest(Request: TJSONObject): TJSONObject;
implementation
function CoordinateJSON(P: T3DCoordinate; Factor: Double): TJSONArray;
begin
  Result:=TJSONArray.Create;
  Result.Add(P.X*Factor); Result.Add(P.Y*Factor); Result.Add(P.Z*Factor);
end;
function LengthFactor(M: TFreeShip): Double;
begin
  if M.ProjectSettings.ProjectUnits=fuImperial then Result:=0.3048 else Result:=1;
end;
function MassFactor(M: TFreeShip): Double;
begin
  if M.ProjectSettings.ProjectUnits=fuImperial then Result:=1.0160469088 else Result:=1;
end;
procedure LoadModel(M: TFreeShip; const Path, Encoding: String);
var B: TFreeFileBuffer;
begin
  if not FileExists(Path) then raise Exception.Create('Model file does not exist');
  M.Preferences.FbmEncoding:=Encoding;
  if LowerCase(ExtractFileExt(Path))='.ftm' then B:=TFreeTextBuffer.Create
  else if LowerCase(ExtractFileExt(Path))='.fbm' then B:=TFreeFileBuffer.Create
  else raise Exception.Create('Only .fbm and .ftm are supported');
  try
    B.LoadFromFile(Path); M.LoadProject(B);
    if not (B is TFreeTextBuffer) and (B.Position<>B.Count) then
      raise Exception.Create('Unconsumed model data; refusing a lossy load');
  finally B.Free; end;
  if M.Surface.NumberOfControlFaces=0 then raise Exception.Create('Empty model');
end;
procedure SaveModel(M: TFreeShip; const Path: String; Version: Integer);
var B: TFreeFileBuffer; Check: TFreeShip; OldVersion: TFreeFileVersion;
begin
  OldVersion:=M.FileVersion;
  if Version=335 then M.FileVersion:=fv335 else if Version=462 then M.FileVersion:=fv462
  else if Version<>0 then raise Exception.Create('Output version must be 335, 462, or 0 (preserve)');
  if M.DetectMinFileVersion>M.FileVersion then
    raise Exception.Create('Requested format cannot represent model features');
  if LowerCase(ExtractFileExt(Path))='.ftm' then B:=TFreeTextBuffer.Create
  else if LowerCase(ExtractFileExt(Path))='.fbm' then B:=TFreeFileBuffer.Create
  else raise Exception.Create('Output model must be .fbm or .ftm');
  try
    B.Version:=M.FileVersion; M.SaveProject(B);
    if not B.SaveToFile(Path) then raise Exception.Create('Model save failed');
  finally B.Free; end;
  Check:=TFreeShip.Create(nil);
  try
    LoadModel(Check,Path,M.Preferences.FbmEncoding);
    if (Check.Surface.NumberOfControlPoints<>M.Surface.NumberOfControlPoints) or
       (Check.Surface.NumberOfControlFaces<>M.Surface.NumberOfControlFaces) or
       (Check.NumberOfLayers<>M.NumberOfLayers) or
       (Check.ProjectSettings.ProjectUnits<>M.ProjectSettings.ProjectUnits) then
      raise Exception.Create('Saved model failed native reload verification');
  finally Check.Free; M.FileVersion:=OldVersion; end;
end;
function Inspect(M: TFreeShip): TJSONObject;
var Layers: TJSONArray; L: TFreeSubdivisionLayer; O: TJSONObject;
    I: Integer; MinP,MaxP: T3DCoordinate; F: Double;
begin
  Result:=TJSONObject.Create; F:=LengthFactor(M);
  Result.Add('model_units',GetEnumName(TypeInfo(TFreeUnitType),Ord(M.ProjectSettings.ProjectUnits)));
  Result.Add('format_version',GetEnumName(TypeInfo(TFreeFileVersion),Ord(M.FileVersion)));
  Result.Add('length_m',M.ProjectSettings.ProjectLength*F);
  Result.Add('beam_m',M.ProjectSettings.ProjectBeam*F);
  Result.Add('draft_m',M.ProjectSettings.ProjectDraft*F);
  Result.Add('split_section_m',M.ProjectSettings.ProjectSplitSectionLocation*F);
  Result.Add('density_model_units',M.ProjectSettings.ProjectWaterDensity);
  if M.ProjectSettings.ProjectUnits=fuImperial then
    Result.Add('density_t_m3',M.ProjectSettings.ProjectWaterDensity*0.00045359237/Power(0.3048,3))
  else Result.Add('density_t_m3',M.ProjectSettings.ProjectWaterDensity);
  Result.Add('appendage_coefficient',M.ProjectSettings.ProjectAppendageCoefficient);
  Result.Add('coefficient_reference',GetEnumName(TypeInfo(TFreeHydrostaticCoeff),Ord(M.ProjectSettings.ProjectCoefficients)));
  Result.Add('control_points',M.Surface.NumberOfControlPoints);
  Result.Add('control_edges',M.Surface.NumberOfControlEdges);
  Result.Add('control_faces',M.Surface.NumberOfControlFaces);
  M.Extents(MinP,MaxP);
  Result.Add('geometry_min_m',CoordinateJSON(MinP,F)); Result.Add('geometry_max_m',CoordinateJSON(MaxP,F));
  Layers:=TJSONArray.Create;
  for I:=0 to M.NumberOfLayers-1 do
  begin
    L:=M.Layer[I]; O:=TJSONObject.Create;
    O.Add('index',I); O.Add('name',L.Name); O.Add('faces',L.Count);
    O.Add('symmetric',L.Symmetric); O.Add('hydrostatics',L.UseInHydrostatics);
    O.Add('intersections',L.UseForIntersections); O.Add('linesplan',L.ShowInLinesplan); Layers.Add(O);
  end;
  Result.Add('layers',Layers);
  Result.Add('stations',M.NumberOfStations); Result.Add('waterlines',M.NumberOfWaterlines);
  Result.Add('buttocks',M.NumberOfButtocks);
end;
function Hydrostatics(M: TFreeShip; DraftM,TrimM,Heel: Double): TJSONObject;
var H: TFreeHydrostaticCalc; D: TFreeHydrostaticsData; F,MF,VF,App: Double;
begin
  Result:=TJSONObject.Create; H:=TFreeHydrostaticCalc.Create(M);
  try
    F:=LengthFactor(M); MF:=MassFactor(M); VF:=F*F*F; App:=M.ProjectSettings.ProjectAppendageCoefficient;
    if App<=0 then raise Exception.Create('Appendage coefficient must be positive');
    H.Draft:=DraftM/F; H.Trim:=TrimM/F; H.HeelingAngle:=Heel;
    { Exclude GUI SAC/Bonjean report file side effects. }
    H.Calculations:=[hcVolume,hcMidship,hcWaterline,hcLateralArea]; H.Calculate; D:=H.Data;
    Result.Add('draft_m',DraftM); Result.Add('trim_m',TrimM); Result.Add('heel_degrees',Heel);
    Result.Add('keel_model_z_m',M.FindLowestHydrostaticsPoint*F);
    Result.Add('centres_reference','Native hydrostatic frame: keel z removed; rotated for specified trim and heel');
    Result.Add('no_immersion',(feNothingSubmerged in H.Errors) or (D.Volume<=0));
    if feMakingWater in H.Errors then raise Exception.Create('Hull leaks at the requested waterplane');
    if feNotEnoughBuoyancy in H.Errors then raise Exception.Create('Not enough buoyancy');
    Result.Add('volume_corrected_m3',D.Volume*VF); Result.Add('volume_geometry_m3',D.Volume*VF/App);
    Result.Add('displacement_t',D.Displacement*MF);
    Result.Add('lcb_ap_m',D.CenterOfBuoyancy.X*F); Result.Add('tcb_m',D.CenterOfBuoyancy.Y*F);
    Result.Add('vcb_m',D.CenterOfBuoyancy.Z*F);
    Result.Add('lcb_midship_fraction',D.CenterOfBuoyancy.X/M.ProjectSettings.ProjectLength-0.5);
    Result.Add('waterline_length_m',D.LengthWaterline*F); Result.Add('waterline_beam_m',D.BeamWaterline*F);
    Result.Add('waterline_min_m',CoordinateJSON(D.WlMin,F));
    Result.Add('waterline_max_m',CoordinateJSON(D.WlMax,F));
    Result.Add('waterplane_area_m2',D.Waterplanearea*F*F); Result.Add('lcf_ap_m',D.WaterplaneCOG.X*F);
    Result.Add('bm_transverse_m',(D.KMtransverse-D.CenterOfBuoyancy.Z)*F);
    Result.Add('bm_longitudinal_m',(D.KMlongitudinal-D.CenterOfBuoyancy.Z)*F);
    Result.Add('km_transverse_m',D.KMtransverse*F); Result.Add('km_longitudinal_m',D.KMlongitudinal*F);
    Result.Add('block_coefficient',D.BlockCoefficient); Result.Add('waterplane_coefficient',D.WaterplaneCoeff);
    Result.Add('prismatic_coefficient',D.PrismCoefficient); Result.Add('midship_coefficient',D.MidshipCoeff);
    Result.Add('wetted_surface_m2',D.WettedSurface*F*F);
  finally H.Free; end;
end;
function Validate(M: TFreeShip): TJSONObject;
var I,J,BadNormals,NonManifold,Degenerate: Integer; E: TFreeSubdivisionControlEdge;
    A,B: TFreeSubdivisionFace; P,Q: TFreeSubdivisionPoint; DirA,DirB: Integer;
    Leaks: TJSONArray; O: TJSONObject; CP: TFreeSubdivisionControlPoint;
begin
  Result:=TJSONObject.Create; M.Surface.Rebuild; Result.Add('integrity',M.Surface.CheckIntegrity);
  NonManifold:=0; BadNormals:=0; Degenerate:=0;
  for I:=0 to M.Surface.NumberOfControlEdges-1 do
  begin
    E:=M.Surface.ControlEdge[I]; if E.NumberOfFaces>2 then Inc(NonManifold);
    if E.NumberOfFaces=2 then
    begin
      A:=E.Face[0]; B:=E.Face[1]; DirA:=0; DirB:=0;
      for J:=0 to A.NumberOfPoints-1 do
      begin
        P:=A.Point[J]; Q:=A.Point[(J+1) mod A.NumberOfPoints];
        if (P=E.StartPoint) and (Q=E.EndPoint) then DirA:=1;
        if (Q=E.StartPoint) and (P=E.EndPoint) then DirA:=-1;
      end;
      for J:=0 to B.NumberOfPoints-1 do
      begin
        P:=B.Point[J]; Q:=B.Point[(J+1) mod B.NumberOfPoints];
        if (P=E.StartPoint) and (Q=E.EndPoint) then DirB:=1;
        if (Q=E.StartPoint) and (P=E.EndPoint) then DirB:=-1;
      end;
      if (DirA=DirB) or (DirA=0) or (DirB=0) then Inc(BadNormals);
    end;
  end;
  Leaks:=TJSONArray.Create;
  for I:=0 to M.Surface.NumberOfControlPoints-1 do
  begin
    CP:=M.Surface.ControlPoint[I];
    if CP.IsLeak then
    begin O:=TJSONObject.Create; O.Add('point_index',I);
      O.Add('coordinate_m',CoordinateJSON(CP.Coordinate,LengthFactor(M))); Leaks.Add(O); end;
  end;
  for I:=0 to M.Surface.NumberOfControlFaces-1 do
    if VectorLength(M.Surface.ControlFace[I].FaceNormal)<1e-8 then Inc(Degenerate);
  Result.Add('nonmanifold_edges',NonManifold); Result.Add('inconsistent_normal_edges',BadNormals);
  Result.Add('degenerate_faces',Degenerate); Result.Add('open_boundary_points',Leaks);
  Result.Add('scope','Topology, adjacent face orientation and native leak candidates; no global self-intersection proof');
end;
procedure MakeBox(M: TFreeShip; R: TJSONObject);
var L,B,H: Double; P: array[0..7] of T3DCoordinate; I: Integer;
begin
  L:=R.Get('length_m',20.0); B:=R.Get('beam_m',6.0); H:=R.Get('height_m',8.0);
  if (L<=0) or (B<=0) or (H<=0) then raise Exception.Create('Box dimensions must be positive');
  P[0]:=SetPoint(0,0,0); P[1]:=SetPoint(0,B/2,0); P[2]:=SetPoint(L,B/2,0); P[3]:=SetPoint(L,0,0);
  P[4]:=SetPoint(0,0,H); P[5]:=SetPoint(0,B/2,H); P[6]:=SetPoint(L,B/2,H); P[7]:=SetPoint(L,0,H);
  M.Surface.AddControlFace([P[0],P[1],P[2],P[3]],4); M.Surface.AddControlFace([P[1],P[5],P[6],P[2]],4);
  M.Surface.AddControlFace([P[0],P[4],P[5],P[1]],4); M.Surface.AddControlFace([P[3],P[2],P[6],P[7]],4);
  for I:=0 to M.Surface.NumberOfControlFaces-1 do M.Surface.ControlFace[I].Layer:=M.ActiveLayer;
  for I:=0 to M.Surface.NumberOfControlEdges-1 do M.Surface.ControlEdge[I].Crease:=True;
  for I:=0 to M.Surface.NumberOfControlPoints-1 do M.Surface.ControlPoint[I].VertexType:=svCorner;
  M.ProjectSettings.ProjectLength:=L; M.ProjectSettings.ProjectBeam:=B;
  M.ProjectSettings.ProjectDraft:=R.Get('draft_m',4.0);
  M.ProjectSettings.ProjectWaterDensity:=R.Get('density_t_m3',1.025);
  M.ProjectSettings.ProjectAppendageCoefficient:=R.Get('appendage_coefficient',1.0);
  M.ProjectSettings.SavePreview:=False; M.FileVersion:=fv462; M.Built:=False;
  if R.Get('imperial_storage',False) then
  begin
    M.ProjectSettings.ProjectUnits:=fuImperial;
    { Test-model input is SI. Set the physical density explicitly after the
      upstream unit setter, whose legacy Lbs constant is nonstandard. }
    M.ProjectSettings.ProjectWaterDensity:=R.Get('density_t_m3',1.025)*Power(0.3048,3)/0.00045359237;
  end;
end;
procedure AddSections(M: TFreeShip; R: TJSONObject);
var Kind,I,J,Existing: Integer; Values: TJSONArray; Key: String; T: TFreeIntersectionType; F: Double;
    Section: TFreeIntersection; Plane: T3DPlane;
    Found: Boolean;
begin
  F:=LengthFactor(M);
  if R.Get('replace_existing',True) then
  begin
    while M.NumberOfStations>0 do M.Station[0].Delete(False);
    while M.NumberOfWaterlines>0 do M.Waterline[0].Delete(False);
    while M.NumberOfButtocks>0 do M.Buttock[0].Delete(False);
  end;
  for Kind:=0 to 2 do
  begin
    case Kind of
      0:begin Key:='stations_m'; T:=fiStation; end;
      1:begin Key:='waterlines_m'; T:=fiWaterline; end;
      2:begin Key:='buttocks_m'; T:=fiButtock; end;
    end;
    if R.Find(Key)<>nil then
    begin Values:=R.Arrays[Key];
      for I:=0 to Values.Count-1 do
      begin
        case T of fiStation:Existing:=M.NumberOfStations; fiWaterline:Existing:=M.NumberOfWaterlines;
          fiButtock:Existing:=M.NumberOfButtocks; end;
        Found:=False;
        for J:=0 to Existing-1 do
        begin
          case T of fiStation:Section:=M.Station[J]; fiWaterline:Section:=M.Waterline[J];
            fiButtock:Section:=M.Buttock[J]; end;
          if Abs(Section.Distance-Values.Floats[I]/F)<1e-5 then Found:=True;
        end;
        if Found then Continue;
        Section:=M.Edit.Intersection_Add(T,Values.Floats[I]/F);
        if Section=nil then
        begin
          { Keep explicitly requested empty endpoint stations as positions.
            The original GUI helper discards these; no curve is invented. }
          Section:=TFreeIntersection.Create(M); Section.IntersectionType:=T;
          Plane.a:=0; Plane.b:=0; Plane.c:=0; Plane.d:=-Values.Floats[I]/F;
          case T of fiStation:Plane.a:=1; fiWaterline:Plane.c:=1; fiButtock:Plane.b:=1; end;
          Section.Plane:=Plane; Section.Rebuild; M.Edit.Intersection_AddToList(Section);
        end;
      end;
    end;
  end;
end;
procedure MakeMesh(M: TFreeShip; R: TJSONObject);
var Points,Faces,V,Face: TJSONArray; P: array of T3DCoordinate; I,J,Index: Integer;
begin
  Points:=R.Arrays['points_m']; Faces:=R.Arrays['faces'];
  for I:=0 to Faces.Count-1 do
  begin
    Face:=TJSONArray(Faces[I]); SetLength(P,Face.Count);
    if Face.Count<3 then raise Exception.Create('Face needs three points');
    for J:=0 to Face.Count-1 do
    begin
      Index:=Face.Integers[J];
      if (Index<0) or (Index>=Points.Count) then raise Exception.Create('Invalid face index');
      V:=TJSONArray(Points[Index]); P[J]:=SetPoint(V.Floats[0],V.Floats[1],V.Floats[2]);
    end;
    M.Surface.AddControlFace(P,Length(P));
  end;
  if R.Get('crease_edges',False) then
    for I:=0 to M.Surface.NumberOfControlEdges-1 do M.Surface.ControlEdge[I].Crease:=True;
  for I:=0 to M.Surface.NumberOfControlFaces-1 do M.Surface.ControlFace[I].Layer:=M.ActiveLayer;
  M.ProjectSettings.ProjectLength:=R.Get('length_m',0.0);
  M.ProjectSettings.ProjectBeam:=R.Get('beam_m',0.0);
  M.ProjectSettings.ProjectDraft:=R.Get('draft_m',0.0);
  M.ProjectSettings.ProjectWaterDensity:=R.Get('density_t_m3',1.025);
  M.ProjectSettings.ProjectAppendageCoefficient:=R.Get('appendage_coefficient',1.0);
  M.ProjectSettings.SavePreview:=False; M.FileVersion:=fv462; M.Built:=False;
  M.Precision:=fpVeryHigh;
  M.Surface.Rebuild;
end;
function Lines(M: TFreeShip): TJSONArray;
var Kind,I,J,K,N,Count: Integer; Section: TFreeIntersection; S: TFreeSpline;
    O: TJSONObject; Points: TJSONArray; Params: TFloatArray; Key: String; F: Double;
begin
  Result:=TJSONArray.Create; F:=LengthFactor(M);
  for Kind:=0 to 2 do
  begin
    case Kind of
      0:begin Key:='station'; Count:=M.NumberOfStations; end;
      1:begin Key:='waterline'; Count:=M.NumberOfWaterlines; end;
      2:begin Key:='buttock'; Count:=M.NumberOfButtocks; end;
    end;
    for I:=0 to Count-1 do
    begin
      case Kind of 0:Section:=M.Station[I]; 1:Section:=M.Waterline[I]; 2:Section:=M.Buttock[I]; end;
      Section.Rebuild;
      for J:=0 to Section.Count-1 do
      begin
        S:=Section.Items[J]; S.Rebuild;
        { Same 100 fragments + knuckle parameters as FreeLinesplanFrme.AddSpline. }
        N:=0; SetLength(Params,S.NumberOfPoints+100);
        for K:=1 to S.NumberOfPoints-2 do
          if S.Knuckle[K] then begin Params[N]:=S.Parameter[K]; Inc(N); end;
        for K:=0 to 99 do begin Params[N]:=K/99; Inc(N); end;
        SortFloatArray(Params,N); Points:=TJSONArray.Create;
        for K:=0 to N-1 do Points.Add(CoordinateJSON(S.Value(Params[K]),F));
        O:=TJSONObject.Create; O.Add('kind',Key); O.Add('section_index',I);
        O.Add('distance_m',Section.Distance*F); O.Add('points_m',Points); Result.Add(O);
      end;
    end;
  end;
end;
function ExecuteRequest(Request: TJSONObject): TJSONObject;
var M: TFreeShip; Op,Path: String; I,J: Integer; F,TargetVol,TargetMass,LCB: Double;
    A: TJSONArray; Selected: array of Boolean; Transform: THeadlessLackenby; Success: Boolean;
    P: T3DCoordinate; H: TJSONObject; Results: TJSONArray;
begin
  Op:=Request.Get('operation','');
  if Op='engine_info' then
  begin
    Result:=TJSONObject.Create; Result.Add('version','0.1.0'); Result.Add('protocol_version',1);
    Result.Add('upstream_commit','1de17e99fb2b1cc559cdf27c5cafb595a627a641'); Result.Add('headless',True);
    Result.Add('float_type','IEEE 754 single (upstream)');
    Result.Add('operations',TJSONArray.Create(['inspect_model','validate_model','save_model','scale_model',
      'rebuild_hull','generate_sections','calculate_hydrostatics','calculate_hydrostatics_series','linesplan_geometry','create_box','create_mesh'])); Exit;
  end;
  M:=TFreeShip.Create(nil);
  try
    if Op='create_box' then MakeBox(M,Request)
    else if Op='create_mesh' then MakeMesh(M,Request)
    else LoadModel(M,Request.Get('model_path',''),Request.Get('encoding','cp1252'));
    F:=LengthFactor(M);
    if Op='calculate_hydrostatics' then
      Result:=Hydrostatics(M,Request.Get('draft_m',M.ProjectSettings.ProjectDraft*F),Request.Get('trim_m',0.0),Request.Get('heel_degrees',0.0))
    else if Op='calculate_hydrostatics_series' then
    begin
      A:=Request.Arrays['drafts_m']; Results:=TJSONArray.Create;
      for I:=0 to A.Count-1 do
      begin
        Results.Add(Hydrostatics(M,A.Floats[I],Request.Get('trim_m',0.0),Request.Get('heel_degrees',0.0)));
        WriteLn(StdErr,'FS_PROGRESS ',(I+1)/A.Count:0:6,' Hydrostatic draft ',I+1);
      end;
      Result:=TJSONObject.Create; Result.Add('rows',Results);
    end
    else if Op='validate_model' then Result:=Validate(M)
    else if Op='linesplan_geometry' then begin Result:=Inspect(M); Result.Add('curves',Lines(M)); end
    else
    begin
      Result:=nil;
      if Op='scale_model' then
      begin
        P:=SetPoint(Request.Get('x_factor',1.0),Request.Get('y_factor',1.0),Request.Get('z_factor',1.0));
        if (P.X<=0) or (P.Y<=0) or (P.Z<=0) then raise Exception.Create('Scale factors must be positive');
        if not Request.Get('allow_locked',False) then
          for I:=0 to M.Surface.NumberOfControlPoints-1 do
            if M.Surface.ControlPoint[I].Locked then raise Exception.Create('Model has locked points; allow_locked must be explicit');
        M.Edit.Model_Scale(P,Request.Get('allow_locked',False),Request.Get('scale_markers',True)); M.Built:=False;
        if Request.Get('x_offset_m',0.0)<>0 then
        begin
          for I:=0 to M.Surface.NumberOfControlPoints-1 do
          begin
            P:=M.Surface.ControlPoint[I].Coordinate;
            P.X:=P.X+Request.Get('x_offset_m',0.0)/F;
            M.Surface.ControlPoint[I].Coordinate:=P;
          end;
          if Request.Get('scale_markers',True) then
            for I:=0 to M.NumberOfMarkers-1 do
              for J:=0 to M.Marker[I].NumberOfPoints-1 do
              begin
                P:=M.Marker[I].Point[J]; P.X:=P.X+Request.Get('x_offset_m',0.0)/F;
                M.Marker[I].Point[J]:=P;
              end;
          M.Built:=False;
        end;
        if Request.Find('project_length_m')<>nil then
        begin
          if Request.Get('project_length_m',0.0)<=0 then raise Exception.Create('Project length must be positive');
          M.ProjectSettings.ProjectLength:=Request.Get('project_length_m',0.0)/F;
        end;
        if Request.Find('project_beam_m')<>nil then
        begin
          if Request.Get('project_beam_m',0.0)<=0 then raise Exception.Create('Project beam must be positive');
          M.ProjectSettings.ProjectBeam:=Request.Get('project_beam_m',0.0)/F;
        end;
        if Request.Find('project_draft_m')<>nil then
        begin
          if Request.Get('project_draft_m',0.0)<=0 then raise Exception.Create('Project draft must be positive');
          M.ProjectSettings.ProjectDraft:=Request.Get('project_draft_m',0.0)/F;
        end;
      end
      else if Op='generate_sections' then AddSections(M,Request)
      else if Op='rebuild_hull' then
      begin
        TargetMass:=Request.Get('displacement_t',0.0);
        if TargetMass<=0 then raise Exception.Create('Target displacement must be positive');
        TargetVol:=DisplacementToVolume(TargetMass/MassFactor(M),M.ProjectSettings.ProjectWaterDensity,
          M.ProjectSettings.ProjectAppendageCoefficient,M.ProjectSettings.ProjectUnits);
        LCB:=Request.Get('lcb_ap_m',-1.0)/F;
        if (LCB<=0) or (LCB>=M.ProjectSettings.ProjectLength) then raise Exception.Create('LCB must be inside perpendicular length');
        SetLength(Selected,M.NumberOfLayers); for I:=0 to High(Selected) do Selected[I]:=False;
        A:=Request.Arrays['layer_indices'];
        for I:=0 to A.Count-1 do
        begin J:=A.Integers[I]; if (J<0) or (J>M.NumberOfLayers-1) then raise Exception.Create('Layer index out of range'); Selected[J]:=True; end;
        Transform:=THeadlessLackenby.Create(M,LCB,Selected,Request.Get('allow_locked',False));
        try
          Transform.Transform(TargetVol,Request.Get('max_iterations',15),False,Success);
          if not Success then raise Exception.CreateFmt('Lackenby did not converge: displacement relative residual %.9g; LCB/length residual %.9g',
            [Transform.DisplacementRelativeError,Transform.LCBLengthRelativeError]);
          Result:=TJSONObject.Create; Result.Add('iterations',Transform.Iterations);
          Result.Add('sac_displacement_relative_residual',Transform.DisplacementRelativeError);
          Result.Add('sac_lcb_length_relative_residual',Transform.ActualLCBLengthRelativeError);
          Result.Add('sac_lcb_convergence_metric',Transform.LCBLengthRelativeError);
          H:=Hydrostatics(M,M.ProjectSettings.ProjectDraft*F,0,0); Result.Add('hydrostatics',H);
          Result.Add('actual_displacement_residual_t',H.Get('displacement_t',0.0)-TargetMass);
          Result.Add('actual_lcb_residual_m',H.Get('lcb_ap_m',0.0)-LCB*F);
          Result.Add('hydrostatic_targets_within_native_tolerance',
            (Abs(H.Get('displacement_t',0.0)-TargetMass)/TargetMass<=1e-4) and
            ((Abs(H.Get('lcb_ap_m',0.0)-LCB*F)/(M.ProjectSettings.ProjectLength*F)<=5e-5) or
             (Abs(H.Get('lcb_ap_m',0.0)-LCB*F)<=0.002*F)));
        finally Transform.Free; end;
      end
      else if (Op<>'inspect_model') and (Op<>'save_model') and (Op<>'create_box') and (Op<>'create_mesh') then raise Exception.Create('Unknown engine operation');
      if Result=nil then Result:=Inspect(M) else Result.Add('model',Inspect(M));
      if Op<>'inspect_model' then
      begin
        Path:=Request.Get('output_path',''); if Path='' then raise Exception.Create('output_path is required');
        SaveModel(M,Path,Request.Get('output_version',0)); Result.Add('output_path',Path);
      end;
    end;
  finally M.Free; end;
end;
end.
