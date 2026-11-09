# Fase 17 — Melhorias na aba Logística

Plano: `docs/plano-logistica-melhorias.md`. Spec: `docs/spec-logistica-melhorias.md` (decisões L1 a L10, de 2026-11-09). Branch `logistica-melhorias`, a partir de `inspecao-datas`. Desenvolvido e testado só na API de dev (8001); **nada foi aplicado na API oficial (8000)**. Nada foi enviado com push.

## Objetivo

- L1 e L2: pedido ainda em inspeção entra no LOG, em qualquer etapa, após confirmação. A lista mostra a etapa da inspeção e o LOG mostra quantos pedidos não têm DOC BIM.
- L3: janela "Registrar andamento" do LOG, no padrão da Inspeção, com data "Aconteceu em" (Hoje/Ontem/outra) e observação.
- L5 e L6: relatório PDF do LOG (uma página, sem links) e relatório PDF da Carga, com logo da Industel.
- L7: painel "Dados do LOG" sem vazio e com caminhos curtos.
- L8: contador de dias para na entrega; etapa "Entregue" na lista.
- L9: filtros por etapa, estado e carga na lista, e exportação XLSX que respeita os filtros.
- L10: pedido já no LOG continua no LOG quando a inspeção muda ou o PD muda; só cancelar tira do LOG.
- L4 fica fora do escopo (decisão do Henrique).

## Implementação por tarefa

- **T1 (API, pedido em inspeção):** `service.py` deixa de recusar pedido sem inspeção finalizada. Pedido sem DOC BIM devolve 409 `LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED` com a lista de propostas (`proposal_number`, `pd_code`, `inspection_stage`); reenvio com `confirm_inspection: true` passa. `EligibleProposalOut` ganha `inspection_stage` e `inspection_finished`. `LogItemOut` ganha os mesmos campos da inspeção; `LogOut` ganha `without_doc_count`. Pedido sem PD ou sem inspeção cadastrada continua fora da lista (decisão do Claude). `proposal_links.py`: mudança de PD ou reprovação só registra evento no histórico do LOG; cancelamento continua tirando a proposta do LOG.
- **T2 (API, andamento com data real):** migration `20261109_0047_logistics_stage_dates_and_notes.py` (ADDITIVE) com `logistics_logs.stage_occurred_on`, `logistics_events.occurred_on` e `logistics_events.note`. `DocsPayload`, `ApprovePayload` (corpo opcional em `POST /logs/{id}/approve`) e `LogDeliveryPayload` aceitam data e observação. Avisos de data pelo `calendar_rules`, com `confirm_dates`; data inexistente é 422. `EventOut` ganha `occurred_on` e `note`; `LogOut` ganha `stage_since_date`.
- **T3 (API, entrega):** etapa derivada, sem migration. `LogOut` ganha `display_stage` (`entregue` quando `delivered_on` existe). Dias na etapa de LOG entregue contam de `stage_since_date` até `delivered_on` e param ali (dias úteis por `business_days_between`). Filtro `stage=entregue` usa `delivered_on`.
- **T4 (API, filtros):** `GET /logistics/logs` ganha `state` (sem diferença de caixa) e `load_id`. Nova rota `GET /logistics/log-states` com os estados distintos.
- **T5 (Desktop, cliente e serviço):** `logistics_client.py` e `logistics_service.py` passam `occurred_on`, `note`, `confirm_dates`, `confirm_inspection`, `state` e `load_id`. O 409 de confirmação chega à tela.
- **T6 (Desktop, andamento):** `app/ui/logistics_progress.py` (novo) com `RecordLogProgressDialog`, irmão pequeno de `RecordProgressDialog` da Inspeção, com os resultados do LOG: `reservada` → Documentação enviada (NF, XML, BIM); `docs` → Aprovada para entrega; `aprovada` → Entregue no CD (link do comprovante). `LogDetailDialog` ganha um único botão primário "Registrar andamento". Saem os botões antigos de etapa; "Editar datas" continua secundário.
- **T7 (Desktop, pedido em inspeção):** `logistics_dialogs.py` mostra a etiqueta da inspeção em cada pedido. 409 de confirmação abre pergunta com a lista e o botão "Incluir mesmo assim". Aba Propostas ganha coluna "Inspeção"; aviso "N pedidos ainda sem DOC BIM" sem bloquear.
- **T8 (Desktop, painel "Dados do LOG"):** causa do vazio corrigida no layout do painel (alinhamento no topo, `AlignTop`). Campos NF, XML, BIM e comprovante mostram só o nome do arquivo, com botão "Abrir" e caminho completo na dica. Botão "Gerar relatório" ligado ao gancho da T10.
- **T9 (Desktop, lista):** `logistics_page.py` mostra `display_stage` e dias congelados; "Entregue" tem selo próprio por token. Filtros de Etapa, Estado e Carga ao lado da busca, combinados com ela.
- **T10 (Desktop, relatórios e XLSX):**
  - `app/services/xlsx_export.py`: exportação XLSX com `openpyxl==3.1.5` fixado em `requirements.txt`. Cabeçalho em negrito, larguras, filtro ligado, texto começando com `=` gravado como texto.
  - `app/services/log_report.py`: `build_log_report` e `build_load_report`, HTML impresso com `QPrinter` em PDF (mesmo caminho de `process_page.py`). Sem links. Tabela que passa de uma página quebra com cabeçalho repetido.
  - `app/ui/report_actions.py`: ações de "Salvar como" e abertura do arquivo gerado (`QDesktopServices.openUrl`), com aviso se falhar.
  - `ControleProducao.spec` inclui `openpyxl`.

