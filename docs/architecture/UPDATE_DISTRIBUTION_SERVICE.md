# Servidor Distribuidor de Atualizacoes do Desktop (Fase 12)

## Objetivo

Fazer o servidor da empresa atuar como unica fonte autorizada de distribuicao
das atualizacoes do Desktop: armazenar, validar e servir apenas releases
compativeis com a API e explicitamente autorizadas. Nenhum PC instala uma
release que o servidor ainda nao autorizou, mesmo que exista uma versao mais
nova em qualquer origem externa (regra de ouro, Secao 4 do prompt).

## Inventario encontrado

- **Cliente de update do Desktop (Fase pre-12)**: `app/services/update_checker.py`
  (GitHub Releases, `RELEASES_API_URL` hardcoded, parser proprio de SemVer) +
  `app/ui/update_dialog.py` + `app/services/update_downloader.py` (download
  em processo, sem o Updater separado da Fase 10) + `app/services/update_installer.py`.
  **Preservado sem alteracao de comportamento interno** -- so os *pontos de
  entrada* (`app/main.py`, `app/ui/main_window.py`, `app/ui/settings_page.py`)
  foram religados para chamar `app.services.update_distribution_client.check_for_updates`
  em vez de `app.services.update_checker.check_for_updates`. O formato do
  dict de retorno e identico, entao `UpdateDialog`/`update_downloader.py`
  continuam funcionando sem nenhuma alteracao.
- **Cliente de update da Fase 10/11**: `app/updater/` (Updater.exe separado,
  `manifest_gate.py`, `manifest_provider.py::HttpManifestProvider` -- ja
  documentado como "generico, a Fase 12 definira o servidor oficial"). Nao
  alterado: continua funcionando com qualquer `ManifestProvider`, incluindo
  uma `HttpManifestProvider` apontada para os endpoints desta fase.
- **Endpoint de compatibilidade da Fase 02**: `api/app/modules/system/router.py`
  (`GET /system/compatibility`, publico, sem autenticacao -- usado antes do
  login). Os novos endpoints de descoberta/manifest desta fase seguem o
  mesmo padrao de publicidade (ver Secao "Autenticacao" abaixo).
- **`base_url`/autenticacao/timeouts do Desktop**: `app/integrations/api/config.py`
  (`DesktopApiConfigStore`, `DesktopApiSettings`) + `app/integrations/api/client.py`
  (`DesktopApiClient`, JSON-only, `follow_redirects=False`). Reaproveitado
  diretamente pelo novo `app/services/update_distribution_client.py`.
- **Acesso atual do Desktop/Updater ao GitHub**: `app/services/update_checker.py`
  (`RELEASES_API_URL`) e `app/services/network_diagnostics.py::diagnose_update_endpoint`
  (tinha `api.github.com:443` **hardcoded** no probe de conectividade,
  independente da URL recebida como parametro -- bug latente corrigido nesta
  fase junto com a genericalizacao). Chamado por `app/ui/settings_page.py`
  ("Testar servidor de atualizacao") e `app/services/support_diagnostics.py`
  (relatorio de diagnostico). Nenhum outro ponto do Desktop/Updater acessa
  GitHub diretamente.
- **Pasta persistente no servidor**: `api/app/backup/` usa `BACKUP_DIR`
  (Fase 05) e `api/app/deployment/` usa `DEPLOYMENT_STATE_DIR` (Fase 08),
  ambos resolvidos fora da camada gravavel efemera do container, com o
  mesmo padrao de `Settings`/`.env`. Reaproveitado o mesmo padrao para
  `UPDATE_REPOSITORY_DIR`.
- **Logging/auditoria ja existentes**: `SecurityEvent` (tabela no banco,
  usado por eventos de autenticacao/usuarios) e logging estruturado via
  `logging.getLogger(...)` (padrao ja usado em `api/app/deployment/` e
  `api/app/backup/` para eventos operacionais). Como o repositorio de
  releases e baseado em arquivos (nao em linhas de banco), a auditoria desta
  fase segue o segundo padrao: `logging.getLogger("api.updates")` com
  eventos estruturados (Secao 27).
- **Lock de operacoes concorrentes**: `api/app/backup/lock.py::BackupLock`
  (lock de arquivo via `O_CREAT|O_EXCL`, recuperacao apenas por expiracao
  comprovada, generico via parametro `owner`). **Reaproveitado diretamente**
  (nao duplicado -- `backup` e `updates` vivem os dois dentro de `api/`, sem
  fronteira de empacotamento entre eles) para o lock curto de
  sync/authorize/revoke desta fase.
