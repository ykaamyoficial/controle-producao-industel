# 08 - Estado do SERVIDOR (leitura, 2026-11-19)

Leitura só de leitura feita no SERVIDOR (192.168.2.128) pelo agente Leitor. Nada foi alterado. Os arquivos temporários criados em `C:\ControleProducao\tmp_leitura` foram apagados ao fim. Nenhum valor de `.env`, segredo, senha ou hash foi impresso ou gravado.

## Hora e fuso

- Hora local do SERVIDOR: 2026-11-19 17:43 (quinta-feira).
- Fuso: E. South America Standard Time, (UTC-03:00) Brasília. Em UTC: 20:44.

## A1. Banco e números da migração

- Revisão Alembic: `20261014_0038`.
- `inspections`: NULL (tabela não existe). `logistics_logs`: NULL (não existe).
- Perfis `admin`: 1.
- `nf_canceladas_hoje` (fiscal_invoices com status CANCELADA): 0.
- `nf_que_a_0043_vai_cancelar`: 8.
- `propostas_entregues_almox` (warehouse_status ALMOXARIFADO_ENTREGUE): 228.
- Usuários: 14 no total, 14 ativos.

## A2. Versão em execução e imagens

- `controle_producao_api` usa `local/controle-producao-api:0.11.0`, status `Up 9 days (healthy)`.
- `/api/v1/system/version`: `server_version` 0.11.0, `commit_sha` 1c18459, `api_stage` official-fiscal, `database_revision` 20261014_0038.
- Imagem `0.11.0` presente (481 MB). Também existe o arquivo `C:\ControleProducao\api-0.11.0.tar` (122 MB), que serve de rollback.

## A3. Volumes Docker

- Volumes existentes: `controle_producao_industel_postgres_prod_data` e `controle_producao_industel_update_repository_data` (1,3 GB de updates).
- Container da API monta só `controle_producao_industel_update_repository_data` -> `/var/lib/controle-producao/updates`.
- Volume `controle_producao_industel_api_data` não existe (ainda não criado, como esperado).
- Mount do Postgres não foi inspecionado (só a lista de volumes).

## A4. Variáveis do container da API (só nomes)

- Presentes (nomes): `SECRET_KEY`, `DATABASE_URL`, `PASSWORD_MIN_LENGTH`, `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCK_MINUTES`, `PROVISIONING_SECRET`, `NOMUS_ENCRYPTION_KEY`, `SMTP_*`, `OPERATIONAL_*`, `BUILD_COMMIT_SHA`, `BUILD_TIME_UTC`, entre outras.
- Ausentes: `ALMOX_INTEGRATION_SECRET`, `ALMOX_WEBHOOK_URL`, `CLIENT_VERSION_ENFORCEMENT_ENABLED`, `LOGIN_IP_MAX_FAILURES`, `LOGIN_IP_WINDOW_SECONDS`.
- Consequência: o container não tem Almox+ configurado hoje (nenhum dos dois nomes existe).

## A5. Anexos

- `/app/data/storage` não existe. Logo, 0 arquivos e 0 bytes de anexos.
- `/app/data/audit_spool` existe (2,0 MB). `/app/data/system_state` não existe.
- Conclusão: a cópia de `/app/data/storage` (Passos 4 e 9) não é necessária hoje.

## A6. Disco e memória

- `C:`: 85,3 GB usados, 137,6 GB livres (acima do mínimo de 5 GB).
- RAM livre: 2,8 GB.
- Docker: imagens 1,22 GB; volumes locais 1,403 GB; containers 5,6 MB; build cache 0.

## A7. Backups

- Tarefa `ControleProducaoBackup`: `LastRunTime` 2026-11-19 02:00:00, `LastTaskResult` 0, próxima execução 2026-11-20 02:00.
- Arguments: `-NoProfile -ExecutionPolicy Bypass -File C:\ControleProducao\backup_db.ps1`. Sem `-Destino` (cópia externa não configurada na tarefa).
- Dumps locais (`C:\ControleProducao\backups`): `cp_20261111_0200` até `cp_20261119_0200`, um por dia, de 2,1 a 2,6 MB. O último é `cp_20261119_0200.dump` (2 216 179 bytes).
- Log: última execução OK. Única falha registrada: 2026-11-04 11:43:57, cópia externa para `\\Srv\geral\...` recusada por senha de rede incorreta (dump local mantido). Desde então só cópia local.
- Restauração de teste: não feita nesta leitura (só leitura, sem restore).

## A8. Saúde e relógio

- `controle_producao_postgres` (healthy), `controle_producao_api` (healthy), `controle_producao_cloudflared` (Up 9 days). Nenhum container `caddy`.
- `/api/v1/health/ready`: HEALTHY, banco OK, revisão `20261014_0038` compatível, `maintenance_state` OFF.
- `w32tm /query /status` não retornou linhas de sincronização nesta leitura (não confirmado).

## A9. Compose e arquivos em C:\ControleProducao

- `docker-compose.prod.yml` não contém `api_data` (False, como esperado).
- Arquivos: `.env` (1141 B, 04/11), `api-0.11.0.tar` (122 MB), `backup_db.ps1`, `backup_externo.ps1`, `Caddyfile` (1703 B), `counts.sql`, `counts_destino.txt`, `docker-compose.prod.yml` (8073 B), `docker-compose.servidor.yml` (532 B), `final.dump` (3,5 MB), `updates.tar` (1,3 GB). Todos com data de 04/11/2026.
- Sobras de 04/11 para revisar depois (`counts.sql`, `counts_destino.txt`, `final.dump`): só anotadas, nada apagado.
- `.env` do SERVIDOR tem `CADDY_HOSTNAME`, `CADDY_TLS_CERT_PATH`, `CADDY_TLS_KEY_PATH` (configuração antiga, sem container Caddy).

