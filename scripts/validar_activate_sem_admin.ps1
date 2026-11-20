<#
Valida o --activate do Updater SEM administrador, numa pasta com a ACL do instalador
(usuario atual nao cria arquivo na raiz; Modify so em current.json). Nao toca em
C:\Program Files nem em C:\ProgramData\Industel: tudo vai para -Work.

Pre-requisitos: dist\Updater e dist\Launcher gerados (PyInstaller) e um "app de mentira"
(-StandinExe) que, ao receber --post-update <id>, grava <CONTROLE_PRODUCAO_DATA_DIR>\updater\handshake\<id>.ok.

Cenarios (-Cenario):
  Sucesso        (padrao) ponteiro troca para a versao nova sem elevacao, handshake confirmado,
                 fases CLOSING -> RESTARTING -> SUCCESS no updater.log.
  FalhaPonteiro  nega escrita em current.json ao usuario atual e roda o --activate com --no-elevate,
                 com um "app de mentira" VIVO dentro da pasta da versao antiga. Exige: exit 1, status FAILED
                 em pt-BR, current.json inalterado, sem quit.request e o processo de mentira ainda vivo
                 (o programa nao pode fechar quando a troca de versao falha).

Todos os cenarios rodam o Updater com --no-elevate (nunca aparece UAC).

Uso: powershell -File scripts\validar_activate_sem_admin.ps1 -Work <pasta vazia> -StandinExe <exe> [-Cenario Sucesso|FalhaPonteiro]
Saida 0 = cenario validado.
#>
param(
    [Parameter(Mandatory)][string]$Work,
    [Parameter(Mandatory)][string]$StandinExe,
    [ValidateSet('Sucesso', 'FalhaPonteiro')][string]$Cenario = 'Sucesso',
    [string]$Dist = '',
    [string]$OldVersion = '2.10.0',
    [string]$NewVersion = '2.10.2',
    [string]$OldUpdaterRepo = ''   # controle negativo: roda 'python -m app.updater' deste checkout antigo (sem --no-elevate) no lugar do Updater.exe novo
)
$ErrorActionPreference = 'Stop'
if (-not $Dist) { $Dist = Join-Path (Split-Path -Parent (Split-Path -Parent $PSCommandPath)) 'dist' }
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
# O exe de mentira entra antes do icacls: depois dele o usuario nao cria arquivo na pasta.
if ($Cenario -eq 'FalhaPonteiro') { Copy-Item (Join-Path $env:SystemRoot 'System32\ping.exe') (Join-Path $install "versions\$OldVersion\app-de-mentira.exe") }
& icacls $install /inheritance:r /Q | Out-Null
& icacls $install /grant:r '*S-1-5-32-545:(OI)(CI)RX' /Q | Out-Null
& icacls $pointer /grant '*S-1-5-32-545:(M)' /Q | Out-Null
& icacls $install | Write-Host
# Prova de que a raiz esta travada e o ponteiro nao:
$canCreate = $true; try { New-Item -ItemType File (Join-Path $install 'x.tmp') -ErrorAction Stop | Out-Null; Remove-Item (Join-Path $install 'x.tmp') } catch { $canCreate = $false }
if ($canCreate) { throw 'ACL nao travou a raiz (consegui criar arquivo): teste invalido.' }
Write-Host 'OK: nao crio arquivo na raiz.'

