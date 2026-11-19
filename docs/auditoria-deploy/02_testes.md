# 02 - Auditoria de testes (branch `logistica-melhorias`, HEAD c1d31a3)

Data: 2026-11-19. Python 3.14.6, PySide6, pytest 8.4.2 + pytest-timeout. Nada alterado no código; só este arquivo foi escrito.

## Resumo

| Suíte | Resultado (saída real) | Duração |
|---|---|---|
| Desktop `tests/` (222 arquivos, 4 lotes, `QT_QPA_PLATFORM=offscreen`, `--timeout=60`) | **2475 passed, 23 skipped, 0 failed** (855+1s / 548+7s / 557+14s / 515+0s) | 170+104+117+95 s |
| API `api/tests/` sem banco (exclui 2 arquivos Docker) | **957 passed, 512 skipped, 0 failed** | 85,7 s |
| API integração em Postgres descartável, Logística+Inspeção (`test_logistics.py`, `test_inspection.py`) | **63 passed, 0 skipped** | 420 s |
| API integração em Postgres descartável, Almox/estoque/remanejamento (9 arquivos, lista abaixo) | **87 passed, 0 skipped** | 720 s |
| `test_docker_release_integration.py`, `test_deployment_rollback_integration.py` | **NÃO rodados** (ver achado T2) | - |

Zero falha, zero erro, zero flaky (sem falha para repetir 2x).

Comandos (a partir da raiz do repo):

- Desktop: `QT_QPA_PLATFORM=offscreen python -m pytest <arquivos do lote> -q -p no:cacheprovider --timeout=60 -rfEs; echo EXIT=$?` (4 lotes por ordem alfabética, todos EXIT=0).
- API sem banco: `python -m pytest api/tests -q -p no:cacheprovider --timeout=60 -rfEs --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py` -> `957 passed, 512 skipped, 56 warnings in 85.67s`, EXIT=0. (Marcador do `api/tests/conftest.py` força 120 s por teste na API, acima do `--timeout=60`.)
- API integração: `APP_ENV=test POSTGRES_TEST_DATABASE_URL=<container Docker descartável, 127.0.0.1:55461, banco controle_producao_test_audit> python -m pytest ...`. Arquivos do 2o lote: `test_warehouse_enter/items/list/stock_deduction`, `test_migration_warehouse_stock_deduction`, `test_remanagement_rows`, `test_remanagement_different_flows`, `test_galvanized_remanagement`, `test_inspection_entry`. Container `audit_tests_pg` (postgres:16) criado só para isto e removido ao fim. Não toquei no Postgres da porta 5432 do host, nem na 8000/8001/SERVIDOR.

## Como as suítes rodam (mapeamento)

- `pytest.ini`: `testpaths = tests api/tests`, `timeout = 25` (thread). README: `python -m pytest tests api/tests -q` (baseline 3.0.0 citada lá: 330 passed / 35 skipped, defasada; hoje são ~3.400 testes coletados).
- `scripts/run_api_tests.bat`: `unittest discover` dentro do Docker com `DATABASE_URL=` vazio (só unit). `scripts/run_api_integration_tests.bat`: recria `controle_producao_test` no Postgres dev (porta 55432) e roda `test_*integration*.py`; recusa nome de banco sem "test".
- Guard das integrações API: `APP_ENV=test` + `POSTGRES_TEST_DATABASE_URL` com "test" no nome do banco. Sem isso, pulam (é o caso padrão e o de CI comum).
- Desktop usa só fakes: as URLs `127.0.0.1:8000` encontradas nos testes são strings de `DesktopApiSettings` com clientes falsos; `test_desktop_api_integration.py` só roda com `DESKTOP_API_INTEGRATION=1` (não setado). Nenhum teste escreve em produção; `api/.env` não existe (o `.env.production` da raiz não é lido pela config).
- Referência de CI: `docs/architecture/CI_CD_PIPELINE.md` (job `test` = suíte completa; Docker+Postgres real ficam `skipped` em CI comum, por design).

## Achados

