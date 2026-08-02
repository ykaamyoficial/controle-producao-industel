# Etapa 9 - Estabilizacao e homologacao PostgreSQL

## Objetivo

Estabilizar a migracao oficial de propostas para API/PostgreSQL antes de mover a maquina completa de setores e status.

Esta etapa nao migra Producao, Galvanizacao, Expedicao, Almoxarifado, Fiscal, cargas, relatorios ou historico completo para a API.

## Correcao de estabilidade

O teste `test_galvanization_load_manager_dialog.py::test_main_table_is_load_only_with_action_column` dependia da data real da maquina.

A fixture usava `data_prevista_retorno = 20/07/2026`. Em `21/07/2026`, a regra correta passou a classificar a carga como atrasada, alterando o tooltip esperado de "aguardando" para "atrasada".

Solucao aplicada:

- criado `current_date()` em `app/ui/galvanization_load_dialog.py`;
- `_is_load_overdue()` passou a usar esse ponto unico;
- o teste principal congela a data em `19/07/2026`;
- novo teste cobre explicitamente o atraso em `21/07/2026`.

## Homologacao PostgreSQL

Foi usado um cluster PostgreSQL temporario isolado, criado via binarios locais do PostgreSQL 18, em porta local temporaria.

Regras observadas:

- nenhum banco de producao foi usado;
- nenhuma credencial real foi documentada;
- `APP_ENV=test`;
- banco de teste com nome contendo `test`;
- migrations aplicadas ate `head`;
- cluster temporario parado ao final da execucao.

Resultado:

```text
api/tests/test_postgresql_integration.py
api/tests/test_auth_integration.py
api/tests/test_proposals_integration.py

20 passed
```

## Migrations

Revisao final esperada:

```text
20260720_0005
```

Validacoes executadas:

- `python scripts/check_migration_checksums.py`
- suite de integracao PostgreSQL com downgrade/upgrade em banco temporario;
- endpoint de versao validando revision compativel;
- schema estrutural validado pelos testes.

Resultado:

```text
Checksums das migrations OK.
```

## Testes executados

Desktop completo:

```text
python -m pytest tests -q
425 passed, 3 skipped
```

API local sem PostgreSQL externo:

```text
python -m pytest api/tests -q
19 passed, 20 skipped
```

PostgreSQL temporario:

```text
python -m pytest api/tests/test_postgresql_integration.py api/tests/test_auth_integration.py api/tests/test_proposals_integration.py -q
20 passed
```

## Fluxo oficial validado

Validados por testes automatizados:

- criacao oficial de proposta com itens pela API;
- leitura oficial;
- edicao permitida antes da liberacao;
- criacao, edicao e exclusao logica de itens;
- conflito de versao com `PROPOSAL_VERSION_CONFLICT`;
- duplicidade de numero com `PROPOSAL_NUMBER_ALREADY_EXISTS`;
- rejeicao de campos financeiros no payload oficial;
- cancelamento por endpoint oficial;
- liberacao para Producao por endpoint oficial;
- eventos de proposta;
- autenticacao e permissoes;
- cliente HTTP do desktop mapeando `401`, `403`, `404`, `409`, `422`, `500`, timeout e conexao.

## Desktop API-first

Com `postgresql_official_proposals_enabled=true`, os caminhos oficiais de proposta usam:

```text
ProcessFormDialog -> BackendService -> OfficialProposalApiStorage -> ProposalsApiClient -> API -> PostgreSQL
```

Testes adicionados na Etapa 9 confirmam que:

- `BackendService.save_process()` chama `OfficialProposalApiStorage.save_process()`;
- `BackendService.proposal_items()` chama `OfficialProposalApiStorage.proposal_items()`;
- filtros pendentes oficiais nao caem no repository SQLite;
- `process_rows("CONTROLE GERAL")` usa linhas da API;
- falha de API vira `AppError` com mensagem de usuario;
- o repository SQLite fake falha se for chamado nesses cenarios.

## PDF e Nomus

O fluxo permanece controlado:

```text
PDF/Nomus -> conferencia humana -> formulario oficial -> API
```

Nao ha gravacao direta em SQLite no fluxo oficial quando a flag esta ativa.

## Pontos ainda legados

Ainda leem e escrevem SQLite:

- Producao;
- Galvanizacao;
- Expedicao;
- Almoxarifado;
- Fiscal;
- cargas e retornos de galvanizacao;
- remanejamento;
- historico operacional completo;
- auditoria legada;
- dashboards e relatorios;
- login principal do desktop;
- configuracoes locais.

## Riscos residuais

- Existem dois conjuntos de identificadores durante a transicao: ids oficiais da API e ids legados SQLite.
- A tela oficial de propostas usa `api_id` e `api_version`, mas os setores ainda operam por ids SQLite.
- Nao deve haver mistura de telas oficiais com movimentacoes legadas para a mesma proposta sem uma etapa especifica de migracao.
- O Controle Geral oficial esta pronto para proposta nova, mas o fluxo operacional completo ainda nao esta centralizado na API.

## Gate da Etapa 9

Status: aprovado para seguir com a proxima etapa tecnica.

Condicao: a Etapa 10 deve migrar a maquina de status/setores por modulo, com endpoints oficiais e testes, sem reativar escrita SQLite para propostas oficiais.
