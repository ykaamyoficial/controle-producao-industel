# Backup diario do PostgreSQL de producao + volumes de arquivos no SERVIDOR (D10).
#
# Etapas (qualquer falha => exit != 0, retencao NAO roda e backups antigos ficam):
#   1. pg_dump -Fc DENTRO do container do Postgres (nunca por redirecionamento do PowerShell,
#      que corrompe binarios) e docker cp para -Pasta.
#   2. Validacao: pg_restore --list no container (exit 0 e indice nao vazio), tamanho minimo,
#      sha256 do dump gravado em <dump>.sha256 e conferido contra o sha256 calculado dentro do
#      container (pega corrupcao na copia).
#   3. Volumes de arquivos (anexos de proposta/chat em /app/data e repositorio de updates do
#      Desktop) empacotados com tar por um container auxiliar descartavel (usa a mesma imagem
#      do Postgres, ja presente no host, sem pull) e verificados com tar -t.
#   4. Copia externa opcional (-DestinoExterno). Vazio => aviso claro de que NAO ha copia externa.
#   5. Retencao local (-RetencaoDias) somente depois de tudo acima ter dado certo.
#
# Parametros:
#   -DestinoExterno    pasta/compartilhamento para copia externa (alias: -Destino). Sem default.
#   -CredencialXml     credencial DPAPI usada so com -DestinoExterno UNC (criar com Export-Clixml).
#   -Pasta             pasta local dos backups. Default C:\ControleProducao\backups
#   -Container         container do Postgres. Default controle_producao_postgres
#   -VolumeStorage     volume nomeado de /app/data da API (anexos). Default
#                      controle_producao_industel_api_data (projeto do compose + _api_data).
#   -VolumeUpdates     volume do repositorio de updates. Default
#                      controle_producao_industel_update_repository_data. Confirme os nomes reais
#                      com `docker volume ls`; sem o volume o script falha (nao finge sucesso).
#   -ImagemAuxiliar    imagem do container auxiliar do tar. Vazio = imagem do container Postgres.
#   -RetencaoDias      dias de retencao local, de 1 a 3650 (0/negativo apagaria o backup recem-criado).
#                      Default 14.
# Codigos de saida: 0 ok; 1 falha de dump/validacao/volume; 2 falha na copia externa.
# Uso: backup_db.ps1 [-DestinoExterno \\PC\pasta] [-RetencaoDias 14]
param(
    [Alias('Destino')]
    [string]$DestinoExterno = '',
    [ValidateRange(1,3650)]
    [int]$RetencaoDias = 14,
    [string]$CredencialXml = 'C:\ControleProducao\cred_backup.xml',
    [string]$Pasta = 'C:\ControleProducao\backups',
    [string]$Container = 'controle_producao_postgres',
    [string]$VolumeStorage = 'controle_producao_industel_api_data',
    [string]$VolumeUpdates = 'controle_producao_industel_update_repository_data',
    [string]$ImagemAuxiliar = ''
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Pasta | Out-Null
$log = Join-Path $Pasta 'backup.log'
function Log($m) { Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m) -Encoding utf8 }

$carimbo = "{0:yyyyMMdd_HHmm}" -f (Get-Date)
$nome = "cp_$carimbo.dump"
$local = Join-Path $Pasta $nome
$gerados = New-Object System.Collections.ArrayList

# Empacota um volume nomeado em <Pasta>\<arquivo>.tar via container auxiliar e confere com tar -t.
function Backup-Volume([string]$volume, [string]$arquivo, [string]$imagem) {
    docker volume inspect $volume | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "volume '$volume' nao existe (ajuste -VolumeStorage/-VolumeUpdates)" }
    $aux = "cp_backup_aux_$carimbo"
    try {
        docker run --name $aux -v "${volume}:/dados:ro" --entrypoint sh $imagem -c "tar cf /tmp/${arquivo} -C /dados . && tar tf /tmp/${arquivo} > /dev/null"
        if ($LASTEXITCODE -ne 0) { throw "tar do volume '$volume' falhou ($LASTEXITCODE)" }
        $destino = Join-Path $Pasta $arquivo
        docker cp "${aux}:/tmp/${arquivo}" $destino
        if ($LASTEXITCODE -ne 0) { throw "docker cp do volume '$volume' falhou ($LASTEXITCODE)" }
    } finally {
        docker rm -f $aux | Out-Null
    }
    $tam = (Get-Item $destino).Length
    if ($tam -le 0) { throw "tar do volume '$volume' vazio" }
    $hash = (Get-FileHash $destino -Algorithm SHA256).Hash.ToLower()
    Set-Content -Path "$destino.sha256" -Value "$hash  $arquivo" -Encoding ascii
    [void]$gerados.Add($destino); [void]$gerados.Add("$destino.sha256")
    Log "OK volume $volume -> $arquivo ($tam bytes, sha256 $hash)"
}

