# Auditoria 06: operação e deploy da API (SERVIDOR)

Data: 2026-11-19. Branch `logistica-melhorias`. Somente leitura: nada foi executado no SERVIDOR (192.168.2.128), na API oficial (8000), nem scripts de deploy, backup ou rollback. Tudo abaixo vem de leitura de código, docs e memória. O que depende do estado real do SERVIDOR está marcado como "verificar".

Caminhos relativos à raiz `c:\Users\Industel\Documents\New project\Nova pasta`.

## 0. Resumo

- O que roda de fato hoje na produção é um fluxo manual: imagem `local/controle-producao-api:0.11.0` por `docker save`/`docker load`, `docker compose` (`docker-compose.prod.yml` + `docker-compose.servidor.yml`), backup por `scripts/servidor/backup_db.ps1`. Os scripts `scripts/deployment/*`, `scripts/run_rollback.py` e `.github/workflows/release-server.yml` (orquestrador Fase 08/09) nunca foram a via real da migração e, como estão, não servem ao SERVIDOR (achado B3).
- O código atual (`API_VERSION = "0.11.0"`, head `20261109_0047`) é diferente do que roda na produção (mesma versão `0.11.0`, banco em `20261014_0038`). Deploy sem subir a versão destrói a imagem de rollback (B1).
- Há 3 achados que bloqueiam deploy (B1 a B3) e 1 a confirmar (B4, Almox).

## 1. Achados

Severidade: **B** bloqueia deploy, **C** corrigir antes, **D** pode depois.

