@echo off
rem Ambiente de desenvolvimento Docker (API de dev na porta 8001).
rem Se a variavel ja existir no Windows, ela e preservada.
rem
rem Os SEGREDOS (SECRET_KEY, PROVISIONING_SECRET, NOMUS_ENCRYPTION_KEY) nao ficam
rem no repositorio: vem de um arquivo FORA dele, por padrao
rem %USERPROFILE%\.controle-producao-dev\dev.env (formato CHAVE=valor, uma por
rem linha; linhas com # sao ignoradas). Para criar o arquivo: python scripts\gerar_segredos_dev.py
rem Outro caminho: defina CONTROLE_DEV_ENV_FILE antes de chamar.
rem Quem chama deve checar "if errorlevel 1 exit /b 1" depois do call.

if "%CONTROLE_DEV_ENV_FILE%"=="" set "CONTROLE_DEV_ENV_FILE=%USERPROFILE%\.controle-producao-dev\dev.env"
if not exist "%CONTROLE_DEV_ENV_FILE%" (
  echo ERRO: arquivo de segredos de dev nao encontrado: %CONTROLE_DEV_ENV_FILE%
  echo Gere com: python scripts\gerar_segredos_dev.py
  exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%CONTROLE_DEV_ENV_FILE%") do (
  if not defined %%A set "%%A=%%B"
)
for %%V in (SECRET_KEY PROVISIONING_SECRET NOMUS_ENCRYPTION_KEY) do (
  if not defined %%V (
    echo ERRO: %%V nao esta definida em %CONTROLE_DEV_ENV_FILE%
    echo Gere com: python scripts\gerar_segredos_dev.py --forcar
    exit /b 1
  )
)

if "%POSTGRES_DB%"=="" set "POSTGRES_DB=controle_producao_dev"
if "%POSTGRES_USER%"=="" set "POSTGRES_USER=controle_dev"
if "%POSTGRES_PASSWORD%"=="" set "POSTGRES_PASSWORD=controle_dev"
if "%POSTGRES_PORT%"=="" set "POSTGRES_PORT=55432"
if "%OPERATIONAL_COMPANY_CODE%"=="" set "OPERATIONAL_COMPANY_CODE=local-dev"
if "%OPERATIONAL_COMPANY_NAME%"=="" set "OPERATIONAL_COMPANY_NAME=Empresa Local"
if "%OPERATIONAL_ENVIRONMENT_TYPE%"=="" set "OPERATIONAL_ENVIRONMENT_TYPE=production"
if "%API_PORT%"=="" set "API_PORT=8001"
