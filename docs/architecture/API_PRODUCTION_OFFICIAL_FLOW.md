# Etapa 10 - Producao oficial e fluxo por item na API

## Decisao

A Producao passa a ser controlada pela API/PostgreSQL para propostas oficiais criadas no novo fluxo.

O desktop nao deve executar SQL local para listar, iniciar, definir fluxo de itens, editar pesos ou finalizar itens de Producao quando a flag `postgresql_official_proposals_enabled` estiver ativa.

## Escopo entregue

- Endpoints oficiais de Producao na API.
- Leitura da aba Producao via API.
- Inicio de Producao pela API.
- Definicao de fluxo por item pela API.
- Edicao de pesos por item pela API.
- Finalizacao parcial ou completa por item pela API.
- Eventos de dominio em `proposal_events`.
- Validacao por `version` para concorrencia otimista.
- Sem migracao nova, pois os campos necessarios ja existiam na revisao `20260720_0005`.

## Fora do escopo

Ainda continuam legados nesta etapa:

- Galvanizacao operacional.
- Montagem de cargas.
- Retorno de cargas.
- Expedicao.
- Almoxarifado.
- Fiscal.
- Remanejamento de material.
- Relatorios, auditoria visual e dashboards.
- Subprocessos parciais legados no formato `CP00000-P1`.

## Endpoints oficiais

```text
GET   /api/v1/production/proposals
GET   /api/v1/production/proposals/{proposal_id}
POST  /api/v1/production/proposals/{proposal_id}/start
PATCH /api/v1/production/proposals/{proposal_id}/item-flow
PATCH /api/v1/production/proposals/{proposal_id}/item-weights
POST  /api/v1/production/proposals/{proposal_id}/complete-items
```

## Permissoes

```text
proposals.view
proposals.change_status
proposal_items.update
```

Foram reutilizadas permissoes ja existentes. Nenhuma permissao nova foi criada.

## Estados de Producao

Estados aceitos para operar a Producao oficial:

```text
LIBERADO_PRODUCAO
NAO_INICIADO
INICIADO
PARADO
FINALIZADO_PARCIAL
ITEM_PENDENTE_FABRICACAO
```

Estados ativos na lista de Producao:

```text
LIBERADO_PRODUCAO
NAO_INICIADO
INICIADO
PARADO
FINALIZADO_PARCIAL
ITEM_PENDENTE_FABRICACAO
```

Quando a proposta sai completamente da Producao, ela deixa de aparecer na lista oficial da aba Producao.

## Entrada na Producao

O fluxo oficial comeca no Controle Geral.

```text
CONTROLE_GERAL / AGUARDANDO_LIBERACAO
  -> PRODUCAO / LIBERADO_PRODUCAO
```

Ao liberar para Producao, a API inicializa:

```text
current_area = PRODUCAO
current_status = LIBERADO_PRODUCAO
general_status = EM_PRODUCAO
production_status = NAO_INICIADO
flow_situation = NORMAL
has_production_pending = false
```

## Inicio de Producao

Inicio permitido quando a proposta esta em:

```text
LIBERADO_PRODUCAO
NAO_INICIADO
ITEM_PENDENTE_FABRICACAO
PARADO
```

Resultado:

```text
current_area = PRODUCAO
current_status = INICIADO
general_status = EM_PRODUCAO
production_status = INICIADO
```

A API bloqueia o inicio quando:

- a proposta nao esta na area de Producao;
- nao existem itens ativos;
- nao existe item produzido internamente;
- a versao enviada esta desatualizada.

## Fluxo por item

Cada item possui definicao individual:

```text
produce_internally
requires_galvanization
non_production_reason
flow_defined
produced
```

Regras:

- Item produzido internamente precisa passar pela Producao.
- Item nao produzido internamente exige motivo.
- Item nao produzido internamente e marcado como produzido para efeito de pendencia de Producao.
- Item com galvanizacao segue para a proxima etapa com indicacao de galvanizacao.
- Item sem galvanizacao segue para Expedicao quando a Producao terminar.
- Item com fluxo indefinido bloqueia a finalizacao.