| # | Sev | Achado | Evidência |
|---|---|---|---|
| B1 | B | Versão não mudou. HEAD declara `0.11.0` e esperado `20261109_0047`; a tag `api-v0.11.0` (commit `1c18459`, 2026-10-14) declarava `0.11.0` e `20261014_0038`. Desde a tag há 9 migrations (0039 a 0047) e 49 arquivos alterados em `api/app` + `api/alembic`. A produção roda a imagem `0.11.0` com banco em `0038`. Construir de novo com `--registry local` gera a mesma tag `local/controle-producao-api:0.11.0`; `docker load` no SERVIDOR sobrescreve a tag e a imagem antiga fica sem nome, sem rollback. | `api/app/core/config.py:10,14,21`; `git diff --name-only api-v0.11.0 HEAD -- api/alembic/versions`; `docs/plano-migracao-api-servidor.md:82,224`; `docker-compose.prod.yml:46` |
| B2 | B | Anexos de foto/vídeo de proposta e do chat vão para `CHAT_STORAGE_ROOT` (default `data/storage`, ou seja `/app/data/storage` dentro do container). O compose só monta o volume `update_repository_data`. Recriar o container (todo deploy com imagem nova) apaga os arquivos; as linhas do banco ficam apontando para nada. Mesma coisa para `AUDIT_SPOOL_DIR` e `MAINTENANCE_STATE_DIR` (menos grave). Verificar com `docker exec controle_producao_api ls /app/data/storage` [AUTORIZAÇÃO DO HENRIQUE, produção]. | `api/app/core/config.py:119,127,135`; `api/app/modules/proposal_attachments/router.py:18`; `docker-compose.prod.yml:102-107,148-151`; `api/Dockerfile:63` |
| B3 | B | Rollback e pipeline automáticos não funcionam no SERVIDOR. (a) `docker_control.run_container` recria o container com `docker run` sem volume, sem `--restart`, com `-p 8000:8000` em todas as interfaces: perde `update_repository_data`, a política de reinício e o bind em `127.0.0.1`. (b) `run_deploy` faz `docker pull` da tag; com registry `local` não existe registry para puxar. (c) Os scripts leem o banco por `DATABASE_URL` a partir do host, mas o Postgres não publica porta. (d) `backup/service.py` exige `pg_dump`/`pg_restore` no PATH do host; a imagem não tem cliente PostgreSQL. (e) `rollback_to_previous_healthy_release` exige uma release HEALTHY no estado; `deployments/state` não existe, então devolve `RollbackNotAllowedError`. (f) A imagem antiga recusa o schema novo: readiness exige revisão igual à esperada. Logo, depois de migrar, rollback de aplicação sozinho deixa a API não saudável; o rollback real é restaurar o dump anterior (perde o que entrou depois). O workflow ainda exige runner self-hosted `[production, deploy]` e GHCR, que não existem no SERVIDOR (verificar). | `api/app/deployment/docker_control.py:73-88`; `scripts/deployment/run_deploy.py:99,142-144`; `docker-compose.prod.yml:38-42`; `api/app/backup/service.py:220-221`; `api/Dockerfile:60-85`; `api/app/deployment/service.py:197-201,258-262`; `api/app/database/health.py:45-47`; `.github/workflows/release-server.yml:25,213` |
| B4 | B? | Integração Almox+ não chega ao container. `ALMOX_INTEGRATION_SECRET` e `ALMOX_WEBHOOK_URL` não estão no bloco `environment:` do compose de produção, e o compose não usa `env_file`. Colocar as variáveis no `.env` do SERVIDOR não adianta: só viram variável do container as que o compose cita. Sem elas a conciliação responde 503 e nenhum webhook sai. Também não aparecem no compose de dev. Verificar no que roda hoje: `docker exec controle_producao_api printenv` filtrando só os nomes [AUTORIZAÇÃO]. Se a integração estava ativa antes da virada, ela quebrou. | `docker-compose.prod.yml:52-93`; `api/app/main.py:203-206`; `api/app/modules/almox_integration/router.py:31-37` |
| C1 | C | Backup diário (`backup_db.ps1`) é só `pg_dump -Fc` com checagem de tamanho (mínimo 100 KB). Não confere `pg_restore --list`, nem `sha256`, nem contagem. Guarda no mesmo disco do SERVIDOR. Cópia externa só ocorre se passar `-Destino`; o `schtasks` do plano não passa, e o `backup_externo.ps1` citado no plano não está no repositório. Não cobre o volume `update_repository_data` (1,3 GB), nem anexos (B2). A retenção apaga por `LastWriteTime` > 14 dias, só depois de um dump novo com sucesso (ok). | `scripts/servidor/backup_db.ps1:20,26,33-36,38`; `docs/plano-migracao-api-servidor.md:150,222` |
| C2 | C | Teste de restauração do backup agendado não está registrado. O ensaio da Tarefa 5 restaurou um dump manual (contagens de 43 tabelas iguais). O item "teste de restauração" da Tarefa 6 continua sem registro de execução. | `docs/plano-migracao-api-servidor.md:152,216-225` |
| C3 | C | Caddy continua no `docker-compose.prod.yml` com `CADDY_HOSTNAME`/`CADDY_TLS_*` obrigatórios; no SERVIDOR o `.env` leva valores fictícios. Um `docker compose up -d` sem nomes de serviço tenta subir o Caddy (443, certificado inexistente). Hoje só a disciplina de citar `postgres api` protege. | `docker-compose.prod.yml:122-146`; `docs/plano-migracao-api-servidor.md:31` |
| C4 | C | Smoke tests cobrem só `live`, `ready`, `system/compatibility`, `system/version`. Não há login, leitura de proposta, manifesto de update, conciliação Almox, nem teste pela URL pública (túnel). | `api/app/health/smoke.py:50-54,76-110` |
| C5 | C | Janela de rollback para a máquina antiga acabou em 2026-11-11 (D11: 7 dias a partir de 2026-11-04). Hoje são 8 dias depois. O Postgres antigo guarda um banco de 2026-11-04, já defasado; subir a API antiga com ele seria perda de 15 dias de dados. A tarefa `CloudflaredTunnel` está desativada, não removida: reativá-la cria dois conectores no mesmo túnel. | `docs/spec-migracao-api-servidor.md:58`; memória `controle-producao-migracao-servidor.md:12` |
| C6 | C | Imagens base flutuantes: `postgres:16` e `caddy:2-alpine` por tag, sem digest. Um `docker pull` futuro pode trocar a menor versão do Postgres. `cloudflared` está fixo por tag (`2026.9.3`). | `docker-compose.prod.yml:23,123`; `docker-compose.servidor.yml:5` |
| C7 | C | Estado do SERVIDOR (Autologon, tarefas `IniciarDockerDesktop` e `ControleProducaoBackup`, `.env`, `cloudflared/`, `cred_backup.xml`, powercfg) existe só na máquina. Não há script versionado que recrie; só `backup_db.ps1`. Reinstalar o SERVIDOR não é repetível. | `scripts/servidor/` (1 arquivo); plano Tarefas 0, 3, 4, 6 |
| C8 | C | Documentação defasada: checkboxes do plano seguem desmarcados (vale o "Registro da execução", linhas 214-225); a memória automática do projeto (`project_server_migration.md`, índice "T0-T6 feitas, falta Autologon/T7/virada") está velha, a virada ocorreu em 2026-11-04; `CLAUDE.md` do repo não cita o endereço do SERVIDOR; `API_RUNTIME_DEV.md` ainda manda abrir `127.0.0.1:8000` (a dev real é 8001, `docker-compose.dev.yml:75`) e usa rotas `/system/health`. | `docs/architecture/API_RUNTIME_DEV.md:177-186`; `docker-compose.dev.yml:75` |
| C9 | C | Flags de comportamento não passam pelo compose de produção: `REMANAGEMENT_BY_ROWS_ENABLED` (dev liga, produção fica `false` por default), `CLIENT_VERSION_ENFORCEMENT_ENABLED`, `AUTH_RETENTION_ENABLED`, dirs de estado. Decidir de forma explícita antes de cada deploy qual deve ficar ligada. | `docker-compose.dev.yml:59`; `api/app/core/config.py:65,70` |
| D1 | D | Pendências de segurança operacional: trocar senhas expostas na migração, remover `sudo` sem senha e chave da VM Ubuntu, cópia externa do backup (credencial recusada). | plano Tarefa 10; spec Q6 a Q8 |
| D2 | D | `HEALTHCHECK` da imagem: interval 30 s, retries 5, start 20 s (até cerca de 2,5 min para marcar unhealthy). `restart: unless-stopped` não reinicia container unhealthy; API travada com processo vivo fica travada. Sem alerta externo. | `api/Dockerfile:84`; `docker-compose.prod.yml:48` |
| D3 | D | Imagem de produção instala `requirements-dev.txt` (pytest etc.). A doc diz que não há lock, mas `api/requirements-lock.txt` existe e é usado. | `api/Dockerfile:36-37`; `docs/architecture/DOCKER_RELEASE_IMAGES.md:24-27` |
| D4 | D | RAM do SERVIDOR (2,2 GB livres de 15,4 GB; Docker com 8 GB) sem monitoramento nem registro das primeiras 24 h. | spec seção 6; plano "Foco de revisão" 4 |

