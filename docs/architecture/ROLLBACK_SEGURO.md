# Rollback seguro do servidor (Fase 08)

## Objetivo

Permitir reverter rapidamente para a ultima release do backend (`api/`) que
esteve comprovadamente saudavel, quando um deployment novo falha -- sem
depender de rebuild e sem jamais restaurar automaticamente o PostgreSQL.

Fora de escopo (nao implementado nesta fase): pipeline completo de deploy
(CI/CD), rollback do Desktop (`app/`, que se auto-atualiza por outro
mecanismo), restauracao automatica de banco de dados.

## Por que o PostgreSQL nunca e revertido automaticamente

Um rollback reativa apenas a **imagem Docker** da API. O schema do banco
permanece exatamente como estava antes do rollback ser disparado. Reverter um
banco de producao automaticamente e uma operacao destrutiva de alto risco
(perda de dados escritos entre o deploy com problema e o rollback) que exige
julgamento humano e, quando necessaria, deve ser feita deliberadamente a
partir de um backup pre-deployment (Fase 05, `api/app/backup/`) -- nunca como
efeito colateral automatico de um rollback de aplicacao.

Isso implica uma regra central: **o rollback so e seguro se o codigo da
release anterior conseguir operar corretamente sobre o schema atual do
banco**, que pode ja ter avancado alem do que aquela release conhecia.

## Compatibilidade de schema: reaproveitando a Fase 04

`api/app/deployment/schema_compatibility.py` reaproveita o mesmo registro de
risco classificado manualmente na Fase 04
(`api/alembic/migration_risk_registry.json`) e o `ScriptDirectory` real do
Alembic (`api/app/core/migration_state.py`) -- nenhuma heuristica nova, nenhum
parser de SQL, nenhuma inferencia por nome de coluna.

`evaluate_rollback_schema_compatibility(from_revision, to_revision)`:

1. Se `from_revision == to_revision`, e sempre compativel (nada mudou).
2. Caso contrario, percorre a cadeia real de migrations entre as duas
   revisoes (`ScriptDirectory.walk_revisions`) e verifica se alguma delas
   esta classificada como `DESTRUCTIVE` no registro da Fase 04.
3. Qualquer `DESTRUCTIVE` no caminho bloqueia o rollback automatico
   (`compatible=False`) -- a versao anterior nao pode operar com seguranca
   sobre colunas/constraints que ela nao conhece.
4. Qualquer ambiguidade (revisao desconhecida, revisao atual do banco
   indisponivel, ordem entre as revisoes indeterminada) tambem bloqueia --
   **fail-closed**, nunca assume seguranca por falta de informacao.

Quando bloqueado, o deployment associado (se houver) e escalado para
`MANUAL_INTERVENTION_REQUIRED`: a partir dai a decisao e humana (reverter o
schema manualmente a partir de um backup, ou aceitar rodar sem rollback ate
uma correcao "forward-fix").

## Maquina de estados (`DeploymentState`/`DeploymentStatus`)

```
PREPARING -> DEPLOYING -> VALIDATING -> HEALTHY
                                      -> FAILED -> ROLLING_BACK -> ROLLED_BACK
                                                                 -> ROLLBACK_FAILED -> MANUAL_INTERVENTION_REQUIRED
                                                 -> MANUAL_INTERVENTION_REQUIRED  (bloqueio de schema)
```

Cada avanco de estado grava um **novo** registro imutavel
(`DeploymentState` e `frozen=True`; `DeploymentStateStore` escreve um arquivo
JSON por `deployment_id`, atomicamente via `os.replace`, mesmo padrao dos
manifests de backup da Fase 05). O historico completo nunca e reescrito --
`DeploymentStateStore.last_healthy()` sempre resolve a "release anterior
saudavel" percorrendo esse historico por `started_at_utc` real, nunca por
ordenacao textual de versao/tag (uma reversao manual para uma versao
numericamente anterior deve valer como a nova "anterior saudavel" dali em
diante).

Transicoes fora do mapa permitido (`api/app/deployment/service.py`,
`_ALLOWED_TRANSITIONS`) levantam `InvalidDeploymentTransitionError` --
nenhum estado pula etapas silenciosamente.

## Fluxo de rollback (`DeploymentOrchestrator.rollback_to_previous_healthy_release`)

1. Adquire o lock de arquivo (`api.app.backup.lock.BackupLock`, reaproveitado
   sem duplicar a mesma logica de exclusao mutua para um proposito novo).
2. Resolve a ultima release `HEALTHY` conhecida. Sem uma, `RollbackNotAllowedError`.
3. Avalia compatibilidade de schema (secao acima). Se bloqueado, escala o
   deployment associado (se houver) para `MANUAL_INTERVENTION_REQUIRED` e
   levanta `RollbackNotAllowedError` -- nenhuma acao Docker e executada.
4. Cria um novo `DeploymentState` (`status=ROLLING_BACK`) representando a
   propria tentativa de rollback -- o registro `FAILED` original (se houver)
   e apenas anotado (`rollback_allowed`/`rollback_reason`), nunca reescrito
   para outro status.
5. **Idempotencia**: se o container ja esta executando a imagem alvo
   (`docker inspect --format {{.Config.Image}}`), pula a troca de container e
   vai direto para a validacao -- um rollback repetido nunca reinicia um
   container que ja esta correto.
