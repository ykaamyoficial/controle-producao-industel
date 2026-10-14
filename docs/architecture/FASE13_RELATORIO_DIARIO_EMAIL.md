# Fase 13 — Relatório diário por e-mail

## Objetivo

Tirar o e-mail do papel de "aviso solto por evento" e dar a ele o papel de **relatório das
propostas**: onde elas estão agora, o que mudou de status no período e o que exige atenção
(prazo), em HTML legível e uma vez por dia útil. O foco é a **proposta e o seu status**; peças
aparecem só como apoio por proposta ("12 de 30 peças"). O sino e a bandeja continuam sendo o canal de
aviso imediato; o e-mail imediato fica restrito a severidade `alta`/`critica` (já o padrão da
Fase 11).

Decisões de produto fechadas com o usuário: escopo por papel (superusuário vê a fábrica
inteira, os demais só as propostas que criaram); dias úteis às 07:00; segunda-feira cobre
sexta a domingo; dia sem movimento não envia; seções panorama por etapa, o que mudou (por tipo
de movimento, lista completa), atenção (atrasadas, vencem em 3 dias, paradas, parciais
pendentes — 5 por lista + "e mais N") e sistema (importações Nomus).

## Implementação

### API — `api/app/modules/notifications/daily_report/`

- `schemas.py`: `DailyReport` (dados puros, sem HTML), `ReportWindow` e
  `report_window_for()` — janela [00:00, 00:00) desde o último dia processado (ou do último dia
  útil). `DailyReport.has_activity` ignora pendências: atraso sozinho não é "movimento".
- `collector.py`: `collect_daily_report()` — somente leitura, centrado em propostas. Panorama
  (`proposals` abertas por `current_area`/`current_status`), movimentos (primeiro "de" e último
  "para" de cada proposta em `proposal_events` no período, classificados por
  `classify_movement()` pelo estado final), atenção (atrasadas, vencem em 3 dias, paradas há
  `STALE_DAYS`=7 sem evento, mães com parciais abertas) e importações (`sync_runs`). Peças só
  como apoio por proposta, vindas dos eventos de produção, galvanização e expedição. Não
  depende da tabela `notifications`. Escopo `scope_user_id=None` = fábrica; com id, filtra
  `proposals.created_by`.
- `renderer.py`: `render_daily_report()` — HTML em tabelas com CSS inline (compatível com
  Outlook), largura 100% do painel, seções vazias omitidas; versão em texto puro e assunto.
  Todo valor de usuário passa por `html.escape`. Status sem acento no banco são acentuados por
  um mapa de palavras conhecidas (`humanize`).

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
3. Dia sem movimento (nenhuma proposta mudou de status, nenhuma criada/cancelada, nenhuma
   importação) não gera e-mail, mesmo havendo propostas atrasadas ou paradas.
4. Usuário que não é superusuário nunca vê dados de propostas criadas por outras pessoas.
5. Valores vindos do banco são escapados no HTML; o texto puro acompanha toda mensagem HTML.
6. Com `NOTIFICATIONS_DAILY_REPORT_ENABLED` desligado (padrão) o comportamento anterior —
   e-mail por evento + digest em texto — é preservado byte a byte.
7. Com `REDIRECT_TO` preenchido nenhum usuário recebe nada além do relatório global para o
   endereço configurado: o envio imediato (`_process_immediate`) também fica desligado, para
   notificações pendentes não irem aos e-mails reais dos usuários.
8. Desktop antigo + API nova continuam compatíveis: os campos novos de configuração são
   opcionais e não zeram a preferência existente.
9. Nenhuma execução desta fase tocou a API oficial (8000).

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
- Visual: o HTML gerado com dados reais da dev (13/10/2026: 112 propostas abertas, 26 mudaram
  de status, 8 entregues, 60 atrasadas; ~40 KB) foi conferido pelo usuário, que aprovou o
  layout centrado em propostas. A versão anterior, por peças, foi enviada e conferida no
  Outlook do almoxarifado.

## Pendência encontrada

- **Dev:** a migration `0038` foi aplicada na dev (com backup antes) e a API de dev foi
  recriada com `NOTIFICATIONS_DAILY_REPORT_ENABLED=true` e `REDIRECT_TO` para o almoxarifado
  (SMTP só no ambiente do processo, nada gravado em arquivo). O ciclo automático rodou:
  `emails=0 digests=1`, idempotente no mesmo dia, sem tocar nas entregas pendentes.
  Falta apenas conferir a chegada do e-mail automático e decidir a liberação na oficial.
- **Papel "gestão" = `is_superuser`:** os papéis do sistema são "Permissões de <pessoa>", sem
  um papel de gestão nomeado. Se for necessário um grupo intermediário, falta criar uma
  permissão própria (ex.: `reports.daily_global`).
- **"Paradas há muito tempo":** critério de 7 dias sem evento marca 87 de 112 propostas abertas
  na dev (muitas são "Em separação" na expedição, aguardando retirada). Calibrar com dados
  reais — subir o prazo ou excluir essa situação — antes de liberar na oficial.
- **Tamanho:** o HTML completo do dia 13/10 chega a ~40 KB com as listas de atenção limitadas;
  sem o limite passou de 120 KB e o Gmail corta acima de ~102 KB.
- **Liberação na oficial** depende de autorização explícita e do checklist `release-checklist`.
