# Backup Pre-Deployment e Validação de Restauração (Fase 05)

Barreira de segurança obrigatória antes de qualquer atualização do servidor:
gera um dump consistente do PostgreSQL via `pg_dump`, valida estruturalmente o
artefato, associa o backup à versão/revisão do sistema no momento em que foi
tirado, e produz um resultado tipado que qualquer automação futura de
deployment (Fase 06+) deve checar antes de prosseguir. Esta fase **não**
implementa deploy automático, restauração automática de produção, nem
maintenance mode — apenas a garantia de que existe um backup válido e
comprovadamente restaurável.

## Onde vive o mecanismo

`api/app/backup/` — independente de PySide e de qualquer endpoint HTTP,
chamável hoje manualmente (`scripts/run_predeployment_backup.py`) e por um
pipeline/deployer nas fases futuras:

| Arquivo | Responsabilidade |
| --- | --- |
| `models.py` | `BackupResult`, `BackupStatus` (`SUCCESS`/`FAILED`), `ValidationStatus` (`PENDING`/`VALID`/`INVALID`/`UNKNOWN`) |
| `connection.py` | `DATABASE_URL` (asyncpg) → parâmetros libpq (host/porta/usuário/senha/banco), sem nunca logar a senha |
| `naming.py` | `backup_id`/nome de arquivo únicos e não sobrescrevíveis |
| `validation.py` | `BackupValidator` — validação estrutural mínima obrigatória via `pg_restore --list` |
| `retention.py` | Política de retenção conservadora, opera apenas sobre manifests reconhecidos |
| `lock.py` | Lock de arquivo entre processos, com timeout explícito |
| `service.py` | `PreDeploymentBackupService` — orquestra todo o fluxo |

Nenhuma infraestrutura de backup pré-existente foi encontrada para o
PostgreSQL (inventário desta fase): `backups/pre_migrations_20260615_143827/`
é um artefato avulso da era SQLite (anterior à migração para Postgres, iniciada
em 2026-07-20) e `app/services/update_installer.py::create_pre_update_backup`
é Desktop-side e hoje um no-op (o dado operacional já está no Postgres via
API). Nada foi duplicado.

## Fluxo (Seção 11 do prompt)

```
adquire lock -> coleta metadados (server_version, database_revision real) ->
verifica destino + espaço em disco -> executa pg_dump -> confere exit code ->
confere arquivo existe e size_bytes > 0 -> valida com pg_restore --list ->
calcula SHA-256 -> grava manifest atomicamente -> aplica retenção -> libera lock

QUALQUER FALHA EM QUALQUER ETAPA -> BackupResult(status=FAILED) -> deployment bloqueado
```

`PreDeploymentBackupService.run()` **nunca levanta exceção para o chamador**
por uma falha esperada (pg_dump ausente, exit code != 0, arquivo vazio,
`pg_restore --list` rejeitando o dump, lock ocupado, espaço insuficiente,
revisão do banco indisponível) — sempre retorna um `BackupResult` tipado, e
`result.is_usable_for_deployment` (`status == SUCCESS and validation_status ==
VALID`) é a **única** condição que autoriza uma fase futura a prosseguir.
Falhas inesperadas (bug, exceção não prevista) também nunca escapam sem
registro: qualquer exceção fora dos caminhos previstos deve ser corrigida no
código, não mascarada — o serviço só suprime as exceções que ele mesmo sabe
mapear para um `error_code` específico.

## Comando `pg_dump`

```
pg_dump
  --format=custom
  --file=<caminho>.dump
  --no-owner
  --no-privileges
  -h <host> -p <porta> -U <usuário>
  <database>
```