## Contrato novo da API

- `POST` de criação e inclusão de LOG: `confirm_inspection`; 409 `LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED` com `details` por proposta.
- Lista de propostas elegíveis: `inspection_stage`, `inspection_finished`.
- Item do LOG: `inspection_stage`, `inspection_finished`. LOG: `without_doc_count`, `display_stage`, `stage_since_date`.
- Andamento e entrega: `occurred_on`, `note`, `confirm_dates`. `POST /logs/{id}/approve` aceita corpo opcional.
- Evento do histórico: `occurred_on`, `note`.
- Lista de LOGs: filtros `state` e `load_id`. Nova rota `GET /logistics/log-states`.
- Revisão esperada do banco: `EXPECTED_DATABASE_REVISION = "20261109_0047"` (`api/app/core/config.py`).
- Migration `20261109_0047` com entrada em `api/alembic/migration_risk_registry.json` (ADDITIVE) e checksum atualizado em `migration_checksums.json`.

## Decisões do Claude (ajustáveis)

- Pedido sem PD ou sem inspeção cadastrada continua fora da lista de elegíveis.
- Dias na etapa de LOG entregue são congelados em `delivered_on`, sem migration; LOG sem `delivered_on` continua contando.
- XLSX com `openpyxl` fixado em 3.1.5; PDF com `QPrinter` (sem dependência nova para PDF).
- Relatório é "uma página" no caso comum, mas quebra em páginas seguintes e não corta dados.

## Commits

Ordem cronológica, da mais antiga para a mais nova:

- `ed6230a` Migration 0047: data real e observação nos andamentos do LOG
- `54e7544` API da Logistica: pedido em inspecao entra no LOG com confirmacao e andamento com data real
- `41267d6` API da Logistica: contador para na entrega, etapa Entregue e filtros por estado e carga
- `3572718` API da Logistica: auditoria guarda data e observacao, evento de PD legivel e teste da Carga com pedido sem DOC
- `5bef03f` Desktop: cliente e servico da Logistica com data do andamento, confirmacao de inspecao e filtros
- `2b39dfa` Relatorios PDF do LOG e da Carga e exportacao XLSX da lista de Logistica
- `c613924` Pagina de Logistica: filtros de etapa, estado e carga, etapa Entregue e botao Exportar
- `593b661` Dialogos de Logistica: janela Registrar andamento, pedido em inspecao no LOG e painel Dados do LOG
- `5d4e342` Pagina de Logistica: botao Exportar fica desabilitado durante a geracao
- `cebd079` Dialogos de Logistica: Corrigir entrega, etapa Entregue no selo e fim do aviso morto de troca de PD

Os arquivos `.claude/agents/*` modificados, `output/`, `nao_existe.json` e o atalho `.lnk` ficaram fora dos commits.

## Auditorias