## Extra 1. Chaves do .env (só nomes; valores nunca impressos)

- `ALMOX_INTEGRATION_SECRET`: AUSENTE.
- `ALMOX_WEBHOOK_URL`: AUSENTE.
- `LOGIN_IP_MAX_FAILURES`: AUSENTE.
- `BOOTSTRAP_ADMIN_PASSWORD`: AUSENTE.
- `SECRET_KEY`: presente, com valor não vazio.

## Extra 2. Arquivos com nome de Almox/segredo/webhook em C:\ControleProducao

- Nenhum arquivo encontrado (busca recursiva por nome: `almox`, `segredo`, `secret`, `webhook`).

## Extra 3. Perfis e superusuários

- 14 perfis (roles), 1 usuário em cada: `admin` (Administrador) e 13 perfis `desktop_user_2` a `desktop_user_14`, cada um ligado a um usuário.
- Superusuários ativos: 1, username `admin`.

## Extra 4. Postgres

- Container `controle_producao_postgres`. Variáveis (só nomes): `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`. Uso: `docker exec controle_producao_postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`.

## Extra 5. B1 - eventos de login do admin (desde 2026-01-01)

- Linhas do admin (LOGIN_SUCCESS, LOGIN_FAILED, ACCOUNT_LOCKED): 177. Total geral de `security_events`: 10 188.

| user_agent (60 chars) | IP | tipo | n | primeira | última |
|---|---|---|---|---|---|
| ControleProducaoIndustel/desktop-api-client | 172.19.0.1 | LOGIN_SUCCESS | 10 | 2026-09-04 12:02:32 | 2026-09-04 13:28:03 |
| curl/8.19.0 | 172.19.0.1 | LOGIN_SUCCESS | 6 | 2026-09-04 12:03:31 | 2026-09-04 13:41:27 |
| curl/8.19.0 | 172.21.0.1 | LOGIN_SUCCESS | 1 | 2026-09-04 16:01:38 | 2026-09-04 16:01:38 |
| ControleProducaoIndustel/desktop-api-client | 172.21.0.1 | LOGIN_SUCCESS | 91 | 2026-09-04 15:02:27 | 2026-10-23 18:28:19 |
| ControleProducaoIndustel/desktop-api-client | 172.21.0.1 | LOGIN_FAILED | 67 | 2026-09-04 15:02:24 | 2026-10-23 18:02:23 |
| ControleProducaoIndustel/desktop-api-client | 172.21.0.1 | ACCOUNT_LOCKED | 2 | 2026-09-28 18:48:15 | 2026-10-06 12:29:46 |

- User agents distintos: 2 (`ControleProducaoIndustel/desktop-api-client` e `curl/8.19.0`). Horários em UTC.
- Por dia (sucessos / falhas / bloqueios):
  - 09-04: 20 / 1 / 0. 09-08: 12 / 8 / 0. 09-09: 1 / 0 / 0. 09-11: 7 / 4 / 0. 09-14: 6 / 0 / 0. 09-16: 3 / 4 / 0. 09-17: 1 / 1 / 0. 09-18: 1 / 0 / 0. 09-21: 1 / 1 / 0. 09-22: 1 / 0 / 0. 09-23: 1 / 0 / 0.
  - 09-28: 6 / 12 / 1. 09-29: 2 / 4 / 0. 10-02: 4 / 2 / 0. 10-06: 3 / 24 / 1. 10-07: 11 / 1 / 0. 10-08: 13 / 0 / 0. 10-13: 1 / 3 / 0. 10-14: 0 / 1 / 0. 10-15: 2 / 0 / 0. 10-16: 3 / 0 / 0. 10-19: 3 / 0 / 0. 10-20: 1 / 0 / 0. 10-21: 2 / 0 / 0. 10-23: 3 / 1 / 0.
- Sem eventos do admin após 2026-10-23.
- Pontos para olhar: 7 sucessos com `curl/8.19.0` (todos em 2026-09-04, de 172.19.0.1 e 172.21.0.1; cliente de linha de comando, não o Desktop); 2 bloqueios de conta (2026-09-28 e 2026-10-06); 1 evento de login sem ator nem alvo (não ligado ao admin).
- Os IPs 172.19.0.1 e 172.21.0.1 são gateways internos do Docker, não o IP real de origem.

## GATE

- Revisão == `20261014_0038`? **SIM** (banco ainda na 0038; as migrações 0043/0044 ainda não rodaram).
- >= 5 GB livres em `C:`? **SIM** (137,6 GB).
- Anexos em `/app/data/storage`: **0 arquivos, 0 bytes** (diretório não existe). Cópia de anexos não necessária.
- Nomes reais dos volumes: `controle_producao_industel_postgres_prod_data`, `controle_producao_industel_update_repository_data`. `controle_producao_industel_api_data` ainda não existe.
- Nomes das imagens: `local/controle-producao-api:0.11.0` (481 MB), `cloudflare/cloudflared:2026.9.3` (97,6 MB), `postgres:16` (642 MB).
- Containers: `controle_producao_api`, `controle_producao_postgres`, `controle_producao_cloudflared`.
- `nf_que_a_0043_vai_cancelar`: **8**.
- `nf_canceladas_hoje`: **0**.
- `propostas_entregues_almox`: **228**.
- Usuários: **14 total / 14 ativos**.
- Almox+ no container: `ALMOX_INTEGRATION_SECRET` e `ALMOX_WEBHOOK_URL` ausentes (nem no .env, nem no container).