## 2. Fluxo de deploy que o código suporta

Orquestrador `api/app/deployment/service.py` (estados em `models.py:9-28`, transições em `service.py:53-63`):

```
PREPARING -> DEPLOYING -> VALIDATING -> HEALTHY
   |            |             |
   +------------+-------------+--> FAILED -> ROLLING_BACK -> ROLLED_BACK
                                       |                  -> ROLLBACK_FAILED -> MANUAL_INTERVENTION_REQUIRED
                                       +--> MANUAL_INTERVENTION_REQUIRED (schema inseguro ou sem release anterior)
```

Cada avanço grava um registro novo (nunca reescreve); lock de arquivo em `DEPLOYMENT_STATE_DIR` impede dois deploys; `recover_incomplete_deployment_state` escala para intervenção manual se o processo morrer no meio.

Passos do pipeline (`.github/workflows/release-server.yml`), cada um um script:

1. `validate_tag.py`: tag `api-vX.Y.Z` igual a `API_VERSION`.
2. Testes + `check_migration_checksums.py` + `check_migration_safety.py`; `build_release_image.py` e push para GHCR.
3. `precheck.py`: versão alvo igual a `API_VERSION`, Docker disponível, banco `connected`, 500 MB livres, `begin_deployment` (estado PREPARING), manutenção DRAINING (10 s) e depois ACTIVE.
4. `run_deploy.py`: backup obrigatório (`PreDeploymentBackupService`, falha bloqueia), `DEPLOYING`, `docker pull` + conferência de digest, preflight de histórico Alembic, `alembic upgrade head` em container efêmero, confere revisão pós-migration, remove e recria o container (`docker run`), `VALIDATING`.
5. `run_verify.py`: espera `healthy` (90 s), manutenção RECOVERY, smoke, versão igual à alvo, `HEALTHY`, manutenção OFF.
6. `run_rollback.py` (job automático se deploy ou verify falharem): ver B3.

