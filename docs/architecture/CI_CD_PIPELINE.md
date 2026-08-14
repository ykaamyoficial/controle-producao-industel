# Pipeline CI/CD do servidor (Fase 09)

## Objetivo

Centralizar o release do backend (`api/`) em GitHub Actions, orquestrando as
protecoes ja construidas nas Fases 01-08 -- este pipeline **nao inventa**
logica de versionamento, backup, migration, health check ou rollback: cada
etapa apenas chama o script/servico ja existente e interpreta o resultado.

## Dois workflows, separados por proposito

### `.github/workflows/ci.yml`

Roda em todo push de branch e em todo Pull Request. **Nunca** tem acesso a
secrets de producao, nunca declara `environment:`, nunca publica imagem.
Etapas: validação sintática dos próprios workflows, checksums/classificação de
risco de migrations (Fase 04) e a suite completa de testes (Desktop + API)
contra um Postgres efêmero fornecido pelo próprio GitHub Actions
(`services: postgres`).

### `.github/workflows/release-server.yml`

Só dispara por um evento deliberado (Secao 7):
- push de uma tag no formato **`api-vX.Y.Z`** -- convenção **exclusiva** de
  release do servidor, deliberadamente distinta das tags históricas do
  repositório (ex.: `v2.3.0-relatorios-operacionais`, que marcam entregas de
  produto/Desktop, não do backend) para o pipeline de produção nunca disparar
  por engano a partir de uma tag com outro propósito;
- `workflow_dispatch` manual com um input `version` obrigatório.

Nunca dispara em push comum para `main`.

## Grafo de jobs

```
validate-tag ──► test ──► build-and-publish ──► check-production-runner ──► precheck ──► deploy ──► verify ──► rollback ──► summary
   (cloud)     (cloud)         (cloud)                  (cloud)              (self-hosted, environment: production, concurrency: production-deploy)
```

- **validate-tag**: `scripts/deployment/validate_tag.py` -- extrai a versão da
  tag (ou usa o input manual) e a compara contra `api.app.core.config.API_VERSION`
  (reaproveita `resolve_release_tag`, Fase 07). Tag/versão divergente aborta
  aqui, antes de qualquer build.
- **test**: suite completa (mesmos gates do CI), agora sobre o commit exato da
  tag -- falha aqui impede build/publicação (Secao 12).
- **build-and-publish**: builda a imagem com `scripts/build_release_image.py`
  (Fase 07), publica no GHCR com duas tags (`X.Y.Z` e `sha-<commit>`) e captura
  o digest resultante. Único job com `packages: write`.
- **check-production-runner**: confirma via API do GitHub que existe um
  runner self-hosted **online** com os rótulos `production`+`deploy` antes de
  enfileirar os jobs de produção -- evita o pipeline ficar preso
  indefinidamente esperando um runner inexistente (Secao 14). Se a API não
  puder ser consultada (permissão/plano), emite um aviso e prossegue -- ver
  "Limitações conhecidas" abaixo.
- **precheck / deploy / verify / rollback / summary**: só rodam em
  `runs-on: [self-hosted, production, deploy]`, dentro do `environment: production`
  e do mesmo grupo de concorrência exclusivo `production-deploy`
  (`cancel-in-progress: false` -- nunca cancela um deploy em andamento às
  cegas, Secao 9).

## PRECHECK → DEPLOY → VERIFY → ROLLBACK

- **`scripts/deployment/precheck.py`** (Secao 15): valida a versão alvo,
  confirma Docker disponível, PostgreSQL alcançável e espaço em disco, e
  chama `DeploymentOrchestrator.begin_deployment` (Fase 08) -- que já rejeita
  um novo deployment se houver outro em andamento não-terminal, cumprindo
  "adquirir deployment lock" e "confirmar estado atual". Produz o artefato
  `DeploymentMetadata` (Secao 13), publicado como artifact do workflow para os
  jobs seguintes nunca "redescobrirem" uma imagem diferente da aprovada.
- **`scripts/deployment/run_deploy.py`** (Secoes 16-19): backup obrigatório
  via `PreDeploymentBackupService` (Fase 05) -- só prossegue se
  `backup_result.is_usable_for_deployment`; pull da imagem aprovada +
  confirmação de digest; migration executada a partir da própria imagem já
  pulled (`docker run --rm ... alembic upgrade head`, mesmo padrão de
  `scripts/run_api_migrations.bat`), preflight via `build_migration_state`
  (Fase 04); só então troca o container (`docker rm -f` + `docker run`).
  Qualquer falha marca o deployment `FAILED` com o `failed_stage` exato e
  interrompe antes da etapa seguinte.
- **`scripts/deployment/run_verify.py`** (Secoes 20-21): readiness via
  `docker_control.wait_for_healthy` (reaproveita o `HEALTHCHECK` da própria
  imagem, Fase 07, que chama `/health/ready` da Fase 06) e smoke tests via
  `SmokeTestRunner` (Fase 06) uma única vez. Sucesso só é aceito se a versão
  reportada bater exatamente com a release alvo.
- **`scripts/run_rollback.py`** (Fase 08, **reaproveitado sem alteração**):
  disparado pelo job `rollback` quando `deploy` ou `verify` falham. Avalia
  compatibilidade de schema (registro de risco da Fase 04) antes de agir;
  rollback inseguro nunca improvisa downgrade -- marca
  `MANUAL_INTERVENTION_REQUIRED` e preserva backup/logs.