## Pesos

Pesos oficiais ficam no item:

```text
unit_weight
total_weight
```

Regra:

```text
total_weight = quantity * unit_weight
```

A API valida pesos negativos e usa `version` do item para evitar sobrescrever alteracoes concorrentes.

## Finalizacao parcial

A finalizacao parcial recebe uma lista de itens internos produzidos.

Se ainda existir item interno pendente:

```text
current_area = PRODUCAO
current_status = FINALIZADO_PARCIAL
general_status = EM_PRODUCAO
production_status = FINALIZADO_PARCIAL
flow_situation = PARCIAL_COM_PENDENCIA
has_production_pending = true
```

A proposta continua aparecendo na Producao para fabricar o restante.

Nesta etapa oficial, a API nao cria subprocessos `P1`, `P2`. O controle parcial fica no nivel dos itens produzidos e pendentes.

## Finalizacao completa

Quando todos os itens internos ativos estao produzidos:

```text
production_status = FINALIZADO
flow_situation = NORMAL
has_production_pending = false
is_completed = false
```

Se algum item produzido exige galvanizacao:

```text
current_area = GALVANIZACAO
current_status = AGUARDANDO_ENVIO
general_status = EM_GALVANIZACAO
galvanization_status = AGUARDANDO_ENVIO
```

Se nenhum item produzido exige galvanizacao:

```text
current_area = EXPEDICAO
current_status = EM_SEPARACAO
general_status = EM_EXPEDICAO
shipping_status = EM_SEPARACAO
```

## Acoes retornadas para o desktop

A API devolve acoes calculadas para orientar a interface:

```text
DEFINE_ITEM_FLOW
INICIAR_PRODUCAO
REGISTRAR_PRODUCAO
EDITAR_PESOS
```

O desktop converte essas acoes para os comandos ja esperados pela tela legada.

## Auditoria

Eventos gravados em `proposal_events`:

```text
production_started
production_item_flow_updated
production_item_weights_updated
production_items_completed
proposal_status_changed
```

Tambem sao gerados eventos de seguranca pelo fluxo comum da API.

## Erros padronizados

```text
PRODUCTION_INVALID_STATE
PRODUCTION_ITEM_FLOW_REQUIRED
PRODUCTION_NO_INTERNAL_ITEMS
PRODUCTION_ITEM_NOT_AVAILABLE
PRODUCTION_WEIGHT_INVALID
PROPOSAL_VERSION_CONFLICT
PROPOSAL_ITEM_VERSION_CONFLICT
```

## Integracao desktop

Com `postgresql_official_proposals_enabled = true`:

- a lista da aba Producao usa `OfficialProposalApiStorage.list_production_proposals`;
- o detalhe da Producao usa `get_production_process`;
- inicio de Producao usa `start_production`;
- finalizacao parcial/completa usa `complete_production_items`;
- resumo de fluxo por item usa `production_item_flow_summary`;
- edicao de fluxo por item usa `update_production_item_flow`;
- edicao de pesos usa `update_production_item_weights`.

## Inconsistencias conhecidas preservadas

- O fluxo legado ainda cria subprocessos parciais; o fluxo oficial da Etapa 10 usa controle parcial por item.
- Galvanizacao e Expedicao ainda nao consomem os novos endpoints oficiais de destino.
- Remanejamento ainda nao esta migrado para a API.
- Relatorios e dashboards ainda podem depender do legado ate suas etapas proprias.

## Atualizacao - Etapa 11

Galvanizacao, cargas e retorno parcial foram migrados para API/PostgreSQL.

Documentos:

```text
docs/architecture/API_GALVANIZATION_OFFICIAL_FLOW.md
docs/architecture/API_GALVANIZATION_STAGE11_HOMOLOGATION.md
```

Os itens produzidos com `requires_galvanization = SIM` agora entram na fila oficial de montagem de carga.

## Proxima etapa recomendada

Migrar Expedicao para consumir os itens retornados pela Galvanizacao oficial.
