# Etapa 11 - Galvanizacao, cargas e retorno oficial na API

## Decisao

Galvanizacao e cargas passam a ser controladas pela API/PostgreSQL para propostas oficiais novas.

Com `postgresql_official_proposals_enabled = true`, o desktop nao deve gravar cargas, itens de carga, envio ou retorno no SQLite.

## Fluxo anterior

O legado concentrava as regras em `production_repository.py` e usava as tabelas SQLite:

```text
cargas_galvanizacao
cargas_galvanizacao_itens
cargas_galvanizacao_item_detalhes
retornos_galvanizacao
retornos_galvanizacao_itens
processos
proposta_itens
historico_status
auditoria
```

Estados reais preservados:

```text
AGUARDANDO_LIBERACAO
LIBERADA_PARA_ENVIO
RETORNO_PARCIAL
RETORNADA_GALVANIZACAO
CANCELADA
```

`Atrasada` continua sendo indicador calculado por data prevista, nao status persistido.

## Fluxo novo

```text
Desktop
  -> API REST
  -> PostgreSQL
```

A API decide:

- quais itens podem entrar em carga;
- saldo disponivel por item;
- duplicidade;
- peso oficial;
- envio;
- retorno total;
- retorno parcial por proposta;
- retorno parcial por item;
- encaminhamento logico para Expedicao;
- status resumido da proposta;
- status resumido da carga.

## Modelagem

Migration:

```text
20260721_0006_create_galvanization_loads.py
```

Tabelas oficiais:

```text
galvanization_loads
galvanization_load_items
galvanization_load_events
```

Campos principais da carga:

```text
id, code, driver_name, max_weight, total_weight, status,
expected_return_date, sent_at, returned_at, closed_at,
notes, version, active, created_by, updated_by,
created_at, updated_at
```

Campos principais do item da carga:

```text
load_id, proposal_id, proposal_item_id,
sent_quantity, returned_quantity,
unit_weight, sent_weight, returned_weight,
status, version, active, returned_at
```

## Elegibilidade

Um item so entra em carga quando:

- pertence a uma proposta oficial ativa;
- a proposta nao esta cancelada;
- o item esta ativo;
- o item foi produzido;
- o item precisa de galvanizacao;
- o fluxo do item esta definido;
- o item ainda nao retornou integralmente;
- existe saldo nao enviado em carga nao cancelada.

Itens sem galvanizacao, pendentes de producao ou ja retornados integralmente sao rejeitados pela API.

## Peso

O peso da carga e calculado pela API:

```text
sent_weight = sent_quantity * unit_weight
total_weight = soma(sent_weight dos itens ativos)
```

Se `max_weight` for informado, a API bloqueia carga acima da capacidade.

## Estados

### AGUARDANDO_LIBERACAO

Permite:

- editar dados da carga;
- substituir itens;
- liberar para envio.

### LIBERADA_PARA_ENVIO

Permite:

- registrar retorno total;
- registrar retorno parcial por proposta;
- registrar retorno parcial por item.

Nao permite edicao comum de itens.

### RETORNO_PARCIAL

Permite novos retornos para o saldo pendente.

### RETORNADA_GALVANIZACAO

Indica que todos os itens ativos da carga retornaram.

Permite encerramento administrativo, que preenche `closed_at` sem inventar novo status.

### CANCELADA

Estado reservado na modelagem oficial. Cancelamento operacional nao foi exposto nesta etapa porque a regra pos-envio ainda depende de correcao administrativa formal.

## Retorno parcial

O retorno pode ser registrado:

- por proposta;
- por item;
- por quantidade parcial de item.

Quando uma proposta tem apenas parte dos itens retornados:

```text
galvanization_status = RETORNOU_PARCIAL
shipping_status = AGUARDANDO_SEPARACAO_PARCIAL
current_area = GALVANIZACAO
```

Quando todos os itens de galvanizacao da proposta retornam:

```text
galvanization_status = RETORNOU_GALVANIZACAO
shipping_status = EM_SEPARACAO
current_area = EXPEDICAO
```

A API nao executa separacao, entrega, fiscal ou remanejamento.

## Endpoints

```text
GET   /api/v1/galvanization/candidates
GET   /api/v1/galvanization/loads
POST  /api/v1/galvanization/loads
GET   /api/v1/galvanization/loads/{load_id}
PATCH /api/v1/galvanization/loads/{load_id}
POST  /api/v1/galvanization/loads/{load_id}/release
POST  /api/v1/galvanization/loads/{load_id}/returns
POST  /api/v1/galvanization/loads/{load_id}/close
```

## Permissoes

Permissoes reaproveitadas:

```text
proposals.view
proposals.change_status
```

A UI pode ocultar botoes, mas a API continua validando permissao.

## Eventos

Eventos oficiais:

```text
GALVANIZATION_LOAD_CREATED
GALVANIZATION_LOAD_UPDATED
GALVANIZATION_LOAD_RELEASED
GALVANIZATION_ITEM_ADDED_TO_LOAD
GALVANIZATION_ITEM_SENT
GALVANIZATION_ITEM_RETURNED
GALVANIZATION_RETURN_REGISTERED
GALVANIZATION_PROPOSAL_RETURN_RECALCULATED
GALVANIZATION_LOAD_CLOSED
```

Eventos sao gravados em `galvanization_load_events`, `proposal_events` e `security_events`.

## Concorrencia

Toda mutacao de carga valida `version`.

Conflito retorna:

```text
GALVANIZATION_LOAD_VERSION_CONFLICT
```

## Desktop

Com a flag oficial ativa:

- candidatos de Galvanizacao vem da API;
- cargas vem da API;
- detalhes da carga vem da API;
- criacao/edicao de carga usa API;
- liberacao usa API;
- retorno parcial usa API;
- retorno total usa API;
- nenhum fallback SQLite e executado.

## Dependencias legadas

Ainda ficam para proximas etapas:

- Separacao em Expedicao;
- entrega;
- remanejamento;
- Fiscal;
- Almoxarifado;
- relatorios;
- dashboards;
- historico visual completo.

## Proxima etapa

Migrar Expedicao para consumir os itens retornados da Galvanizacao oficial.