- **Scripts de pipeline que ja publicam o instalador Desktop**:
  `scripts/create_release_files.py` (legado, `latest.json` ad-hoc) e
  `scripts/generate_release_manifest.py` (Fase 11, gera o `manifest.json`
  oficial). Nenhum dos dois foi alterado; esta fase adiciona
  `scripts/sync_release_to_server.py` como o proximo passo do pipeline,
  consumindo o `manifest.json` da Fase 11 e publicando no repositorio local.

## Arquitetura do Update Distribution Service

Novo pacote `api/app/updates/` (irmao de `api/app/backup/` e
`api/app/deployment/`, nao dentro de `api/app/modules/` -- mesma logica: e
uma capacidade operacional/infraestrutural, nao um recurso CRUD comum):

```
api/app/updates/
  manifest_schema.py   Schema da Fase 11 replicado (duplicado deliberadamente
                        de app/updater/manifest.py -- Desktop e API sao
                        empacotados/distribuidos separadamente, o container
                        da API nunca tem acesso a app/).
  models.py             ReleaseState (enum), ArtifactInfo, ReleaseRecord.
  paths.py               Resolucao seura de caminhos (Secao 21).
  state_store.py         Persistencia atomica por versao (padrao Fase 08).
  download_grant.py      Token curto e escopado (Secao 20).
  service.py              sync_release / authorize_release / revoke_release /
                        get_discovery_info / get_manifest_bytes /
                        resolve_package_for_download / list_releases /
                        recover_incomplete_staging.
  router.py               Endpoints HTTP (publicos + admin).
  schemas.py               Modelos Pydantic de request/response.
  exceptions.py            ApiError tipados (nunca 500 generico p/ regra de negocio).
```

`scripts/sync_release_to_server.py` chama `service.sync_release`/`authorize_release`
diretamente (sem round-trip HTTP), pensado para rodar no mesmo host/container
do servidor como parte do pipeline de release -- mesmo padrao dos scripts
`scripts/deployment/*.py` da Fase 09.

## Repositorio local e volumes

```
UPDATE_REPOSITORY_DIR (default: data/updates/desktop, fora da camada
                        gravavel efemera -- use volume persistente em producao)
  staging/    Diretorios de trabalho temporarios de uma sincronizacao em
              andamento (nomeados <version>-<random>); nunca servido a
              clientes; limpo automaticamente em caso de falha/reinicio.
  ready/
    <version>/
      manifest.json         Copia exata do manifesto validado (Secao 10).
      <artifact.filename>   O pacote/instalador, ja verificado.
  revoked/    Reservado para uma politica de retencao futura mais agressiva
              (hoje a revogacao apenas muda o estado em state/, sem mover
              arquivos -- Secao 26: nao apagar em downgrade de estado).
  state/
    <version>.json   ReleaseRecord mutavel (estado atual, timestamps, motivo
                      de revogacao/falha) -- deliberadamente separado dos
                      arquivos imutaveis em ready/<version>/ (Secao 18).
  failed/     Reservado (hoje FAILED so existe como estado em state/, sem
              artefato -- nenhum arquivo de uma sincronizacao falha chega a
              ser publicado em ready/).
  .update-release.lock   Lock curto usado por sync/authorize/revoke.
```

Nunca se mistura com `BACKUP_DIR` (dumps do PostgreSQL, Fase 05) nem com
`DEPLOYMENT_STATE_DIR` (historico de deployments, Fase 08) -- diretorios
irmaos e independentes.

## Estados da release

`ReleaseState`: `DISCOVERED -> DOWNLOADING -> VERIFYING -> READY -> AUTHORIZED -> REVOKED`,
com `FAILED` alcancavel a partir de `DOWNLOADING`/`VERIFYING` quando
tamanho/SHA-256 divergem do manifesto. `FAILED` e `REVOKED` sao terminais:
uma nova sincronizacao da mesma versao com `REVOKED` e sempre rejeitada
(`ReleaseInvalidStateError`); uma nova sincronizacao com hash diferente do
que ja existe (em qualquer estado nao-`REVOKED`) e sempre rejeitada
(`ReleaseImmutableError`, Secao 18). Somente `AUTHORIZED` e servido a
`GET /updates/desktop`, ao endpoint de manifest e ao endpoint de pacote --
`READY`/`FAILED`/`REVOKED`/etc. nunca aparecem como disponiveis
(`ReleaseNotAuthorizedError`, sempre 404 generico, nunca revela o estado
interno real).