- **`scripts/deployment/summarize.py`** (Secoes 23/25): projeta o
  `DeploymentState` já persistido (nunca recalcula nada) em um
  `DeploymentResult` estruturado, escrito no `$GITHUB_STEP_SUMMARY` e
  publicado como artifact JSON.

## Pré-requisitos operacionais (fora do alcance de um commit de código)

Estes itens precisam ser configurados por um humano com acesso ao GitHub e ao
host de produção -- nenhum agente de código consegue criá-los via arquivo:

1. **Environment `production`** em Settings → Environments, com os secrets
   abaixo no escopo mais restrito possível (Secao 8):
   - `PROD_DATABASE_URL`, `PROD_SECRET_KEY`, `PROD_PROVISIONING_SECRET`,
     `PROD_NOMUS_ENCRYPTION_KEY`, `PROD_OPERATIONAL_COMPANY_CODE`,
     `PROD_OPERATIONAL_COMPANY_NAME`.
   - Variables (não-secretas): `PROD_CONTAINER_NAME` (default
     `controle_producao_api`), `PROD_DOCKER_NETWORK`, `PROD_HEALTH_BASE_URL`.
   - Se o plano do repositório suportar, configurar required reviewers/wait
     timer no environment -- o workflow já está preparado para respeitar esse
     gate nativamente, mas **não depende dele** para ser seguro (Secao 8).
2. **Runner self-hosted** registrado no repositório com os rótulos
   `self-hosted`, `production`, `deploy`, instalado no host que roda o Docker
   de produção (mesmo host de `docker-compose.prod.yml`, Fase 07). Deve ser
   dedicado/fortemente restrito a este workflow -- nunca executar jobs de PR
   (Secao 14).
3. **`GITHUB_TOKEN`**: usado para publicar no GHCR (não requer PAT). Se a
   consulta à API de runners (`check-production-runner`) exigir permissão que
   o `GITHUB_TOKEN` padrão não tenha no plano/configuração deste repositório,
   ver limitação abaixo.

## Limitações conhecidas (não verificáveis a partir deste ambiente de trabalho)

- **API de runners self-hosted**: a chamada `gh api repos/.../actions/runners`
  no job `check-production-runner` pode exigir uma permissão que o
  `GITHUB_TOKEN` padrão nem sempre carrega, dependendo do plano/configuração
  do repositório. O job trata essa falha como aviso (não bloqueia o pipeline)
  em vez de assumir sucesso ou falhar incorretamente -- mas isso significa que,
  nesse cenário, a garantia de "falhar com mensagem clara se o runner não
  existir" (Secao 14) degrada para o comportamento nativo do GitHub Actions
  (fila indefinida). Validar com um runner real registrado antes de depender
  disso em produção.
- **`actionlint` não disponível neste ambiente**: a validação das duas YAMLs
  foi feita com `yaml.safe_load` (sintaxe) + revisão manual semântica
  (chaves, expressões `${{ }}`, `needs`/`if`) + os testes estruturais em
  `api/tests/test_release_workflows_policy.py`. Recomenda-se rodar
  `actionlint` (ou equivalente) num ambiente com acesso a instalar a
  ferramenta antes do primeiro uso real do workflow.
- **Dependências de sistema para testes Qt headless no runner do CI**: os
  pacotes `apt-get` listados em `ci.yml`/`release-server.yml` (libegl1,
  libxkbcommon0 etc.) seguem o conjunto comumente necessário para PySide6 em
  modo `offscreen` em runners Ubuntu, mas não puderam ser validados contra um
  runner GitHub-hosted real a partir deste ambiente local. Se a suite Desktop
  falhar por biblioteca ausente na primeira execução real, ajustar essa lista.
- **`test`/`build`/`deploy`/`verify`/`rollback` para Docker+Postgres real das
  Fases 07/08** (`test_docker_release_integration.py`,
  `test_deployment_rollback_integration.py`) continuam gated por
  `dev_postgres_network()`, que procura o container de desenvolvimento
  nomeado `controle_producao_postgres_dev` -- inexistente no runner de CI
  hospedado. Esses testes portanto **não rodam em CI comum** (ficam
  `skipped`), por design (Secao 28: "testes destrutivos/integrais devem usar
  ambiente isolado", não o CI de todo PR). A cobertura real desses caminhos
  continua exigindo execução manual num ambiente com Docker + Postgres de
  desenvolvimento, como já era o caso nas Fases 07/08.

## Testes

- `api/tests/test_deployment_pipeline_validate_tag.py` -- convenção de tag,
  divergência de versão.
- `api/tests/test_deployment_pipeline_metadata.py` -- round-trip do artefato.
- `api/tests/test_deployment_pipeline_precheck.py` -- todos os gates do
  PRECHECK, com `DeploymentOrchestrator` real + `FakeDocker`.
- `api/tests/test_deployment_pipeline_deploy.py` -- backup inválido, digest
  divergente, migration falha, revisão pós-migration divergente: todos
  bloqueiam antes da troca do container.
- `api/tests/test_deployment_pipeline_verify.py` -- readiness nunca atingida,
  smoke falho, versão divergente.
- `api/tests/test_deployment_pipeline_summarize.py` -- classificação do
  `DeploymentResult` (SUCCESS/FAILED/ROLLED_BACK/MANUAL_INTERVENTION).
- `api/tests/test_release_workflows_policy.py` -- sintaxe YAML, separação
  CI×deploy, permissões mínimas, ambiente/concorrência/rótulos de runner nos
  jobs de produção, reuso do `scripts/run_rollback.py` (nunca reimplementado).
