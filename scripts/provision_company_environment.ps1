param(
    [Parameter(Mandatory = $true)]
    [string]$CompanyCode,

    [Parameter(Mandatory = $true)]
    [string]$CompanyName,

    [int]$ApiPort = 8000,

    [int]$PostgresPort = 55432,

    [string]$ProvisioningSecret = "",

    [string]$OutputRoot = "",

    [switch]$Start,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Code {
    param([string]$Value)
    $normalized = $Value.Trim().ToLowerInvariant() -replace "[^a-z0-9_-]", "-"
    $normalized = $normalized -replace "-{2,}", "-"
    $normalized = $normalized.Trim("-")
    if (-not $normalized) {
        throw "Informe um codigo de empresa valido."
    }
    return $normalized
}

function New-Secret {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($buffer).TrimEnd("=") -replace "\+", "-" -replace "/", "_"
}

function Assert-Port {
    param(
        [int]$Port,
        [string]$Name
    )
    if ($Port -lt 1024 -or $Port -gt 65535) {
        throw "$Name deve estar entre 1024 e 65535."
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "deploy\companies"
}

Assert-Port -Port $ApiPort -Name "ApiPort"
Assert-Port -Port $PostgresPort -Name "PostgresPort"

$code = Normalize-Code $CompanyCode
$dbSafeCode = $code -replace "-", "_"
$target = Join-Path $OutputRoot $code
$composePath = Join-Path $target "docker-compose.yml"
$envPath = Join-Path $target ".env"
$readmePath = Join-Path $target "README.md"

if ((Test-Path -LiteralPath $target) -and -not $Force) {
    throw "A pasta '$target' ja existe. Use -Force para sobrescrever os arquivos de provisionamento."
}

New-Item -ItemType Directory -Path $target -Force | Out-Null

$instanceId = [guid]::NewGuid().ToString()
$postgresDb = "controle_$dbSafeCode"
$postgresUser = "controle_$dbSafeCode"
$postgresPassword = New-Secret -Bytes 24
$secretKey = New-Secret -Bytes 48
if (-not $ProvisioningSecret) {
    $ProvisioningSecret = $env:OPERATIONAL_PROVISIONING_SECRET
}
if (-not $ProvisioningSecret) {
    $ProvisioningSecret = New-Secret -Bytes 32
}
$provisioningSecret = $ProvisioningSecret
$apiContainer = "controle_producao_api_$code"
$postgresContainer = "controle_producao_postgres_$code"
$volumeName = "controle_producao_postgres_${dbSafeCode}_data"
$composeContext = ($repoRoot -replace "\\", "/")

$envContent = @"
COMPANY_CODE=$code
COMPANY_NAME=$CompanyName
OPERATIONAL_INSTANCE_ID=$instanceId
API_PORT=$ApiPort
POSTGRES_PORT=$PostgresPort
POSTGRES_DB=$postgresDb
POSTGRES_USER=$postgresUser
POSTGRES_PASSWORD=$postgresPassword
SECRET_KEY=$secretKey
PROVISIONING_SECRET=$provisioningSecret
OPERATIONAL_ENVIRONMENT_TYPE=production
"@

$dollar = '$'
$composeContent = @"
services:
  postgres:
    image: postgres:16
    container_name: $postgresContainer
    environment:
      POSTGRES_DB: ${dollar}{POSTGRES_DB}
      POSTGRES_USER: ${dollar}{POSTGRES_USER}
      POSTGRES_PASSWORD: ${dollar}{POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:${dollar}{POSTGRES_PORT}:5432"
    volumes:
      - ${volumeName}:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${dollar}${dollar}{POSTGRES_USER} -d ${dollar}${dollar}{POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  api:
    build:
      context: "$composeContext"
      dockerfile: api/Dockerfile
    container_name: $apiContainer
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      APP_ENV: production
      API_HOST: 0.0.0.0
      API_PORT: 8000
      DATABASE_URL: postgresql+asyncpg://${dollar}{POSTGRES_USER}:${dollar}{POSTGRES_PASSWORD}@postgres:5432/${dollar}{POSTGRES_DB}
      DATABASE_POOL_SIZE: 5
      DATABASE_MAX_OVERFLOW: 10
      DATABASE_CONNECT_TIMEOUT: 10
      DATABASE_POOL_TIMEOUT: 30
      DATABASE_POOL_RECYCLE: 1800
      DATABASE_ECHO: "false"
      SECRET_KEY: ${dollar}{SECRET_KEY}
      PROVISIONING_SECRET: ${dollar}{PROVISIONING_SECRET}
      OPERATIONAL_INSTANCE_ID: ${dollar}{OPERATIONAL_INSTANCE_ID}
      OPERATIONAL_COMPANY_CODE: ${dollar}{COMPANY_CODE}
      OPERATIONAL_COMPANY_NAME: ${dollar}{COMPANY_NAME}
      OPERATIONAL_ENVIRONMENT_TYPE: ${dollar}{OPERATIONAL_ENVIRONMENT_TYPE}
      ACCESS_TOKEN_EXPIRE_MINUTES: 15
      REFRESH_TOKEN_EXPIRE_DAYS: 7
      LOGIN_MAX_FAILED_ATTEMPTS: 5
      LOGIN_LOCK_MINUTES: 15
      PASSWORD_MIN_LENGTH: 4
      CORS_ALLOWED_ORIGINS: ""
    ports:
      - "127.0.0.1:${dollar}{API_PORT}:8000"
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/system/health', timeout=5).read()\""]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

volumes:
  ${volumeName}:
"@

$readmeContent = @"
# Ambiente operacional - $CompanyName

Este diretorio foi gerado para manter uma API e um PostgreSQL isolados para a empresa `$code`.

## Dados para cadastrar no Admin Platform

- Empresa: $CompanyName
- Codigo/slug: $code
- URL da API operacional local: http://127.0.0.1:$ApiPort
- URL da API para o Admin Platform em container: http://host.docker.internal:$ApiPort
- Alias do banco: $postgresDb
- Instancia operacional: $instanceId

## Comandos

Subir a stack:

```powershell
docker compose --env-file .env -f docker-compose.yml up -d --build
```

Rodar migrations:

```powershell
docker compose --env-file .env -f docker-compose.yml run --rm --no-deps api sh -c "cd /app/api && python -m alembic upgrade head"
```

Verificar saude da API:

```powershell
Invoke-RestMethod http://127.0.0.1:$ApiPort/api/v1/system/health
```

## Atualizar status no Admin Platform

Quando o ambiente estiver vinculado no Admin Platform, o provisionador deve atualizar o status:

~~~powershell
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8100/api/v1/environments/<ENVIRONMENT_ID>/provisioning" -Headers @{"X-Provisioning-Secret" = "$provisioningSecret"} -ContentType "application/json" -Body '{"provisioning_status":"ready","provisioning_step":"validation","provisioning_message":"Ambiente operacional pronto.","operational_api_url":"http://127.0.0.1:$ApiPort","database_alias":"$postgresDb","operational_instance_id":"$instanceId","last_database_status":"current"}'
~~~

## Observacao

O Admin Platform deve registrar e monitorar este ambiente. A criacao de containers e bancos deve ficar com um provisionador/script controlado no servidor, nao dentro da API Admin.
"@

Set-Content -LiteralPath $envPath -Value $envContent -Encoding UTF8
Set-Content -LiteralPath $composePath -Value $composeContent -Encoding UTF8
Set-Content -LiteralPath $readmePath -Value $readmeContent -Encoding UTF8

Write-Host "Ambiente gerado em: $target"
Write-Host "API local prevista: http://127.0.0.1:$ApiPort"
Write-Host "API para Admin Platform em Docker: http://host.docker.internal:$ApiPort"
Write-Host "Banco PostgreSQL isolado: $postgresDb"
Write-Host "Instancia operacional: $instanceId"

if ($Start) {
    Push-Location $target
    try {
        docker compose --env-file .env -f docker-compose.yml up -d --build
        docker compose --env-file .env -f docker-compose.yml run --rm --no-deps api sh -c "cd /app/api && python -m alembic upgrade head"
    }
    finally {
        Pop-Location
    }
}