O que dá para rodar hoje de verdade:

- `python -m api.app.cli create-admin | purge-auth-data [--apply] | reset-proposals-development-data` (este só roda em `development`/`test`, `api/app/cli.py:129`). A CLI não faz deploy, migration, backup nem smoke.
- `python -m api.app.health.smoke --base-url <url> [--expected-server-version V] [--json]`: somente leitura, 4 GET, exit 0 só com tudo PASS. Seguro rodar contra a dev (8001).
- `python scripts/run_predeployment_backup.py`: precisa de `pg_dump`/`pg_restore` no PATH do host e `DATABASE_URL` alcançável. Não é o caminho da produção atual.
- `python scripts/build_release_image.py --registry local [--tag X]`: constrói e confere label da imagem; não faz push.
- Na produção o que existe é manual: compose, `docker save/load`, `backup_db.ps1`, `Stop-/Disable-ScheduledTask`.

## 3. Backup pré-deploy

Dois mecanismos, só um em uso:

| | `PreDeploymentBackupService` (código) | `backup_db.ps1` (SERVIDOR, em uso) |
|---|---|---|
| Dump | `pg_dump --format=custom --no-owner --no-privileges` no host | `pg_dump -Fc` dentro do container, `docker cp` |
| Verificação | `pg_restore --list`, `sha256`, manifest atômico, `database_revision` | só tamanho > 100 KB |
| Retenção | 10 válidos e 7 dias mínimos (por manifest) | 14 dias por data do arquivo |
| Destino | `BACKUP_DIR` (default container: `/var/backups/controle-producao`, sem volume) | `C:\ControleProducao\backups`; cópia externa só com `-Destino` |
| Agenda | nenhuma (só pelo deploy) | tarefa `ControleProducaoBackup`, 02:00 |

Restaurar (a partir da doc `BACKUP_PRE_DEPLOYMENT.md:209-227`, adaptado ao container):

```powershell
# no SERVIDOR; testa em banco novo, nunca sobre o de produção
Get-FileHash C:\ControleProducao\backups\<arquivo>.dump -Algorithm SHA256
docker cp C:\ControleProducao\backups\<arquivo>.dump controle_producao_postgres:/tmp/t.dump
docker exec controle_producao_postgres sh -c 'createdb -U "$POSTGRES_USER" teste_restore && pg_restore --no-owner -U "$POSTGRES_USER" -d teste_restore /tmp/t.dump && psql -U "$POSTGRES_USER" -d teste_restore -tAc "select version_num from alembic_version"'
docker exec controle_producao_postgres sh -c 'dropdb -U "$POSTGRES_USER" teste_restore; rm -f /tmp/t.dump'
```

Restore sobre produção real (`pg_restore --clean --if-exists`, API parada) é decisão do Henrique [AUTORIZAÇÃO DO HENRIQUE]. Há dumps manuais antigos em `backups/` (ex.: `prod_antes_0.10.0_*.dump`), mostrando que antes se fazia dump manual antes de cada versão.

## 4. Healthchecks e smoke

- `GET /api/v1/health/live`: processo vivo, `server_version`, sem banco (`api/app/health/service.py:23-25`).
- `GET /api/v1/health/ready`: `SELECT 1` + `alembic_version` igual à esperada (crítico), versão, `commit_sha`, `build_time_utc`, estado de manutenção (`service.py:27-30`, `checks/database.py:73-94`). Usado pelo `HEALTHCHECK` da imagem e pelo `depends_on: service_healthy` do `cloudflared`.
- `GET /api/v1/system/compatibility` e `/system/version`: versão, contrato, revisão, status do banco.
- Em manutenção ACTIVE/RECOVERY tudo de negócio bloqueia; `/health`, `/system/maintenance`, `/system/compatibility`, `/updates` seguem liberados (`maintenance/middleware.py:29-34`).

