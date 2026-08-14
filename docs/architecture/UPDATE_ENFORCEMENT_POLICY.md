# Atualização Obrigatória e Opcional (Fase 13)

## Objetivo

Uma política única e server-driven decide se uma versão Desktop pode operar
normalmente, deve apenas avisar sobre uma atualização, ou deve bloquear a
operação até que uma release obrigatória seja instalada com sucesso. O
Desktop nunca hardcoda que uma versão específica é obrigatória — o mesmo
executável recebe políticas diferentes ao longo do tempo sem recompilação
(Seção 4, regra de ouro).

## Inventário encontrado

- **`CompatibilityPolicy`/estados (Fases 01-03)**: `api/app/core/versioning.py`
  (`CompatibilityStatus` com `COMPATIBLE`/`UPDATE_AVAILABLE`/`UPDATE_REQUIRED`/
  `INCOMPATIBLE`, `evaluate_desktop()` já pronto mas **nunca chamado em
  produção** antes desta fase — só existia em testes). Lado Desktop:
  `app/versioning/models.py` (mesmo enum + `CHECKING`/`MAINTENANCE`/
  `CHECK_FAILED`, estados de orquestração da Fase 03) e
  `app/versioning/compatibility.py::evaluate_startup_compatibility`.
- **`/system/compatibility` (Fase 02)**: `api/app/modules/system/{router,service,schemas}.py`
  — endpoint público, sem parâmetro de versão do cliente; a decisão
  acontecia inteiramente no Desktop, comparando os campos recebidos contra
  `APP_VERSION` local.
