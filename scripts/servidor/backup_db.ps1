# Backup diario do PostgreSQL de producao no SERVIDOR (D10).
# Gera o dump DENTRO do container, copia com docker cp (nunca por redirecionamento do PowerShell,
# que corrompe binarios), aplica retencao local e copia para uma pasta compartilhada (opcional).
# Uso: backup_db.ps1 [-Destino \\PC\pasta] [-RetencaoDias 14]
param(
    [string]$Destino = '',
    [int]$RetencaoDias = 14,
    [string]$CredencialXml = 'C:\ControleProducao\cred_backup.xml',
    [string]$Pasta = 'C:\ControleProducao\backups',
    [string]$Container = 'controle_producao_postgres'
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Pasta | Out-Null
$log = Join-Path $Pasta 'backup.log'
function Log($m) { Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m) -Encoding utf8 }

$nome = "cp_{0:yyyyMMdd_HHmm}.dump" -f (Get-Date)
$local = Join-Path $Pasta $nome
try {
    docker exec $Container sh -c "pg_dump -U `"`$POSTGRES_USER`" -d `"`$POSTGRES_DB`" -Fc -f /tmp/$nome"
    if ($LASTEXITCODE -ne 0) { throw "pg_dump falhou ($LASTEXITCODE)" }
    docker cp "${Container}:/tmp/$nome" $local
    if ($LASTEXITCODE -ne 0) { throw "docker cp falhou ($LASTEXITCODE)" }
    docker exec $Container rm -f "/tmp/$nome" | Out-Null
    $tam = (Get-Item $local).Length
    if ($tam -lt 100KB) { throw "dump suspeito: $tam bytes" }
    Log "OK dump $nome ($tam bytes)"
} catch {
    Log "ERRO dump: $($_.Exception.Message)"
    exit 1
}

Get-ChildItem $Pasta -Filter 'cp_*.dump' | Where-Object LastWriteTime -lt (Get-Date).AddDays(-$RetencaoDias) | ForEach-Object {
    Remove-Item $_.FullName -Force
    Log "retencao: removido $($_.Name)"
}

if ($Destino) {
    try {
        # Credencial criptografada (DPAPI, so o mesmo usuario e PC leem). Criar com:
        #   Get-Credential Srv\usuario | Export-Clixml C:\ControleProducao\cred_backup.xml
        if (Test-Path $CredencialXml) {
            $cred = Import-Clixml $CredencialXml
            $raiz = ($Destino -split '\\' | Where-Object { $_ })[0..1] -join '\'
            New-PSDrive -Name BKPEXT -PSProvider FileSystem -Root "\\$raiz" -Credential $cred -ErrorAction Stop | Out-Null
        }
        Copy-Item -LiteralPath $local -Destination (Join-Path $Destino $nome) -Force -ErrorAction Stop
        Log "OK copia externa em $Destino"
    } catch {
        Log "ERRO copia externa para ${Destino}: $($_.Exception.Message) (dump local mantido)"
        exit 2
    } finally {
        Remove-PSDrive -Name BKPEXT -ErrorAction SilentlyContinue
    }
}