Smoke que falta (só leitura, sem usuário real de produção, ou com usuário de teste dedicado):

1. Pela URL pública `https://api.ykora.com.br/api/v1/health/ready` (prova túnel + API).
2. Login de um usuário de teste e `GET` de propostas (limite 1).
3. `/api/v1/updates` discovery responde (manifesto de update do Desktop).
4. Conciliação Almox com assinatura de teste: 503 se desligada, 200 se ligada (ver seção 7).
5. `alembic_version` conferida contra `EXPECTED_DATABASE_REVISION` do release.
6. Anexo: gravar e ler um anexo de teste, recriar o container, ler de novo (prova do volume, B2).
7. Disco e RAM livres do SERVIDOR, existência do dump do dia.

## 5. Rollback

- Critérios sugeridos (não estão escritos em nenhum doc): `ready` diferente de 200 por 2 min depois da subida; smoke 1 a 3 falhando; erro 5xx em login; migration falha; contagens de tabelas diferentes do dump pré-deploy.
- Rollback "de aplicação" (trocar imagem mantendo o banco) só é seguro se não houve migration. Com migration, a imagem antiga fica unhealthy (B3 f). Caminho real: parar API, restaurar dump pré-deploy, subir imagem antiga (precisa ainda estar no SERVIDOR com sua tag, ver B1). Perde tudo que entrou depois do dump: decisão consciente.
- `scripts/run_rollback.py --reason "<motivo>" [--failed-deployment-id ID]`: lê `DATABASE_URL` e variáveis `ROLLBACK_CONTAINER_ENV_*` do ambiente. Não rodar no SERVIDOR sem refazer B3.
- Rollback para a máquina antiga: a janela fechou em 2026-11-11 e o banco de lá é de 2026-11-04. O plano (Tarefa 9, linhas 190-202) cobre o rollback "imediato" e o "tardio" (dump do SERVIDOR restaurado lá). Hoje só o tardio faria sentido e exige decisão do Henrique. O comando de reativar o túnel antigo (`Enable-ScheduledTask`/`Start-ScheduledTask CloudflaredTunnel`) nunca deve ser usado com o `cloudflared` do SERVIDOR ligado.
- Sobre a produção antiga: manter parada e decidir limpeza com confirmação (containers, volumes `controle_producao_industel_postgres_prod_data` e `..._update_repository_data`). Antes de apagar, guardar um dump final dela fora do PC. [AUTORIZAÇÃO DO HENRIQUE]

## 6. Pendências da migração: o que ainda é verdade (em 2026-11-19)

| Item | Fonte | Situação |
|---|---|---|
| T0 a T7 | plano, Registro da execução (linha 216) | Feitas em 2026-11-04. A nota "T0-T6 feitas, falta Autologon/T7/virada" da memória automática do projeto está desatualizada. |
| Virada | memória `controle-producao-migracao-servidor.md:11` | Concluída 2026-11-04, parada de cerca de 11 min, login testado de outro PC. |
| Autologon | plano linhas 44, 221 | Configurado. Se a senha do Windows mudar (a troca de senha é pendência), o Autologon pode desativar (`AutoAdminLogon=0`): conferir depois de trocar. |
| Reinício do SERVIDOR | plano 220 | Testado, 92 s até API e banco saudáveis. Não repetido depois (verificar). |
| Backup local 02:00 | plano 222 | Agendado. Conferir `backup.log` (não há registro aqui de que foi lido nos dias seguintes). |
| Cópia externa do backup | plano 222, memória 14 | Ainda pendente (credencial recusada). Ainda é verdade até prova contrária. |
| Trocar senhas expostas; VM Ubuntu (`sudo` e chave) | spec Q7 e Q8 | Pendente. |
| Limpeza da máquina antiga | D11 | Prazo venceu em 2026-11-11. Sem decisão registrada. |
| `fase-report` de fechamento; `CLAUDE.md` com endereço | plano Tarefa 10 | Pendente (`CLAUDE.md` não cita o SERVIDOR). |
| Migrations 0039 a 0047 | spec seção 4 | Fora da virada de propósito. Ainda não aplicadas na produção. É o próximo deploy (B1). |