### T1 - 512 testes de API pulam por padrão; incluem quase toda a Logística, Almox e remanejamento por linhas (corrigir antes: rodar a suíte de integração antes do deploy)
Evidência: `957 passed, 512 skipped` no comando acima. Motivo dos pulos: 356+92+54+5+3+1+1 = guard `APP_ENV=test`/`POSTGRES_TEST_DATABASE_URL`. Maiores: `test_proposals_integration` 84, `test_chat_integration` 53, `test_logistics` 39, `test_proposal_undo` 23, `test_inspection` 19, `test_sync_integration` 18, `test_expedition_fiscal_read_path` 17, `test_warehouse_stock_deduction` 16, `test_inspection_entry` 16.
Mitigação feita: rodei Logística, Inspeção, Almoxarifado, remanejamento por linhas e galvanizado em Postgres descartável: 150 passed, 0 failed (acima). **Não rodei** os outros ~360 pulados (propostas, chat, desfazer, sync, fiscal, canais, atualização, auditoria, auth). A Fase 16 registra uma rodada completa antes (`1462 passed, 6 failed, 2 skipped, 4574 s`, falhas conhecidas), mas nada que prove que ela foi refeita depois dos commits da Fase 17. Recomendo uma rodada completa de integração (~1h15) em banco descartável antes de publicar.

### T2 - Dois arquivos de teste Docker travam a suíte quando o Docker local está ativo (corrigir antes / pode depois, é ambiente)
Evidência: primeira rodada, `python -m pytest api/tests ... ` com Docker ligado, parou com `+++ Timeout +++` em `api/tests/test_docker_release_integration.py:42 setUpClass -> build_image -> subprocess.run(docker build)`; `EXIT=1`. O guard desse arquivo é só `docker_available()` (não exige `APP_ENV`/banco), então ele **constrói uma imagem de verdade** em qualquer máquina com Docker, e o timeout de thread mata o processo inteiro de pytest (derrubou as demais ~25% da suíte). Deixa imagens `controle-producao-api-test:*` para trás (removi as 2 da minha rodada; há outras 13 de outras execuções, não mexi). Classificação: teste/ambiente, não bug de produto. Para rodar: excluir com `--ignore` ou rodar à parte com `--timeout=600`. O Postgres dev (`controle_producao_postgres_dev`) está parado, então os testes de runtime desses arquivos pulariam de qualquer forma.

### T3 - Teste de paginação do PDF pulado por falta de fonte (pode depois)
Evidência: `SKIPPED tests\test_logistics_reports.py:250: sem fonte instalada o Qt grava caixas em vez de texto` (`test_pdf_sweep_never_splits_totals_or_leaves_footer_only_page`). É o teste que confere "não parte total" e "sem página só com rodapé". Os demais (`test_pagination_sweep_geometry`, `test_footer_has_issuer_date_and_page_x_of_y`, `test_locked_pdf_raises_and_keeps_old_file`) passaram. A própria FASE17 admite que o texto do PDF não foi conferido com dados reais. Fazer uma conferência visual do PDF de LOG/carga grande no ambiente de dev antes de usar.

### T4 - Desktop: 22 outros pulos, todos por arquivo/ambiente ausente (pode depois)
`test_desktop_api_integration.py` (exige `DESKTOP_API_INTEGRATION=1`), 6 + 13 + 1 de importação de PDF (sem `NOMUS_PDF_TEST_FILE` / PDFs reais locais). Sem impacto nas funções novas.

### T5 - `REMANAGEMENT_BY_ROWS_ENABLED`: estado padrão desligado não tem teste próprio (pode depois)
A chave é o módulo `remanagement.REMANAGEMENT_BY_ROWS_ENABLED = False` OU `Settings.remanagement_by_rows_enabled` (env, default False) em `remanagement_rows.py:92`. `test_remanagement_rows.py` liga a chave por `patch(SWITCH, True)` e confere o motor antigo com a chave desligada num cenário (linha ~399), mas nenhum teste afirma que o default de `Settings` é False nem que a variável de ambiente liga/desliga. Risco: alguém ligar a variável em produção sem querer. Deploy: conferir que a variável não está setada no servidor.

### T6 - README com baseline de testes defasada (pode depois)
`README.md` diz `330 passed, 35 skipped`. Hoje: Desktop 2475 + API 957 passed. Só documentação.

## Cobertura das funcionalidades novas (grep nos testes)

Legenda: (I) = só roda com Postgres de teste; sem (I) roda na suíte padrão.

