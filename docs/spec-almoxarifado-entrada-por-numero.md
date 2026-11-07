# Especificação: Almoxarifado com entrada por número, abas e baixa de estoque

Status: **aguardando aprovação do Henrique** (nada foi construído).
Data: 2026-11-07. Branch de trabalho sugerida: nova, a partir de `integracao-almox` (a branch atual tem trabalho da Fase 14 ainda sem commit; não misturar).

## Intenção e porquê

Hoje a aba Almoxarifado lista **toda** proposta ativa. O Henrique quer o Almoxarifado sob controle dele: a proposta só entra quando ele digita o número (muitas vezes a proposta chega depois da liberação), entregues saem da lista, e ele controla se já deu baixa do material no estoque.

## Objetivos

1. Duas abas no topo do Almoxarifado: **Propostas** e **Itens** (mesmo desenho de Expedição/Galvanização: `ExpeditionAreaPage`).
2. **Entrada por número**: o Henrique digita um ou mais números de proposta; elas entram já com status **EM_SEPARACAO**.
3. Proposta **não entra mais sozinha** no Almoxarifado.
4. Proposta **entregue** (`ALMOXARIFADO_ENTREGUE`) **sai da aba**, mas só depois que a baixa no estoque estiver confirmada.
5. Ação **Confirmar baixa no estoque** (e desfazer), individual e em lote.
6. **Contador discreto** no cabeçalho com as propostas que ainda faltam dar baixa.

## Não-objetivos

- Controle de separação ou baixa **por item** (a aba Itens é só consulta).
- Qualquer mudança no Almox+ (integração por webhook; ver `docs/architecture/ALMOX_INTEGRATION.md`). Esta spec trata só da aba do Controle de Produção. Conferir no plano que o gancho do Almox+ não depende de `warehouse_status`.
- Mexer na API oficial (8000). Tudo na API de dev (8001); produção só com autorização explícita.

## Anti-objetivo

Não apagar nenhum dado. "Sumir da aba" é filtro de listagem, nunca exclusão.

## Regras de negócio

**Quem aparece na aba Propostas** (`GET /warehouse/proposals`): proposta ativa, não cancelada, sem mãe, com `warehouse_status` em `EM_SEPARACAO`, `SEPARADO`, `ALMOXARIFADO_ENTREGUE_PARCIAL`, `SEM_PARAFUSOS`, ou `ALMOXARIFADO_ENTREGUE` **com baixa pendente**. Ficam fora: `NULL` (Não definido), `AGUARDANDO_CONFIRMACAO` e `ALMOXARIFADO_ENTREGUE` com baixa confirmada.

**Entrada por número:** aceita lista (vírgula, espaço ou quebra de linha), sem repetidos. Para cada número, resultado individual:
- `ENTROU`: estava `NULL` ou `AGUARDANDO_CONFIRMACAO`; vira `EM_SEPARACAO`.
- `JA_NA_ABA`: já em separação/separado/parcial/sem parafusos.
- `JA_ENTREGUE`: já entregue.
- `NAO_ENCONTRADA`, `CANCELADA`, `PROPOSTA_PARCIAL` (número de proposta filha: orientar a usar a mãe).
Operação por número independente: um erro não derruba os outros. Idempotente (repetir não duplica nem regride status).

**Baixa no estoque:**
- Só pode ser confirmada com `warehouse_status` em `SEPARADO`, `ALMOXARIFADO_ENTREGUE_PARCIAL` ou `ALMOXARIFADO_ENTREGUE`.
- Guarda quando e quem (campos novos na proposta). Pode ser desfeita (volta a pendente).
- `SEM_PARAFUSOS` não tem baixa (não há material separado): nunca conta no contador.
- **Contador** = propostas na aba com status `SEPARADO`, `ALMOXARIFADO_ENTREGUE_PARCIAL` ou `ALMOXARIFADO_ENTREGUE` **e baixa pendente**. Calculado na API (não somado só nas linhas da página).