Executado via `subprocess.run` com lista de argumentos (nunca concatenação de
shell), timeout configurável (`BACKUP_TIMEOUT_SECONDS`, default 900s), e a
senha é passada exclusivamente via variável de ambiente `PGPASSWORD` no
subprocesso — nunca em `argv` (visível em `ps`/logs) nem em nenhum arquivo.
`pg_dump`/`pg_restore` são localizados via `PG_DUMP_PATH`/`PG_RESTORE_PATH`
(default: nomes simples, resolvidos via `PATH`) e sua ausência é detectada
antes de tentar rodar (`shutil.which`), produzindo `PG_DUMP_NOT_FOUND` em vez
de um erro genérico de subprocesso.

**Não coberto pelo `pg_dump` do banco** (documentado conforme Seção 8):
roles/usuários do cluster PostgreSQL, configurações a nível de cluster, e
extensões instaladas fora do schema `public` do banco de aplicação — nenhum
desses é usado hoje pelo projeto (confirmado no inventário desta fase: sem
extensões customizadas, sem lógica dependente de roles do cluster além do
usuário de conexão já configurado via `DATABASE_URL`). Se isso mudar no
futuro, o procedimento de restauração completo deve incluir também
`pg_dumpall --globals-only` separadamente.

## Validação obrigatória (Seção 14) — nunca aceita apenas `exists()`

1. `pg_dump` exit code `== 0`
2. arquivo existe
3. `size_bytes > 0`
4. `pg_restore --list <arquivo>` exit code `== 0` **e** retorna pelo menos um
   objeto (uma listagem vazia também é tratada como inválida)
5. SHA-256 calculado com sucesso
6. manifest gravado com sucesso

Qualquer uma dessas etapas falhando marca `validation_status` como `INVALID`
(arquivo/estrutura comprovadamente ruins) ou `UNKNOWN` (não foi possível
confirmar — ex.: `pg_restore` ausente, timeout) — **ambos bloqueiam** o
deployment com o mesmo peso que `INVALID`; só `VALID` libera.

## Identidade e nome do artefato (Seção 9)

```
predeploy_20260810T201530Z_server-0.8.0_db-rev20260810_0015_a1b2c3d4.dump
```

Componentes: timestamp UTC + `server_version` (`API_VERSION`, Fase 01) +
`database_revision` (revisão real aplicada, lida via
`api.app.database.health.current_database_revision()`, Fase 04) + 8 hex
aleatórios (`secrets.token_hex`), garantindo unicidade mesmo em duas chamadas
no mesmo segundo. A identidade oficial é o `backup_id` completo (registrado no
manifest), nunca um nome fixo — o mecanismo nunca produz `backup.dump` ou
`ultimo.dump` e nunca sobrescreve um arquivo existente silenciosamente.

## Local de armazenamento

`BACKUP_DIR` (default `backups/predeployment`, resolvido relativo à raiz do
repositório quando um caminho relativo é informado) — fora de qualquer pasta
temporária da aplicação e fora do diretório `api/` que um deployment
substituiria. Configurável por ambiente (`.env`/variável `BACKUP_DIR`).
Dumps **não são versionados no Git** (`backups/` não deve ir para o
repositório — mesma convenção já aplicada ao artefato legado existente) e
**não são servidos por nenhum endpoint HTTP**.

## Metadados e manifest (Seções 16-17)

Ao lado de cada `.dump`, um `<backup_id>.manifest.json` sem nenhum secret:

```json
{
  "backup_id": "predeploy_20260810T201530Z_server-0.8.0_db-rev20260810_0015_a1b2c3d4",
  "status": "SUCCESS",
  "created_at_utc": "2026-08-10T20:15:30.123456+00:00",
  "completed_at_utc": "2026-08-10T20:15:41.987654+00:00",
  "file_path": "C:/.../backups/predeployment/predeploy_..._a1b2c3d4.dump",
  "size_bytes": 128782,
  "sha256": "…",
  "database_name": "controle_producao_dev",
  "database_revision": "20260810_0015",
  "server_version": "0.8.0",
  "api_contract_version": "v1",
  "target_release_version": null,
  "environment": "production",
  "build_sha": null,
  "validation": "VALID",
  "error_code": null,
  "error_message": null
}
```