- **B1 (API, T1 a T4): PASSA sem ALTA.** Achado MÉDIA: foco 2 (proposta cancelada dentro do LOG) sem teste. Teste adicionado. BAIXAS corrigidas.
- **B2 (Desktop diálogos, T5 a T8): CORRIGIR por ALTA.** Achado ALTA: perda do caminho de "Corrigir entrega" no diálogo. Corrigido: botão "Corrigir entrega" restaurado, selo com `display_stage` (etapa Entregue), e ramo morto "sai do LOG" na troca de PD removido (ele nunca rodava, pois L10 deixou de tirar a proposta).
- **B3 (Desktop lista e relatórios, T9 e T10): PASSA com 5 BAIXAS.** Corrigida: botão Exportar fica desabilitado durante a geração. Aceitas, sem correção nesta fase:
  - erro silencioso ao carregar os estados do filtro;
  - paginação por offset, sem snapshot (lista muda entre páginas se houver gravação concorrente);
  - `ValueError` em data inválida vira aviso, em vez de bloquear;
  - título do LOG pode ficar órfão no fim da página do PDF da Carga.

## Validação

API de dev, banco de teste local (Postgres em `127.0.0.1:55440`, sem credenciais registradas aqui):

```
APP_ENV=test POSTGRES_TEST_DATABASE_URL=<banco de teste em 127.0.0.1:55440> python -m pytest api/tests/test_logistics.py -q -p no:cacheprovider --timeout=25 --timeout-method=thread
```

Resultado: **41 passed, 0 skipped**, sem skip contra o banco de teste.

Linha de base antes da fase:

- API sem banco: 23 passed, 32 skipped (`-k logistics`).
- API com banco, `test_logistics.py` + `test_inspection.py`: 53 passed.
- Desktop `-k logistics`: 72 passed.

Desktop, depois da fase (`pytest -k logistics`, com timeout do `pytest.ini`): **134 passed**.

## Suíte completa

Comando: `APP_ENV=test POSTGRES_TEST_DATABASE_URL=<banco de teste em 127.0.0.1:55440> python -m pytest tests api/tests -q -rs -p no:cacheprovider --timeout=25 --timeout-method=thread`.

Resultado real (2026-11-09): **8 failed, 3879 passed, 23 skipped** em 1h23min44s. Nenhuma das 8 falhas e de Logistica:

- 2 em `test_replica_views_parity.py` (campo `requires_inspection` ausente na replica): preexistentes, tambem falham no commit `ef88d2f` (antes da branch).
- 2 (`test_postgresql_integration::test_readiness_with_available_database` e `FreshDatabaseMigrationTests::test_app_initializes_and_serves_against_fresh_database`): 503 por falta de `SECRET_KEY` forte (32+ caracteres) no ambiente de teste. Com a chave, `test_postgresql_integration.py`, `test_migrations_fresh_and_upgrade.py` e `test_update_audit_router.py` rodados juntos deram 27 passed e 1 failed (o failed e o item abaixo).
- 3 em testes de Docker real (`RollbackRealDockerTests` x2, `ReleaseImageRuntimeSmokeTests`): "container nao ficou healthy", ambiente (imagem/Docker local), nao testados fora da suite.
- 1 em `test_update_audit_router.py::test_events_endpoint_triggers_its_own_drain_caller_never_has_to_drain_manually` (0 != 1): falha tambem isolada; o modulo `update_audit` e o teste nao foram tocados nesta branch (sem diff contra `ef88d2f`), mas NAO foi confirmado no commit base. Pendencia.

Logistica: `api/tests/test_logistics.py` 41 passed sem skip; Desktop `-k logistics` 134 passed (linha de base 72).

## Pendência encontrada

Não resolvidas nesta fase:

- Conferência visual do Henrique na edição de teste (`scripts/build_test_installer.py`, contra a dev 8001). Painel "Dados do LOG", janela "Registrar andamento", relatórios e filtros não foram vistos com dados reais.
- Build PyInstaller com `openpyxl` não rodado. Falta conferir que a biblioteca entra no executável.
- Texto do PDF não verificável em teste offscreen (fonte vazia no ambiente de teste). Teste confere só que o arquivo existe, tem tamanho maior que zero e que o XLSX é relido com as linhas esperadas.
- `LogDeliveryPayload` não tem `confirm_dates`: a entrega não avisa data fora do dia útil nem data futura. Só o andamento avisa.
- Decisão do Henrique: push e merge da branch `logistica-melhorias`.

## Conclusão

Logística alinhada à Inspeção: pedido em inspeção entra no LOG com confirmação, andamento com data escolhida, contador para na entrega, painel e filtros corrigidos, XLSX e PDFs do LOG e da Carga. Validado só na API de dev e em testes, com a auditoria B2 corrigida. Falta a conferência visual e o build com `openpyxl` antes de qualquer uso. Nada foi para a API oficial.
