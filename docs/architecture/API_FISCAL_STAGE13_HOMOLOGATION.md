# Homologacao da Etapa 13 - Fiscal oficial

## Resultado

Etapa 13 aprovada em ambiente local com PostgreSQL temporario.

```text
API_VERSION = 0.8.0
API_STAGE = official-fiscal
EXPECTED_DATABASE_REVISION = 20260721_0008
```

## Migration

Migration criada:

```text
20260721_0008_create_fiscal_records.py
```

Estruturas:

- `fiscal_records`
- `fiscal_items`
- `fiscal_invoices`
- `fiscal_invoice_items`
- `fiscal_events`

Permissoes:

- `fiscal.view`
- `fiscal.register_emission`
- `fiscal.cancel_link`

## Cenarios validados

- entrada automatica na fila Fiscal;
- detalhe fiscal por proposta;
- emissao manual parcial;
- emissao manual total;
- multiplas notas por proposta;
- duplicidade de nota;
- conflito de versao;
- cancelamento interno de vinculo;
- recalculo de pendencia;
- retirada de nota pelo cliente;
- indicadores fiscais;
- pendencia critica independente do estado operacional;
- execucao com PostgreSQL real temporario.

## Evidencia sem SQLite

Com a flag oficial ativa, `backend_adapter` chama `api_proposal_storage` para Fiscal. As chamadas oficiais nao usam `production_repository` para escrita e nao fazem dupla escrita.

## Gate

A etapa so deve ir para a proxima fase mantendo:

- checksums de migrations OK;
- migrations em `head`;
- testes API verdes;
- testes desktop verdes;
- PostgreSQL real verde;
- sem fallback SQLite para Fiscal no modo oficial.

