# Fase 13 — Relatório diário por e-mail

## Objetivo

Tirar o e-mail do papel de "aviso solto por evento" e dar a ele o papel de **relatório do
dia**: o que foi produzido, galvanizado, entregue, o que mudou nas propostas e o que está
atrasado, em HTML legível e uma vez por dia útil. O sino e a bandeja continuam sendo o canal de
aviso imediato; o e-mail imediato fica restrito a severidade `alta`/`critica` (já o padrão da
Fase 11).

Decisões de produto fechadas com o usuário: escopo por papel (superusuário vê a fábrica
inteira, os demais só as propostas que criaram); dias úteis às 07:00; segunda-feira cobre
sexta a domingo; dia sem movimento não envia; seções produção, galvanização, expedição,
propostas, atenção e sistema; propostas atrasadas limitadas às 5 mais antigas + contagem; peso
só aparece quando existe.

## Implementação

### API — `api/app/modules/notifications/daily_report/`

- `schemas.py`: `DailyReport` (dados puros, sem HTML), `ReportWindow` e
  `report_window_for()` — janela [00:00, 00:00) desde o último dia processado (ou do último dia
  útil). `DailyReport.has_activity` ignora pendências: atraso sozinho não é "movimento".
- `collector.py`: `collect_daily_report()` — somente leitura, agregando direto de
  `proposal_events`, `galvanization_load_events`, `expedition_events`, `proposals`,
  `galvanization_loads` e `sync_runs`. Não depende da tabela `notifications` (por usuário e
  filtrada por preferência). Escopo `scope_user_id=None` = fábrica; com id, filtra
  `proposals.created_by`.
- `renderer.py`: `render_daily_report()` — HTML em tabelas com CSS inline (compatível com
  Outlook), largura 100% do painel, seções vazias omitidas, coluna de peso só quando há peso;
  versão em texto puro e assunto. Todo valor de usuário passa por `html.escape`.

### API — envio, worker e preferências

- `email_sender.py`: `send_email(..., body_html=None)`; com HTML vai como
  `multipart/alternative` (texto + HTML). Sem HTML o comportamento é o anterior.
- `delivery_worker.py`: `_process_daily_report()` substitui o digest em texto **somente** quando
  `NOTIFICATIONS_DAILY_REPORT_ENABLED=true`. Idempotente por
  `NotificationUserSettings.last_digest_date`; falha de SMTP não marca o dia como processado;
  ao enviar, marca como `enviado` o que estava `agrupado_digest` do usuário.
- `NOTIFICATIONS_DAILY_REPORT_REDIRECT_TO`: enquanto preenchido, só o relatório global é gerado
  e vai para esse único endereço (trava de teste em dev).
- Migration `20261014_0038` (ADDITIVE): `notification_user_settings.daily_report_enabled`
  (default `true`) e `daily_report_hour` (nullable, CHECK 0–23). `PUT /notifications/settings`
  aceita os campos como opcionais (`model_fields_set`) para não sobrescrever a escolha de um
  Desktop antigo. `EXPECTED_DATABASE_REVISION` → `20261014_0038`.

### Desktop

- `NotificationPreferencesWidget`: seção "Relatório diário por e-mail" (caixa liga/desliga +
  horário 0–23 h), carregada e salva junto com o horário de silêncio.

### Ferramentas e referência visual

- `scripts/preview_daily_report.py`: gera o HTML/texto a partir da dev, sem enviar.
- `scripts/send_daily_report_test.py`: envia UM relatório `[TESTE]` (dry-run por padrão,
  `--send` explícito, SMTP do ambiente, nada gravado no banco).
- `prototipos/email_relatorio_diario/`: HTML de referência aprovado (global e por usuário).

## Garantias

1. O relatório nunca é enviado em sábado/domingo nem antes da hora configurada do usuário.
2. Um usuário recebe no máximo um relatório por dia (`last_digest_date`); falha de envio não
   consome o dia.
3. Dia sem movimento (produção, galvanização, expedição, propostas, importações) não gera
   e-mail, mesmo havendo propostas atrasadas.
4. Usuário que não é superusuário nunca vê dados de propostas criadas por outras pessoas.
5. Valores vindos do banco são escapados no HTML; o texto puro acompanha toda mensagem HTML.
6. Com `NOTIFICATIONS_DAILY_REPORT_ENABLED` desligado (padrão) o comportamento anterior —
   e-mail por evento + digest em texto — é preservado byte a byte.
7. Com `REDIRECT_TO` preenchido nenhum usuário recebe nada além do relatório global para o
   endereço configurado.
8. Desktop antigo + API nova continuam compatíveis: os campos novos de configuração são
   opcionais e não zeram a preferência existente.
9. Nenhuma execução desta fase tocou a API oficial (8000) nem aplicou a migration na dev.

## Validação

- `python -m compileall -q api/app app/ui/notification_preferences_widget.py` → OK.
- `python -m pytest api/tests -q -k "not docker_release" --deselect api/tests/test_docker_release_integration.py`
  → **812 passed, 376 skipped, 8 deselected** (os skipped incluem a suíte PostgreSQL).
- `python -m pytest api/tests/test_daily_report_email.py api/tests/test_daily_report_render.py -q`
  → **8 passed** (multipart, texto puro intacto, regra de dia útil/hora, janela de datas,
  escape de HTML, seções omitidas).
- `python -m pytest tests/test_notification_preferences_widget.py tests/test_settings_dialog.py -q`
  → **8 passed**.
- `python scripts/check_migration_checksums.py` e `python scripts/check_migration_safety.py`
  → **OK** (revision `20261014_0038` ADDITIVE).
- Visual: o HTML gerado com dados reais da dev (13/10/2026: 971 peças produzidas, 401
  entregues, 60 propostas atrasadas) foi enviado manualmente ao almoxarifado e conferido no
  Outlook pelo usuário, que aprovou o layout.

## Pendência encontrada

- **Envio automático não exercitado:** `_process_daily_report` contra PostgreSQL real e com
  SMTP real não foi executado — a dev não tem SMTP e a migration `0038` não foi aplicada nela.
  Antes de ligar a chave: migrar a dev, subir a API nova e rodar com `REDIRECT_TO`.
- **Papel "gestão" = `is_superuser`:** os papéis do sistema são "Permissões de <pessoa>", sem
  um papel de gestão nomeado. Se for necessário um grupo intermediário, falta criar uma
  permissão própria (ex.: `reports.daily_global`).
- **Peso:** na dev só 715 de 1217 itens têm `unit_weight`; nenhum item produzido em 13/10 tem
  peso, então o peso total fica oculto até a sincronização Nomus preencher.
- **Liberação na oficial** depende de autorização explícita e do checklist `release-checklist`.