**Transições** (`WAREHOUSE_NEXT_STATUSES`): mantém as atuais e acrescenta `EM_SEPARACAO -> SEM_PARAFUSOS`, porque a entrada agora vai direto a EM_SEPARACAO e senão "Sem parafusos" ficaria inalcançável.

**Aba Itens:** consulta dos itens ativos das propostas que estão na aba Propostas, com busca e "Detalhes da proposta", seguindo `ExpeditionItemsPage`. Sem ações.

## Dados

- Migration Alembic **aditiva**: em `proposals`, `warehouse_stock_deducted_at` (timestamp, nulo) e `warehouse_stock_deducted_by_user_id` (nulo). Entrada em `migration_risk_registry.json` (skill `migration-check`).
- **Backfill (migração de dados)**: propostas hoje em `ALMOXARIFADO_ENTREGUE` recebem baixa preenchida (sem isso todo o histórico reapareceria na aba e inflaria o contador). Classificar como `DATA_MIGRATION` no registro. Ver pergunta P1.
- Eventos de histórico novos: `WAREHOUSE_STOCK_DEDUCTED` e `WAREHOUSE_STOCK_DEDUCTION_REVERTED`; a entrada por número grava `WAREHOUSE_STATUS_CHANGED` com `metadata.source = "entrada_por_numero"`. Incluir os rótulos nos dois mapas de eventos de `service.py` e na Fase 14 (desfazer): conferir se a baixa entra como ação desfazível ou se é desfeita pelo próprio botão.

## Interfaces (API)

| Rota | Função |
|---|---|
| `POST /warehouse/proposals/enter` | corpo `{numbers: [str]}` (máx. 200); devolve lista `{number, result, proposal_id?}` |
| `POST /warehouse/proposals/{id}/stock-deduction` | corpo `{version, deducted: bool}`; confirma ou desfaz a baixa |
| `GET /warehouse/proposals` | passa a aplicar o filtro de visibilidade acima e a devolver `stock_deducted: bool` e `stock_deducted_at` por linha |
| `GET /warehouse/summary` (ou campo `pending_stock_deduction` na listagem) | total do contador |

Permissão: a mesma do status de Almoxarifado (`proposals.change_status` na área `warehouse`). Lote reutiliza a seleção por caixinha já existente (`_CHECKBOX_BATCH_AREAS` inclui ALMOXARIFADO) e o padrão `batch_action_center`.

## Interfaces (Desktop)

- `WarehouseAreaPage` (novo, em `app/ui/`), cópia do padrão de `ExpeditionAreaPage`: abas "Propostas" (`ProcessPage` de ALMOXARIFADO) e "Itens". Trocar o registro em `main_window.py` (ao lado de `ExpeditionAreaPage`).
- Botão **Adicionar propostas** na aba Propostas abre diálogo no padrão `qt-industrial-ui` (tela sobreposta, um botão primário, cor só por token) com campo multilinha e, depois de enviar, o resultado por número.
- Ação **Confirmar baixa no estoque / Desfazer baixa** no Action Center (verificar com o agente `action-center-reviewer`) e no lote.
- Contador discreto no cabeçalho (usar `format_count_badge`; número pintado em `paintEvent`, não via `setText`).
- Coluna ou selo "Baixa" na tabela (pendente / confirmada), sem trocar a identidade visual.

## Critérios de aceite

1. Liberar uma proposta não a coloca no Almoxarifado.
2. Digitar `A, B, C` (um número inexistente, um já na aba) mostra resultado correto para cada um e coloca as válidas em Em separação.
3. As propostas `NULL`/`AGUARDANDO_CONFIRMACAO` não aparecem; nenhuma linha do banco é apagada.
4. Entregue sem baixa continua na aba; ao confirmar a baixa, sai.
5. Contador bate com a quantidade de pendentes, também com mais de uma página de resultados, e some/zera quando não há pendência.
6. Baixa desfeita volta a contar.
7. Aba Itens lista só itens das propostas que estão na aba.
8. Suíte oficial `python -m pytest tests api/tests -q` passa; `scripts/check_migration_safety.py` passa; testes novos na API (entrada, visibilidade, baixa, contador) e no Desktop (diálogo, abas, contador).