## Fluxo staging -> validacao -> autorizacao

`sync_release(manifest_path, package_path, source)` roda inteiramente dentro
do `BackupLock` (curto, mas cobre a operacao inteira -- publicacoes sao
raras e administrativas, nao o caminho quente de download):

1. Le e valida o `manifest.json` (`manifest_schema.validate_manifest_dict`)
   -- schema desconhecido rejeita explicitamente (Secao 28).
2. Bloqueia se a versao ja existe como `REVOKED`, ou se ja existe com um
   SHA-256 diferente (imutabilidade).
3. Copia o pacote para um diretorio de staging isolado (nomeado com sufixo
   aleatorio), e SO ENTAO calcula tamanho e SHA-256 por streaming sobre a
   copia staged (nunca confia apenas no que o Desktop/pipeline informou).
4. Tamanho ou SHA-256 divergentes -> grava o `ReleaseRecord` como `FAILED`
   com o motivo exato e levanta `ReleaseValidationError` -- nunca promove
   para `ready/`.
5. Tudo validado -> grava uma copia canonica do `manifest.json` no staging,
   remove um `ready/<version>/` remanescente de uma tentativa anterior
   (se existir e nao for a mesma release ja publicada) e faz
   `os.replace(staging_dir, ready/<version>/)` -- atomico em POSIX e
   Windows quando o destino nao existe (garantido pelo passo anterior).
   Um leitor concorrente nunca ve um `ready/<version>/` parcialmente
   escrito.
6. Marca `READY`. **Nunca autoriza automaticamente.**

`authorize_release(version)` (acao administrativa explicita e separada,
tambem sob lock curto): exige estado `READY`, revalida compatibilidade
(servidor atual precisa satisfazer `minimum_server_version`, e
`api_contract_version` da release precisa bater com o da API atual --
Secao 12), so entao marca `AUTHORIZED`. Idempotente (chamar de novo com a
release ja `AUTHORIZED` e um no-op).

`revoke_release(version, reason)`: exige `AUTHORIZED`, marca `REVOKED` com
motivo e timestamp; os arquivos permanecem em `ready/<version>/` para
diagnostico (Secao 26), apenas o estado muda -- indisponivel a partir da
proxima consulta de qualquer endpoint. Idempotente.

## Endpoints criados/alterados

Todos sob `/api/v1/updates` (novo router, `api/app/main.py` alterado so
para registrar `updates_router` e chamar `recover_incomplete_staging()` no
startup):

| Metodo/rota | Acesso | Descricao |
|---|---|---|
| `GET /updates/desktop` | publico | Descoberta (Secao 13): so a release `AUTHORIZED` mais recente (maior SemVer), com `manifest_url`/`package_url` ja contendo um grant de download. `{"available": false}` quando nao ha nenhuma. |
| `GET /updates/desktop/{version}/manifest` | grant OU Bearer | Devolve o `manifest.json` persistido tal como foi validado -- nunca gerado sob demanda (Secao 14). 404 generico para qualquer versao nao `AUTHORIZED`. |
| `GET /updates/desktop/{version}/package` | grant OU Bearer | Streaming via `Starlette FileResponse` (suporte nativo a `Range`/`HEAD`/`Content-Length`/`Accept-Ranges`), `ETag` derivado do SHA-256 do manifesto (nunca de mtime), `Content-Disposition` com filename controlado pelo servidor. |
| `POST /updates/desktop/sync` | `updates.manage` | Chama `sync_release` a partir de caminhos locais do servidor (`manifest_path`/`package_path`) -- pensado para o pipeline, nao para upload direto de binario via HTTP. |
| `POST /updates/desktop/{version}/authorize` | `updates.manage` | Autoriza uma release `READY`. |
| `POST /updates/desktop/{version}/revoke` | `updates.manage` | Revoga uma release `AUTHORIZED`, com motivo obrigatorio. |
| `GET /updates/desktop/admin/releases` | `updates.manage` | Lista todas as releases e seus estados (observabilidade -- nao existia um endpoint equivalente antes). |