## 7. Docker e compose

- Imagem: `${IMAGE_REGISTRY}/controle-producao-api:${SERVER_VERSION}`, sem `latest` (testado por `api/tests/test_release_compose_policy.py`). Na produção `IMAGE_REGISTRY=local` (sem registry, sem digest).
- Build reprodutível: base `python:3.12-slim` fixada por digest, `pip install -c requirements-lock.txt`, multi-stage, usuário não root, labels OCI com versão, commit e hora (`api/Dockerfile:23,37,45-58`). A reprodutibilidade fica fraca porque a tag não muda entre builds (B1) e a imagem não tem digest local.
- Volumes: `postgres_prod_data` (banco), `update_repository_data` (releases do Desktop, 1,3 GB, dono uid 100), `caddy_data` (sem uso no SERVIDOR). Faltam volumes de `/app/data` (B2) e do destino de backup do container.
- Reinício: `restart: unless-stopped` em postgres, api, caddy e cloudflared.
- Nomes de variáveis obrigatórias (sem default, `${VAR:?}`): `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `IMAGE_REGISTRY`, `SERVER_VERSION`, `SECRET_KEY`, `PROVISIONING_SECRET`, `NOMUS_ENCRYPTION_KEY`, `OPERATIONAL_COMPANY_CODE`, `OPERATIONAL_COMPANY_NAME`, `CADDY_HOSTNAME`, `CADDY_TLS_CERT_PATH`, `CADDY_TLS_KEY_PATH`. Opcionais com default: `API_BIND_HOST`, `API_PORT`, `API_LOG_LEVEL`, `DATABASE_*`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `LOGIN_*`, `PASSWORD_MIN_LENGTH`, `CORS_ALLOWED_ORIGINS`, `BACKUP_DIR`, `UPDATE_REPOSITORY_DIR`, `NOTIFICATIONS_*`, `SMTP_*`, `OPERATIONAL_INSTANCE_ID`, `OPERATIONAL_COMPANY_ID`.
- `compose.prod` x `compose.servidor`: o segundo acrescenta só o serviço `cloudflared` (perfil `tunel`, `depends_on api healthy`, config e credencial em `./cloudflared` somente leitura). Não altera API nem Postgres. Rodam juntos com dois `-f`. No SERVIDOR: `API_BIND_HOST=127.0.0.1` (o `.env` sobrescreve o default `0.0.0.0` do compose), Caddy com valores fictícios e nunca iniciado.
- `Caddyfile`: só serve para HTTPS interno (443, certificado de CA interna, `reverse_proxy api:8000`). Não é usado na produção atual (decisão D8: Cloudflare termina o TLS). Pode ficar para um futuro acesso interno.
- Túnel: tunnel id e hostname `api.ykora.com.br` estão no plano; o apontamento é `http://api:8000` dentro da rede do compose.

## 8. Integração Almox+

O que precisa estar no deploy (só nomes):

- `ALMOX_INTEGRATION_SECRET`: mesmo valor nos dois sistemas, mínimo 32 caracteres; sem ele a conciliação responde 503.
- `ALMOX_WEBHOOK_URL`: URL `http`/`https` do Almox+; sem ela nenhum webhook sai (`dispatcher.py:40-42`).
- O compose de produção precisa citar as duas no `environment:` (B4) e o `.env` do SERVIDOR precisa tê-las.
- Saída do SERVIDOR para `almox.ykora.com.br` (internet) liberada. O webhook usa User-Agent próprio por causa do bloqueio 1010 da Cloudflare (`dispatcher.py:19-21`).
- Relógio do SERVIDOR correto: a assinatura vale ±300 s (`ALMOX_INTEGRATION.md:71`). Windows com NTP.
- Sem migration; sem fila persistente; webhook perdido é corrigido pela conciliação horária do Almox+.