`database_revision` é sempre a revisão **real aplicada** no momento do backup
(lida da tabela `alembic_version`, nunca a constante estática
`EXPECTED_DATABASE_REVISION`) — exatamente o ponto de recuperação que a Seção
25 exige registrar **antes** de qualquer migration futura rodar. Gravado de
forma atômica: arquivo temporário no mesmo diretório + `os.replace()` (atômico
em POSIX e Windows), nunca um manifest parcial em caso de falha no meio da
escrita.

## Retenção (Seção 21)

Defaults conservadores, configuráveis via `.env`:

```
BACKUP_RETENTION_KEEP_LAST_SUCCESSFUL=10
BACKUP_RETENTION_MINIMUM_AGE_DAYS=7
```

`protect_current_backup_id` é sempre aplicado internamente pelo serviço: o
backup que acabou de ser criado (o que "protegeu" o deployment atual) nunca é
removido pela mesma execução, mesmo que já esteja fora da janela de
quantidade/idade. A limpeza só considera arquivos com um `*.manifest.json`
reconhecido e `validation == "VALID"` — nunca apaga um arquivo arbitrário da
pasta, nem um backup cuja validação não pôde ser confirmada.

## Lock e concorrência (Seção 18)

Lock de arquivo (`<BACKUP_DIR>/.predeployment-backup.lock`), criação exclusiva
atômica (`O_CREAT|O_EXCL`, funciona igual em POSIX e Windows — sem depender de
`fcntl`/`msvcrt` nem de dependência nova). Contém `owner`/`pid`/`hostname`/
`acquired_at_utc` para diagnóstico. Timeout configurável
(`BACKUP_LOCK_TIMEOUT_SECONDS`, default 1800s); um lock só é recuperado quando
sua idade **comprovadamente** excede o timeout (nunca removido às cegas), e um
lock com conteúdo corrompido/ilegível é tratado como **ativo** (falha
fechada), nunca removido automaticamente. Um lock abandonado por um processo
morto (crash) se resolve sozinho após o timeout configurado; para destravar
manualmente antes disso, um operador precisa inspecionar e remover o arquivo
de lock deliberadamente — o mecanismo nunca faz isso por conta própria.

## Segurança e credenciais (Seção 23)

- Reaproveita o mecanismo oficial de configuração (`Settings`/`DATABASE_URL`,
  Fase 01/já existente) — nenhum novo mecanismo de secrets foi criado.
- Senha nunca aparece em manifest, log ou argumento de linha de comando —
  somente na variável de ambiente `PGPASSWORD` do subprocesso `pg_dump`, e
  `PgConnectionParams.sanitize_for_log()` redige qualquer ocorrência literal
  da senha antes de qualquer mensagem de erro ser logada ou devolvida no
  `BackupResult.error_message`.
- Dumps não são enviados a nenhum lugar (sem upload, sem GitHub, sem
  endpoint HTTP público).

## Logs e auditoria (Seção 22)

Eventos estruturados via o logger `api.backup`: `BACKUP_STARTED`,
`BACKUP_DUMP_CREATED`, `BACKUP_VALIDATED`, `BACKUP_FAILED` (com
`error_code`), `BACKUP_RETENTION_APPLIED`. Nunca inclui a senha, token ou
conteúdo do banco — apenas `backup_id`, tamanho, duração e identificadores.

## Procedimento de restauração manual (Seção 24)

**Nunca restaura automaticamente sobre produção.** Procedimento manual, em
ambiente isolado:

1. Selecionar o `backup_id` (via manifest em `BACKUP_DIR`).
2. Conferir o `sha256` do manifest contra `sha256sum <arquivo>.dump` (ou
   equivalente) antes de confiar no arquivo.
3. Criar um banco de destino **vazio e novo** (nunca reutilizar um banco em
   uso): `CREATE DATABASE <nome_temporario>;`
