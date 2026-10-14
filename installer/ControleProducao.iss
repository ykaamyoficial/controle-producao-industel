#define MyAppName "Controle de Producao Industel"
#define MyAppVersion "2.8.0"
#define MyAppPublisher "Industel"
; ControleProducao.exe na raiz e o LAUNCHER (dist\Launcher): le current.json e
; abre versions\<versao>\ControleProducaoApp.exe. Atalhos e Startup apontam
; sempre para o launcher, que nao muda entre versoes.
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
OutputBaseFilename=ControleProducaoSetup-2.8.0
SetupIconFile=..\app\assets\images\Logo_Industel_Icone.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; O [Code] abaixo encerra o app, o agente de bandeja (--notifier) e o Updater
; antes de copiar. CloseApplications=force cobre o que o Restart Manager ainda
; encontrar; RestartApplications=no evita reabrir o app no meio da instalacao.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Dirs]
Name: "{commonappdata}\{#MyDataDir}"; Permissions: users-modify
Name: "{commonappdata}\{#MyDataDir}\backups"; Permissions: users-modify

[InstallDelete]
; Migracao do layout plano (2.8.x e anteriores) para o versionado: a pasta
; _internal e o Updater.exe da RAIZ eram do app antigo. O launcher traz o seu
; proprio _internal logo em seguida; o app novo vive em versions\<versao>\.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\Updater.exe"

[Files]
; Launcher (ControleProducao.exe + _internal proprio) na raiz.
Source: "..\dist\Launcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; App real (ControleProducaoApp.exe + _internal) numa pasta por versao. O
; Updater.exe vai junto: app/services/update_coordinator.py o resolve ao lado
; do executavel da versao em execucao.
Source: "..\dist\ControleProducao\*"; DestDir: "{app}\versions\{#MyAppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\Updater\*"; DestDir: "{app}\versions\{#MyAppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
; O instalador encerra o agente de avisos (--notifier); religa-o ao terminar, com o
; usuario original (nunca como administrador, senao os baloes iriam para a conta errada).
Filename: "{app}\{#MyAppExeName}"; Parameters: "--notifier"; Flags: nowait runhidden runasoriginaluser

[UninstallDelete]
Type: filesandordirs; Name: "{app}\versions"
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\current.json"

[Code]
procedure KillByImageName(const ImageName: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM ' + ImageName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ Encerra TODO processo do produto, inclusive o agente --notifier que roda em
  segundo plano e antes impedia a instalacao ("nao conseguiu fechar um processo"). }
procedure StopRunningApp();
begin
  KillByImageName('ControleProducao.exe');
  KillByImageName('ControleProducaoApp.exe');
  KillByImageName('Updater.exe');
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
  podem alterar SOMENTE esse arquivo (a pasta versions\ continua so de
  administrador), para o Updater ativar uma versao ja preparada sem novo UAC. }
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
