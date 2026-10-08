# Fluxo oficial de Expedicao na API

## Escopo

A Etapa 12 migrou Expedicao, separacao, entrega parcial/total e remanejamento para API/PostgreSQL.

O desktop continua usando a interface existente, mas no modo oficial a regra de negocio fica na API:

```text
Desktop -> API -> PostgreSQL
```

## Estruturas oficiais

Migration criada:

```text
20260721_0007_create_expedition_items.py
```

Tabelas:

- `expedition_items`: saldo disponivel, separado, entregue e remanejado por item.
- `expedition_events`: auditoria operacional da Expedicao por proposta/item.

O item da proposta continua sendo a origem principal de fluxo. A proposta guarda apenas estado resumido.

## Origem da disponibilidade

Um item entra na Expedicao por dois caminhos:

- `PRODUCAO`: item produzido, ativo, fluxo definido, sem galvanizacao e ainda nao entregue.
- `GALVANIZACAO`: quantidade retornada oficialmente em carga nao cancelada.

A API sincroniza a fila de Expedicao a partir dessas fontes ao listar, detalhar ou executar comandos.

## Estados usados

```text
EM_SEPARACAO
AGUARDANDO_SEPARACAO_PARCIAL
SEPARACAO_INICIADA
SEPARADO
ENTREGUE_PARCIAL
ENTREGUE
REMANEJADO
```

## Comandos oficiais

```text
GET  /api/v1/shipping/proposals
GET  /api/v1/shipping/items
GET  /api/v1/shipping/proposals/{proposal_id}
POST /api/v1/shipping/proposals/{proposal_id}/start-separation
POST /api/v1/shipping/proposals/{proposal_id}/separate-items
POST /api/v1/shipping/proposals/{proposal_id}/deliver-items
POST /api/v1/shipping/proposals/{proposal_id}/remanage-items
POST /api/v1/shipping/proposals/{proposal_id}/deliver-by-remanagement
```

Todos os comandos exigem permissao, versao atual e registram evento.

### Lista de itens (`GET /shipping/items`)

Leitura (permissao `EXPEDITION_VIEW`) que devolve **uma linha por item** da Expedicao, ja com a proposta dele (numero, versao, cliente, obra/site, lote). E o que alimenta a aba "Itens em expedicao". Filtro, ordenacao e paginacao rodam no SQL.

| Parametro | Padrao | Efeito |
|---|---|---|
| `search` | - | numero, cliente, obra/site ou lote da proposta, numero da NF, ou codigo/descricao do item |
| `status` | - | situacao do item (`EM_SEPARACAO`, `SEPARACAO_INICIADA`, `SEPARADO`, `ENTREGUE`) |
| `pending_only` | `true` | so itens com saldo a entregar (mesmo criterio de `_active_expedition_items`); com `false` entram tambem os ja entregues, mas so das propostas que continuam na Expedicao |
| `limit` / `offset` | 50 / 0 | `limit` ate 500 |

Ordem: situacao do item (aguardando separacao, separacao iniciada, separado), numero da proposta, numero do item. Cada linha traz disponivel, separado, entregue, remanejado e saldo pendente (`pending_quantity`), peso, origem e situacao.

## Regras principais

- Nao entrega item sem saldo separado.
- Nao separa quantidade maior que o saldo disponivel.
- Nao entrega quantidade maior que o saldo separado.
- Nao remaneja quantidade maior que o saldo pendente.
- Entrega parcial mantem a proposta aberta na Expedicao.
- Entrega total so encerra a proposta quando todos os itens ativos estiverem entregues e nao houver pendencia produtiva.
- Remanejamento devolve a proposta de origem para `PRODUCAO / ITEM_PENDENTE_FABRICACAO`.
- Entrega antecipada por remanejamento encerra a proposta destino e devolve a fonte para Producao no mesmo comando transacional.

## Relacao com Fiscal

A partir da Etapa 13, o Fiscal possui estado independente em API/PostgreSQL.

Uma proposta entregue sem nota pode aparecer como `PENDENCIA_FISCAL_CRITICA` no Fiscal, mas isso nao altera automaticamente o estado de Expedicao. Da mesma forma, uma nota fiscal emitida nao encerra a Expedicao por si so.

O Fiscal usa a situacao operacional da Expedicao apenas para classificar disponibilidade, alerta e criticidade.

## Desktop

Quando `postgresql_official_proposals_enabled` esta ativo:

- a aba Expedicao tem duas abas, "Propostas" (lista propostas pela API) e "Itens em expedicao" (`GET /shipping/items`, so leitura: situacao, disponivel, entregue, saldo e abertura dos detalhes da proposta; separar, entregar e remanejar continuam por proposta);
- detalhes de Expedicao vem da API;
- separacao e entrega chamam endpoints REST;
- `pending_delivery` vem de `expedition_items`;
- remanejamento antecipado usa comando oficial da API.

Nao ha fallback SQLite no fluxo oficial da Expedicao.

## Fora do escopo

Nao foram migrados nesta etapa:

- Fiscal;
- Almoxarifado;
- relatorios;
- dashboards;
- chat;
- notificacoes;
- subprocessos P1/P2;
- dados antigos SQLite;
- sincronizacao bidirecional;
- valores financeiros.
