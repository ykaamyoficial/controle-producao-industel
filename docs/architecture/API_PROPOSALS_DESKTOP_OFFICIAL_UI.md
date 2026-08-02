# Etapa 8 - Tela oficial de propostas via API/PostgreSQL

## Fluxo anterior

A tela oficial `ProcessFormDialog` preenchia dados manuais, PDF Nomus e Nomus API, mas ao salvar chamava `BackendService.save_process`, que gravava pelo repository SQLite.

Itens eram enviados no mesmo dicionario legado e persistidos em `processos`/`proposta_itens`.

## Fluxo novo

Com `postgresql_official_proposals_enabled=true`, a tela passa a usar:

```text
ProcessFormDialog -> BackendService -> OfficialProposalApiStorage -> ProposalsApiClient -> API -> PostgreSQL
```

Sem fallback para SQLite.

## Arquivos alterados

- `app/ui/process_form_dialog.py`
- `app/ui/process_page.py`
- `app/services/backend_adapter.py`
- `app/services/api_proposal_storage.py`
- `app/integrations/api/client.py`
- `app/integrations/api/exceptions.py`
- `tests/test_process_form_official_api.py`
- `tests/test_api_proposal_storage.py`
- `tests/test_desktop_api_client.py`

## Operacoes disponiveis

- Criar proposta oficial com itens.
- Editar dados permitidos da proposta.
- Adicionar item.
- Editar item.
- Excluir logicamente item removido da lista.
- Cancelar proposta oficial pelo endpoint da API.
- Liberar proposta para `PRODUCAO / LIBERADO_PRODUCAO`.
- Listar propostas oficiais do Controle Geral pela API.
- Reabrir proposta oficial pela API.

## Tratamento de erros

O client HTTP agora preserva erros de negocio em `ApiBusinessError`, incluindo codigo oficial.

Mensagens tratadas para usuario final:

- `PROPOSAL_VERSION_CONFLICT`: orienta recarregar dados oficiais.
- `PROPOSAL_NUMBER_ALREADY_EXISTS`: informa duplicidade de numero.
- conexao/timeout: informa indisponibilidade do servidor e mantem dados na tela.
- `401`, `403`, `422`: mensagens sem traceback nem payload bruto.

## Concorrencia

A tela guarda a versao da proposta e dos itens carregados pela API.

Na edicao, o adaptador recarrega a proposta oficial antes de salvar e envia as versoes esperadas nos endpoints de update.

Nao ha merge automatico nesta etapa.

## Flag

`postgresql_official_proposals_enabled=false`:

- comportamento legado permanece disponivel para rollback controlado.

`postgresql_official_proposals_enabled=true`:

- `ProcessFormDialog` salva pela API;
- `BackendService.save_process` nao chama `repo.save_process`;
- `proposal_items` da tela vem da API;
- listagem do Controle Geral vem da API;
- guard SQLite continua ativo para bloquear escritas legadas acidentais.

## Importacoes

PDF Nomus e Nomus API continuam no mesmo fluxo:

```text
Fonte -> conferencia humana -> formulario -> salvar pela API
```

A importacao continua sem gravar diretamente no banco.

Campos financeiros nao sao transferidos para o payload oficial.

## Sem fallback SQLite

Quando a API falha, a tela mostra erro e mantem os dados preenchidos.

Nao cria proposta local, nao grava arquivo temporario e nao chama repository SQLite.

## Dependencias ainda legadas

- Produção, Galvanização, Expedição, Almoxarifado, Fiscal, cargas e relatorios ainda usam SQLite.
- A listagem oficial foi migrada somente para Controle Geral.
- Historico visual detalhado ainda depende do fluxo legado fora do cadastro.
- Login principal do desktop ainda e local; para a API e necessario existir sessao/token da API configurado.

## Testes executados

- `tests/test_process_form_official_api.py`
- `tests/test_api_proposal_storage.py`
- `tests/test_nomus_form_transfer.py`
- `tests/test_nomus_api_form_integration.py`
- `tests/test_desktop_api_client.py`
- `tests/test_official_proposal_storage_guard.py`

## Estabilizacao da Etapa 9

Validado em:

```text
docs/architecture/API_PROPOSALS_STAGE9_HOMOLOGATION.md
```

Resultado da suite desktop completa:

```text
425 passed, 3 skipped
```

Testes adicionais confirmam que os caminhos oficiais de cadastro, leitura de itens e listagem do Controle Geral usam `OfficialProposalApiStorage`, sem chamada ao repository SQLite legado quando a flag `postgresql_official_proposals_enabled` esta ativa.

## Proximos passos

Migrar a maquina completa de status/setores e substituir as acoes de detalhes, historico, Producao, Galvanizacao, Expedição, Almoxarifado e Fiscal por endpoints oficiais.
