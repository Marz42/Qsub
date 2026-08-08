; QwenSubtitle Inno Setup 7 script (Phase 8 — Spec §5, §39)
; Build via: uv run python scripts/build_installer.py
;
; Requires a prepared portable tree at SourceDir (default:
;   dist\portable\QwenSubtitle)
; Full offline release must include models\ (build_runtime.py --with-models).

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#ifndef SourceDir
  #define SourceDir "..\..\dist\portable\QwenSubtitle"
#endif

#ifndef OutputDir
  #define OutputDir "..\..\dist\installer"
#endif

#define MyAppName "QwenSubtitle"
#define MyAppPublisher "QwenSubtitle"
#define MyAppURL "https://github.com/"
#define MyAppExeName "QwenSubtitle.vbs"

[Setup]
AppId={{B2E8F0A1-6C3D-4E9F-A17B-8D4C2E5F9012}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\licenses\LICENSE.txt
InfoBeforeFile=..\..\licenses\THIRD_PARTY_NOTICES.txt
OutputDir={#OutputDir}
OutputBaseFilename=QwenSubtitle-Setup
SetupIconFile=
UninstallDisplayIcon={app}\runtime\Scripts\pythonw.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Spec §39: full offline tree exceeds 4 GB — use disk spanning
DiskSpanning=yes
DiskSliceSize=2100000000
AllowNoIcons=yes
ChangesEnvironment=no
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addpath"; Description: "将 qsub.cmd 所在目录加入用户 PATH（可选）"; GroupDescription: "高级:"; Flags: unchecked

[Files]
; Exclude test trees / caches to shrink the offline package (runtime still works).
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "__pycache__\*,*.pyc,*.pyo,.pytest_cache\*,*\tests\*,*\test\*,*\testing\*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "本地离线字幕生成"
Name: "{group}\qsub CLI 帮助"; Filename: "{cmd}"; Parameters: "/k ""{app}\qsub.cmd"" --help"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Optional user PATH append for CLI (qsub.cmd)
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Tasks: addpath; \
  Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent shellexec

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  { Avoid duplicate PATH entries (case-insensitive) }
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