## Registro de decisões

| ID | Tema | Decisão | Motivo | Quem | Data |
|---|---|---|---|---|---|
| D1 | Abas | Propostas e Itens, como Expedição | consistência | Henrique | 2026-11-07 |
| D2 | Entrada | Só por número digitado, status inicial EM_SEPARACAO | proposta às vezes demora a chegar | Henrique | 2026-11-07 |
| D3 | Dados atuais | Não definido/Aguardando somem da aba, sem apagar | aba limpa | Henrique | 2026-11-07 |
| D4 | Entregue | Sai da aba só com baixa confirmada | não perder pendência | Henrique | 2026-11-07 |
| D5 | Baixa | Ação de confirmar baixa com contador discreto no cabeçalho | controle | Henrique | 2026-11-07 |
| D6 | Aba Itens | Só consulta, itens das propostas na aba | simples de manter | Henrique | 2026-11-07 |
| D7 | Baixa disponível | A partir de Separado | "depois de separar baixo" | Henrique (palpite aceito) | 2026-11-07 |
| D8 | Formato da entrada | Lista com vírgula/espaço/linha e relatório por número | palpite aceito | Henrique | 2026-11-07 |
| D9 | Desfazer e lote | Baixa desfazível; individual e em lote | palpite aceito | Henrique | 2026-11-07 |
| D10 | Ambiente | Só API de dev (8001) | regra permanente | Henrique | 2026-11-07 |
| D11 | Transição nova | `EM_SEPARACAO -> SEM_PARAFUSOS` | mantém "Sem parafusos" alcançável | Claude | 2026-11-07 |
| D12 | Backfill | Entregues antigas recebem baixa preenchida | evitar reaparecer o histórico | Henrique (confirmou) | 2026-11-07 |
| D13 | Contador | Calculado na API, exclui Sem parafusos | correto com paginação | Claude | 2026-11-07 |
| D14 | Desfazer vs baixa | Desfazer a última transição de status (Fase 14) de uma proposta com baixa confirmada **zera a baixa** | manter status e baixa coerentes | Henrique | 2026-11-07 |

## Premissas e riscos

- `warehouse_status` é lido fora da aba (relatório diário, dashboard, relatórios operacionais, Parciais, Fase 14 desfazer). O plano deve listar todos os consumidores antes de mudar o filtro; mudar só `list_warehouse_proposals`.
- Propostas `SEPARADO` antigas, esquecidas, entrarão no contador logo de início (pendência real ou lixo antigo).
- Depende de nada externo; Almox+ não é tocado.
- Trabalho em andamento na branch atual (Fase 14, 13 arquivos modificados) toca `provider.py`, `undo_dialog.py` e `undo.py`: risco de conflito. Commitar ou isolar antes.

## Perguntas em aberto (dono: Henrique)

- ~~**P1**~~ Fechada em 2026-11-07 (D12, Henrique): propostas antigas `ENTREGUE` são marcadas como "baixa feita" no backfill.
- ~~**P2**~~ Fechada em 2026-11-07 (Henrique): propostas antigas em `SEPARADO` sem baixa entram no contador desde o primeiro dia.
- ~~**P3**~~ Fechada em 2026-11-07 (Henrique): `SEM_PARAFUSOS` continua na aba como hoje.

Sem perguntas em aberto.

## Dependências e ordem de implementação

1. Migration + registro de risco + backfill (P1).
2. API: filtro de visibilidade, entrada por número, baixa, contador, eventos. Testes.
3. Cliente HTTP, `api_proposal_storage` e `backend_adapter` no Desktop.
4. `WarehouseAreaPage` + aba Itens.
5. Diálogo de entrada, ação de baixa (individual e lote), contador, coluna Baixa.
6. Doc de fechamento `docs/architecture/FASEn_*.md` (skill `fase-report`).
