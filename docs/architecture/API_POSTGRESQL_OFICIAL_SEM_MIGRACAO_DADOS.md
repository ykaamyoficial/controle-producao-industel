# Migração definitiva para PostgreSQL sem preservar dados de teste

## Decisão

Os dados existentes no SQLite local foram considerados dados de teste e nao precisam ser migrados para o PostgreSQL.

A estrategia deixa de ser:

```text
SQLite oficial -> replica PostgreSQL -> validacao -> migracao gradual
```

E passa a ser:

```text
PostgreSQL oficial vazio -> API como unica camada de dados -> Desktop consumindo API
```

## Consequencia principal

Nao sera necessario criar uma ferramenta completa de migracao historica dos dados atuais.

Ainda sera necessario migrar:

- schema;
- regras de negocio;
- permissoes;
- auditoria;
- telas do desktop;
- consultas;
- relatorios;
- exportacoes;
- fluxo de status;
- cargas;
- itens;
- fiscal;
- almoxarifado;
- galvanizacao;
- expedicao.

## Atualizacao Etapa 13 - Fiscal

O modulo Fiscal foi migrado para o fluxo oficial API/PostgreSQL na revisao `20260721_0008`.

Novos dados fiscais devem nascer no PostgreSQL por meio da API. Os registros fiscais antigos do SQLite nao sao migrados, conforme a decisao deste documento.

Com `postgresql_official_proposals_enabled=true`, fila fiscal, detalhes, indicadores, registro manual de nota, retirada de nota e cancelamento interno de vinculo usam API sem fallback SQLite.

## Regras da virada

- O PostgreSQL passa a ser o banco oficial para dados novos.
- A API passa a ser a unica camada autorizada a criar, editar, excluir ou movimentar dados.
- O desktop nao deve acessar PostgreSQL diretamente.
- O desktop nao deve continuar escrevendo no SQLite para funcionalidades migradas.
- O SQLite pode permanecer temporariamente apenas como legado/desativado, fallback tecnico ou referencia de codigo.
- Nao usar sincronizacao bidirecional.
- Nao tentar manter SQLite e PostgreSQL oficiais ao mesmo tempo.
- Nao migrar dados de teste do SQLite para producao.

## Ordem recomendada

### 1. Congelamento da decisao

Registrar que os dados atuais do SQLite podem ser descartados.

Criar ambiente PostgreSQL limpo com migrations ate `head`.

Criar usuario administrador oficial na API.

### 2. Modelo oficial de propostas

Transformar o read model atual em modulo oficial de propostas.

Adicionar endpoints de escrita pela API:

```text
POST /api/v1/proposals
PATCH /api/v1/proposals/{id}
PATCH /api/v1/proposals/{id}/status
POST /api/v1/proposals/{id}/items
PATCH /api/v1/proposal-items/{id}
```

Somente depois disso o desktop deve parar de cadastrar/alterar propostas pelo SQLite.

### 3. Regras de status

Centralizar na API a maquina de status profissional definida nas etapas anteriores.

Regras parciais, subprocessos e remanejamento devem ficar na API.

### 4. Cargas e setores

Migrar modulos:

- producao;
- galvanizacao;
- expedicao;
- almoxarifado;
- fiscal;
- cargas;
- retornos;
- entregas;
- remanejamentos.

Cada modulo deve ter migration, models, schemas, service, repository, router e testes.

### 5. Desktop API-first

Substituir gradualmente os repositories SQLite por clients HTTP.

Para cada tela migrada:

- leitura pela API;
- escrita pela API;
- erros padronizados;
- permissao validada;
- auditoria centralizada;
- nenhum SQL local.

### 6. Relatorios e exportacoes

Reescrever relatorios para consultar a API ou endpoints de relatorio.

Exportacoes devem usar dados vindos da API/PostgreSQL.

### 7. Desativacao do SQLite

Quando todas as telas oficiais estiverem migradas:

- remover escrita SQLite;
- remover escolha de banco SQLite da interface oficial;
- manter apenas rotinas antigas em modo arquivado, se necessario;
- atualizar documentacao operacional.

## O que nao fazer

- Nao tentar migrar todos os arquivos em uma unica alteracao.
- Nao manter duas fontes oficiais.
- Nao acessar PostgreSQL diretamente pelo desktop.
- Nao reaproveitar a sincronizacao manual como mecanismo produtivo definitivo.
- Nao criar regras duplicadas no desktop e na API.

## Proxima etapa pratica

Etapa 7 iniciada e documentada em:

```text
docs/architecture/API_PROPOSALS_OFFICIAL_WRITE.md
```

Objetivo:

- PostgreSQL vazio como fonte oficial para propostas novas;
- API criando/editando/cancelando propostas e itens;
- endpoint antigo de sync removido;
- guard de escrita SQLite preparado por flag;
- regras iniciais de status centralizadas na API.

Etapa 8 tambem foi registrada em:

```text
docs/architecture/API_PROPOSALS_DESKTOP_OFFICIAL_UI.md
```

Ela migrou a tela oficial de cadastro/edicao para API quando a flag `postgresql_official_proposals_enabled` esta ativa.

Proxima etapa recomendada apos a validacao da Etapa 8:

```text
Migrar a maquina completa de status/setores para consumir somente a API.
```

## Etapa 9

Etapa 9 estabilizada e documentada em:

```text
docs/architecture/API_PROPOSALS_STAGE9_HOMOLOGATION.md
docs/architecture/PROPOSAL_STATE_MACHINE_CURRENT_AS_IS.md
```

Resultado: PostgreSQL homologado em ambiente temporario isolado, migrations ate `20260720_0005`, suite desktop completa verde, API local verde e integracoes PostgreSQL verdes.

## Etapa 10

Etapa 10 implementada e documentada em:

```text
docs/architecture/API_PRODUCTION_OFFICIAL_FLOW.md
docs/architecture/API_PRODUCTION_STAGE10_HOMOLOGATION.md
```

Resultado: a aba Producao e o controle de fluxo por item passaram a consumir API/PostgreSQL para propostas oficiais novas quando `postgresql_official_proposals_enabled` esta ativa.

Nao foi criada migration nova. A revisao final permanece `20260720_0005`.

Ainda continuam fora do fluxo oficial: Galvanizacao, Cargas, Expedicao, Almoxarifado, Fiscal, remanejamentos, relatorios e dashboards.

## Etapa 11

Etapa 11 implementada e documentada em:

```text
docs/architecture/API_GALVANIZATION_OFFICIAL_FLOW.md
docs/architecture/API_GALVANIZATION_STAGE11_HOMOLOGATION.md
```

Resultado: Galvanizacao, cargas e retorno parcial passaram a usar API/PostgreSQL para propostas oficiais novas.

Migration criada:

```text
20260721_0006_create_galvanization_loads.py
```

Revisao final:

```text
20260721_0006
```

Ainda continuam fora do fluxo oficial: Expedicao, entrega, remanejamento, Fiscal, Almoxarifado, relatorios e dashboards.

## Etapa 12

Etapa 12 implementada e documentada em:

```text
docs/architecture/API_EXPEDITION_OFFICIAL_FLOW.md
docs/architecture/API_EXPEDITION_STAGE12_HOMOLOGATION.md
```

Resultado: Expedicao, separacao, entrega parcial/total e remanejamento passaram a usar API/PostgreSQL para propostas oficiais novas.

Migration criada:

```text
20260721_0007_create_expedition_items.py
```

Revisao final:

```text
20260721_0007
```

Ainda continuam fora do fluxo oficial: Fiscal, Almoxarifado, relatorios, dashboards, chat, notificacoes e subprocessos P1/P2.

## Classificacao

Com a decisao de descartar os dados atuais, a replica de leitura deixa de ser caminho principal de migracao de dados e passa a ser aprendizado tecnico validado.

A prioridade agora e migrar regras e telas, nao transportar historico de teste.
