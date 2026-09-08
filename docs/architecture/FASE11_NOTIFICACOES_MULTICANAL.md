# Fase 11 — Notificações multicanal

## Objetivo

Tirar a notificação do sistema do nível "só chat, só toast genérico quando o app está fechado"
e levá-la a uma camada única, orientada a eventos de negócio, com entrega em três canais
(sino/Central no app, agente de bandeja sempre ativo, e-mail) e preferências por usuário —
para o usuário saber o que está acontecendo mesmo fora do programa.

## Implementação

### API — módulo genérico `api/app/modules/notifications/`

- `Notification` (uma linha por usuário-destino, idempotente por `(user_id, dedup_key)`) e
  `NotificationDelivery` (auditoria de entrega por canal: `in_app` / `tray` / `email`, com
  `status`, `attempts`, `last_error`).
- `service.emit(...)` é o ponto único de entrada: grava a notificação, resolve o plano de
  entrega por usuário (`_delivery_plan`) e registra as `NotificationDelivery`. Não faz commit
  nem publica WebSocket — quem chama commita e depois chama `publish_created(...)`.
- `router.py`: `GET /notifications`, `/unread-summary`, `/catch-up`, `POST /{id}/read`,
  `/mark-all-read`, `GET|PUT /preferences`, `GET|PUT /settings`. Permissão nova
  `notifications.view` (semeada e vinculada à role `admin` na migration + em
  `sync_official_permissions`).
- `NotificationPreference` (`(user_id, category)` → flags de canal + `min_severity_email`) e
  `NotificationUserSettings` (`quiet_start` / `quiet_end` / `quiet_channels` / `last_digest_date`).
  Ausência de linha = default da categoria (`defaults.py`, catálogo `CHAT_*`, `PROPOSTA_STATUS`,
  `PRODUCAO_LOTE`, `GALVANIZACAO_LOTE`, `ALMOXARIFADO`, `NOMUS_IMPORTACAO`, `EXPEDICAO`,
  `SISTEMA`). `critica` sempre fura o horário de silêncio.
- Canal e-mail: `email_sender.py` (SMTP da stdlib fora do event loop via `asyncio.to_thread`) +
  `delivery_worker.py` (loop único no lifespan, só sobe com `notifications_email_ready`):
  envia `pendente`/`falhou` (`attempts < NOTIFICATIONS_EMAIL_MAX_ATTEMPTS`) quase em tempo real
  e monta o digest diário dos `agrupado_digest` depois de `NOTIFICATIONS_DIGEST_HOUR`.
  Configuração SMTP em `Settings` e `api/.env.example`.

### API — produtores

- `chat/service.py::_insert_notification` passou a **espelhar** todo aviso do chat para a
  camada genérica (`_mirror_notification_to_generic`), sem parar de escrever em
  `chat_notifications`. Mapeamento `notification_type` → `category`/`severity`, `deep_link`
  `proposal/<id>?message=<mid>` ou `chat/<cid>?message=<mid>`.
- `proposals/service.py::_record_event` — choque único: uma allowlist curada
  (`_NOTIFY_PROPOSAL_EVENTS`) dispara `notifications.emit` depois de gravar o evento, para
  status de proposta, produção, galvanização de item, expedição, almoxarifado e remanejo
  compensado. Destinatários = criador da proposta + participantes do chat dela, menos o ator.
  Título reaproveita `_activity_headline`; `dedup_key` usa o `request_id`. Best-effort:
  falha na notificação nunca derruba a transação de negócio.
- `users.email` (coluna opcional nova) exposta em `UserCreate` / `UserUpdate` / `MeUpdate` /
  `UserOut` e no serviço de usuários (`_normalize_email`).

### Desktop — agente de bandeja (`app/services/notifier_agent.py`, reescrito)

- Event loop Qt com `QSystemTrayIcon` permanente (tooltip com contador, menu abrir/marcar
  todas/sair), ativo mesmo com o app principal aberto.
- `_NotifierRealtime`: WebSocket reconectável (`/chat/ws`, backoff 1–30 s, token renovado por
  tentativa); qualquer evento `notification.*` dispara um ciclo imediato. Poll de 60 s como
  rede de segurança.
- Ciclo: `GET /notifications/catch-up?since_id=<last_seen>` + `unread-summary`. Estado local
  (`notifier_state.json`) guarda `last_seen_notification_id`.
- `plan_toasts()` (função pura): severidade `alta`/`critica` → um toast por notificação com
  deep-link próprio; o resto → um toast agrupado; app principal aberto → nenhum toast (só
  contador). Toast `winotify` com `launch = "<exe>" --open <deep_link>`; falha de toast não
  avança o ponteiro.
- `stash_pending_deep_link` / `consume_pending_deep_link` + branch `--open <route>` em
  `app/main.py`.

### Desktop — app principal

- `NotificationsApiClient` + métodos no `api_proposal_storage` e no `backend_adapter`
  (`notifications_page`, `notifications_unread_summary`, `notification_mark_read`,
  `notifications_mark_all_read`, `notification_preferences[_update]`,
  `notification_settings[_update]`). `DesktopApiClient.put` adicionado.
