; EDICAO DE TESTE: instala em paralelo ao oficial. Nada aqui e compartilhado com
; installer\ControleProducao.iss (AppId, pasta, grupo, executaveis, dados, taskkill).
; Usado por scripts\build_test_installer.py (PyInstaller com
; CONTROLE_PRODUCAO_EDITION=teste -> dist_teste\ e build_teste\).
#define MyAppName "Controle de Producao Industel TESTE"
#define MyAppVersion "2.9.0"
#define MyAppPublisher "Industel"
; ControleProducaoTeste.exe na raiz e o LAUNCHER de teste (le current.json e abre
; versions\<versao>\ControleProducaoTesteApp.exe).
#define MyAppExeName "ControleProducaoTeste.exe"
#define MyAppDir "Industel\Controle de Producao TESTE"
#define MyDataDir "Industel\ControleProducaoTeste"

[Setup]
AppId={{5B3F8E2A-7C41-4D9E-A6B0-3E7D12C94F58}
AppName={#MyAppName}
AppVersion={#MyAppVersion}-teste
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppDir}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release\teste
OutputBaseFilename=ControleProducaoTesteSetup-2.9.0
SetupIconFile=..\build_teste\assets\images\Logo_Industel_Icone.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; O [Code] abaixo encerra SO os processos de teste (nomes proprios). Nunca mira
; Os executaveis oficiais nunca sao alvo.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Dirs]
Name: "{commonappdata}\{#MyDataDir}"; Permissions: users-modify
Name: "{commonappdata}\{#MyDataDir}\backups"; Permissions: users-modify

[Registry]
; Nada e criado aqui: so limpa, na desinstalacao, o que o app de teste grava no HKCU
; (inicio com o Windows do agente de avisos e identidade dos baloes).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "ControleProducaoIndustelTesteNotificacoes"; Flags: dontcreatekey uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\AppUserModelId\{#MyAppName}"; ValueType: none; Flags: dontcreatekey uninsdeletekey

[InstallDelete]
; Limpa a pasta da versao: DLLs de instalacao anterior (ex.: icuuc.dll) quebram o import do QtWidgets.
Type: filesandordirs; Name: "{app}\versions\{#MyAppVersion}"

[Files]
; Config de teste (API de dev 8001), so se ainda nao existir; o app tambem a forca por codigo.
Source: "..\build_teste\controle_producao_config.json"; DestDir: "{commonappdata}\{#MyDataDir}"; Flags: onlyifdoesntexist
; Launcher de teste (ControleProducaoTeste.exe + _internal proprio) na raiz.
Source: "..\dist_teste\Launcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; App de teste + UpdaterTeste.exe numa pasta por versao.
Source: "..\dist_teste\ControleProducaoTeste\*"; DestDir: "{app}\versions\{#MyAppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist_teste\UpdaterTeste\*"; DestDir: "{app}\versions\{#MyAppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
; Agente de avisos (--notifier) de teste, com o usuario original (nunca como administrador).
Filename: "{app}\{#MyAppExeName}"; Parameters: "--notifier"; Flags: nowait runhidden runasoriginaluser

[UninstallDelete]
Type: filesandordirs; Name: "{app}\versions"
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\current.json"
; Dados proprios da edicao de teste (config, logs de updates, backups).
Type: filesandordirs; Name: "{commonappdata}\{#MyDataDir}"

[Code]
procedure KillByImageName(const ImageName: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM ' + ImageName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ Encerra TODO processo da edicao de TESTE (inclusive o agente --notifier). }
procedure StopRunningApp();
begin
  KillByImageName('ControleProducaoTeste.exe');
  KillByImageName('ControleProducaoTesteApp.exe');
  KillByImageName('UpdaterTeste.exe');
  Sleep(800);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp();
  Result := True;
end;

{ current.json aponta o launcher para a versao instalada. Usuarios comuns
  podem alterar SOMENTE esse arquivo. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  PointerFile: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    PointerFile := ExpandConstant('{app}\current.json');
    SaveStringToFile(PointerFile,
      '{"schema": 1, "version": "{#MyAppVersion}", "dir": "versions/{#MyAppVersion}", "previous_version": null, "updated_at": ""}',
      False);
    Exec(ExpandConstant('{sys}\icacls.exe'), '"' + PointerFile + '" /grant *S-1-5-32-545:(M)', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