4. `pg_restore -h <host> -p <porta> -U <usuário> -d <nome_temporario>
   --no-owner --no-privileges <arquivo>.dump`
5. Verificar a revisão: `SELECT version_num FROM alembic_version;` deve bater
   com `database_revision` do manifest.
6. Rodar smoke queries básicas (ex.: `SELECT count(*) FROM permissions;`,
   `SELECT count(*) FROM proposals;`) e comparar com o que é esperado.
7. Só depois desses passos o backup é considerado efetivamente restaurável.
   A decisão de restaurar sobre produção de fato pertence ao plano de
   rollback de uma fase futura, não a este procedimento manual.

## Como rodar o teste de restore real (Seção 27)

O teste de integração completo (`api/tests/test_backup_restore_integration.py`)
faz exatamente esse ciclo de ponta a ponta — gera dump real, restaura em banco
temporário isolado, valida revisão e dados, descarta o banco — mas exige:

1. Um PostgreSQL de teste descartável, mesmo guard de segurança das Fases 04
   (`APP_ENV=test` + `POSTGRES_TEST_DATABASE_URL` contendo `test` no nome do
   banco).
2. `pg_dump`/`pg_restore` alcançáveis via `PG_DUMP_PATH`/`PG_RESTORE_PATH`
   (ou `pg_dump`/`pg_restore` no `PATH`).

Neste ambiente de desenvolvimento (Windows, sem cliente PostgreSQL local
instalado — confirmado no inventário desta fase), o teste fica `skipped` por
padrão. Ele **foi executado e passou de verdade** durante o desenvolvimento
desta fase, usando o Postgres de desenvolvimento já disponível em Docker
(`controle_producao_postgres_dev`) através de dois pequenos scripts
utilitários que encaminham `pg_dump`/`pg_restore` para dentro do container via
`docker exec`/`docker cp` (esses scripts são apenas uma conveniência local de
verificação, não fazem parte do repositório nem do serviço de produção, que
sempre assume `pg_dump`/`pg_restore` reais no `PATH`/`PG_DUMP_PATH`).

Para reproduzir com um cliente PostgreSQL real instalado (recomendado em CI ou
em qualquer máquina com `postgresql-client`):

```bash
export APP_ENV=test
export POSTGRES_TEST_DATABASE_URL="postgresql+asyncpg://usuario:senha@host:porta/algum_nome_com_test"
export PGPASSWORD=senha              # mesma senha do DATABASE_URL de teste
python -m pytest api/tests/test_backup_restore_integration.py -v
```

Se `pg_dump`/`pg_restore` não estiverem no `PATH`, aponte `PG_DUMP_PATH`/
`PG_RESTORE_PATH` para os binários (ou, como feito nesta verificação, para um
wrapper que os invoque via container).

## Relação com a Fase 04 (migrations)

```
BACKUP_VALID    -> migration/deployment permitido pela fase futura
BACKUP_FAILED   -> migration NAO inicia
UNKNOWN         -> migration NAO inicia (tratado com o mesmo peso de FAILED)
```

O `database_revision` registrado no manifest é sempre a revisão **antes** de
qualquer migration da Fase 04 rodar — é exatamente o ponto de recuperação que
um `RESTORE_REQUIRED` (política de downgrade da Fase 04,
`docs/architecture/DATABASE_MIGRATIONS.md`) usaria. Esta fase não aciona
migrations nem decide quando elas rodam — apenas produz e comprova a evidência
de recuperação que uma fase futura de orquestração de deployment vai exigir
antes de autorizar uma migration de risco médio/alto.

## Fora de escopo desta fase

Deploy automático do servidor, `docker pull`/`up` automático, health check
pós-deployment (Fase 06), rollback automático de API/container, restauração
automática do banco de produção, GitHub Actions de produção, upload de backup
para nuvem, Updater.exe, distribuição de atualização Desktop, maintenance mode
completo.
