# Sistema Central de Versoes (Fase 01)

Fonte unica de verdade para as quatro dimensoes de versao do sistema: Desktop, Servidor/API,
Contrato da API e Schema do banco. Esta fase criou apenas a fundacao (leitura, parsing,
comparacao e modelos de compatibilidade) — nenhum mecanismo de atualizacao, distribuicao ou
endpoint publico foi implementado aqui.

## Onde cada versao nasce

| Dimensao | Fonte oficial | Arquivo |
| --- | --- | --- |
| Desktop | `APP_VERSION` | [`app/version.py`](../../app/version.py) |
| Servidor/API | `API_VERSION` | [`api/app/core/config.py`](../../api/app/core/config.py) |
| Contrato da API | `API_CONTRACT_VERSION` | [`api/app/core/config.py`](../../api/app/core/config.py) |
| Schema do banco (esperado) | `EXPECTED_DATABASE_REVISION` | [`api/app/core/config.py`](../../api/app/core/config.py) |
| Schema do banco (aplicado) | tabela `alembic_version` | lido em [`api/app/database/health.py`](../../api/app/database/health.py) |

Para alterar uma versao:

- **Desktop**: edite `APP_VERSION` (e `APP_BUILD` se aplicavel) em `app/version.py`. Nao crie
  constantes paralelas — toda tela, log ou script que precisar da versao deve importar deste
  arquivo (diretamente ou via `app.versioning.get_desktop_version()`).
- **Servidor**: edite `API_VERSION` em `api/app/core/config.py`. Uma correcao interna
  (bugfix/patch) normalmente **nao** exige mudar `API_CONTRACT_VERSION`.
- **Contrato da API**: so mude `API_CONTRACT_VERSION` quando houver alteracao deliberada e
  incompativel do contrato publico consumido pelo Desktop (ex.: `v1` -> `v2`).
- **Schema do banco**: nunca defina manualmente. A revisao aplicada e sempre lida da tabela
  `alembic_version` via Alembic. `EXPECTED_DATABASE_REVISION` deve ser atualizado apenas quando
  uma nova migration for criada e se tornar a revisao esperada em producao.

## Por que existem duas implementacoes de parsing/comparacao

Desktop e API sao empacotados e distribuidos separadamente neste repositorio (Desktop via
PyInstaller a partir de `app/main.py`; API via Docker copiando somente a pasta `api/`, ver
`api/Dockerfile`). Por isso a camada de versionamento foi criada **dentro de cada componente**,
em vez de um pacote `shared/` cross-boundary que quebraria o build da imagem Docker da API (que
nao inclui `app/`):

- Desktop: `app/versioning/`
- API: `api/app/core/versioning.py`

As duas implementacoes de SemVer (`parse_version`, `compare_versions`, `is_version_at_least`,
`is_version_newer`) sao pequenas, puras e deliberadamente identicas em comportamento. O contrato
real entre os dois lados e o JSON trafegado pela API (`/api/v1/system/version`,
`/api/v1/system/identity`), nao codigo Python compartilhado — exatamente como um cliente e um
servidor reais se comunicariam. Qualquer mudanca de regra de comparacao deve ser replicada nos
dois arquivos.

O `app/services/update_checker.py` (verificacao de novas releases no GitHub) mantem seu proprio
parser tolerante a sufixos de tag (`v2.4.1-hotfix`), pois trata um problema diferente (parsing de
tags de release externas, nao SemVer estrito de compatibilidade Desktop/API) e ja possui testes
proprios. Ele nao foi migrado nesta fase para evitar risco de regressao em uma feature fora do
escopo desta fase (distribuicao/atualizacao).

## Como comparar versoes

Nunca compare strings diretamente (`"3.10.0" < "3.9.0"` esta errado). Use sempre:

```python
# Desktop
from app.versioning import compare_versions, is_version_at_least, is_version_newer

# API
from api.app.core.versioning import compare_versions, is_version_at_least, is_version_newer
```

