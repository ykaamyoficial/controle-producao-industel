<#
Destrava a atualizacao do Controle de Producao em PC que ainda esta na 2.9.0 (ou na 2.10.0).

Quando "Atualizar agora" prepara a nova versao mas falha ao trocar de versao (instalador antigo
nao deixava o usuario comum criar arquivo na pasta do programa), a pasta
<InstallRoot>\versions\<nova> ja esta pronta. Este script so aponta o current.json para a MAIOR
versao (>= 2.10.0) pronta em versions\ (com ControleProducaoApp.exe e arquivo VERSION igual ao nome da pasta).
Nao precisa de administrador: usuario comum pode alterar o arquivo current.json.

Uso (duplo clique em destravar_atualizacao_2_10.bat, ou):
  powershell -ExecutionPolicy Bypass -File destravar_atualizacao_2_10.ps1 [-InstallRoot <pasta>] [-BackupDir <pasta>]
Codigos de saida: 0 apontou (ou ja estava certo); 1 nada pronto/erro.
#>
param(
    [string]$InstallRoot = (Join-Path ${env:ProgramFiles} 'Industel\Controle de Producao'),
    [string]$BackupDir = ''
)
$ErrorActionPreference = 'Stop'
$MinVersion = [version]'2.10.0'
$AppExe = 'ControleProducaoApp.exe'

function Fail([string]$msg) { Write-Host ''; Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path -LiteralPath $InstallRoot -PathType Container)) { Fail "Pasta do programa nao encontrada: $InstallRoot" }
$pointerFile = Join-Path $InstallRoot 'current.json'
$versionsDir = Join-Path $InstallRoot 'versions'

# Maior versao (>= 2.10.0) realmente pronta.
$ready = @()
if (Test-Path -LiteralPath $versionsDir -PathType Container) {
    foreach ($dir in Get-ChildItem -LiteralPath $versionsDir -Directory) {
        if ($dir.Name -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') { continue }
        if ([version]$dir.Name -lt $MinVersion) { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $dir.FullName $AppExe) -PathType Leaf)) { continue }
        $marker = Join-Path $dir.FullName 'VERSION'
        if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { continue }
        if ((Get-Content -LiteralPath $marker -Raw).Trim() -ne $dir.Name) { continue }
        $ready += [version]$dir.Name
    }
}
if ($ready.Count -eq 0) {
    Write-Host 'Nenhuma versao nova (2.10.0 ou maior) esta pronta neste PC.'
    Write-Host 'Abra o Controle de Producao e clique em "Atualizar agora" primeiro (aceite o aviso do Windows).'
    Write-Host 'Se isso ja falhou, ou o botao nao aparece, instale o Setup mais novo (ControleProducaoSetup-2.10.x.exe).'
    exit 1
}
$target = ($ready | Sort-Object -Descending | Select-Object -First 1).ToString()

# Versao hoje ativa (vira previous_version).
$previous = $null
if (Test-Path -LiteralPath $pointerFile -PathType Leaf) {
    try { $current = (Get-Content -LiteralPath $pointerFile -Raw | ConvertFrom-Json).version } catch { $current = $null }
    if ($current -is [string] -and $current -match '^\d+\.\d+\.\d+$') { $previous = $current }
    if ($current -eq $target) {
        Write-Host "Ja esta apontando para a versao $target. Nada a fazer: abra o programa normalmente."
        exit 0
    }
}
if ($previous -eq $target) { $previous = $null }

# Backup fora da pasta do programa (usuario comum nao cria arquivo la).
if (-not $BackupDir) { $BackupDir = Join-Path ${env:ProgramData} 'Industel\ControleProducao\updater\backup_ponteiro' }
if (Test-Path -LiteralPath $pointerFile -PathType Leaf) {
    try {
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    } catch {
        $BackupDir = Join-Path ${env:TEMP} 'ControleProducao_backup_ponteiro'
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    }
    $backup = Join-Path $BackupDir ('current.json.' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bak')
    Copy-Item -LiteralPath $pointerFile -Destination $backup
    Write-Host "Backup do ponteiro antigo: $backup"
}

$payload = [ordered]@{
    schema           = 1
    version          = $target
    dir              = "versions/$target"
    previous_version = $previous
    updated_at       = (Get-Date).ToUniversalTime().ToString('o')
}
# UTF-8 sem BOM: o launcher le com json.loads e rejeitaria o BOM.
try {
    [System.IO.File]::WriteAllText($pointerFile, ($payload | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
} catch {
    Fail "Nao foi possivel gravar $pointerFile : $($_.Exception.Message). Instale o Setup mais novo (como administrador)."
}
$check = Get-Content -LiteralPath $pointerFile -Raw | ConvertFrom-Json
if ($check.version -ne $target) { Fail 'Conferencia falhou depois de gravar o ponteiro.' }

Write-Host ''
Write-Host "Pronto: o programa vai abrir na versao $target (anterior: $(if ($previous) { $previous } else { 'desconhecida' }))."
Write-Host 'Feche o Controle de Producao se estiver aberto e abra de novo.'
exit 0
