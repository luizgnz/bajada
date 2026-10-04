[Setup]
AppId={{4900C11D-9D5F-45B0-9B2F-897E744C03C2}
AppName=Bajada
AppVersion=0.7.0
DefaultDirName={localappdata}\Programs\DescargaFacil
DefaultGroupName=Bajada
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=Bajada-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\bajada.ico
MinVersion=10.0.19041
UninstallDisplayIcon={app}\DescargaFacil.exe
[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: checkedonce
[Dirs]
Name: "{userprofile}\Videos\Bajada"; Flags: uninsneveruninstall
[Files]
Source: "..\dist\DescargaFacil\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Bajada"; Filename: "{app}\DescargaFacil.exe"
Name: "{autodesktop}\Bajada"; Filename: "{app}\DescargaFacil.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\DescargaFacil.exe"; Description: "Abrir Bajada"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if not Exec(ExpandConstant('{app}\DescargaFacil.exe'), '--self-check',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException('No se pudieron comprobar los componentes de Bajada.');
    if ExitCode <> 0 then
      RaiseException('Falta un componente o no puede ejecutarse. La instalación no se completó correctamente.');
  end;
end;