- **Fluxo de startup/login**: `app/main.py::run_startup_compatibility_check`
  (Fase 03) já bloqueia a criação da `MainWindow` via `CompatibilityGateDialog`
  (`app/ui/compatibility_gate_dialog.py`) até a checagem resolver — exatamente
  o ponto de bloqueio que esta fase precisa (Seção 13: "bloquear antes de
  iniciar uma nova sessão operacional").
- **Updater/dialogs da Fase 10**: `app/updater/process_control.py::launch_detached_process`
  já tinha o comentário "usado... futuramente, para o Desktop lançar o
  Updater" — o ponto de integração já estava preparado. `app/updater/manifest_gate.py`
  (Fase 11) já expõe `fetch_and_validate_manifest`/`download_and_verify_artifact`/
  `build_update_request` prontos para reuso.
- **Update Distribution Service (Fase 12)**: `api/app/updates/service.py`
  (`ReleaseState.AUTHORIZED`, `get_discovery_info`), `api/app/updates/paths.py`,
  `ReleaseStateStore` — reaproveitados sem alteração para validar que uma
  `authorized_release_version` configurada nesta fase realmente está
  `AUTHORIZED` no momento da avaliação.
- **Regras de `minimum_version`/`latest_version`/`update_required`**: nenhuma
  regra de obrigatoriedade existia antes desta fase — só o par
  minimo/recomendado das Fases 01-03 (sem noção de "obrigatório").
- **Temporizadores/checks periódicos durante a sessão**: `app/ui/main_window.py`
  só tinha um check de update **único** (`QTimer.singleShot(1500, ...)`,
  mecanismo legado GitHub/Fase 12) — nenhum re-check periódico durante uma
  sessão já ativa existia. Adicionado nesta fase (ver Seção 14 abaixo).
- **Testes existentes de compatibilidade/update**: `tests/test_compatibility_check.py`,
  `tests/test_compatibility_gate_dialog.py`, `tests/test_versioning.py`,
  `tests/test_system_api_client_compatibility.py`, `api/tests/test_system_compatibility.py`
  — todos preservados e ainda passando; estendidos (não substituídos) onde a
  assinatura de `SystemApiClient.compatibility()` ganhou um parâmetro novo.

## Modelo central da política

Persistida na tabela genérica `system_metadata` (mesma já usada pela Fase 02
para `operational_instance_identity` — nenhuma tabela nova, nenhuma
migration) sob a chave `desktop_update_policy`
(`api/app/updates/policy.py::DesktopUpdatePolicyRecord`):

```
enforcement: NONE | OPTIONAL | RECOMMENDED | REQUIRED | BLOCKED
authorized_release_version: str | None   (so um POINTER -- nunca copia dados da Fase 12)
grace_until: datetime | None (UTC)
message: str
policy_revision: int         (incrementado so quando o conteudo realmente muda)
updated_at: datetime
```

Deliberadamente **não duplica** `minimum_desktop_version`/`recommended_desktop_version`
(seguem vindo de `api/app/core/config.py`, Fases 01/02) nem o estado de uma
release (Fase 12) — `authorized_release_version` é revalidado **ao vivo**
contra `api.app.updates.service`/`ReleaseStateStore` a cada avaliação
(`resolve_effective_policy`), nunca copiado/cacheado. Se a release apontada
deixou de estar `AUTHORIZED` (revogada, nunca existiu), a política degrada
com segurança: `authorized_update_version` vira `None` e, se o enforcement
configurado era `REQUIRED`, ele é rebaixado para `RECOMMENDED` (nunca
`REQUIRED` apontando para algo que ninguém consegue instalar).

## Estados e enforcement implementados

`CompatibilityStatus` (server-side, `api/app/core/versioning.py`; Desktop-side
espelhado em `app/versioning/models.py`) ganhou `UPDATE_RECOMMENDED`, ficando
com exatamente os 6 estados pedidos (Seção 2):
`COMPATIBLE`/`UPDATE_AVAILABLE`/`UPDATE_RECOMMENDED`/`UPDATE_REQUIRED`/
`INCOMPATIBLE`/`CHECK_FAILED` (este último continua um estado de
transporte/orquestração, nunca produzido pela função pura).

`EnforcementMode` (nova, `api/app/core/versioning.py`): `NONE`/`OPTIONAL`/
`RECOMMENDED`/`REQUIRED`/`BLOCKED` — grau de obrigatoriedade administrativo,
independente da comparação pura de versão.

`evaluate_desktop_with_enforcement()` combina os dois, em ordem determinística:
1. Acima do máximo, ou `enforcement=BLOCKED` → `INCOMPATIBLE` (nunca oferece
   continuidade, mesmo com versão tecnicamente compatível).
2. Abaixo do mínimo → `UPDATE_REQUIRED` (piso rígido, nunca amaciado por
   enforcement — só `BLOCKED` é mais severo).
3. `enforcement=REQUIRED` e a versão atual desatualizada em relação ao alvo
   (`authorized_update_version` ou, na ausência, `recommended_desktop_version`)
   → `UPDATE_REQUIRED`, exceto durante o grace period (`UPDATE_RECOMMENDED`).
4. Abaixo do recomendado → `UPDATE_RECOMMENDED` quando `enforcement=RECOMMENDED`,
   senão `UPDATE_AVAILABLE`.
5. Caso contrário → `COMPATIBLE`.

Testado exaustivamente (`api/tests/test_versioning_enforcement.py`, 16 casos)
incluindo os três exemplos exatos da Seção 8 do prompt.

## Alterações em /system/compatibility

Contrato estendido de forma **aditiva** (Seção 10, "preserve campos
existentes"): `GET /system/compatibility` aceita agora um query param
opcional `desktop_version`. Sem ele, a resposta é idêntica à da Fase 02 mais
os novos campos com default seguro (`desktop_state: null`, `enforcement:
"NONE"`, etc.) — um cliente anterior à Fase 13 continua funcionando sem
qualquer alteração de comportamento. Com `desktop_version` informado (e um
SemVer válido), o servidor calcula e retorna `desktop_state` diretamente —
o Desktop não reproduz a conta de enforcement/grace period sozinho.

```json
{
  "server_version": "3.2.0", "api_contract_version": "v1",
  "minimum_desktop_version": "3.1.0", "recommended_desktop_version": "3.2.0",
  "desktop_state": "UPDATE_RECOMMENDED", "enforcement": "RECOMMENDED",
  "authorized_update_version": "3.2.0", "policy_revision": 12,
  "grace_until": null, "message": "Nova versao disponivel."
}
```

`desktop_version` inválido (ou ausente) nunca falha a requisição — só deixa
`desktop_state: null`, e o Desktop cai no fallback local (ver Seção
"Integração com Updater" abaixo).

Novos endpoints administrativos (`updates.manage`, mesma permissão da Fase
12): `GET/PUT /api/v1/updates/policy` — leitura/escrita do registro bruto
persistido (não a versão resolvida/degradada).

## Grace period e policy_revision

`grace_until` (timezone-aware, UTC) e a decisão de "antes/depois do prazo"
são sempre calculados no `now` do **servidor**
(`datetime.now(UTC)` dentro de `evaluate_for_desktop`), nunca no relógio
local do PC — o Desktop nunca recebe ou usa seu próprio horário para essa
decisão. Antes do prazo: `UPDATE_RECOMMENDED` (avisa fortemente, permite
continuar). Depois: `UPDATE_REQUIRED` (bloqueia). Testado com `now` injetado
explicitamente (`api/tests/test_versioning_enforcement.py::GracePeriodTests`).

`policy_revision` incrementa **somente quando o conteúdo efetivamente muda**
(`save_policy` compara o registro novo contra o armazenado antes de
incrementar) — chamadas repetidas com o mesmo valor não inflam a revisão.

## Fluxo OPTIONAL

`enforcement=NONE`/`OPTIONAL` com versão abaixo da recomendada →
`UPDATE_AVAILABLE`. O Desktop entra normalmente; `CompatibilityGateDialog`
fecha sozinho (`proceed=True`) e o aviso discreto já existente (mensagem
repassada via `run_startup_compatibility_check`) continua funcionando
inalterado. Durante a sessão, o novo monitor periódico
(`app/services/session_policy_monitor.py`) classifica esse estado como
`severity="info"`, sem interromper.

## Fluxo RECOMMENDED

`enforcement=RECOMMENDED` (ou `REQUIRED` ainda dentro do grace period) →
`UPDATE_RECOMMENDED`. Mesmo comportamento não-bloqueante de OPTIONAL no
startup (`CompatibilityGateDialog` fecha sozinho), mas com mensagem mais
forte (`_STATE_MESSAGES[UPDATE_RECOMMENDED]`) e, durante a sessão, um banner
persistente com `severity="warning"` (mais visível que o de OPTIONAL, sem
popup, sem repetição em loop — Seção 16).

## Fluxo REQUIRED

`CompatibilityGateDialog` (startup, antes da `MainWindow` existir) bloqueia
com `retry`/`exit` — nunca um botão "Ignorar" (Seção 17). Quando o servidor
informou `authorized_update_version`, um terceiro botão **"Atualizar
agora"** aparece, delegando integralmente a
`app.services.update_coordinator.UpdateCoordinator` (Seção 21):

1. `start_required_update()` consulta `GET /updates/desktop` (Fase 12) —
   nunca uma URL do GitHub — e confirma que a versão descoberta bate com
   `authorized_update_version` (defesa contra corrida: a release obrigatória
   mudou entre a consulta de compatibilidade e o clique).
2. `fetch_and_validate_manifest` + `download_and_verify_artifact` (Fase 11,
   reaproveitados sem alteração) baixam e validam o pacote **no processo
   principal**, antes de qualquer handoff.
3. Só com o artefato `VALID`, `build_update_request` monta o `UpdateRequest`
   (Fase 10) e o Updater separado é lançado via
   `launch_detached_process` (`Updater.exe --request <path>` empacotado, ou
   `python -m app.updater --request <path>` em desenvolvimento).
4. O diálogo fecha com `proceed=False` (nunca um `QMessageBox` modal
   bloqueando o fechamento do app — corrigido durante os testes, ver
   Riscos/Pendências) — `main.py` já trata `proceed=False` retornando sem
   construir a `MainWindow`, então o app termina sozinho para o Updater
   assumir.
5. Ao relançar (Fase 10, handshake já existente), o Desktop roda uma nova
   consulta de compatibilidade — só então libera a operação.

## Fluxo BLOCKED / CHECK_FAILED

`INCOMPATIBLE` (versão acima do máximo, ou `enforcement=BLOCKED`) usa o
mesmo bloqueio de `CompatibilityGateDialog`, também com "Atualizar agora"
quando há um pacote autorizado disponível (Seção 18) — nunca tenta uma URL
externa quando não há. `CHECK_FAILED` continua fail-closed (Fase 03,
inalterado): qualquer falha de transporte, resposta inválida ou política
inconsistente bloqueia, nunca assume `COMPATIBLE` nem `REQUIRED` sem
evidência (Seção 19) — o `desktop_state`/enforcement só são avaliados
**depois** de uma resposta HTTP válida ser obtida.

## Integração com Updater

`app/versioning/compatibility.py::evaluate_startup_compatibility` ganhou um
parâmetro opcional `server_desktop_state`: quando presente e reconhecido,
usado **diretamente** (o servidor já considerou enforcement/grace period);
ausente ou não reconhecido (servidor anterior à Fase 13, ou
`desktop_version` não enviado) → cai no fallback local (`evaluate_desktop`,
comportamento idêntico ao pré-Fase-13, nunca produz `UPDATE_RECOMMENDED`
nesse caminho, porque a matemática pura não conhece enforcement).
`maintenance_mode`/`api_contract_version` continuam prioridade 1/2, antes de
consultar `server_desktop_state` — preservados exatamente como na Fase 03.

## Integração com manifest/SHA-256

Nenhuma validação de integridade foi reduzida ou contornada. `UpdateCoordinator`
reaproveita `app.updater.manifest_gate` inalterado: manifest inválido,
tamanho ou SHA-256 divergente sempre abortam **antes** de qualquer
`UpdateRequest` ser construído ou do Updater ser lançado — mesmo em
`UPDATE_REQUIRED` (Seção 22, testado explicitamente em
`tests/test_update_coordinator.py::test_tampered_artifact_never_launches_updater`).

## Integração com servidor distribuidor

`authorized_update_version` exposto ao Desktop só existe quando
`resolve_effective_policy` confirma, **no momento da avaliação**, que a
release correspondente está `AUTHORIZED` na Fase 12 — nunca `DISCOVERED`/
`READY`, nunca `REVOKED` (testado em
`api/tests/test_updates_policy.py::ResolveEffectivePolicyTests`, incluindo o
cenário de revogação recalculando a política imediatamente). `UpdateCoordinator`
nunca recebe uma URL do GitHub — só os endpoints da Fase 12
(`/updates/desktop`, `/updates/desktop/{version}/manifest`,
`/updates/desktop/{version}/package`).

## Comportamento durante sessão ativa

`app/ui/main_window.py` ganhou um segundo timer (`_start_session_policy_timer`,
20 minutos, separado do check único de update legado já existente): reavalia
a compatibilidade periodicamente enquanto a sessão está ativa, usando a MESMA
`run_compatibility_check`/`SystemApiClient` do startup (`desktop_version`
sempre enviado). `app/services/session_policy_monitor.py::classify_session_policy_action`
(função pura, testada isoladamente) decide a reação:

- `COMPATIBLE`/`MAINTENANCE`/`CHECK_FAILED` → silencioso (falha transitória
  de rede durante a sessão não deve virar alarme a cada poll).
- `UPDATE_AVAILABLE` → banner discreto (`severity="info"`).
- `UPDATE_RECOMMENDED` → banner mais visível (`severity="warning"`), nunca
  interrompe.
- `UPDATE_REQUIRED`/`INCOMPATIBLE` → banner persistente (`severity="blocking"`)
  orientando salvar o trabalho e reiniciar o sistema.

**Limite de escopo desta fase** (ver Riscos/Pendências): o banner persistente
é o mecanismo real de aviso durante a sessão, mas esta fase não implementa um
bloqueio forçado de "novas ações críticas" dentro de telas já abertas — não
existe hoje um ponto central de "checkpoint seguro" na UI para prender essa
lógica sem tocar em cada tela individualmente (fora do escopo pedido: "menor
arquitetura segura"). O bloqueio efetivo e garantido acontece na próxima
inicialização, via `CompatibilityGateDialog` (que já impede a `MainWindow` de
sequer ser criada).

## Arquivos criados

`api/app/updates/policy.py`; `docs/architecture/UPDATE_ENFORCEMENT_POLICY.md`;
`app/services/update_coordinator.py`; `app/services/session_policy_monitor.py`;
7 arquivos de teste novos (`api/tests/test_versioning_enforcement.py`,
`test_updates_policy.py`, `test_updates_policy_integration.py`,
`test_updates_policy_router.py`, `tests/test_session_policy_monitor.py`,
`tests/test_update_coordinator.py`, `tests/test_compatibility_gate_dialog_update_flow.py`).

## Arquivos alterados

- `api/app/core/versioning.py`: `CompatibilityStatus.UPDATE_RECOMMENDED`,
  `EnforcementMode` (novo), `evaluate_desktop_with_enforcement` (novo);
  `evaluate_desktop` original preservado, agora efetivamente usado.
- `api/app/modules/system/{schemas,service,router}.py`: `desktop_version`
  query param + 6 campos novos aditivos na resposta.
- `api/app/main.py`: registra `updates_router`, sem outra alteração desta fase.
- `app/versioning/models.py`: `CompatibilityStatus.UPDATE_RECOMMENDED`.
- `app/versioning/compatibility.py`: `server_desktop_state` opcional em
  `evaluate_startup_compatibility`.
- `app/integrations/api/models.py`: `SystemCompatibilityDto` com 6 campos
  novos, todos com default seguro.
- `app/integrations/api/system_client.py`: `compatibility(desktop_version=...)`.
- `app/integrations/api/client.py`: correção pequena em `IDEMPOTENT_GET_PATHS`
  (compara o path sem query string) para o retry continuar funcionando com
  `?desktop_version=` anexado.
- `app/services/compatibility_check.py`: envia `desktop_version` e repassa
  `dto.desktop_state` para `evaluate_startup_compatibility`.
- `app/ui/compatibility_gate_dialog.py`: `UPDATE_RECOMMENDED` não-bloqueante;
  botão "Atualizar agora" para `UPDATE_REQUIRED`/`INCOMPATIBLE`.
- `app/ui/main_window.py`: timer de re-checagem periódica + banner persistente.

## Testes criados

**83 testes novos**, todos passando: `test_versioning_enforcement.py` (16),
`test_updates_policy.py` (10), `test_updates_policy_integration.py` (10),
`test_updates_policy_router.py` (8), `tests/test_session_policy_monitor.py` (9),
`tests/test_update_coordinator.py` (11), `tests/test_compatibility_gate_dialog_update_flow.py` (9),
mais 5 novos em `tests/test_compatibility_check.py::ServerDesktopStateOverrideTests`
e 5 novos em `tests/test_system_api_client_compatibility.py`.

## Resultado da suite completa

Ver relatório entregue ao usuário para os números exatos da execução
completa. Nenhum teste pré-existente foi desabilitado; dois arquivos de
teste do Desktop (`test_compatibility_check.py`,
`test_system_api_client_compatibility.py`) tiveram um `FakeSystemApiClient`
local atualizado para a nova assinatura de `compatibility(desktop_version=...)`
-- mudança de assinatura legítima, não uma supressão de cobertura.

## Riscos/pendências

- Bloqueio de "novas ações críticas" durante uma sessão já ativa (Seção 14)
  é limitado a um banner persistente, não um bloqueio estrutural de telas
  individuais — ver justificativa em "Comportamento durante sessão ativa".
- `QMessageBox.information()` modal foi removido do fluxo de sucesso do
  "Atualizar agora" durante a implementação: bloqueava o event loop
  esperando um clique que nunca viria no fluxo automático de fechamento
  (encontrado pelos próprios testes automatizados, corrigido antes da
  entrega — nunca chegou a versão final incorreta).
- `POST /updates/desktop/sync`/`authorize`/`revoke` (Fase 12) continuam sem
  UI administrativa própria — a política desta fase (`PUT /updates/policy`)
  também só tem endpoint HTTP, sem tela dedicada (fora de escopo, igual à
  Fase 12).
- Concorrência com uma segunda sessão de desenvolvimento trabalhando em
  paralelo na Fase 14 (Maintenance Mode) foi observada durante esta
  implementação (`api/app/modules/system/service.py`/`schemas.py` ganharam
  o campo `maintenance` nesse meio-tempo) -- verificado que a integração
  entre as duas fases funciona corretamente (suite re-executada após cada
  mudança externa), mas nenhuma decisão de design da Fase 14 foi tomada por
  esta sessão.

## O que ficou fora de escopo

Maintenance mode completo e tela de manutenção (Fase 14); canal
piloto/teste → produção (Fase 15); dashboard/histórico completo de updates
(Fase 16); assinatura digital/certificado de código (preservado como
estava); downgrade automático de Desktop; modo offline novo; atualização
silenciosa sem interação quando o programa está aberto.
