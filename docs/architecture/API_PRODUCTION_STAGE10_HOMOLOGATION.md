# Etapa 10 - Homologacao da Producao oficial

## Objetivo

Validar a migracao da aba Producao e do fluxo por item para API/PostgreSQL, mantendo os demais setores fora do escopo.

## Resultado

Classificacao: aprovada.

A Producao oficial esta pronta para uso em homologacao com PostgreSQL como fonte de dados para propostas oficiais novas.

## Ambiente

```text
Desktop: aplicacao existente
API: FastAPI
Banco: PostgreSQL via migrations
Revisao final: 20260720_0005
Flag desktop: postgresql_official_proposals_enabled
```

Nenhuma migration nova foi criada nesta etapa.

Motivo: os campos necessarios para Producao e fluxo por item ja existiam nas tabelas oficiais `proposals`, `proposal_items` e `proposal_events`.

## Validacoes executadas

### Testes focados do desktop/API client

```text
python -m pytest tests/test_backend_official_proposals.py tests/test_desktop_api_client.py tests/test_api_proposal_storage.py -q
```

Resultado:

```text
22 passed
```

### Testes focados de Producao desktop

```text
python -m pytest tests/test_item_weights.py tests/test_backend_official_proposals.py -q
```

Resultado:

```text
15 passed, 1 warning
```

### Suite completa da API local

```text
python -m pytest api/tests -q
```

Resultado:

```text
19 passed, 24 skipped, 2 warnings
```

### Integracao PostgreSQL temporaria

```text
python -m pytest api/tests/test_postgresql_integration.py api/tests/test_auth_integration.py api/tests/test_proposals_integration.py -q
```

Resultado:

```text
24 passed, 2 warnings
```

### Suite completa do desktop

```text
python -m pytest tests -q
```

Resultado:

```text
428 passed, 3 skipped, 1 warning
```

### Checksums das migrations

```text
python scripts/check_migration_checksums.py
```

Resultado:

```text
Checksums das migrations OK.
```

## Falhas encontradas e corrigidas

### Soma de Decimal no progresso

Problema:

```text
sum(...) iniciava com inteiro 0 e podia misturar tipos com Decimal.
```

Correcao:

```text
sum(..., Decimal("0"))
```

### Importacao faltante no service

Problema:

```text
ProductionProposalListItem era usado no service e precisava estar importado.
```

Correcao:

```text
import explicito no modulo de propostas.
```

### BackendService em testes sem config

Problema:

```text
Alguns testes criam BackendService.__new__ sem atributo config.
```

Correcao:

```text
official_proposals_enabled agora usa getattr defensivo.
```

## Evidencias de nao uso do SQLite na Producao oficial

Com a flag oficial ativa:

- listagem de Producao vem de `GET /api/v1/production/proposals`;
- detalhe vem de `GET /api/v1/production/proposals/{id}`;
- iniciar Producao chama `POST /api/v1/production/proposals/{id}/start`;
- fluxo por item chama `PATCH /api/v1/production/proposals/{id}/item-flow`;
- pesos chamam `PATCH /api/v1/production/proposals/{id}/item-weights`;
- finalizar itens chama `POST /api/v1/production/proposals/{id}/complete-items`;
- atualizacao de pesos nao cria backup SQLite;
- definicao de fluxo nao atualiza tabelas locais.

## Cenarios validados

- Proposta liberada para Producao.
- Inicio de Producao.
- Bloqueio por versao desatualizada.
- Bloqueio quando nao ha item interno.
- Bloqueio de finalizacao com fluxo de item indefinido.
- Definicao de item sem producao interna com motivo obrigatorio.
- Edicao de peso por item.
- Finalizacao parcial mantendo a proposta na Producao.
- Finalizacao completa enviando para Galvanizacao quando necessario.
- Finalizacao completa enviando direto para Expedicao quando nao ha galvanizacao.
- Itens mistos mantendo resumo de destino.
- Filtros e paginacao da lista oficial de Producao.
- Desktop usando API para acoes oficiais de Producao.

## Riscos residuais

- Galvanizacao ainda precisa ser migrada para consumir oficialmente a saida da Producao.
- Cargas ainda precisam ser migradas para nao depender do legado.
- Expedicao ainda nao esta preparada para remanejamento oficial por API.
- Relatorios podem nao refletir 100% dos dados oficiais enquanto nao forem migrados.
- O modelo oficial da Etapa 10 nao cria subprocessos `P1`, `P2`; usa controle parcial por item.

## Decisao final

A Etapa 10 esta aprovada para homologacao.

Nao houve commit, push, tag, instalador ou alteracao no banco de producao.
