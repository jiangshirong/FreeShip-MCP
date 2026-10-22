program freeship_engine;
{$mode objfpc}{$H+}
{$if FPC_FULLVERSION <> 30202}{$fatal This engine requires Free Pascal 3.2.2}{$endif}
{$ifndef LCLnogui}{$fatal This engine requires the LCL nogui widgetset}{$endif}
uses Interfaces, SysUtils, Classes, fpjson, jsonparser, HeadlessModel;
var Request: TJSONData; Response: TJSONObject; Line: String; Failed: Boolean;
begin
  SetMultiByteConversionCodePage(CP_UTF8);
  SetMultiByteFileSystemCodePage(CP_UTF8);
  SetMultiByteRTLFileSystemCodePage(CP_UTF8);
  SetTextCodePage(Input,CP_UTF8); SetTextCodePage(Output,CP_UTF8); SetTextCodePage(StdErr,CP_UTF8);
  DefaultFormatSettings.DecimalSeparator:='.';
  Request:=nil; Response:=nil; Failed:=False;
  try
    ReadLn(Line); Request:=GetJSON(Line);
    if not (Request is TJSONObject) then raise Exception.Create('Request must be an object');
    Response:=ExecuteRequest(TJSONObject(Request)); Response.Add('ok',True);
  except on E:Exception do
    begin
      Response.Free; Response:=TJSONObject.Create;
      Response.Add('ok',False); Response.Add('error',E.ClassName+': '+E.Message);
      WriteLn(StdErr,E.ClassName,': ',E.Message); Failed:=True;
    end;
  end;
  WriteLn(Response.AsJSON); Request.Free; Response.Free;
  if Failed then Halt(1);
end.