Como testar sem afetar o Almox real:

1. Testes automáticos: `python -m pytest api/tests/test_almox_integration.py -q` (usa chaves e servidor falsos, sem rede). Rodar com o timeout habitual do projeto.
2. Dev (8001) com segredo descartável e `ALMOX_WEBHOOK_URL` apontando para um receptor local sem efeito (por exemplo `http://127.0.0.1:<porta>` de um servidor de teste que só imprime). Exige antes acrescentar as duas variáveis ao compose de dev. Nunca apontar para `almox.ykora.com.br`.
3. Conciliação: `GET /api/v1/integrations/almox/proposals?estado=LIBERADA` com `X-Timestamp` e `X-Signature` calculados com o segredo de teste sobre a query string crua. Somente leitura.
4. Na produção só depois de definir o segredo com o Henrique; primeira prova é a conciliação (leitura), antes de liberar qualquer proposta.

## 9. Rascunho de runbook (deploy manual no SERVIDOR)

Premissa: é o fluxo que já funcionou na virada. Marcar cada passo executado. [AUTORIZAÇÃO DO HENRIQUE] = mexe na produção.

**Pré-requisitos (nada disso toca a produção)**

1. Decidir e subir a versão (`API_VERSION`) acima de `0.11.0` e atualizar `EXPECTED_DATABASE_REVISION` se preciso (B1). Commit local, tag `api-vX.Y.Z`.
2. Corrigir B2 (volume para `/app/data`) e B4 (variáveis Almox no compose) em branch própria; rodar `python -m pytest api/tests/test_release_compose_policy.py -q`.
3. Rodar os testes da API e `scripts/check_migration_checksums.py` e `scripts/check_migration_safety.py`.
4. Ensaiar a migration 0038 para 0047 numa cópia do banco de produção, na dev (8001), com um dump restaurado em banco temporário. Medir o tempo. (As outras agentes de auditoria cobrem o conteúdo das migrations.)
5. Construir a imagem: `python scripts/build_release_image.py --registry local`, `docker save local/controle-producao-api:<nova> -o <pasta>\api-<nova>.tar`, `Get-FileHash` do `.tar`.
6. Avisar a equipe do horário e da parada (cerca de 15 min, a medir no ensaio).

**Janela** (todos [AUTORIZAÇÃO DO HENRIQUE], por SSH com `.ps1` copiado por `scp`, nunca aspas na linha de comando)

7. Copiar o `.tar` para `C:\ControleProducao\`, conferir `sha256`, `docker load -i`, comparar `docker image inspect --format '{{.Id}}'` nos dois lados. Confirmar que a imagem antiga `0.11.0` continua listada.
8. Conferir RAM e disco livres, `backup.log` do dia anterior, `docker ps` saudável.
9. Backup pré-deploy: `powershell -NoProfile -ExecutionPolicy Bypass -File C:\ControleProducao\backup_db.ps1`. Depois conferir `sha256`, tamanho, e restaurar em banco temporário como na seção 3 (esta validação extra ainda não está no script). Copiar o dump para fora do SERVIDOR.
10. Manutenção: se disponível, ativar pelo admin de manutenção (ver `api/app/maintenance/`); caso contrário, o passo 11 já derruba a API.
11. Parar só a API: `docker compose --env-file C:\ControleProducao\.env -f docker-compose.prod.yml -f docker-compose.servidor.yml stop api`. Postgres continua. Dump final (mesmo método do passo 9), pois a imagem antiga não opera o schema novo.
12. Atualizar `SERVER_VERSION` no `.env` (só o nome da chave; sem imprimir o conteúdo).
13. Migration a partir da imagem nova: `docker compose --env-file C:\ControleProducao\.env -f docker-compose.prod.yml -f docker-compose.servidor.yml run --rm --no-deps api sh -c "cd /app/api && python -m alembic upgrade head"` (mesmo comando de `run_deploy.py:34`). Conferir `select version_num from alembic_version` igual a `EXPECTED_DATABASE_REVISION` do release.
14. Subir: `... up -d api` (citar o serviço; nunca `up -d` sem nomes por causa do Caddy, C3). Esperar `healthy`.
15. Smoke (seção 4), de dentro do SERVIDOR (`http://127.0.0.1:8000`) e depois pela URL pública: `python -m api.app.health.smoke --base-url https://api.ykora.com.br --expected-server-version <nova>`. Login de teste e uma leitura de proposta.
16. Conferir `docker logs --tail 200 controle_producao_api` sem erro, e `docker stats` sem OOM.
17. Se havia manutenção ativa, desligar. Avisar a equipe.

