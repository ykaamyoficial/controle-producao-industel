# Etapa 11 - Homologacao da Galvanizacao oficial

## Objetivo

Validar Galvanizacao, cargas e retorno parcial na API/PostgreSQL.

## Resultado

Classificacao: aprovada.

## Ambiente

```text
API: FastAPI
Banco: PostgreSQL
Revisao final: 20260721_0006
API_VERSION: 0.6.0
API_STAGE: official-galvanization
Feature: galvanization_official
```

## Migration

Criada:

```text
api/alembic/versions/20260721_0006_create_galvanization_loads.py
```

Nao houve alteracao silenciosa na `0005`.

Checksums atualizados e validados:

```text
python scripts/check_migration_checksums.py
Checksums das migrations OK.
```

## Testes

### API local

```text
python -m pytest api/tests -q
19 passed, 26 skipped, 2 warnings
```

### Desktop completo

```text
python -m pytest tests -q
429 passed, 3 skipped, 1 warning
```

### Testes focados de galvanizacao e adapter

```text
python -m pytest tests/test_backend_official_proposals.py tests/test_galvanization_partial_return.py tests/test_galvanization_load_weights.py tests/test_galvanization_load_manager_dialog.py -q
32 passed, 1 warning
```

### PostgreSQL temporario

```text
python -m pytest api/tests/test_postgresql_integration.py api/tests/test_auth_integration.py api/tests/test_proposals_integration.py -q
26 passed, 2 warnings
```

O banco temporario foi criado em PostgreSQL 18 na porta `55441` e parado ao final.

## Cenarios validados

- Migration upgrade/downgrade em PostgreSQL.
- Health/version com revisao `20260721_0006`.
- Listagem de itens elegiveis para carga.
- Exclusao de item sem galvanizacao.
- Criacao de carga com itens de mais de uma proposta.
- Bloqueio de item duplicado.
- Liberacao da carga para envio.
- Conflito de versao da carga.
- Retorno parcial por item.
- Retorno por proposta.
- Retorno total da carga.
- Encerramento com `closed_at`.
- Itens retornados ficam elegiveis logicamente para Expedicao.
- Proposta parcialmente retornada permanece em Galvanizacao.
- Desktop usa API sem repository SQLite quando a flag oficial esta ativa.

## Problemas encontrados e corrigidos

### Lazy load assincrono

Problema: criacao de carga acessava `load.items` em objeto recem-criado e disparava IO implicito.

Correcao: a API passou a consultar itens existentes explicitamente antes de substituir itens da carga.

### Teste estrutural

Problema: teste de tabelas estruturais nao conhecia as novas tabelas oficiais de Galvanizacao.

Correcao: lista esperada atualizada com `galvanization_loads`, `galvanization_load_items` e `galvanization_load_events`.

### Banco temporario sujo

Problema: apos uma falha intermediaria, o downgrade da `0005` encontrou dados oficiais com `source_hash` nulo.

Correcao: banco temporario foi dropado/recriado e a validacao limpa passou.

## Evidencia sem SQLite

Com `postgresql_official_proposals_enabled = true`, `BackendService` chama `OfficialProposalApiStorage` para:

- `galvanization_load_candidates`;
- `galvanization_loads`;
- `get_galvanization_load_dict`;
- `galvanization_load_items`;
- `galvanization_load_proposal_items`;
- `galvanization_return_proposals`;
- `galvanization_return_items`;
- `save_galvanization_load`;
- `release_galvanization_load`;
- `register_galvanization_partial_return`.

Testes usam repository legado que falha se for chamado.

## Gate

A Etapa 11 esta aprovada para homologacao.

Nao houve commit, push, tag, release ou instalador.