- `NotificationCenterPanel` migrado para `/api/v1/notifications`: consome a forma genérica
  (`category`/`severity`/`title`/`body`/`deep_link`), ícone por categoria, cor por severidade,
  `_open` dispara `on_open_deep_link(route)`.
- `NotificationBell` / `TitleBar` recebem `on_open_deep_link`; o contador do sino vem de
  `notifications_unread_summary().total_unread` (todas as categorias), via poll dedicado em
  `MainWindow` (`_apply_notifications_unread_summary`), alimentado pelo timer e pelos eventos
  realtime `notification.*`.
- `MainWindow.open_deep_link(route)` — dispatcher: `proposal/<id>?message=<mid>` e
  `chat/<cid>?message=<mid>` abrem a Central de Chats no contexto certo; rota desconhecida
  abre a Central. Consome o deep-link pendente no fim de `start()`.
- Nova categoria "Notificações" em `SettingsPage` + `NotificationPreferencesWidget` (grade
  categoria × canal + severidade mínima de e-mail + horário de silêncio, carga sob demanda,
  salva via `PUT`).

## Garantias

1. Uma mesma notificação (mesmo `(user_id, dedup_key)`) nunca é gravada duas vezes, mesmo sob
   retry ou reprocessamento.
2. `emit` nunca commita nem publica WebSocket por conta própria; o produtor controla o commit,
   e o evento `notification.created` só sai depois dele.
3. Uma falha na camada de notificação (emit, espelho do chat, envio de e-mail) nunca derruba a
   transação de negócio nem o fluxo do chat — todos os pontos são best-effort com log.
4. O comportamento do sino do chat e do `chat_notifications` não muda: o chat continua
   escrevendo na tabela antiga e apenas espelha para a nova.
5. Notificação de severidade `critica` sempre fura o horário de silêncio; as demais respeitam
   preferência de canal e silêncio.
6. O canal e-mail não envia nada quando `NOTIFICATIONS_EMAIL_ENABLED` está desligado ou o SMTP
   não está configurado — as `NotificationDelivery` de e-mail ficam apenas registradas.
7. O agente de bandeja só avança `last_seen_notification_id` quando todos os toasts do lote
   foram exibidos (ou quando o app principal está aberto e os toasts são suprimidos de
   propósito); um toast que falha é retentado no próximo ciclo.
8. Uma única instância do agente `--notifier` por vez (mutex nomeado), preservando a proteção
   do refresh token compartilhado.

## Validação

- `python -m compileall -q app api/app`
- `python -m pytest api/tests -q -k "not docker_release" --deselect api/tests/test_docker_release_integration.py`
  → **687 passed, 269 skipped** (os 269 skipped incluem a suíte PostgreSQL de
  `api/tests/test_notifications_service.py`, executada no CI com `APP_ENV=test` +
  `POSTGRES_TEST_DATABASE_URL`).
- `python scripts/check_migration_safety.py` → **Politica de risco das migrations OK**
  (revisions `20260908_0031` TRANSITIONAL, `20260908_0032` ADDITIVE, `20260908_0033` ADDITIVE).
- Desktop (subconjunto tocado pela fase):
  `python -m pytest tests/test_notifier_agent.py tests/test_notification_center_panel.py tests/test_notification_bell.py tests/test_notification_preferences_widget.py tests/test_title_bar.py tests/test_settings_dialog.py tests/test_toast_manager.py tests/test_session_sync_service.py tests/test_chat_realtime_routing.py tests/test_proposal_activity_panel.py -q`
  → **63 passed**.
- `python -m pytest tests/test_installer_version_consistency.py -q` → **3 passed** (após
  `installer/ControleProducao.iss` → 2.7.0).

## Pendência encontrada

- A suíte Desktop completa (`python -m pytest tests -q`) tem falhas/travamentos **anteriores a
  esta fase** (ex.: `tests/test_diagnostic_service.py::RunDiagnosticsCompatibilityTests`,
  `tests/test_api_diagnostic_dialog.py`, `tests/test_fiscal_item_selection_dialog.py` em
  execução conjunta) — confirmadas em `git stash`. Não foram introduzidas aqui; a validação
  acima usa o subconjunto relevante.
- Notificações de jobs de sync (`/admin/sync/*` — Nomus fiscal, galvanização, propostas) e a
  nível de carga de galvanização (`_record_load_event`) ficaram fora da allowlist da Fase 4 —
  follow-up.
- `release/latest.json` / `release/manifest.json` não foram alterados: são artefatos do
  pipeline de release (`release-checklist`), publicados no passo de release, não aqui.

## Versão

- `API_VERSION` 0.8.1 → **0.9.0**; `RECOMMENDED_DESKTOP_VERSION` 2.5.2 → 2.7.0;
  `SUPPORTED_FEATURES` += `notifications_multichannel`; `EXPECTED_DATABASE_REVISION` →
  `20260908_0033`.
- `APP_VERSION` 2.6.2 → **2.7.0**, `APP_BUILD` → `2026.09.08`. `MINIMUM_API_VERSION` mantido
  em 0.8.1 de propósito: um Desktop 2.7.0 apontando para uma API antiga sem `/notifications`
  degrada em silêncio (a Central mostra estado de erro), sem bloquear a inicialização.
