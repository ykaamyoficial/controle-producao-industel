# Homologacao da Etapa 12 - Expedicao oficial

## Resultado

A Etapa 12 foi implementada com Expedicao oficial em API/PostgreSQL para propostas novas.

Revisao final das migrations:

```text
20260721_0007
```

Versao da API:

```text
0.7.0
```

Stage:

```text
official-expedition
```

Feature declarada:

```text
expedition_official
```

## Validacoes executadas

```text
python -m compileall api/app app/services app/integrations -q
python -m pytest api/tests -q
python scripts/check_migration_checksums.py --update
python scripts/check_migration_checksums.py
python -m pytest tests/test_desktop_api_client.py tests/test_api_proposal_storage.py tests/test_backend_official_proposals.py -q
python -m pytest api/tests/test_postgresql_integration.py api/tests/test_auth_integration.py api/tests/test_proposals_integration.py -q
python -m pytest -q
```

Resultados:

- API local: `19 passed, 29 skipped`.
- Desktop/API focado: `23 passed`.
- PostgreSQL temporario: `29 passed`.
- Suite completa: `448 passed, 32 skipped`.
- Checksums: OK.

Avisos conhecidos:

- `StarletteDeprecationWarning` no `fastapi.testclient`.
- `DeprecationWarning` do `pytest_asyncio` em Python 3.14.

## Cenarios homologados

- Fluxo Producao sem galvanizacao -> Expedicao.
- Bloqueio de entrega antes da separacao.
- Inicio da separacao.
- Separacao por item.
- Entrega total.
- Retorno parcial de galvanizacao entrando parcialmente na Expedicao.
- Entrega parcial mantendo proposta aberta.
- Remanejamento devolvendo proposta fonte para Producao como `ITEM_PENDENTE_FABRICACAO`.
- Entrega antecipada por remanejamento.
- Migration upgrade/head em PostgreSQL real temporario.
- Tabelas estruturais novas presentes.
- Desktop consumindo API para itens pendentes de entrega.

## Correcoes relevantes durante a etapa

- A selecao vazia de entrega agora falha quando nao existe item separado.
- A fila de Expedicao deixou de duplicar item em memoria ao criar `expedition_items`.
- A proposta so vira `ENTREGUE` quando todos os itens ativos estao entregues e nao ha pendencia produtiva.
- Chamadas legadas no adapter que usavam a flag oficial como atributo foram corrigidas para chamar o metodo.

## Situacao final

Expedicao esta oficialmente migrada para API/PostgreSQL no modo oficial.

Ainda continuam fora do fluxo oficial:

- Fiscal;
- Almoxarifado;
- relatorios;
- dashboards;
- chat;
- notificacoes;
- subprocessos P1/P2;
- dados antigos SQLite.