| Funcionalidade | Testes existentes | Lacuna |
|---|---|---|
| Logística Fase 17: API (pedido em inspeção, confirmação 409, andamento com data, entrega congelada, filtros estado/carga, cargas, desfazer) | `api/tests/test_logistics.py` (41 testes, 39 (I)), `test_logistics_state_resolver.py`; Desktop: `tests/test_logistics_desktop.py` (80), `test_logistics_list.py` (9), `test_logistics_progress.py` (12), `test_inspection_logistics_confirm.py`, `test_process_detail_inspection_logistics_tab.py` | Rodado e verde em Postgres descartável (63 passed). Pelo plano da FASE16, `LOGISTICS_LOG_EMPTY` sem teste próprio no Desktop (não reconferido). Sem teste fim a fim Desktop real contra API. |
| Relatório LOG/carga com peso | `tests/test_log_weight.py` (9), `tests/test_logistics_reports.py` (40: total "—", não consultado, aviso de peso faltando, "gerar assim mesmo", informar peso, erro de API), `test_row_actions_desktop.py` (27) | Peso por proposta roda na thread de UI (limitação declarada, sem teste de carga grande). "Informar peso" só em Produção, 409 nas outras áreas: pendência de decisão. |
| PDF: paginação e arquivo bloqueado | `test_logistics_reports.py`: `test_pagination_sweep_geometry`, `test_footer_has_issuer_date_and_page_x_of_y`, `test_locked_pdf_raises_and_keeps_old_file` (só Windows, passou); `test_pdf_sweep_never_splits_totals_or_leaves_footer_only_page` **pulado (T3)** | Texto real do PDF não verificado sem fonte; sem conferência com dados reais. |
| XLSX da lista de LOGs | `test_logistics_list.py:128`, `test_logistics_reports.py:70-91` (lê o `.xlsx` com `openpyxl`) | Nenhuma relevante. |
| Fase 16 datas (inspeção/LOG, avisos de calendário, fuso) | `tests/test_date_warnings.py` (4), `test_local_today.py` (1), `test_inspection_desktop.py` (55), `api/tests/test_calendar_rules.py` (5), `test_inspection.py` (22, 19 (I)), `test_inspection_entry.py` (I) | Rodado e verde em Postgres descartável. Cobertura de fuso "só em teste" (admitido na FASE16). |
| Almoxarifado por número (abas Propostas/Itens, baixa de estoque, contador) | Desktop: `test_warehouse_area_page.py` (abas, selo/contador, tabela de itens), `test_warehouse_enter_dialog.py` (17), `test_api_warehouse_client.py` (21); API (I): `test_warehouse_enter` (9), `test_warehouse_items` (6), `test_warehouse_list` (8), `test_warehouse_stock_deduction` (16), `test_migration_warehouse_stock_deduction` (1) | Rodado e verde em Postgres descartável. Memória do projeto diz "falta validar na dev": nenhum teste cobre dado real. |
| Remanejamento por linhas P1/P2 (chave) | `api/tests/test_remanagement_rows.py` (12, todos (I), ligados por `patch`), `test_remanagement_badges.py`, `test_remanagement_compensation.py`, `test_stage_ledger.py`, `test_stage_swap.py`; Desktop: `test_remanagement_wizard.py` (102), `test_remanagement_badges.py` (23) | Rodado e verde (12 + vizinhos). Default da chave e leitura da env sem teste (T5). Motor novo só na dev. |
| Edição de teste do Desktop | `tests/test_edition.py` (17) | Cobertura boa. Instalador de teste (`build_teste/`) não testado fora do build. |
| Integração Almox+ (webhook assinado, conciliação) | `api/tests/test_almox_integration.py` (28; HMAC válido/adulterado, timestamp velho, retry com mesmo `event_id`, desistência sem exceção, dispatcher desligado sem URL/segredo, conciliação assinada/sem segredo) passam sem banco | Nenhuma lacuna evidente. Não testado contra o Almox+ real (só fakes). |
| Padrão de janelas (casca 24 px, mola, chave de emergência) | `tests/test_dialog_shell.py` (8), `test_window_shell.py` (18, inclui `test_disabled_key_keeps_the_legacy_frame` e movimento reduzido), `test_message_boxes.py` (11), `test_large_dialog_geometry.py`, `test_settings_motion_and_filters.py` | Pintura só offscreen: aparência real, 3D leve e mola não conferidos com dados reais (pendência já registrada). |

## Classificação de falhas
Nenhuma falha. Único travamento (T2) = ambiente/teste (Docker real dentro da suíte), não produto.

## Não verificado
- ~360 testes de integração restantes (propostas, chat, desfazer, sync, fiscal, canais, atualização, auditoria, auth, migrações fresh/upgrade).
- Testes Docker/rollback (T2).
- Execução repetida (flaky): não aplicável, sem falhas.
- Cobertura de linhas (coverage.py) não medida.