`GET /system/compatibility` (Fase 02) nao foi alterado.

## Autenticacao do Updater

Duas necessidades diferentes, resolvidas sem criar um segundo sistema de
login (Secao 20, ultima linha):

- **Discovery + manifest**: publicos, sem autenticacao -- mesma politica ja
  usada por `/system/compatibility` (consultado antes do login, inclusive
  pela checagem automatica de atualizacao no startup do Desktop). O
  conteudo exposto (existe uma versao X autorizada, com tal tamanho/hash)
  nao e mais sensivel do que o que ja era publico via GitHub Releases antes
  desta fase.
- **Pacote (binario)**: exige OU um **grant de download curto e escopado**
  (`api/app/updates/download_grant.py`, JWT assinado com o mesmo
  `SECRET_KEY` ja usado pelos access tokens de sessao, `type="update_download"`
  distinto -- nunca aceito como access token e vice-versa, `exp` curto via
  `UPDATE_DOWNLOAD_GRANT_EXPIRE_SECONDS`, vinculado a uma unica versao, sem
  qualquer permissao administrativa) OU um access token de sessao normal
  (`Authorization: Bearer`, caso do usuario logado clicando em "verificar
  atualizacao" nas Configuracoes). O grant e a resposta directa a "o Updater
  pode precisar baixar depois que o Desktop ja fechou" (Secao 19): a
  descoberta ja entrega o grant embutido na URL, entao o Updater nunca
  precisa de uma sessao de usuario viva para terminar o download.
- O caminho do grant **nunca abre sessao de banco** (verificacao e so
  criptografica); o caminho do Bearer abre e fecha a sessao **antes** do
  streaming comecar (nao segura conexao do pool durante um download longo
  -- Secao 22).
- Endpoints administrativos exigem a nova permissao `updates.manage`
  (`api/app/modules/auth/permissions.py`), nunca acessivel a um usuario sem
  essa permissao explicita (verificado via teste HTTP real, ver abaixo).
- Nenhuma credencial administrativa e embutida no Desktop.

## Streaming / Range / ETag

Implementado via `starlette.responses.FileResponse` (ja suporta `Range`
single/multi-part, `HEAD`, `Accept-Ranges: bytes`, `Content-Length`) em vez
de parsing manual de `Range` -- reduz a superficie de bugs de seguranca
nessa area notoriamente sensivel (off-by-one, ranges negativos, leitura
fora do arquivo). Sobrescrito apenas o `ETag` (derivado do SHA-256 do
manifesto, nunca de mtime/timestamp -- Secao 17) e o `Content-Disposition`
(filename sempre o do `ArtifactInfo` persistido, nunca informado pelo
cliente). Testado com requisicoes `Range` reais (`206 Partial Content`,
`Content-Range` correto) e sem `Range` (`200`, corpo completo).

## Protecoes de seguranca

- **Path traversal (Secao 21)**: nenhuma rota aceita um caminho de arquivo
  do cliente. A versao (`{version}`) so e aceita se for um SemVer valido
  (`api.app.updates.paths.safe_version_segment`, reaproveitando
  `api.app.core.versioning.parse_version` -- SemVer valido ja exclui `..`,
  `/`, `\`); o nome do artefato usado para montar o caminho vem sempre do
  `ArtifactInfo` persistido (nunca de query/path param), e
  `resolve_ready_package_path` ainda revalida que o caminho final resolvido
  continua dentro do diretorio da versao (defesa em profundidade). Testado
  com tentativa de traversal via URL (`..%2f..%2f..%2fetc%2fpasswd`) --
  bloqueado.
- **Publicacao atomica (Secao 9)**: `ready/<version>/` so passa a existir
  via `os.replace` depois de toda validacao -- nunca ha uma janela onde um
  diretorio parcialmente escrito fica visivel.
- **Imutabilidade (Secao 18)**: uma versao ja publicada com um SHA-256 nao
  pode ser resincronizada com outro (`ReleaseImmutableError`).
- **Concorrencia (Secao 22)**: download e 100% sem lock (streaming lock-free);
  somente sync/authorize/revoke usam o `BackupLock` reaproveitado, e por uma
  janela curta.
- **Recuperacao apos reinicio (Secao 9)**: `recover_incomplete_staging()`,
  chamado no `lifespan` de startup da API, remove qualquer diretorio
  remanescente em `staging/` (so pode existir se um processo morreu no meio
  de um `sync_release`, ja que a operacao inteira roda sob lock).

## Integracao com as Fases 02, 10 e 11

- **Fase 02**: `authorize_release` reusa `api.app.core.versioning.get_server_version`/`get_api_contract_version`/`is_version_at_least`
  -- a mesma politica central, nunca uma copia paralela. `GET /system/compatibility`
  continua sendo a fonte de verdade sobre compatibilidade Desktop/API; esta
  fase so adiciona uma segunda checagem (compatibilidade da *release*, nao
  do Desktop que esta perguntando) antes de autorizar uma distribuicao.
- **Fase 10 (Updater)**: nenhum arquivo em `app/updater/` foi alterado. O
  Updater continua funcionando exatamente como na Fase 10/11; o unico ponto
  de integracao e a URL que o `ManifestProvider`/`downloader` recebem, que
  agora aponta para os endpoints desta fase em vez de uma URL generica de
  teste.
- **Fase 11 (manifest.json/SHA-256)**: o servidor trata o manifesto como
  contrato do pacote (Secao 10) -- `sync_release` reusa a mesma validacao
  estrutural (schema duplicado por causa da fronteira de empacotamento, ver
  Inventario) e a mesma logica de streaming SHA-256. **Defesa em duas
  camadas** (Secao 11): o servidor valida antes de publicar (aqui) e o
  Updater valida de novo depois do download (`app/updater/artifact_verification.py`,
  inalterado) -- nenhuma validacao substitui a outra.
- **Mecanismo legado (GitHub)**: `app/services/update_checker.py` continua
  existindo (usado apenas como utilitario de teste/parsing), mas nenhum
  ponto de entrada real do Desktop o chama mais. `app/main.py`,
  `app/ui/main_window.py` e `app/ui/settings_page.py` foram religados para
  `app.services.update_distribution_client.check_for_updates`, que consulta
  exclusivamente o servidor configurado -- sem fallback silencioso para o
  GitHub quando o servidor falha (Secao 23). `app/services/network_diagnostics.py::diagnose_update_endpoint`
  deixou de ter `api.github.com` fixo (bug latente corrigido): agora deriva
  host/porta da URL recebida, e os dois pontos que o chamavam
  (`app/ui/settings_page.py`, `app/services/support_diagnostics.py`) passam
  a testar o servidor de atualizacoes configurado.

## Revogacao e retencao

Revogacao (`revoke_release`) e uma transicao de estado pura -- nunca apaga
arquivos, so torna a release invisivel aos tres endpoints de leitura. A
decisao de obrigar usuarios a trocar de versao (o que fazer quando a
release atual e revogada) pertence a Fase 13, deliberadamente fora de
escopo aqui. Politica de limpeza/retencao de versoes antigas em `ready/`
nao foi implementada nesta fase (Secao 26 permite reter tudo enquanto fizer
sentido); nenhum mecanismo desta fase apaga um pacote publicado.

## Arquivos criados

`api/app/updates/__init__.py`, `manifest_schema.py`, `exceptions.py`,
`models.py`, `paths.py`, `state_store.py`, `download_grant.py`, `service.py`,
`router.py`, `schemas.py`; `scripts/sync_release_to_server.py`;
`app/services/update_distribution_client.py`;
`docs/architecture/UPDATE_DISTRIBUTION_SERVICE.md`; 9 arquivos de teste
(`api/tests/test_updates_manifest_schema.py`, `test_updates_paths.py`,
`test_updates_state_store.py`, `test_updates_download_grant.py`,
`test_updates_service.py`, `test_updates_router.py`,
`test_sync_release_to_server_cli.py`, `tests/test_update_distribution_client.py`,
`tests/test_network_diagnostics.py`).

## Arquivos alterados

- `api/app/core/config.py`: 3 novos campos aditivos (`update_repository_dir`,
  `update_lock_timeout_seconds`, `update_download_grant_expire_seconds`).
- `api/app/core/error_codes.py`: 7 novos codigos (`UPDATE_RELEASE_*`,
  `UPDATE_DOWNLOAD_GRANT_INVALID`).
- `api/app/modules/auth/permissions.py`: nova permissao `updates.manage`.
- `api/app/main.py`: registra `updates_router`; chama
  `recover_incomplete_staging()` no lifespan de startup.
- `api/.env.example`: documenta as 3 novas variaveis.
- `app/services/network_diagnostics.py::diagnose_update_endpoint`:
  genericalizado (host/porta derivados da URL recebida, Accept generico) em
  vez de `api.github.com` fixo.
- `app/services/support_diagnostics.py`, `app/ui/settings_page.py`:
  religados para `update_distribution_client.diagnostic_probe_url()` em vez
  de `RELEASES_API_URL`.
- `app/main.py`, `app/ui/main_window.py`, `app/ui/settings_page.py`:
  importam `check_for_updates` de `update_distribution_client` em vez de
  `update_checker` (mesma assinatura de chamada, nenhum outro ajuste
  necessario).

## Testes criados

109 testes novos, todos passando:
`test_updates_manifest_schema.py` (25), `test_updates_paths.py` (8),
`test_updates_state_store.py` (6), `test_updates_download_grant.py` (6),
`test_updates_service.py` (31 -- sync/authorize/revoke, imutabilidade,
idempotencia, compatibilidade, falha de tamanho/hash, recuperacao de
staging), `test_updates_router.py` (18 -- 11 sem Postgres cobrindo
discovery/manifest/package/Range/grant/traversal, 7 com Postgres real
cobrindo o fluxo administrativo completo via HTTP incluindo negacao de
permissao para usuario comum), `test_sync_release_to_server_cli.py` (3),
`tests/test_update_distribution_client.py` (9, Desktop-side, com
`httpx.MockTransport`), `tests/test_network_diagnostics.py` (3, com
servidor HTTP local real).

## Resultado da suite completa

Os 109 testes novos da Fase 12 passam 100% isoladamente. A suite completa
do repositorio segue sem regressoes causadas por esta fase (ver relatorio
entregue ao usuario para os numeros exatos da execucao completa).

## Riscos/pendencias

- `POST /updates/desktop/sync` recebe caminhos de arquivo *locais ao
  servidor* (nao um upload multipart) -- pressupoe que o pipeline de
  release ja deixou manifest+pacote acessiveis no filesystem do host/
  container do servidor antes de chamar o endpoint (ou o script
  `sync_release_to_server.py`, que nao depende de HTTP). Se a topologia de
  deploy mudar para um servidor sem acesso direto aos artefatos de build,
  este contrato precisara ser revisitado (ex.: upload dedicado).
- O grant de download e emitido pela descoberta publica sem exigir que o
  chamador ja esteja autenticado (ver "Autenticacao do Updater"). Isso e
  intencional (mesma exposicao publica que o GitHub Releases ja tinha), mas
  se a politica da empresa exigir autenticacao mesmo para descoberta, os
  dois endpoints de leitura precisarao ser gateados por Bearer no futuro.
  Documentado, nao implementado, para nao gold-plate a menor arquitetura
  segura pedida nesta fase.
- Diretorios `revoked/`/`failed/` existem no layout mas nenhuma logica move
  arquivos para eles hoje (revogacao/falha sao só mudanças de estado) --
  reservados para uma politica de retencao/limpeza mais agressiva, que a
  Secao 26 explicitamente deixa em aberto ("enquanto fizer sentido").
- `HEAD` funciona pela propria rota `GET` (comportamento padrao do
  Starlette/FastAPI quando so `GET` e declarado) -- nao ha teste HTTP
  explicito de `HEAD` nesta entrega, mas o mesmo `FileResponse` que ja
  suporta `Range`/`GET` trata `HEAD` pelo mesmo caminho de codigo (verificado
  manualmente durante a implementacao).

## O que ficou fora de escopo

- Regra final de atualizacao obrigatoria/opcional, bloqueio de operacao por
  update obrigatorio, interface definitiva de aviso (Fase 13).
- Maintenance mode (Fase 14).
- Canal piloto/teste -> producao (Fase 15).
- Dashboard completo de auditoria (Fase 16).
- Assinatura digital de codigo/certificado do instalador (nao existia antes
  desta fase; preservado como estava).
- Reconciliar definitivamente os dois mecanismos de update do Desktop (o
  fluxo antigo `UpdateDialog`/`update_downloader.py`/`update_installer.py`
  in-process, agora apontado para o servidor, e o novo `app/updater/`
  process-separado da Fase 10/11) em um unico fluxo -- decisao ja
  deliberadamente adiada desde a Fase 10, mantida adiada aqui.