`compare_versions(a, b)` retorna `-1`, `0` ou `1`. `parse_version(value)` levanta `ValueError`
para strings vazias ou fora do formato `MAJOR.MINOR.PATCH` (prefixo `v` opcional).

## Modelos disponiveis

- `SemVer(major, minor, patch)` — versao tipada e comparavel, rejeita componentes negativos.
- `SystemVersionInfo(desktop_version, server_version, api_contract_version, database_schema_version)`
  — retrato completo das quatro dimensoes, validado na criacao, serializavel via `.to_dict()`.
  Montado tipicamente no Desktop apos consultar `/system/version` (`app.versioning.build_system_version_info`).
- `CompatibilityPolicy(minimum_desktop_version, recommended_desktop_version, server_version,
  api_contract_version, database_schema_version, maximum_desktop_version=None)` — politica
  publicada pelo servidor; preparada para o endpoint `/system/compatibility` da Fase 02.
- `CompatibilityStatus` (Enum: `COMPATIBLE`, `UPDATE_AVAILABLE`, `UPDATE_REQUIRED`,
  `INCOMPATIBLE`) — estado tipado, nunca string solta.
- `evaluate_desktop(policy, current_version) -> CompatibilityStatus` — funcao pura, sem rede nem
  efeitos colaterais, disponivel nos dois lados.

## O que NAO deve ser hardcoded

- Numero de versao do Desktop fora de `app/version.py`.
- Numero de versao do servidor fora de `api/app/core/config.py`.
- Comparacao de versao feita por comparacao de string ou parsing improvisado em qualquer outro
  modulo — use sempre `parse_version`/`compare_versions` do pacote de versionamento do
  componente correspondente.
- Estados de compatibilidade como strings soltas (`"compativel"`, `"update"`, etc.) — use
  `CompatibilityStatus`.
- Revisao de schema do banco reescrita manualmente fora do fluxo do Alembic.

## Endpoint `/system/compatibility` (Fase 02)

`GET /api/v1/system/compatibility` publica, de forma somente leitura, o estado atual de
compatibilidade do sistema. Consome exclusivamente a camada da Fase 01
(`api.app.core.versioning.get_compatibility_policy()`) e a leitura real do banco
(`api.app.database.health.database_check()`) — nenhum numero de versao e hardcoded no router
ou no service.

### Contrato

```
GET /api/v1/system/compatibility
Accept: application/json

200 OK
{
  "server_version": "0.8.0",
  "api_contract_version": "v1",
  "database_revision": "20260810_0015",
  "minimum_desktop_version": "2.5.2",
  "recommended_desktop_version": "2.5.2",
  "maintenance_mode": false
}
```

| Campo | Origem | Semantica |
| --- | --- | --- |
| `server_version` | `api.app.core.versioning.get_server_version()` | Versao real do backend em execucao. |
| `api_contract_version` | `api.app.core.versioning.get_api_contract_version()` | Contrato publico atual (`API_CONTRACT_VERSION`). |
| `database_revision` | `api.app.database.health.database_check()` | Revisao Alembic **real observada** (`alembic_version`), nunca a esperada/estatica — string alfanumerica, sem conversao para inteiro. |
| `minimum_desktop_version` | `CompatibilityPolicy.minimum_desktop_version` | Versao minima aceita do Desktop. |
| `recommended_desktop_version` | `CompatibilityPolicy.recommended_desktop_version` | Versao recomendada/liberada do Desktop. |
| `maintenance_mode` | `api.app.core.config.MAINTENANCE_MODE` | Somente informativo nesta fase; sempre `false`. Nao bloqueia requests nem altera a UI (logica operacional fica para a Fase 14). |

Campos deliberadamente **fora** desta resposta (pertencem a fases futuras): `download_url`,
`installer_url`, `sha256`, `release_notes_url`, `mandatory_update` calculado por cliente,
`rollback_available`, `maximum_desktop_version` (existe em `CompatibilityPolicy` mas nao e
publicado ainda).

### Autenticacao

