# Modelo de leitura da API: propostas e itens

## Decisao da etapa

Esta etapa cria a primeira replica de negocio da API, limitada a consulta de propostas e itens.

O SQLite continua sendo a fonte oficial de gravacao. O PostgreSQL recebe uma copia administrativa somente leitura, usada pela API e pela tela experimental do desktop.

Fluxo permitido:

```text
SQLite oficial -> sincronizacao manual -> PostgreSQL leitura -> API REST -> desktop experimental
```

Fluxos proibidos nesta etapa:

```text
PostgreSQL -> SQLite
API -> criacao/edicao/exclusao de propostas
API -> alteracao de status
API -> alteracao de itens
```

## Escopo

Incluido:

- propostas da tabela legada `processos`;
- itens da tabela legada `proposta_itens`;
- resumo de area e status atual como snapshot textual;
- flags de parcial, cancelada e concluida;
- metadados de sincronizacao;
- preservacao dos IDs SQLite em `legacy_id`.

Fora do escopo:

- valores financeiros;
- regras produtivas;
- movimentacao entre areas;
- criacao de cargas;
- remanejamento;
- sincronizacao automatica;
- telas oficiais do desktop.

## Mapeamento de propostas

| SQLite `processos` | PostgreSQL `proposals` | API |
| --- | --- | --- |
| `id` | `legacy_id` | `legacy_id` |
| `proposta` | `proposal_number` | `proposal_number` |
| `cliente` | `customer_name` | `customer_name` |
| `obra_site` | `project_name` | `project_name` |
| `pedido_compra` | `order_reference` | `order_reference` |
| `lote` | `lot` | `lot` |
| `data_entrada` ou `data_cadastro` | `proposal_date` | `proposal_date` |
| `prazo_entrega` | `deadline_date` | `deadline_date` |
| status derivados do legado | `current_area` | `current_area` |
| status derivados do legado | `current_status` | `current_status` |
| `status_geral` | `general_status` | `general_status` |
| `status_producao` | `production_status` | `production_status` |
| `status_galvanizacao` | `galvanization_status` | `galvanization_status` |
| `status_expedicao` | `shipping_status` | `shipping_status` |
| `status_almoxarifado` | `warehouse_status` | `warehouse_status` |
| `situacao_fluxo` | `flow_situation` | `flow_situation` |
| `tem_pendencia_producao` | `has_production_pending` | `has_production_pending` |
| `tipo_processo` | `process_type` | `process_type` |
| `processo_pai_id` | `parent_legacy_id` | `parent_legacy_id` |
| `numero_parcial` | `partial_number` | `partial_number` |
| `data_cadastro` | `legacy_created_at` | `legacy_created_at` |
| `atualizado_em` | `legacy_updated_at` | `legacy_updated_at` |

Campos calculados pela ferramenta de sincronizacao:

- `is_partial`;
- `is_cancelled`;
- `is_completed`;
- `source`;
- `source_hash`;
- `synced_at`.

## Mapeamento de itens

| SQLite `proposta_itens` | PostgreSQL `proposal_items` | API |
| --- | --- | --- |
| `id` | `legacy_id` | `legacy_id` |
| `processo_principal_id` | relacionamento por `proposal_id` | `proposal_id` |
| `processo_atual_id` | `legacy_current_process_id` | `legacy_current_process_id` |
| `numero_item` | `item_number` | `item_number` |
| `codigo_produto` | `product_code` | `product_code` |
| `descricao` | `description` | `description` |
| `quantidade` | `quantity` | `quantity` |
| valor fixo `un` | `unit` | `unit` |
| `peso` | `total_weight` | `total_weight` |
| calculado quando possivel | `unit_weight` | `unit_weight` |
| `produzir_internamente` | `produce_internally` | `produce_internally` |
| `precisa_galvanizacao` | `requires_galvanization` | `requires_galvanization` |
| campos de fluxo | `flow_defined` | `flow_defined` |
| `produzido` | `produced` | `produced` |
| `galvanizado` | `galvanized` | `galvanized` |
| `entregue` | `delivered` | `delivered` |
| `entregue_em` | `delivered_at` | `delivered_at` |
| `atualizado_em` | `legacy_updated_at` | `legacy_updated_at` |

Descricoes multilinha sao preservadas. Quantidades e pesos usam `Numeric`, nao `float`.

## Endpoints

Leitura:

- `GET /api/v1/proposals`
- `GET /api/v1/proposals/{id}`
- `GET /api/v1/proposals/{id}/items`
- `GET /api/v1/proposal-items/{id}`
- `GET /api/v1/proposals/by-legacy-id/{legacy_id}`

Sincronizacao administrativa:

- `POST /api/v1/admin/sync/proposals`

## Filtros e ordenacao

Filtros da listagem:

- `proposal_number`;
- `customer`;
- `project`;
- `current_area`;
- `current_status`;
- `is_partial`;
- `is_cancelled`;
- `is_completed`;
- `date_from`;
- `date_to`;
- `updated_after`.

Ordenacao permitida:

- `proposal_number`;
- `proposal_date`;
- `deadline_date`;
- `legacy_updated_at`;
- `synced_at`.

## Permissoes

- `proposals.view`: listar e consultar propostas;
- `proposal_items.view`: consultar itens;
- `proposals.sync`: executar sincronizacao administrativa.

## Regras da sincronizacao

- execucao manual;
- leitura do SQLite em modo `mode=ro`;
- envio para a API em lotes;
- upsert por `legacy_id`;
- hash SHA-256 deterministico por registro;
- `dry_run` suportado;
- registros ausentes no SQLite nao sao excluidos do PostgreSQL;
- bloqueio consultivo no PostgreSQL evita duas sincronizacoes simultaneas;
- eventos de auditoria registram sincronizacoes aceitas ou rejeitadas.

## Tela experimental no desktop

A tela `Consulta experimental - somente leitura` fica separada das telas oficiais.

Ela usa o cliente HTTP experimental, exige API habilitada, permissao de leitura e os recursos:

- `proposals_read`;
- `proposal_items_read`.

Ela nao possui botoes para cadastrar, editar, excluir, alterar status ou movimentar proposta.

