# Estabilizacao de migrations e validacao da replica

## Decisao principal

A Etapa 6 identificou risco de alteracao retroativa na migration `20260720_0002_create_auth_security.py`.

O conteudo estabilizado da `0002` fica congelado com a lista original de permissoes de autenticacao e seguranca. Ela nao importa listas vivas do codigo de runtime, pois isso tornaria a migration dependente do estado atual do modulo `permissions.py`.

A correcao posterior foi isolada em nova migration:

```text
20260720_0004_link_admin_proposal_permissions.py
```

Essa migration vincula as permissoes de propostas ao papel `admin`, quando o papel existir, sem inserir regras produtivas e sem alterar o SQLite.

## Linha Alembic final

```text
20260720_0001_create_system_metadata.py
20260720_0002_create_auth_security.py
20260720_0003_create_proposals_read_model.py
20260720_0004_link_admin_proposal_permissions.py
```

Revisao esperada:

```text
20260720_0004
```

## Checksums

O manifesto oficial fica em:

```text
api/alembic/migration_checksums.json
```

Verificar:

```text
python scripts/check_migration_checksums.py
```

Atualizar o manifesto somente quando uma nova migration for criada ou quando houver decisao tecnica explicita:

```text
python scripts/check_migration_checksums.py --update
```

O teste automatizado `tests/test_migration_checksums.py` falha se uma migration existente mudar ou se uma nova migration nao for registrada no manifesto.

## Comparacao de schemas

Ferramenta:

```text
python scripts/compare_api_schema_paths.py --direct-url <url_a> --progressive-url <url_b>
```

Ela compara dois caminhos:

- banco criado do zero com `alembic upgrade head`;
- banco evoluido progressivamente por revisao.

A comparacao cobre tabelas, colunas, tipos, nullability, defaults, PKs, FKs, unique constraints, indices e revisao Alembic.

## Sequencia de downgrade validada

Sequencia usada:

```text
upgrade head
downgrade -1
upgrade head
downgrade 20260720_0002
upgrade head
downgrade base
upgrade head
```

Resultado esperado:

```text
20260720_0004 (head)
```

## Validacao da replica

Ferramenta:

```text
python -m app.integrations.api.validate_proposals_replica --sqlite-path <sqlite> --api-url <api> --username <usuario> --redact
```

Ela compara SQLite versus API/PostgreSQL e gera:

```text
reports/proposals_replica_validation_<data>.json
reports/proposals_replica_validation_<data>.csv
```

`reports/` e ignorado pelo Git porque pode conter dados reais.

Categorias de divergencia:

- `MISSING_IN_POSTGRESQL`;
- `MISSING_IN_SQLITE`;
- `FIELD_MISMATCH`;
- `HASH_MISMATCH`;
- `DUPLICATE_LEGACY_ID`;
- `INVALID_SOURCE_DATA`;
- `UNKNOWN_AREA`;
- `UNKNOWN_STATUS`;
- `ITEM_COUNT_MISMATCH`.

Severidades:

- `critical`;
- `important`;
- `warning`.

## Hash

O hash SHA-256 usa JSON deterministico com:

- ordenacao de chaves;
- serializacao estavel de `Decimal`;
- Unicode preservado;
- quebras `CRLF` e `CR` normalizadas para `LF`;
- item hash independente por item;
- proposal hash sem incluir a lista de itens.

A ordem dos itens nao faz parte do hash da proposta nesta etapa. Mudancas em itens sao controladas pelos hashes dos proprios itens e pela contagem de itens na validacao.

## Snapshot SQLite

A leitura usa:

```text
file:<path>?mode=ro
BEGIN
SELECT ...
COMMIT
```

A ferramenta nao escreve no SQLite, nao executa migrations no SQLite e nao cria sincronizacao automatica.

Se a tabela `proposta_itens` nao existir no snapshot analisado, o inventario registra propostas sem itens em vez de alterar a origem.

## Resultado da validacao local

Snapshot usado:

```text
scripts/controle_producao.db
```

Resultado:

```text
Total de propostas: 1
Total de itens: 0
Propostas sem itens: 1
Itens orfaos: 0
Legacy IDs duplicados: 0
Status desconhecidos: 0
Areas desconhecidas: 0
CP00000: 0
Divergencias criticas: 0
Divergencias importantes: 0
Avisos: 0
```

Observacao: o snapshot local disponivel nao possui a tabela `proposta_itens`. A ferramenta foi validada com esse caso, mas uma aprovacao produtiva ainda deve ser repetida sobre um snapshot real completo.

## Limites da etapa

Permanece proibido:

- tornar PostgreSQL fonte oficial;
- alterar status pela API;
- criar escrita produtiva na API;
- substituir login oficial;
- substituir telas oficiais;
- executar sync automatico;
- executar sync bidirecional.

