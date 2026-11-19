<#
Valida o --activate do Updater SEM administrador, numa pasta com a ACL do instalador
(usuario atual nao cria arquivo na raiz; Modify so em current.json). Nao toca em
C:\Program Files nem em C:\ProgramData\Industel: tudo vai para -Work.

Pre-requisitos: dist\Updater e dist\Launcher gerados (PyInstaller) e um "app de mentira"
(-StandinExe) que, ao receber --post-update <id>, grava <CONTROLE_PRODUCAO_DATA_DIR>\updater\handshake\<id>.ok.

Uso: powershell -File scripts\validar_activate_sem_admin.ps1 -Work <pasta vazia> -StandinExe <exe>
Saida 0 = ponteiro trocou para a versao nova sem elevacao e o handshake foi confirmado.
#>
param(
    [Parameter(Mandatory)][string]$Work,
    [Parameter(Mandatory)][string]$StandinExe,
    [string]$Dist = '',
    [string]$OldVersion = '2.10.0',
    [string]$NewVersion = '2.10.1',
    [string]$OldUpdaterRepo = ''   # controle negativo: roda 'python -m app.updater' deste checkout antigo no lugar do Updater.exe novo
)
$ErrorActionPreference = 'Stop'
if (-not $Dist) { $Dist = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) 'dist' }
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if (([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Rode SEM elevacao (esta sessao e administrador elevada).'
}
if (Test-Path $Work) { throw "-Work ja existe: $Work (use uma pasta nova)" }
$install = Join-Path $Work 'install'; $data = Join-Path $Work 'data'
New-Item -ItemType Directory -Force $install, $data | Out-Null

# Layout igual ao instalador: launcher na raiz, versions\<v> com app + Updater, current.json.
Copy-Item -Recurse (Join-Path $Dist 'Launcher\*') $install
foreach ($v in @($OldVersion, $NewVersion)) {
    $dir = Join-Path $install "versions\$v"
    New-Item -ItemType Directory -Force $dir | Out-Null
    Copy-Item $StandinExe (Join-Path $dir 'ControleProducaoApp.exe')
    Set-Content -NoNewline -Encoding ascii (Join-Path $dir 'VERSION') "$v`n"
}
Copy-Item -Recurse (Join-Path $Dist 'Updater\*') (Join-Path $install "versions\$OldVersion")   # Updater novo, como o que roda
$pointer = Join-Path $install 'current.json'
[IO.File]::WriteAllText($pointer, "{`"schema`": 1, `"version`": `"$OldVersion`", `"dir`": `"versions/$OldVersion`", `"previous_version`": null, `"updated_at`": `"`"}", (New-Object Text.UTF8Encoding($false)))

# ACL do instalador: sem heranca; usuarios leem/executam; Modify so no ARQUIVO current.json.
& icacls $install /inheritance:r /Q | Out-Null
& icacls $install /grant:r '*S-1-5-32-545:(OI)(CI)RX' /Q | Out-Null
& icacls $pointer /grant '*S-1-5-32-545:(M)' /Q | Out-Null
& icacls $install | Write-Host
# Prova de que a raiz esta travada e o ponteiro nao:
$canCreate = $true; try { New-Item -ItemType File (Join-Path $install 'x.tmp') -ErrorAction Stop | Out-Null; Remove-Item (Join-Path $install 'x.tmp') } catch { $canCreate = $false }
if ($canCreate) { throw 'ACL nao travou a raiz (consegui criar arquivo): teste invalido.' }
Write-Host 'OK: nao crio arquivo na raiz.'

$requestId = 'validacao-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$request = [ordered]@{
    request_id = $requestId; current_version = $OldVersion; target_version = $NewVersion
    package_url_or_source = (Join-Path $Work 'pacote-nao-usado-no-activate.zip')
    install_dir = $install; executable_path = (Join-Path $install 'ControleProducao.exe')
    parent_pid = $PID; restart_args = @()
}
$requestFile = Join-Path $Work 'request.json'
[IO.File]::WriteAllText($requestFile, ($request | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))

$env:CONTROLE_PRODUCAO_DATA_DIR = $data
$updater = Join-Path $install "versions\$OldVersion\Updater.exe"
if ($OldUpdaterRepo) {
    Push-Location $OldUpdaterRepo
    $p = Start-Process -FilePath 'python' -ArgumentList @('-m', 'app.updater', '--request', "`"$requestFile`"", '--activate') -Wait -PassThru -NoNewWindow
    Pop-Location
} else {
    $p = Start-Process -FilePath $updater -ArgumentList @('--request', "`"$requestFile`"", '--activate') -Wait -PassThru -NoNewWindow
}
Write-Host "Updater --activate exit=$($p.ExitCode)"
$after = Get-Content -Raw $pointer | ConvertFrom-Json
Write-Host "current.json: version=$($after.version) previous_version=$($after.previous_version)"
$log = Join-Path $data 'updater\logs\updater.log'
if (Test-Path $log) { Get-Content $log | Select-Object -Last 12 | Write-Host }
if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'update_elevation_required' -Quiet)) { throw 'FALHA: o Updater pediu elevacao.' }
$status = Get-ChildItem (Join-Path $data 'updater\status') -Filter '*.json' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($status) { Get-Content $status.FullName | Write-Host }
if ($p.ExitCode -ne 0 -or $after.version -ne $NewVersion -or $after.previous_version -ne $OldVersion) { throw 'FALHA: ponteiro nao trocou como esperado.' }
Write-Host "VALIDADO sem administrador: $OldVersion -> $NewVersion."