6. Caso contrario, reativa a imagem anterior por referencia (tag ou digest),
   sem rebuild: `docker rm -f` do container atual + `docker run` a partir da
   imagem anterior (`api/app/deployment/docker_control.py`).
7. Aguarda o container ficar `healthy` (reaproveita o `HEALTHCHECK` embutido
   na propria imagem, Fase 07) e roda o `SmokeTestRunner` real (Fase 06)
   contra o endpoint HTTP exposto.
8. Sucesso -> `ROLLED_BACK`. Falha em qualquer verificacao -> `ROLLBACK_FAILED`
   seguido imediatamente de `MANUAL_INTERVENTION_REQUIRED` (uma vez que o
   rollback automatico falhou, nao ha mais nenhuma acao segura a tentar sem
   intervencao humana).

## Recuperacao apos reinicio (crash-safety)

`DeploymentOrchestrator.recover_incomplete_deployment_state(running_container_image, running_container_healthy)`
deve ser chamado no startup de qualquer processo que va operar
deploy/rollback, antes de `begin_deployment`/`rollback_to_previous_healthy_release`.
Se o ultimo registro do historico nao esta em um estado terminal (o processo
anterior morreu no meio de uma transicao):

- Se a imagem **realmente em execucao** confirma a imagem alvo daquele
  registro **e** esta saudavel, o estado e resolvido para `HEALTHY`
  (deploy direto) ou `ROLLED_BACK` (rollback) -- a persistencia so nao tinha
  sido concluida.
- Qualquer outra combinacao escala para `MANUAL_INTERVENTION_REQUIRED`. Nunca
  reafirma sucesso so por observar "algum container rodando" -- exige a
  confirmacao explicita de imagem + saude.

## Concorrencia

`begin_deployment` recusa iniciar um novo deployment enquanto o ultimo
registro do historico nao estiver em um estado terminal (`ConcurrentDeploymentOperationError`),
forcando uma recuperacao explicita primeiro. O mesmo lock de arquivo usado
pelo rollback protege essa checagem, entao dois processos (deploy e rollback,
ou dois rollbacks) nunca competem pelo mesmo container.

## CLI

`scripts/run_rollback.py --reason "..." [--failed-deployment-id ID]` --
resolve a revisao atual do banco (leitura, nunca escrita), monta o
orquestrador default (`DeploymentOrchestrator` configurado via `Settings`) e
executa o fluxo acima. Sai com codigo 0 somente quando o estado final for
`ROLLED_BACK`. As variaveis de ambiente do container reativado sao lidas do
proprio ambiente do processo (prefixo `ROLLBACK_CONTAINER_ENV_*`), nunca
hardcoded no script -- evita duplicar o bloco `environment:` do
`docker-compose.prod.yml` dentro de Python.

## Configuracao (`api/app/core/config.py`)

| Variavel | Default | Uso |
|---|---|---|
| `DEPLOYMENT_STATE_DIR` | `deployments/state` | Diretorio dos registros JSON de deployment/rollback |
| `DEPLOYMENT_LOCK_TIMEOUT_SECONDS` | `1800` | Idade maxima antes de um lock ser considerado abandonado |
| `DEPLOYMENT_CONTAINER_NAME` | `controle_producao_api` | Nome do container gerenciado (mesmo nome do `docker-compose.prod.yml`) |
| `DEPLOYMENT_DOCKER_NETWORK` | `""` (obrigatorio na pratica) | Rede Docker onde o container e recriado |
| `DEPLOYMENT_HEALTH_BASE_URL` | `http://127.0.0.1:8000` | Base URL usada pelo `SmokeTestRunner` pos-rollback |
| `DEPLOYMENT_VALIDATION_TIMEOUT_SECONDS` | `60.0` | Timeout de espera por `healthy` apos reativar a imagem |

## Auditoria

Todas as transicoes de estado sao logadas estruturadamente
(`api.deployment`, nunca com secret: apenas `deployment_id`, versao e
imagem/tag) -- ver `DeploymentOrchestrator._apply_transition` e
`rollback_to_previous_healthy_release`. O registro persistido em
`DeploymentState` e, por si so, a trilha de auditoria (quem/quando/o que foi
decidido sobre `rollback_allowed`).

## Testes

- `api/tests/test_deployment_models_and_store.py` -- `DeploymentState`
  imutavel, round-trip JSON, `DeploymentStateStore.last_healthy()` por tempo
  real (nao por texto).
- `api/tests/test_deployment_schema_compatibility.py` -- contra o registro de
  risco **real** da Fase 04 (as duas migrations `DESTRUCTIVE` conhecidas,
  `20260720_0005` e `20260807_0014`, servem de fixture determinista).
- `api/tests/test_deployment_rollback_service.py` -- `DeploymentOrchestrator`
  com um `FakeDocker` injetado (nenhum subprocess real): maquina de estados,
  bloqueio por schema, sucesso, idempotencia, falhas de saude/smoke,
  concorrencia, recuperacao apos reinicio.
- `api/tests/test_deployment_rollback_integration.py` (gated por Docker real
  + Postgres de desenvolvimento, mesmo guard das Fases 04-07) -- builda a
  imagem real (Fase 07), sobe um container real, executa um rollback real
  contra o `SmokeTestRunner` real, confirma idempotencia via ID do container
  Docker e confirma que a revisao do banco de teste nunca muda.
