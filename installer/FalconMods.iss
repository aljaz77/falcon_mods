; FalconMods installer (Inno Setup 6)
; Installs into the existing Falcon Design Space folder, patches its UI resources and
; restores the original files on uninstall. Nothing from Creality is shipped in this installer.

#ifndef AppVer
  #define AppVer "1.0.0"
#endif

[Setup]
AppId={{6F1C2B8A-3D4E-4F5A-9B6C-7D8E9F0A1B2C}
AppName=FalconMods for Falcon Design Space
AppVersion={#AppVer}
AppVerName=FalconMods {#AppVer}
AppPublisher=FalconMods (unofficial community mod)
AppComments=Bed-grid quick camera calibration, extra fill patterns and spiral fill for the Creality Falcon A1
DefaultDirName={code:DefaultFalconDir}
AppendDefaultDirName=no
DirExistsWarning=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
UninstallFilesDir={app}\falconmods\uninstall
UninstallDisplayName=FalconMods {#AppVer} (Falcon Design Space mod)
UninstallDisplayIcon={app}\falconmods\bedgrid\FalconBedGridCalib.exe
OutputDir=..\dist
OutputBaseFilename=FalconMods-Setup-{#AppVer}
SetupIconFile=falconmods.ico
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
InfoBeforeFile=disclaimer.txt
CloseApplications=no

[Messages]
SelectDirDesc=Where is Falcon Design Space installed?
SelectDirLabel3=FalconMods is installed into your Falcon Design Space folder. Select that folder (it contains FalconDesignSpace.exe).

[Tasks]
Name: "bedgrid"; Description: "Quick Calibration: camera calibration from the bed grid (Falcon A1)"
Name: "fill"; Description: "Extra fill patterns for gantry lasers: Offset (concentric), Cross, Zigzag + fill angle"
Name: "spiral"; Description: "Spiral fill tool: one continuous spiral line instead of separate rings"

[Files]
Source: "..\build\dist\bedgrid\*"; DestDir: "{app}\falconmods\bedgrid"; Flags: recursesubdirs ignoreversion
Source: "..\build\dist\FalconModsPatcher.exe"; DestDir: "{app}\falconmods"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\falconmods"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}\falconmods"; Flags: ignoreversion

[Registry]
Root: HKA; Subkey: "Software\Classes\falconbedgrid"; ValueType: string; ValueName: ""; ValueData: "URL:Falcon Bed-Grid Calibration"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\falconbedgrid"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\falconbedgrid\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\falconmods\bedgrid\FalconBedGridCalib.exe"",0"
Root: HKA; Subkey: "Software\Classes\falconbedgrid\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\falconmods\bedgrid\FalconBedGridCalib.exe"" ""%1"""

[Icons]
Name: "{autoprograms}\FalconMods\Falcon Bed-Grid Calibration"; Filename: "{app}\falconmods\bedgrid\FalconBedGridCalib.exe"
Name: "{autoprograms}\FalconMods\FalconMods User Guide"; Filename: "{app}\falconmods\USER_GUIDE.md"
Name: "{autoprograms}\FalconMods\Uninstall FalconMods"; Filename: "{uninstallexe}"

[UninstallRun]
Filename: "{app}\falconmods\FalconModsPatcher.exe"; Parameters: "uninstall --app ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "RestoreOriginalResources"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\falconmods"

[Code]
function FindFalconInUninstallKeys(Root: Integer; var Dir: String): Boolean;
var
  Keys: TArrayOfString;
  I: Integer;
  Base, Name, Loc: String;
begin
  Result := False;
  Base := 'Software\Microsoft\Windows\CurrentVersion\Uninstall';
  if RegGetSubkeyNames(Root, Base, Keys) then
    for I := 0 to GetArrayLength(Keys) - 1 do
      if RegQueryStringValue(Root, Base + '\' + Keys[I], 'DisplayName', Name) and
         (Pos('Falcon Design Space', Name) = 1) and
         RegQueryStringValue(Root, Base + '\' + Keys[I], 'InstallLocation', Loc) and
         FileExists(AddBackslash(Loc) + 'FalconDesignSpace.exe') then
      begin
        Dir := RemoveBackslashUnlessRoot(Loc);
        Result := True;
        Exit;
      end;
end;

function DefaultFalconDir(Param: String): String;
begin
  if not FindFalconInUninstallKeys(HKLM64, Result) then
    if not FindFalconInUninstallKeys(HKCU, Result) then
      Result := ExpandConstant('{commonpf64}\Falcon Design Space');
end;

function FalconRunning: Boolean;
var
  Locator, Service, Procs: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''FalconDesignSpace.exe''');
    Result := Procs.Count > 0;
  except
  end;
end;

function WaitForFalconClosed: Boolean;
begin
  Result := True;
  while FalconRunning do
    if MsgBox('Falcon Design Space is running.' #13#10 'Please close it, then click Retry.',
              mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

function InitializeSetup: Boolean;
begin
  Result := WaitForFalconClosed;
end;

function InitializeUninstall: Boolean;
begin
  Result := WaitForFalconClosed;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not FileExists(AddBackslash(WizardDirValue) + 'FalconDesignSpace.exe') then
  begin
    MsgBox('FalconDesignSpace.exe was not found in this folder.' #13#10 +
           'Please select the folder where Falcon Design Space is installed.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Args, LogFile, Output: String;
  Code: Integer;
  Text: AnsiString;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Args := '';
  if WizardIsTaskSelected('bedgrid') then Args := Args + ' --patch bedgrid_calibration';
  if WizardIsTaskSelected('fill') then Args := Args + ' --patch fill_patterns';
  if WizardIsTaskSelected('spiral') then Args := Args + ' --patch spiral_fill';
  LogFile := ExpandConstant('{app}\falconmods\install.log');
  if Args = '' then
    Exit;
  WizardForm.StatusLabel.Caption := 'Patching Falcon Design Space...';
  Exec(ExpandConstant('{cmd}'),
       '/C ""' + ExpandConstant('{app}\falconmods\FalconModsPatcher.exe') + '" install --app "' +
       ExpandConstant('{app}') + '"' + Args + ' > "' + LogFile + '" 2>&1"',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  if Code <> 0 then
  begin
    Output := '';
    if LoadStringFromFile(LogFile, Text) then
      Output := String(Text);
    MsgBox('Patching Falcon Design Space failed (code ' + IntToStr(Code) + ').' #13#10#13#10 + Output + #13#10 +
           'Your Falcon Design Space files were not changed. The stand-alone ' +
           'Bed-Grid Calibration tool is still installed (Start menu > FalconMods).', mbError, MB_OK);
  end;
end;
