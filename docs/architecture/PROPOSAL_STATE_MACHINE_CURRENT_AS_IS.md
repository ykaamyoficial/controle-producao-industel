# Maquina atual de status de propostas - as-is

## Escopo

Este documento registra o fluxo atual encontrado no codigo legado do desktop/SQLite.

Nao e uma proposta de redesenho. Serve como base antes de migrar a maquina completa para API/PostgreSQL.

Fontes principais:

- `app/services/production_repository.py`
- `app/services/backend_adapter.py`
- `app/ui/status_dialog.py`
- `app/ui/batch_status_dialog.py`
- `app/ui/galvanization_load_dialog.py`

## Areas e colunas

```text
CONTROLE GERAL -> status_geral
PRODUCAO       -> status_producao
GALVANIZACAO   -> status_galvanizacao
EXPEDICAO      -> status_expedicao
ALMOXARIFADO   -> status_almoxarifado
```

## Sequencia nominal

### Controle Geral

```text
NAO_LIBERADO -> LIBERADO_PRODUCAO
NAO_LIBERADO -> CANCELADA
LIBERADO_PRODUCAO -> CANCELADA
```

Cancelamento fora do Controle Geral e bloqueado.

### Producao

```text
NAO_INICIADO -> INICIADO
ITEM_PENDENTE_FABRICACAO -> INICIADO
INICIADO -> PARADO
INICIADO -> FINALIZADO_PARCIAL
INICIADO -> FINALIZADO
PARADO -> INICIADO
FINALIZADO_PARCIAL -> FINALIZADO
```

### Galvanizacao

```text
AGUARDANDO_ENVIO -> EM_CARGA
DISPONIVEL_PARCIAL -> EM_CARGA
EM_CARGA -> ENVIADO_GALVANIZACAO
ENVIADO_GALVANIZACAO -> RETORNOU_GALVANIZACAO
```

`RETORNOU_PARCIAL` existe no modelo, mas a acao direta foi removida. O retorno parcial e controlado pela tela de cargas.

### Expedicao

```text
EM_SEPARACAO -> SEPARACAO_INICIADA
AGUARDANDO_SEPARACAO_PARCIAL -> SEPARACAO_INICIADA
SEPARACAO_INICIADA -> SEPARADO
SEPARADO -> ENTREGUE_PARCIAL
SEPARADO -> ENTREGUE
ENTREGUE_PARCIAL -> ENTREGUE_PARCIAL
ENTREGUE_PARCIAL -> ENTREGUE
```

Quando a proposta esta em contexto parcial ou com pendencia, `SEPARADO -> ENTREGUE` e bloqueado. Deve passar por entrega parcial ou remanejamento.

### Almoxarifado

```text
AGUARDANDO_CONFIRMACAO -> EM_SEPARACAO
AGUARDANDO_CONFIRMACAO -> SEM_PARAFUSOS
EM_SEPARACAO -> SEPARADO
SEPARADO -> ALMOXARIFADO_ENTREGUE_PARCIAL
SEPARADO -> ALMOXARIFADO_ENTREGUE
ALMOXARIFADO_ENTREGUE_PARCIAL -> ALMOXARIFADO_ENTREGUE
```

`SEM_PARAFUSOS` marca `necessita_almoxarifado = NAO` e remove a proposta da aba de Almoxarifado.

## Cascatas automaticas

Ao liberar no Controle Geral:

```text
status_geral = LIBERADO_PRODUCAO
status_producao = NAO_INICIADO
status_almoxarifado = AGUARDANDO_CONFIRMACAO ou SEM_PARAFUSOS
```

Ao concluir Producao completa:

```text
status_galvanizacao = AGUARDANDO_ENVIO
status_geral = EM_GALVANIZACAO
```

Se nenhum item precisa galvanizacao:

```text
status_galvanizacao = vazio
status_expedicao = EM_SEPARACAO
status_geral = EM_EXPEDICAO
```

Ao retornar Galvanizacao completa:

```text
status_expedicao = EM_SEPARACAO
status_geral = EM_EXPEDICAO
entrada fiscal pode ser criada automaticamente
```

## Fiscal oficial - Etapa 13

O estado fiscal passa a ser independente do estado operacional no fluxo API/PostgreSQL.

Estados oficiais persistidos:

```text
FALTA_EMITIR_NOTA_FISCAL
NOTA_FISCAL_PARCIAL
NOTA_FISCAL_EMITIDA
FISCAL_CANCELADO
```

Situacoes fiscais exibidas:

```text
AGUARDANDO_NF
CP_EM_PROCESSAMENTO
NF_EM_PROCESSAMENTO
DISPONIVEL_PARA_EMISSAO
PENDENCIA_FISCAL_CRITICA
NF_PARCIAL
NF_EMITIDA
NF_RETIRADA_CLIENTE
FISCAL_CANCELADO
```

A fila Fiscal oficial e sincronizada pela API para propostas ativas e nao canceladas, preservando o acompanhamento global existente no legado. Registro manual de nota, emissao parcial, emissao total, retirada e cancelamento interno recalculam o estado fiscal sem alterar diretamente a area operacional.

Ao entregar na Expedicao:

```text
status_geral = ENTREGUE
data_retirada preenchida
nota fiscal pode ser marcada como retirada
```

## Processo parcial

Quando uma proposta principal em Producao recebe `FINALIZADO_PARCIAL`:

- a proposta principal permanece em Producao com pendencia;
- e criado um subprocesso `CP00000-P1`, `CP00000-P2`, etc.;
- o subprocesso nasce como `tipo_processo = PARCIAL`;
- o subprocesso nasce com `status_producao = FINALIZADO`;
- o subprocesso nasce em Galvanizacao como `DISPONIVEL_PARCIAL`;
- os itens selecionados passam para o subprocesso.

Fluxo resumido:

```text
Principal CP00010
  Producao: FINALIZADO_PARCIAL
  situacao_fluxo: PARCIAL_COM_PENDENCIA

Subprocesso CP00010-P1
  Producao: FINALIZADO
  Galvanizacao: DISPONIVEL_PARCIAL
  segue parcialmente para carga, retorno, expedicao e entrega
```

Quando o saldo restante da principal e finalizado depois, o codigo pode criar novo subprocesso para esse saldo seguir pelas proximas areas.

## Galvanizacao e cargas

A proposta so entra em carga se estiver visivel para Galvanizacao e possuir peso/item elegivel.

Status da carga:

```text
AGUARDANDO_LIBERACAO
LIBERADA_PARA_ENVIO
RETORNO_PARCIAL
RETORNADA_GALVANIZACAO
```

Atraso da carga e calculado por:

```text
data_prevista_retorno < data atual
```

Carga retornada nunca e marcada como atrasada.

## Remanejamento na Expedicao

O remanejamento acontece na Expedicao.

Regras atuais:

- usuario precisa editar Expedicao;
- destino e origem devem ser propostas diferentes;
- nao permite remanejamento dentro da mesma familia principal/parcial;
- origem precisa estar com `status_producao = FINALIZADO`;
- origem precisa ter material pronto na Expedicao (`SEPARADO` ou `ENTREGUE_PARCIAL`);
- destino nao pode estar entregue/cancelado/finalizado.

Se todo o material da origem for usado:

```text
origem -> volta para Producao como ITEM_PENDENTE_FABRICACAO
destino -> marcado como ENTREGUE
```

Se apenas parte do material da origem for usada:

```text
origem -> permanece na Expedicao com o restante
novo subprocesso de reposicao -> ITEM_PENDENTE_FABRICACAO
destino -> marcado como ENTREGUE
```

## Visibilidade por area

Uma proposta entregue nao aparece nas areas operacionais.

Uma principal com parciais ativas fica oculta das proximas areas, exceto quando ainda precisa continuar na Producao.

Almoxarifado oculta automaticamente propostas sem almoxarifado ou ja entregues pelo almoxarifado.

## Inconsistencias e pontos de atencao

- A maquina completa ainda nao esta toda na API.
- A API oficial ja possui propostas, itens, Producao, Galvanizacao e Expedicao oficial para propostas novas.
- Existem status legados/compatibilidade, como `AGUADANDO_ENVIO`.
- `RETORNOU_PARCIAL` existe no modelo, mas a transicao direta foi bloqueada.
- A regra de parciais e poderosa, mas espalhada entre repository, dialogs e cargas.
- Remanejamento altera origem, destino, itens, historico e auditoria em uma funcao grande.

## Atualizacao Etapa 12

No modo oficial PostgreSQL, a Expedicao passou a ser calculada por `expedition_items`.

Regras oficiais novas:

- entrega exige saldo separado;
- entrega parcial mantem saldo pendente na Expedicao;
- proposta so encerra como `ENTREGUE` quando todos os itens ativos estiverem entregues;
- remanejamento devolve a origem para `PRODUCAO / ITEM_PENDENTE_FABRICACAO`;
- entrega antecipada por remanejamento e transacional na API.

O comportamento legado SQLite permanece descrito acima apenas como referencia historica.
- `ENTREGUE_PARCIAL -> ENTREGUE` depende de contexto e pode ser bloqueado por pendencia/remanejamento.

## Atualizacao - Etapa 10

A Producao oficial foi migrada para API/PostgreSQL para propostas oficiais novas.

Documentos:

```text
docs/architecture/API_PRODUCTION_OFFICIAL_FLOW.md
docs/architecture/API_PRODUCTION_STAGE10_HOMOLOGATION.md
```

O fluxo oficial da Etapa 10 usa controle parcial por item. Ele mantem a proposta na Producao enquanto houver item interno pendente e envia a proposta para Galvanizacao ou Expedicao apenas quando a Producao estiver completamente concluida.

O modelo legado de subprocessos `CP00000-P1`, `CP00000-P2` continua documentado aqui como comportamento as-is, mas ainda nao foi recriado no modulo oficial da API.

## Atualizacao - Etapa 11

Galvanizacao e cargas oficiais foram migradas para API/PostgreSQL.

Documentos:

```text
docs/architecture/API_GALVANIZATION_OFFICIAL_FLOW.md
docs/architecture/API_GALVANIZATION_STAGE11_HOMOLOGATION.md
```

Estados oficiais preservados:

```text
AGUARDANDO_LIBERACAO
LIBERADA_PARA_ENVIO
RETORNO_PARCIAL
RETORNADA_GALVANIZACAO
CANCELADA
```

`Atrasada` permanece como indicador calculado, nao status persistido.

O retorno parcial oficial e calculado por item/quantidade. Propostas com retorno parcial ficam em Galvanizacao com `RETORNOU_PARCIAL`; propostas com todos os itens galvanizados retornados seguem logicamente para Expedicao com `EM_SEPARACAO`.

## Recomendacao para migracao

Migrar agora os proximos setores para consumir a saida oficial da Producao.

Depois migrar, em etapas separadas:

- Producao;
- Galvanizacao e cargas;
- Expedicao e remanejamento;
- Almoxarifado;
- Fiscal;
- historico, auditoria, dashboards e relatorios.