**Publico, sem autenticacao** — mesma politica dos demais endpoints de `/system` (`health`,
`ready`, `version`, `identity`), nenhum dos quais exige token hoje. Justificativa: o Desktop so
obtem token apos login bem-sucedido, mas precisa avaliar compatibilidade *antes* de autenticar
(ex.: para decidir se deve seguir para a tela de login ou pedir atualizacao nas fases futuras).
A resposta contem apenas metadados de versao/politica — nenhuma credencial, DSN, host interno ou
dado de empresa/instancia. Nenhum mecanismo de autenticacao paralelo foi criado.

### Comportamento em falha

O endpoint nunca responde `200` com dado inventado:

- Politica central invalida (SemVer malformado, `api_contract_version`/schema vazios,
  `recommended_desktop_version` menor que `minimum_desktop_version`) -> `503
  CONFIGURATION_ERROR` (`VersionConfigurationError`).
- Banco indisponivel ou nao configurado -> `503 DATABASE_UNAVAILABLE`.
- Revisao do banco desconhecida (`unversioned`) ou divergente da esperada (`incompatible`) ->
  `503 DATABASE_REVISION_INCOMPATIBLE`.

Todas reutilizam os handlers de erro globais existentes (`api.app.core.exceptions`), preservando
`request_id`/`X-Request-ID` como qualquer outro erro da API.

### Garantias

- Read-only: nenhuma escrita no banco, nenhum arquivo criado, nenhuma migration disparada.
- Idempotente: duas chamadas consecutivas sem mudanca de ambiente retornam o mesmo corpo.
- `response_model=SystemCompatibilityResponse` com `extra="forbid"` — nenhum campo extra pode
  vazar.
- Sem cache dedicado: a leitura das constantes e imutavel em memoria por processo e a consulta ao
  banco e uma unica query leve (`SELECT version_num FROM alembic_version`), sem Redis/polling.

## Fluxo do Desktop no startup (Fase 03)

Antes de construir a `MainWindow` (portanto antes do login), `app.main.main()` chama
`run_startup_compatibility_check()`:

```
app = QApplication(...)
        v
run_startup_compatibility_check()
        v
settings.enabled? --nao--> prossegue sem checar (fluxo de login existente ja trata API desativada)
        |sim
        v
CompatibilityGateDialog (QDialog modal)
        v
QThread (start_worker) -> perform_check()
        v
SystemApiClient(client).compatibility()  [app/integrations/api/system_client.py]
        v
SystemCompatibilityDto.from_payload(...)  [app/integrations/api/models.py]
        v
app.services.compatibility_check.run_compatibility_check()
        +--> app.versioning.compatibility.evaluate_startup_compatibility()  [regra pura]
        v
CompatibilityCheckResult(state, dto, ...)
        v
COMPATIBLE/UPDATE_AVAILABLE -> dialogo fecha sozinho, main() continua
UPDATE_REQUIRED/INCOMPATIBLE/MAINTENANCE/CHECK_FAILED -> bloqueia com Tentar novamente/Sair
```

Se `run_startup_compatibility_check()` retorna `proceed=False`, `main()` retorna antes de
importar `MainWindow` — nenhuma janela operacional chega a ser criada. Se retorna
`proceed=True` com uma mensagem (estado `UPDATE_AVAILABLE`), a mensagem e passada para
`MainWindow(update_available_notice=...)` e exibida uma unica vez, ~500ms apos a janela
principal ser montada (nao bloqueia login nem qualquer operacao).

### Camadas (rede / decisao / apresentacao separadas)

