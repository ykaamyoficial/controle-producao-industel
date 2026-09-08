# Validacao com banco real de propostas e itens

## Banco identificado

O banco SQLite selecionado foi o caminho configurado no desktop local:

```text
app/data/controle_producao.db
```

Criterios usados:

- `app/config/controle_producao_config.json` aponta para esse arquivo;
- `app/services/app_paths.py` define `app/data/controle_producao.db` como banco padrao em ambiente nao empacotado;
- o arquivo possui schema completo da aplicacao, incluindo `processos`, `proposta_itens`, `historico_status`, tabelas fiscais, cargas e retornos;
- possui mais estrutura e dados que `scripts/controle_producao.db`, que foi descartado como banco de teste.

## Snapshot

O banco oficial nao foi usado diretamente para sincronizacao. Foi criado snapshot por SQLite Backup API, abrindo a origem em modo somente leitura.

Resultado do snapshot:

```text
Tamanho: 286720 bytes
SHA-256: 852fa0dbf40fb1c9687945a28a6ded102adcf32002fd473c17ea9b2d21c06313
Integrity check: ok
Foreign key check: 0 violacoes
Journal mode: wal
Total de tabelas: 24
```

O snapshot e os relatorios reais ficam em `reports/`, pasta ignorada pelo Git.

## Inventario agregado

```text
Total de propostas: 3
Total de itens: 28
Total de historicos: 22
Total de cargas: 0
Propostas sem itens: 0
Itens orfaos: 0
Propostas parciais: 0
Propostas canceladas: 0
Propostas concluidas: 0
CP00000: 0
Descricoes vazias: 0
Descricoes multilinha: 0
Quantidades nulas: 0
Pesos nulos: 0
Flags indefinidas: 0
```

Areas/status derivados encontrados:

```text
PRODUCAO:INICIADO = 2
PRODUCAO:NAO_INICIADO = 1
```

Status brutos encontrados:

```text
status_almoxarifado:AGUARDANDO_CONFIRMACAO = 3
status_geral:EM_PRODUCAO = 2
status_geral:LIBERADO_PRODUCAO = 1
status_producao:INICIADO = 2
status_producao:NAO_INICIADO = 1
```

Areas desconhecidas: 0.

## Sincronizacao

Fluxo executado com o snapshot:

```text
Dry-run: received=3, created=3, updated=0, unchanged=0, rejected=0
Primeira sync: received=3, created=3, item_created=28, updated=0, rejected=0
Segunda sync: received=3, created=0, updated=0, unchanged=3, rejected=0
Terceira sync: received=3, created=0, updated=0, unchanged=3, rejected=0
```

Idempotencia: aprovada.

Desempenho observado:

```text
Primeira sync real: 0.647s
Segunda sync: 0.734s
Terceira sync: 0.537s
```

## Validacao SQLite x API/PostgreSQL

Resultado da validacao integral:

```text
Total SQLite: 3 propostas
Total SQLite itens: 28
Divergencias: 0
Divergencias criticas: 0
Divergencias importantes: 0
Avisos: 0
```

Descricao truncada: 0 evidencias.

Pesos divergentes: 0.

Quantidades divergentes: 0.

Campos financeiros sincronizados: nao.

## Migration 0003

A migration `20260720_0003_create_proposals_read_model.py` foi alterada na estabilizacao anterior para:

- remover dependencia de imports mutaveis de permissoes;
- tornar a insercao das permissoes de propostas idempotente;
- retirar o vinculo do papel `admin`, movido para a migration `20260720_0004_link_admin_proposal_permissions.py`.

Nao foi criada `0005`, porque nao ha diferenca final de schema a corrigir. A linha Alembic atual foi validada por:

- checksum;
- upgrade direto;
- upgrade progressivo;
- downgrade/upgrade em banco temporario;
- testes de integracao PostgreSQL.

Revisao final:

```text
20260720_0004
```

## Validacoes adicionais

OpenAPI:

```text
GET /api/v1/proposals
GET /api/v1/proposals/{proposal_id}
GET /api/v1/proposals/{proposal_id}/items
GET /api/v1/proposal-items/{item_id}
GET /api/v1/proposals/by-legacy-id/{legacy_id}
POST /api/v1/admin/sync/proposals
```

Nao existem endpoints produtivos para cadastrar, editar, excluir, alterar status, mover area, produzir ou entregar proposta.

Hash Windows/Docker: igual.

Paginacao: validada com desempate estavel por `id`.

Payload financeiro/arbitrario: rejeitado.

## Classificacao

Classificacao final:

```text
Aprovada com ressalvas
```

Motivo da ressalva:

- o banco configurado como oficial local possui schema real e itens reais, mas volume pequeno: 3 propostas e 28 itens;
- foi executada uma observacao real com snapshot completo disponivel;
- as observacoes 2 e 3 devem ser executadas em momentos posteriores, apos movimentacoes normais do sistema.

## Recomendacao

Opcao recomendada:

```text
Opcao A - Periodo adicional de observacao
```

Nao migrar leitura oficial ainda. Manter a tela experimental e repetir snapshot, sincronizacao e validacao em pelo menos mais dois momentos reais de uso.

## Confirmacoes

```text
Banco SQLite oficial alterado: Nao
Snapshot real versionado: Nao
PostgreSQL fonte oficial: Nao
API com escrita produtiva: Nao
Login oficial substituido: Nao
Tela oficial substituida: Nao
Sincronizacao automatica: Nao
Sincronizacao bidirecional: Nao
Valores financeiros sincronizados: Nao
```