try {
    # 1. dump dentro do container
    docker exec $Container sh -c "pg_dump -U `"`$POSTGRES_USER`" -d `"`$POSTGRES_DB`" -Fc -f /tmp/$nome"
    if ($LASTEXITCODE -ne 0) { throw "pg_dump falhou ($LASTEXITCODE)" }

    # 2a. validacao no container: pg_restore --list precisa funcionar e listar algo
    $itens = docker exec $Container sh -c "pg_restore --list /tmp/${nome} > /tmp/${nome}.lst && wc -l < /tmp/${nome}.lst"
    if ($LASTEXITCODE -ne 0) { throw "pg_restore --list falhou ($LASTEXITCODE): dump invalido" }
    if ([int]("$itens".Trim()) -lt 10) { throw "pg_restore --list com indice vazio/curto ($itens linhas)" }
    $hashContainer = ("" + (docker exec $Container sh -c "sha256sum /tmp/${nome}")).Split(' ')[0].ToLower()
    if ($LASTEXITCODE -ne 0 -or $hashContainer.Length -ne 64) { throw "sha256sum no container falhou" }

    docker cp "${Container}:/tmp/$nome" $local
    if ($LASTEXITCODE -ne 0) { throw "docker cp falhou ($LASTEXITCODE)" }
    [void]$gerados.Add($local)

    # 2b. tamanho, sha256 local igual ao do container e arquivo .sha256 ao lado
    $tam = (Get-Item $local).Length
    if ($tam -lt 100KB) { throw "dump suspeito: $tam bytes" }
    $hash = (Get-FileHash $local -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $hashContainer) { throw "sha256 do dump copiado difere do gerado no container (copia corrompida)" }
    Set-Content -Path "$local.sha256" -Value "$hash  $nome" -Encoding ascii
    [void]$gerados.Add("$local.sha256")
    Log "OK dump $nome ($tam bytes, $itens itens no pg_restore --list, sha256 $hash)"

    # 3. volumes de arquivos (anexos e updates)
    if (-not $ImagemAuxiliar) { $ImagemAuxiliar = (docker inspect -f "{{.Config.Image}}" $Container) }
    if ($LASTEXITCODE -ne 0 -or -not $ImagemAuxiliar) { throw "nao consegui descobrir a imagem do container $Container" }
    Backup-Volume $VolumeStorage "cp_storage_$carimbo.tar" $ImagemAuxiliar
    Backup-Volume $VolumeUpdates "cp_updates_$carimbo.tar" $ImagemAuxiliar
} catch {
    Log "ERRO backup: $($_.Exception.Message) (retencao NAO executada; backups antigos preservados)"
    Write-Error "backup falhou: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
} finally {
    # limpa o dump e o .lst temporarios do container, com sucesso ou falha (nao altera o exit code)
    try { docker exec $Container rm -f "/tmp/$nome" "/tmp/$nome.lst" 2>$null | Out-Null } catch { }
}

# 4. copia externa
if ($DestinoExterno) {
    try {
        # Credencial criptografada (DPAPI, so o mesmo usuario e PC leem). Criar com:
        #   Get-Credential Srv\usuario | Export-Clixml C:\ControleProducao\cred_backup.xml
        if (Test-Path $CredencialXml) {
            $cred = Import-Clixml $CredencialXml
            $raiz = ($DestinoExterno -split '\\' | Where-Object { $_ })[0..1] -join '\'
            New-PSDrive -Name BKPEXT -PSProvider FileSystem -Root "\\$raiz" -Credential $cred -ErrorAction Stop | Out-Null
        }
        foreach ($f in $gerados) {
            Copy-Item -LiteralPath $f -Destination (Join-Path $DestinoExterno (Split-Path $f -Leaf)) -Force -ErrorAction Stop
        }
        $copiado = (Get-FileHash (Join-Path $DestinoExterno $nome) -Algorithm SHA256).Hash.ToLower()
        if ($copiado -ne $hash) { throw "sha256 do dump na copia externa difere do local" }
        Log "OK copia externa ($($gerados.Count) arquivos) em $DestinoExterno"
    } catch {
        Log "ERRO copia externa para ${DestinoExterno}: $($_.Exception.Message) (backup local mantido; retencao NAO executada)"
        exit 2
    } finally {
        Remove-PSDrive -Name BKPEXT -ErrorAction SilentlyContinue
    }
} else {
    Log "AVISO: sem copia externa (-DestinoExterno vazio); backup so no disco deste SERVIDOR"
    Write-Warning "SEM COPIA EXTERNA: informe -DestinoExterno. O backup esta apenas neste disco."
}

# 5. retencao: so chega aqui com dump, volumes e copia externa (se pedida) validados
Get-ChildItem $Pasta -File | Where-Object { $_.Name -like 'cp_*.dump' -or $_.Name -like 'cp_*.dump.sha256' -or $_.Name -like 'cp_*.tar' -or $_.Name -like 'cp_*.tar.sha256' } |
    Where-Object LastWriteTime -lt (Get-Date).AddDays(-$RetencaoDias) | ForEach-Object {
        Remove-Item $_.FullName -Force
        Log "retencao: removido $($_.Name)"
    }
exit 0