| Camada | Arquivo | Responsabilidade |
| --- | --- | --- |
| Cliente HTTP | `app/integrations/api/system_client.py` (`SystemApiClient.compatibility`) | So HTTP + parse para `SystemCompatibilityDto`. Reaproveita `DesktopApiClient` (nenhum cliente HTTP novo foi criado); `/api/v1/system/compatibility` foi adicionado a `IDEMPOTENT_GET_PATHS` para retry automatico (`client.py`). |
| Regra pura | `app/versioning/compatibility.py` (`evaluate_startup_compatibility`) | Prioridade determinística: `maintenance_mode` -> `api_contract_version` -> `evaluate_desktop` (min/recomendado, ja existente da Fase 01). Sem I/O. `database_schema_version` e validado (nao vazio) mas nunca influencia o resultado. |
| Coordenador | `app/services/compatibility_check.py` (`run_compatibility_check`) | Orquestra chamada + regra pura; qualquer `ApiClientError` ou `ValueError` (política inválida) vira `CHECK_FAILED` (fail-closed, nunca inventa um estado otimista). |
| Apresentacao | `app/ui/compatibility_gate_dialog.py` (`CompatibilityGateDialog`) | QDialog modal; roda a checagem numa `QThread` via `app.ui.background_worker.start_worker` (worker generico ja existente, reaproveitado). Nao contem nenhuma comparacao de versao. |
| Ponto de entrada | `app/main.py` (`run_startup_compatibility_check`) | Le `DesktopApiConfigStore().load_settings()`, decide se a checagem se aplica, injeta fabricas (`config_store_factory`/`client_factory`/`check_runner`/`dialog_factory`) para testabilidade, igual ao `run_startup_update_check` ja existente. |

### Estados e matriz de comportamento

`CompatibilityStatus` (ja existia na Fase 01 com `COMPATIBLE`/`UPDATE_AVAILABLE`/
`UPDATE_REQUIRED`/`INCOMPATIBLE`) ganhou `CHECKING`, `MAINTENANCE` e `CHECK_FAILED` — estados de
transporte/orquestracao que `evaluate_desktop()` nunca retorna sozinho, usados apenas pelo
coordenador de startup.

| Estado | Libera operar? | Acao |
| --- | --- | --- |
| COMPATIBLE | Sim | Abre normalmente, sem dialogo visivel. |
| UPDATE_AVAILABLE | Sim | Prossegue; aviso unico e nao bloqueante apos login (`MainWindow._show_update_available_notice`). |
| UPDATE_REQUIRED | Nao | Dialogo bloqueante com versao minima exigida; Tentar novamente/Sair. |
| INCOMPATIBLE | Nao | Dialogo bloqueante (contrato de API nao suportado); Tentar novamente/Sair. |
| MAINTENANCE | Nao | Dialogo bloqueante informando manutencao; Tentar novamente/Sair. |
| CHECK_FAILED | Nao | Dialogo bloqueante (timeout/conexao/JSON invalido/política invalida); Tentar novamente/Sair. |

Nenhum estado bloqueante pode ser contornado manualmente: o unico caminho para `proceed=True`
e um resultado `COMPATIBLE`/`UPDATE_AVAILABLE` de uma checagem real.

### Autenticacao e 401/403

`GET /system/compatibility` e publico (mesma decisao da Fase 02) — nenhum token e enviado.
Qualquer `401`/`403` inesperado vindo do cliente HTTP e tratado pelo coordenador como
`CHECK_FAILED` (falha de transporte), nunca como `UPDATE_REQUIRED` — a Fase 03 nao cria
autenticacao paralela nem duplica o login existente.

### Falhas de rede

Timeout, conexao recusada, DNS invalido, 5xx, JSON invalido e campo obrigatorio ausente viram
`ApiClientError` (ja mapeados por `app/integrations/api/client.py`) e sao convertidos em
`CHECK_FAILED` pelo coordenador — nunca em `COMPATIBLE` por omissao. O cliente ja tenta 1 retry
automatico (endpoint idempotente); apos isso, o usuario decide entre Tentar novamente ou Sair.

## Fora de escopo

Download/instalacao de atualizacoes, Updater.exe, substituir o executavel em execucao, releases
do GitHub, pipelines de deploy, backup/rollback automatico, migration automatica, health checks
de deployment, ativacao administrativa de `maintenance_mode`, canais teste/producao, notificacao
recorrente pos-startup, e qualquer alteracao em fluxo de login, producao, galvanizacao,
expedicao, fiscal ou almoxarifado. Essas fases futuras devem consumir a camada criada aqui, sem
reimplementar parsing, comparacao de versao ou o contrato HTTP.