**Critérios para abortar e voltar** (decisão do Henrique, não automática)

- Migration falhou ou revisão final diferente da esperada.
- `ready` não fica 200 em 2 min, ou smoke 1 a 3 falha.
- Erro em login ou em listagem de propostas.
- Voltar: `stop api`, restaurar o dump do passo 11 (`pg_restore --clean --if-exists`), colocar `SERVER_VERSION` antigo no `.env`, `up -d api` com a imagem antiga, repetir o smoke. [AUTORIZAÇÃO DO HENRIQUE] Perde o que entrou após o passo 11 (nada, se ninguém usou).

**Depois**

18. Acompanhar `docker logs` e `backup.log` nas primeiras 24 h; confirmar o backup das 02:00 com o schema novo.
19. Registrar o deploy em `docs/architecture/` (fase-report) e atualizar `CLAUDE.md`/memória.

## 10. Checklist para deploy repetível e seguro

- [ ] Versão e tag mudam a cada deploy; imagem antiga mantida no SERVIDOR (B1).
- [ ] Volume persistente para anexos e estado (B2).
- [ ] Compose cita todas as variáveis que a API lê em produção, incluindo Almox, e existe um `.env.example` de produção só com nomes (B4, C9).
- [ ] Decidir: manter o fluxo manual documentado ou adaptar o pipeline ao SERVIDOR (registry, runner, acesso ao banco, `pg_dump`, rollback via compose). Hoje o pipeline não serve (B3).
- [ ] Verificação do backup: `pg_restore --list`, `sha256`, contagem e registro no log; cópia externa ativa; teste de restauração mensal (C1, C2).
- [ ] Backup do volume `update_repository_data` e dos anexos.
- [ ] Caddy fora do caminho padrão do `up` (perfil) e imagens base por digest (C3, C6).
- [ ] Scripts de provisionamento do SERVIDOR versionados (tarefas agendadas, powercfg, Autologon documentado) (C7).
- [ ] Smoke estendido (seção 4) em um script único, com versão esperada.
- [ ] Alerta externo simples (ping em `ready` pela URL pública, aviso se o backup do dia faltar).
- [ ] Decisão sobre a máquina antiga e o `CloudflaredTunnel` (C5).
- [ ] Documentos e memórias sincronizados (C8).

## 11. Perguntas ao Henrique

1. Posso consultar, só leitura, o container de produção no SERVIDOR para confirmar B2 (`/app/data/storage` com arquivos?) e B4 (variáveis Almox presentes)? Sem isso, essas duas ficam como suspeita forte.
2. O Almox+ está recebendo webhook/conciliação da produção hoje? Se sim, como o segredo chegou ao container?
3. Qual é a próxima versão da API (sugestão `0.12.0`) e quando é o próximo deploy com as migrations 0039 a 0047?
4. O que decidir da máquina antiga: desativar de vez a tarefa `CloudflaredTunnel` e apagar o Postgres de produção de lá, ou manter mais um tempo? Já passou a janela de 7 dias.
5. Quer manter o deploy manual por compose (mais simples) ou investir em adaptar o pipeline GitHub ao SERVIDOR? Recomendo o manual com o runbook acima, mais um script de smoke.
6. Qual PC/pasta recebe a cópia externa do backup e quem digita a credencial (`cred_backup.xml`)?
7. Os anexos de foto e vídeo estão em uso pelos usuários? (define a urgência de B2)
8. A produção deve ficar com `REMANAGEMENT_BY_ROWS_ENABLED` ligada ou desligada no próximo deploy?
