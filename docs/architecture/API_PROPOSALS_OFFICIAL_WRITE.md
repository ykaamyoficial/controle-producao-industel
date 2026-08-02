# Etapa 7 - Propostas e itens oficiais com escrita pela API

## Decisao

Propostas e itens novos passam a ter o PostgreSQL como fonte oficial, com escrita exclusiva pela API.

Os dados SQLite existentes foram classificados como teste e nao serao migrados.

## Escopo entregue

- Migration `20260720_0005_make_proposals_official.py`.
- Tabelas oficiais: `proposals`, `proposal_items`, `proposal_events`.
- Endpoint antigo de sync removido da API.
- Permissao antiga `proposals.sync` removida no upgrade da 0005.
- Campos de replica preservados apenas como legado tecnico nullable: `legacy_id`, `legacy_*`, `source_hash`, `synced_at`.
- Campos oficiais adicionados: `proposal_number` unico, `notes`, `version`, `active`, `created_by`, `updated_by`, `created_at`, `updated_at`.
- Escrita SQLite para propostas bloqueavel por flag `postgresql_official_proposals_enabled`.

## Endpoints oficiais

```text
GET    /api/v1/proposals
GET    /api/v1/proposals/{id}
POST   /api/v1/proposals
PATCH  /api/v1/proposals/{id}
POST   /api/v1/proposals/{id}/status
POST   /api/v1/proposals/{id}/cancel
POST   /api/v1/proposals/{id}/activate
POST   /api/v1/proposals/{id}/deactivate
GET    /api/v1/proposals/{proposal_id}/items
POST   /api/v1/proposals/{proposal_id}/items
GET    /api/v1/proposal-items/{item_id}
PATCH  /api/v1/proposal-items/{item_id}
DELETE /api/v1/proposal-items/{item_id}
```

## Regras iniciais

Estado inicial definido pela API:

```text
Area: CONTROLE_GERAL
Status: AGUARDANDO_LIBERACAO
```

Transicoes implementadas nesta etapa:

```text
CONTROLE_GERAL / AGUARDANDO_LIBERACAO -> PRODUCAO / LIBERADO_PRODUCAO
qualquer estado nao cancelado -> CONTROLE_GERAL / CANCELADA
```

Nao foi migrada a maquina completa de producao, galvanizacao, expedicao, cargas e parciais. Isso fica para a proxima etapa.

## Regras de escrita

- Criacao exige usuario autenticado, permissao, numero de proposta unico, cliente e pelo menos um item.
- O desktop nao envia status na criacao.
- Edicao comum nao altera status.
- Edicao de proposta e itens fica liberada apenas antes da liberacao.
- Cancelamento preserva historico e nao remove fisicamente a proposta.
- Remocao de item e exclusao logica (`active=false`).
- Concorrencia usa `version`; versao divergente retorna `PROPOSAL_VERSION_CONFLICT`.
- Eventos de dominio sao gravados em `proposal_events`.
- Auditoria operacional tambem gera `security_events`.

## Permissoes

```text
proposals.view
proposals.create
proposals.update
proposals.cancel
proposals.delete
proposals.change_status
proposal_items.view
proposal_items.create
proposal_items.update
proposal_items.delete
```

Todas sao atribuidas ao perfil `admin` pela migration.

## Desktop

O client HTTP ganhou metodos oficiais para criar, editar, cancelar, alterar status e manter itens.

A flag `postgresql_official_proposals_enabled` controla a virada. Quando ativa, escritas SQLite legadas de propostas/itens sao bloqueadas para evitar dupla escrita.

Na Etapa 8, a tela `ProcessFormDialog` passou a usar esse client por meio de `OfficialProposalApiStorage` quando a flag esta ativa. O fluxo PDF/Nomus continua apenas preenchendo o formulario e o salvamento final passa pela API oficial.

## Sync legado

O endpoint `/api/v1/admin/sync/proposals` foi removido.

O script `scripts/sync_proposals_to_api.bat` foi desativado.

O modulo `app.integrations.api.proposal_sync` permanece somente como codigo historico/testavel; a CLI recusa execucao sem `ALLOW_DEPRECATED_PROPOSAL_SYNC=1`.

## Limites assumidos

- A tela oficial de cadastro/edicao ja foi conectada ao fluxo API-first na Etapa 8.
- A maquina completa de status/setores ainda precisa ser migrada.
- Relatorios, historico completo, cargas e demais setores ainda continuam fora desta etapa.
- Sem fallback para SQLite nas propostas oficiais.

## Validacao posterior - Etapa 9

A Etapa 9 estabilizou a suite, homologou PostgreSQL em ambiente temporario e registrou o fluxo atual de status legado.

Documentos:

```text
docs/architecture/API_PROPOSALS_STAGE9_HOMOLOGATION.md
docs/architecture/PROPOSAL_STATE_MACHINE_CURRENT_AS_IS.md
```

## Validacao posterior - Etapa 10

A Etapa 10 migrou a Producao oficial e o fluxo por item para API/PostgreSQL.

Documentos:

```text
docs/architecture/API_PRODUCTION_OFFICIAL_FLOW.md
docs/architecture/API_PRODUCTION_STAGE10_HOMOLOGATION.md
```

Continuam fora desta etapa: Galvanizacao, Cargas, Expedicao, Almoxarifado, Fiscal, remanejamento, relatorios e dashboards.