$fake = $null
$pointerDenied = $false
try {
    if ($Cenario -eq 'FalhaPonteiro') {
        # Nega escrita no ponteiro (a negacao vence o Modify de Users) e prova que a escrita realmente falha.
        & icacls $pointer /deny "${me}:(WD,AD,WA,WEA)" /Q | Out-Null
        $pointerDenied = $true
        $canWrite = $true; try { $fs = [IO.File]::Open($pointer, 'Open', 'ReadWrite'); $fs.Close() } catch { $canWrite = $false }
        if ($canWrite) { throw 'ACL nao negou a escrita em current.json: teste invalido.' }
        Write-Host 'OK: nao escrevo em current.json.'
        # "App de mentira" vivo DENTRO da pasta da versao antiga (e o que o Updater mataria se fechasse o app); copiado la antes do icacls.
        $fakeExe = Join-Path $install "versions\$OldVersion\app-de-mentira.exe"
        $fake = Start-Process -FilePath $fakeExe -ArgumentList @('-n', '600', '127.0.0.1') -WindowStyle Hidden -PassThru
        Start-Sleep -Milliseconds 500
        if ($fake.HasExited) { throw 'O app de mentira nao subiu: teste invalido.' }
    }
    $pointerBefore = [IO.File]::ReadAllText($pointer)

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
        $p = Start-Process -FilePath $updater -ArgumentList @('--request', "`"$requestFile`"", '--activate', '--no-elevate') -Wait -PassThru -NoNewWindow
    }
    Write-Host "Updater --activate exit=$($p.ExitCode)"

    if ($pointerDenied) { & icacls $pointer /remove:d $me /Q | Out-Null; $pointerDenied = $false }   # libera para ler/comparar
    $pointerAfterText = [IO.File]::ReadAllText($pointer)
    $after = $pointerAfterText | ConvertFrom-Json
    Write-Host "current.json: version=$($after.version) previous_version=$($after.previous_version)"
    $log = Join-Path $data 'updater\logs\updater.log'
    if (Test-Path $log) { Get-Content $log | Select-Object -Last 14 | Write-Host }
    if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'update_elevation_required' -Quiet)) { throw 'FALHA: o Updater pediu elevacao.' }
    $statusFile = Join-Path $data "updater\status\$requestId.json"
    $status = $null
    if (Test-Path $statusFile) { $status = Get-Content -Raw -Encoding UTF8 $statusFile | ConvertFrom-Json; Write-Host (Get-Content -Raw -Encoding UTF8 $statusFile) }
    $quitFile = Join-Path $data 'updater\quit.request'

    if ($Cenario -eq 'Sucesso') {
        if ($p.ExitCode -ne 0 -or $after.version -ne $NewVersion -or $after.previous_version -ne $OldVersion) { throw 'FALHA: ponteiro nao trocou como esperado.' }
        $phases = @()
        if (Test-Path $log) { $phases = @(Select-String -Path $log -Pattern "versioned_status \| request_id=$requestId \| phase=(\w+)" | ForEach-Object { $_.Matches[0].Groups[1].Value }) }
        $order = ($phases -join '>')
        Write-Host "Fases: $order"
        if ($order -notmatch 'CLOSING>RESTARTING>SUCCESS$') { throw "FALHA: fases fora de ordem (esperado ...CLOSING>RESTARTING>SUCCESS): $order" }
        if (-not $status -or $status.phase -ne 'SUCCESS') { throw 'FALHA: status final nao e SUCCESS.' }
        Write-Host "VALIDADO sem administrador: $OldVersion -> $NewVersion."
    } else {
        if ($p.ExitCode -ne 1) { throw "FALHA: esperado exit 1, veio $($p.ExitCode)." }
        if (-not $status -or $status.phase -ne 'FAILED') { throw 'FALHA: status final nao e FAILED.' }
        if ($status.message -notmatch 'continua aberto' -or $status.message -notmatch 'current\.json') { throw "FALHA: mensagem sem o texto esperado em pt-BR: $($status.message)" }
        if ($pointerAfterText -ne $pointerBefore) { throw 'FALHA: current.json foi alterado.' }
        if (Test-Path $quitFile) { throw 'FALHA: quit.request foi criado (o programa seria fechado).' }
        $fake.Refresh()
        if ($fake.HasExited) { throw 'FALHA: o app de mentira foi encerrado (o programa nao pode fechar se a troca falha).' }
        Write-Host "VALIDADO (FalhaPonteiro): FAILED em pt-BR, current.json intacto, sem quit.request, programa ainda vivo."
    }
} finally {
    if ($pointerDenied) { & icacls $pointer /remove:d $me /Q | Out-Null }
    if ($fake -and -not $fake.HasExited) { Stop-Process -Id $fake.Id -Force -ErrorAction SilentlyContinue }
}
