# Central de Ações da Proposta (`ProposalActionCenter`)

Documento de referência da arquitetura consolidada na Fase 8. Descreve o
que a Central é, o que não é, e a regra a seguir ao adicionar uma nova ação
individual de proposta no futuro.

## 1. Regra oficial de UX

```text
PROPOSTA
↓
selecionar
↓
Ações
↓
ProposalActionCenter
↓
ações válidas naquele contexto
↓
handler especializado
↓
service/API oficial
```

Válida hoje em `Controle Geral`, `Produção`, `Almoxarifado`, `Expedição` e
`Galvanização` (proposta). Um único ponto de entrada,
`open_proposal_action_center(service, process_id, parent, area=None)`
(`app/ui/status_dialog.py`), constrói a instância real da Central
(`StatusDialog`, subclasse de `ProposalActionCenter` com o registry de
todas as áreas) para qualquer chamador — botão "Ações", atalho de tabela e
menu contextual em `ProcessPage`, e o botão "Ações" de `ProcessDetailDialog`
convergem todos para essa função. Nenhum chamador resolve área ou
instancia o diálogo por conta própria.

## 2. Cadeia de responsabilidades

```text
ProposalActionCenter
↓
ProposalActionContext
↓
ActionProvider
↓
ActionDescriptor
↓
ActionRegistry
↓
ActionHandler
↓
Service oficial
↓
API
```

### `ProposalActionCenter` (`app/ui/action_center/proposal_action_center.py`)

Apresentação + descoberta + roteamento de ações individuais da proposta.
Monta o cabeçalho (proposta, cliente, área, status), pede os descriptors ao
provider, renderiza os cards e encaminha o clique ao handler resolvido pelo
registry. Não calcula status, não decide transições, não substitui
services/API. `StatusDialog` (`app/ui/status_dialog.py`) é a única
instância real hoje — já vem com provider e registry pré-configurados para
todas as áreas migradas.

### `ProposalActionContext`

Dataclass imutável identificada por `proposal_id` (nunca linha de tabela,
posição visual ou `QModelIndex`). Carrega área, status atual, dados da
proposta, permissões e a lista de `ActionDescriptor` disponíveis.

### `ActionProvider`

Transforma as ações que o domínio já decidiu que existem (via
`service.process_actions()`) em `ActionDescriptor` de apresentação. Nunca
cria disponibilidade inexistente. `BackendActionProvider`
(`app/ui/action_center/provider.py`) é o provider genérico — funciona para
qualquer área sem ramificação própria. `GalvanizationActionProvider` o
envolve por composição e, somente para `GALVANIZACAO`, acrescenta um
descriptor de navegação puramente de UI (`OPEN_RELATED_GALVANIZATION_LOAD`)
que nunca veio do backend — ver seção 4.

### `ActionDescriptor`

Contrato: `id`, `label`, `description`, `icon`, `category`, `area`,
`order`, `status`, `group`, `raw`. Só dados de apresentação/roteamento —
nenhuma regra de negócio.

### `ActionRegistry` (`app/ui/action_center/registry.py`)

Relaciona `action_id` (com escopo opcional por `area`) ao handler
responsável. Só resolve — não conhece banco, API, widgets ou usuários, e
nunca deve passar a conhecer.

### `ActionHandler`

Recebe o contexto, encaminha para o fluxo oficial (chamada direta ao
service ou abertura de um diálogo especializado) e devolve um
`ActionResult` (`success`, `changed`, `refresh_required`,
`close_action_center`). Não decide elegibilidade, não calcula saldo, não
executa SQL.

### Service/API

Autoridade final de regra de negócio, permissão e persistência. A Central
nunca acessa banco diretamente.

## 3. Categorias visuais

`PRIMARY` (ação principal do estado atual), `NORMAL` (operação comum),
`ATTENTION` (merece atenção, ex. pausa) e `DESTRUCTIVE` (crítica, ex.
cancelamento). Puramente visuais — nunca usadas como permissão ou regra.

## 4. `LegacyActionHandler`

Camada de compatibilidade para ações ainda não migradas para um handler
dedicado (`app/ui/action_center/handlers/legacy.py`). Ao final da Fase 8,
seu único uso restante é `REGISTER_GALVANIZATION_RETURN`, mantido de
propósito: o fluxo oficial de retorno passou a ser
`Proposta → Ações → Abrir carga → Registrar retorno`
(`OPEN_RELATED_GALVANIZATION_LOAD` → `GalvanizationLoadDetailsDialog`), mas
a entrada direta pela proposta continua funcionando até essa navegação
estar comprovada em uso real — ver
`docs/architecture/FASE6_GALVANIZACAO_ACTION_CENTER.md` seções 5 e 21-25.
Não remover essa entrada por estética arquitetural.

## 5. O que NÃO pertence à Central

| Domínio | Onde vive |
|---|---|
| Ações em lote | `BatchSelectionController` / `BatchStatusDialog` (compartilham Action ID/service/validação com a Central quando fizer sentido, nunca estado visual ou seleção) |
| Carga de galvanização (editar, liberar, registrar retorno, histórico) | `GalvanizationLoadDetailsDialog` |
| Fiscal (emissão, cancelamento) | `app/ui/fiscal_page.py` e diálogos próprios |
| Parciais | `ProcessPage(area="PARCIAIS")` — índice de pendências; roteia para a área real da proposta, nunca ganha regra própria |
| Edição estrutural da proposta | `ProcessFormDialog` |
| Detalhes/histórico (consulta) | `ProcessDetailDialog` |
| Operações exclusivamente de item | telas de item (`production_items_page.py`, `galvanization_items_page.py`, etc.) |
| Remanejamento compensado | `EarlyRemanagementDeliveryDialog` |

## 6. Regra para desenvolvimentos futuros

Antes de criar um botão de ação novo em uma tabela de propostas, responda:

```text
Isto é uma ação individual da proposta?
```

**Se sim**: `ActionDescriptor` + `ActionHandler` + `ProposalActionCenter`.
Se a operação exigir entrada complexa, o handler abre um diálogo
especializado (`Central → Handler → Dialog especializado`) — a Central
nunca vira um mega-formulário, ela continua sendo só a porta de entrada.

**Se não** (pertence a carga, lote, Fiscal, item isolado ou edição
estrutural): implemente no contexto próprio dessa entidade, seguindo a
tabela da seção 5. Não crie um botão operacional isolado na tabela de
propostas fora da Central.

Nunca use `row index`/posição visual como identidade — sempre
`proposal_id`/`process_id` real.
