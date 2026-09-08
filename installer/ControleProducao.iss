#define MyAppName "Controle de Producao Industel"
#define MyAppVersion "2.7.1"
#define MyAppPublisher "Industel"
#define MyAppExeName "ControleProducao.exe"
#define MyAppDir "Industel\Controle de Producao"
#define MyDataDir "Industel\ControleProducao"

[Setup]
AppId={{A70CE0BD-780D-45BC-B5D1-4E5D189E8E4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppDir}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=ControleProducaoSetup-2.7.1
SetupIconFile=..\app\assets\images\Logo_Industel_Icone.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Dirs]
Name: "{commonappdata}\{#MyDataDir}"; Permissions: users-modify
Name: "{commonappdata}\{#MyDataDir}\backups"; Permissions: users-modify

[Files]
Source: "..\dist\ControleProducao\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Updater.exe precisa ficar no MESMO diretorio que ControleProducao.exe --
; app/services/update_coordinator.py::_updater_launch_command() resolve o
; caminho como "exe_dir / Updater.exe" quando empacotado. Sem esta linha o
; autoupdate falha com WinError 2 (arquivo nao encontrado) ao tentar lancar
; o Updater (bug real encontrado na primeira atualizacao 2.6.0 -> 2.6.1).
Source: "..\dist\Updater\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
