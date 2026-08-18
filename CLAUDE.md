# Controle de Producao Industel

Sistema de controle de producao industrial. Arquitetura oficial (baseline 3.0.0):

```
Desktop PySide6 -> API FastAPI -> PostgreSQL
```

O desktop é cliente da API. A API centraliza autenticação, permissões, regras de negócio, histórico, auditoria e persistência no PostgreSQL. Nunca acesse o banco diretamente a partir do desktop.

## Estrutura

- `app/` — Desktop PySide6: `ui/` (páginas, dialogs, `action_center/`), `services/`, `models/` (table models Qt), `integrations/api/` (cliente HTTP da API)
- `api/app/modules/<nome>/` — cada módulo de domínio segue `router.py` + `service.py` + `schemas.py` + `models.py` (auth, chat, proposals, product_catalog, nomus_integration, provisioning, roles, security_events, system, update_audit, users, channels, health, maintenance)
- `api/alembic/` — migrations; toda revision nova precisa de entrada em `migration_risk_registry.json` (ver "Migrations" abaixo)
- `docs/architecture/` — um doc por fase finalizada (`FASEn_*.md`) ou por tópico (`UPDATER_DESKTOP.md`, `VERSIONING.md`, `CI_CD_PIPELINE.md` etc.)
- `scripts/` — automação de dev/release (migrations, backup, rollback, build de imagem Docker)
- `tests/` (raiz, PySide6+unittest) e `api/tests/` (FastAPI) — suíte oficial: `python -m pytest tests api/tests -q`

## Convenções de trabalho

- Trabalho costuma chegar em lotes grandes não commitados (às vezes centenas de arquivos cobrindo várias fases de uma vez). Ao commitar, separe por subsistema/área, nunca em um commit único. Use a skill `commit-by-subsystem`.
- Toda fase finalizada ganha um doc de fechamento em `docs/architecture/`. Use a skill `fase-report` para seguir o template atual.
- Toda migration Alembic nova falha `scripts/check_migration_safety.py` até ganhar classificação (`ADDITIVE|TRANSITIONAL|DESTRUCTIVE|DATA_MIGRATION`) + justificativa em `api/alembic/migration_risk_registry.json`. Use a skill `migration-check`.
- Release segue o checklist PRECHECK -> DEPLOY -> VERIFY -> ROLLBACK (`docs/architecture/CI_CD_PIPELINE.md`). Tag de imagem Docker sempre == `API_VERSION`; `:latest` é banido em produção. Use a skill `release-checklist`.

## Testes

- A suíte Desktop (PySide6+unittest) tem timeout configurado em `pytest.ini` (`timeout=25`, `timeout_method=thread`) porque um `Fake<Service>` incompleto pode deixar um `QMessageBox` real abrir e travar a suíte silenciosamente sem consumir CPU. Se a suíte travar ou estourar o timeout, use o agente `test-doctor`.
- Ao mockar `QMessageBox.question/warning/information` em teste de dialog, o patch precisa ser no módulo onde o dialog importa (ex: `app.ui.action_center.batch_action_center.QMessageBox.question`), nunca em `PySide6.QtWidgets` diretamente — senão o mock não tem efeito e o diálogo real abre e trava o teste.
- Convenção de badge/contador: `AppIconButton.set_badge_count` (`app/ui/components/app_icon_button.py`) pinta o número em `paintEvent` (nunca via `setText`), justamente para o botão não redimensionar quando o badge aparece/some. Testes verificam via `format_count_badge(obj._badge_count)` (`app/ui/components/count_badge.py`), não `.text()`.

## Padrão Action Center

Providers de ação de proposta (`app/ui/action_center/`) implementam `ProposalActionProvider.get_actions()` retornando `ActionDescriptor`. Categorização segue a ordem destructive > warning/attention > primary > normal; a ação primária vem de `PRIMARY_ACTION_KEYS`. Batch (`batch_action_center.py`), fiscal (`fiscal_action_center.py`) e itens de produção (`production_items_action_center.py`) têm variantes próprias — nem todas usam um provider formal. Use o agente `action-center-reviewer` antes de revisar/alterar essa área.

## Integração Nomus (fiscal)

Contrato documentado em `docs/architecture/NOMUS_FISCAL_INTEGRATION_CONTRACT.md`. Superfície: `app/services/nomus_*`, `app/ui/nomus_*`, `api/app/modules/nomus_integration/`. Mudanças nessa área devem ser conferidas contra o contrato — use o agente `nomus-integration-guide`.
