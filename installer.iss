; Inno Setup script для Kitsune. RU/EN мастер установки, per-user install (без UAC).
; Cборка: "C:\Program Files (x86)\Inno Setup 6\iscc.exe" installer.iss
; На выходе: dist_installer\KitsuneSetup.exe

#define MyAppName "Kitsune"
#define MyAppVersion "0.5.0"
#define MyAppPublisher "Kitsune Project"
#define MyAppURL "https://github.com/Tawreos228/Kitsune-Connect"
#define MyAppExeName "Kitsune.exe"

[Setup]
AppId={{B6E3C3F8-K1T5-U7E2-9E10-K1TSUNEVP00}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist_installer
OutputBaseFilename=KitsuneSetup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";        Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon";    Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Главный exe + всё что собрал PyInstaller
Source: "dist\Kitsune\Kitsune.exe";        DestDir: "{app}";          Flags: ignoreversion
Source: "dist\Kitsune\_internal\*";        DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Чистим temp-артефакты приложения
Type: filesandordirs; Name: "{tmp}\kitsune_*"
Type: filesandordirs; Name: "{tmp}\kitsune_icons"

[Code]
// При удалении предлагаем убрать настройки тоже
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox(ExpandConstant('{cm:RemoveSettings}'), mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{userappdata}\Kitsune'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\Kitsune'), True, True, True);
    end;
  end;
end;

[CustomMessages]
russian.RemoveSettings=Удалить также пользовательские настройки и кэш?
english.RemoveSettings=Also remove user settings and cache?
