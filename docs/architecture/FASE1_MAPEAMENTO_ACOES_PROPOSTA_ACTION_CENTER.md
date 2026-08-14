# Fase 1 — Mapeamento das ações da proposta

Data da auditoria: 2026-08-12  
Escopo: inventário, comparação e planejamento.  
Alterações funcionais nesta fase: nenhuma.

## 1. Resumo executivo

Foram analisadas as áreas Controle Geral, Produção, Galvanização, Expedição,
Fiscal, Parciais e Almoxarifado, além de Relatórios Operacionais e detalhes de
carga.

Foram encontrados seis padrões principais de entrada:

1. `ACTION_CENTER` — `StatusDialog`, atualmente usado por proposta individual.
2. `MENU_DROPDOWN` — menu de ações em lote e menus de filtros/ações.
3. `CONTEXT_MENU` — menu contextual de propostas, cargas, Fiscal e relatórios.
4. `BOTAO_DIRETO` — botões de detalhes, editar, remanejamento, emissão e ações.
5. `DIALOG_ESPECIFICO` — diálogo próprio para produção, fluxo, pesos, cargas,
   retorno, Fiscal e correção administrativa.
6. `DUPLO_CLIQUE` — abertura de detalhes, distribuição de itens ou seleção em
   listas auxiliares.

Conclusão central: o padrão visual de Produção já existe, mas ainda não é
genérico. Ele é um `StatusDialog` orientado por área e contém ramificações
específicas para Produção, Expedição, Galvanização e correção administrativa.

Os services oficiais estão razoavelmente separados da UI. A maior parte da
migração futura poderá trocar a porta de entrada visual sem mudar o backend,
mas existem operações que pertencem a carga, item ou processo fiscal e não
devem ser forçadas para o Action Center de proposta.

## 2. Tela padrão atual

### Identidade real

- Arquivo: `app/ui/status_dialog.py`
- Classe: `StatusDialog`
- Abertura individual: `ProcessPage.change_status_for_id()` em
  `app/ui/process_page.py`
- Entrada contextual: `ProcessPage.open_context_menu()` adiciona
  `Acoes da proposta (N)` e chama `change_status()`.
- Identificador: `process_id: int`.
- Área: recebida explicitamente ou calculada por
  `service.current_location(base_process)`.
- Dados carregados: `service.get_process_dict()` e
  `service.get_process_area_dict()`.
- Ações: `service.process_actions(process_id, area)`.
- Status exibido: `service.status_for_area()` e
  `service.area_status_label()`.
- Permissão visual: `service.can_edit()`/`can_edit_area()` e `service.can_admin()`.
- Componentes: `StatusBadge`, `ActionCardButton`, `ModernButton`, `QTextEdit`,
  `ProductionPauseDialog`, `ManualStatusDialog` e diálogos especializados.
- Tamanho: mínimo de 720 px, largura inicial de 760 px, sem model/view de cards;
  os cards são criados dinamicamente em grade de duas colunas.
- Tema: usa `service.palette`, tokens de área, `with_alpha()` e `AppIcons`.
- Fechar: `reject()` no botão Fechar.

### A tela é reutilizável?

Classificação: **parcialmente reutilizável**.

O contêiner visual pode ser reaproveitado, mas a implementação está acoplada a
regras de navegação específicas:

- `REGISTER_PRODUCTION` abre `ProductionRegistrationDialog`.
- `DEFINE_ITEM_FLOW` abre `FlowReviewDialog` com origem `Producao`.
- `EDIT_ITEM_WEIGHTS` abre `ItemWeightDialog`.
- `MANAGE_LOAD` abre `GalvanizationLoadManagerDialog`.
- `REGISTER_GALVANIZATION_RETURN` abre `GalvanizationReturnDialog` ou gerenciador.
- `REGISTER_DELIVERY` abre `ItemSelectionDialog` de retirada.
- `PARADO` abre `ProductionPauseDialog`.
- correção administrativa abre `ManualStatusDialog`.

Portanto, a tela ainda mistura apresentação, roteamento de diálogos e decisões
de UX por domínio. A regra de negócio principal permanece nos services/API.

## 3. Inventário por área

### Controle Geral

Arquivo principal: `app/ui/process_page.py`, com `area="CONTROLE GERAL"`.

Entradas encontradas:

- botão direto `Detalhes` → `ProcessDetailDialog`;
- botão direto `Nova proposta` → `ProcessFormDialog`;
- botão direto `Editar` → `ProcessFormDialog`;
- botão `Ações` → `StatusDialog`;
- menu contextual `Ações da proposta (N)` → `StatusDialog`;
- menu contextual `Editar proposta` → `ProcessFormDialog`;
- menu contextual `Duplicar proposta` → fluxo de duplicação;
- duplo clique na tabela → detalhes da proposta;
- `Ações em lote` → `BatchStatusDialog`.

Ações de status calculadas em `BackendAdapter.process_actions()`:

- `AGUARDANDO_LIBERACAO` → `LIBERADO_PRODUCAO`;
- `AGUARDANDO_LIBERACAO` → `CANCELADA`;
- propostas concluídas não recebem novas ações de avanço.

Services/API envolvidos: `release_to_production()`, `cancel_process()`,
`update_status()` e endpoints oficiais de propostas. Permissões: edição do
Controle Geral (`can_edit_process()`/permissão de propostas).

Classificação futura: **candidato forte ao Action Center**, complexidade média,
risco médio por envolver liberação e cancelamento.

### Produção

Arquivos principais:

- `app/ui/process_page.py` — propostas;
- `app/ui/status_dialog.py` — ações individuais;
- `app/ui/production_registration_dialog.py` — mesa de registro;
- `app/ui/production_items_page.py` — itens em produção;
- `app/ui/flow_review_dialog.py` — fluxo dos itens;
- `app/ui/item_weight_dialog.py` — pesos.

Entrada individual atual:

```text
ProcessPage
→ change_status_for_id()
→ StatusDialog
→ service.process_actions()
→ card selecionado
→ diálogo/service oficial
```

Ações reais geradas por `BackendAdapter.process_actions()`:

- `DEFINE_ITEM_FLOW` — Definir fluxo dos itens;
- `STATUS/INICIADO` — Iniciar produção;
- `STATUS/INICIADO` — Retomar produção quando o status é `PARADO`;
- `STATUS/PARADO` — Pausar produção;
- `REGISTER_PRODUCTION` — Registrar produção;
- `EDIT_ITEM_WEIGHTS` — Informar pesos dos itens.

Status de proposta usados na disponibilidade:

- `NAO_INICIADO`;
- `LIBERADO_PRODUCAO`;
- `ITEM_PENDENTE_FABRICACAO`;
- `INICIADO`;
- `PARADO`;
- `FINALIZADO_PARCIAL`;
- `FINALIZADO`.

Registro de produção:

```text
StatusDialog._register_production()
→ ProductionRegistrationDialog
→ revalidação por proposal_items(pending_production=True)
→ next_status_options()
→ service.update_status()
→ official_proposal_storage.complete_production_items()
→ API /production/proposals/{id}/complete-items
```

A produção em lote usa a mesma mesa com várias propostas. A seleção persistente
das propostas ocorre em `BatchSelectionController`; a seleção dos itens é local
na `ProductionRegistrationDialog`.

Produção parcial/total é deduzida pela seleção: conjunto completo de itens aptos
gera `FINALIZADO`; subconjunto gera `FINALIZADO_PARCIAL`. Não existe, na UI/API
atual auditada, registro parcial de quantidade por unidade; a operação é por
`item_ids`.

Classificação futura: **já é o padrão visual de referência**. Não deve ser
migrado agora; deve fornecer o contrato visual para as demais áreas.

### Galvanização

A Galvanização tem dois contextos que não devem ser confundidos:

1. proposta na área de Galvanização;
2. carga de galvanização.

Proposta:

- `ProcessPage(area="GALVANIZACAO")` lista propostas;
- `StatusDialog` pode ser aberto por ação contextual;
- `BackendAdapter.process_actions()` pode retornar `MANAGE_LOAD` para
  `AGUARDANDO_ENVIO`/`DISPONIVEL_PARCIAL`;
- para `ENVIADO_GALVANIZACAO`/`RETORNOU_PARCIAL`, pode retornar
  `REGISTER_GALVANIZATION_RETURN` se houver carga ativa;
- `MANAGE_LOAD` → `GalvanizationLoadManagerDialog`;
- retorno → `GalvanizationReturnDialog` ou gerenciador.

Carga:

- `GalvanizationLoadsPage` e `GalvanizationLoadManagerDialog` usam menus
  contextuais e botões diretos;
- `GalvanizationLoadDetailsDialog` possui menu de `Editar carga`, `Liberar carga`
  e `Registrar retorno`;
- duplo clique abre detalhes da carga;
- `GalvanizationItemsPage` possui menu contextual de carga.

Essas ações são de **carga**, não de proposta. Podem abrir um futuro Action
Center de carga, mas não devem entrar automaticamente no Action Center da
proposta.

Services/API: candidatos de carga, criação/edição de carga, liberação e retorno
parcial em `BackendAdapter`, `ApiProposalStorage` e endpoints de galvanização.

Classificação: proposta → Action Center futuro, complexidade alta; carga →
manter separada, risco alto se misturada com produção/expedição.

### Expedição

Entradas encontradas:

- `ProcessPage(area="EXPEDICAO")` com `StatusDialog` individual;
- menu contextual de proposta;
- botão de remanejamento compensado (`EarlyRemanagementDeliveryDialog`);
- `ProductionItemsPage`/área correspondente para itens;
- menus e diálogos próprios de entrega/separação.

Ações calculadas em `process_actions()`:

- `STATUS/SEPARACAO_INICIADA` — Iniciar separação;
- `STATUS/SEPARADO` — Registrar separação;
- `REGISTER_DELIVERY` — Registrar retirada do cliente.

Status de proposta usados:

- `EM_SEPARACAO`;
- `AGUARDANDO_SEPARACAO_PARCIAL`;
- `SEPARACAO_INICIADA`;
- `SEPARADO`;
- `ENTREGUE_PARCIAL`;
- `ENTREGUE`.

Services/API:

- `start_expedition_separation()`;
- `separate_expedition_items()`;
- `deliver_expedition_items()`;
- remanejamento compensado em service próprio/API.

Entrega pode ser ação da proposta quando o contexto é a retirada daquela
proposta. Separação e remanejamento devem permanecer claramente ligados a itens
ou expedição. Complexidade média, risco alto por afetar entrega e fiscal.

### Fiscal

O Fiscal não usa `StatusDialog` de proposta como porta principal.

Entradas encontradas em `app/ui/fiscal_page.py`:

- tabela de acompanhamento com menu contextual;
- tabela de retiradas com menu contextual;
- botão/menu `Registrar emissão fiscal`;
- menu `Cancelar última emissão interna`;
- `Detalhes da Proposta` abre `FiscalProposalDetailDialog`;
- duplo clique abre detalhes conforme o comportamento da tabela;
- diálogos próprios para emissão e itens fiscais.

Disponibilidade:

- `can_register_fiscal_emission()`;
- status fiscal diferente de `NOTA_FISCAL_EMITIDA` e `FISCAL_CANCELADO`;
- cancelamento exige `can_cancel_fiscal_emission()` e emissão existente.

Status fiscais encontrados:

- `FALTA_EMITIR_NOTA_FISCAL`;
- `AGUARDANDO_NF`;
- `CP_EM_PROCESSAMENTO`;
- `NF_EM_PROCESSAMENTO`;
- `DISPONIVEL_PARA_EMISSAO`;
- `PENDENCIA_FISCAL_CRITICA`;
- `NOTA_FISCAL_PARCIAL`;
- `NOTA_FISCAL_EMITIDA`;
- `NF_RETIRADA_CLIENTE`;
- `FISCAL_CANCELADO`;
- `PENDENTE`, `PARCIAL`, `FATURADO`, `CANCELADO`.

Services/API:

- `register_fiscal_emission()`;
- `cancel_latest_fiscal_emission()`;
- `fiscal_emissions()`;
- `FiscalEmissionDialog` e API fiscal.

Conclusão: emissão/cancelamento são operações do **processo fiscal**, não uma
ação operacional genérica da proposta. O detalhe fiscal pode futuramente ser
acessível a partir de um Action Center somente como navegação contextual.

### Parciais e pendências

`ProcessPage(area="PARCIAIS")` lista propostas/pendências e utiliza os mesmos
componentes de detalhes/ações quando a linha representa uma proposta. Os
status de pendência são projeções operacionais, incluindo:

- `FINALIZADO_PARCIAL`;
- `ITEM_PENDENTE_FABRICACAO`;
- `DISPONIVEL_PARCIAL`;
- `RETORNOU_PARCIAL`;
- `AGUARDANDO_SEPARACAO_PARCIAL`;
- `ENTREGUE_PARCIAL`;
- `NOTA_FISCAL_PARCIAL`;
- `ALMOXARIFADO_ENTREGUE_PARCIAL`.

Esta área é mais um índice de pendências do que um domínio de execução. Deve
abrir a ação do domínio responsável após identificar a área real, sem duplicar
regras de status.

### Almoxarifado

`ProcessPage(area="ALMOXARIFADO")` utiliza `StatusDialog` individual e ações
calculadas por `next_status_options()`/`process_actions()`.

Ações reais:

- `EM_SEPARACAO` — Precisa de Almoxarifado ou confirmar que possui;
- `SEM_PARAFUSOS` — Não precisa de Almoxarifado;
- `SEPARADO` — Confirmar separação concluída;
- `ALMOXARIFADO_ENTREGUE` — Confirmar entrega;
- `ALMOXARIFADO_ENTREGUE_PARCIAL` — Registrar entrega parcial.

É um candidato de baixa/média complexidade para o Action Center, desde que os
status continuem sendo calculados pelo service.

## 4. Matriz de divergências

| Área | Ação | Entrada atual | Componente | Segue padrão de Produção? | Migrar futuramente? | Complexidade | Risco |
|---|---|---|---|---|---|---|---|
| Controle Geral | Liberar produção | Botão, menu contextual, `StatusDialog` | `ProcessPage` + `StatusDialog` | Parcial | Sim | Média | Médio |
| Controle Geral | Cancelar proposta | `StatusDialog`/menu | `StatusDialog` | Parcial | Sim | Média | Alto |
| Produção | Iniciar/pausar/retomar | `StatusDialog` cards | `StatusDialog` | Sim | Não agora | Baixa | Médio |
| Produção | Definir fluxo | Card → diálogo específico | `FlowReviewDialog` | Sim | Não agora | Baixa | Médio |
| Produção | Informar pesos | Card → diálogo específico | `ItemWeightDialog` | Sim | Não agora | Baixa | Médio |
| Produção | Registrar produção | Card → mesa única | `ProductionRegistrationDialog` | Sim | Não agora | Baixa | Alto |
| Galvanização | Adicionar proposta à carga | `StatusDialog` → gerenciador | `GalvanizationLoadManagerDialog` | Não | Sim, como ação de proposta | Alta | Alto |
| Galvanização | Liberar carga | Menu/botão da carga | `GalvanizationLoadDetailsDialog` | Não | Não para proposta | Média | Alto |
| Galvanização | Registrar retorno | Menu/botão da carga ou `StatusDialog` | `GalvanizationReturnDialog` | Não | Separar contexto de carga | Alta | Alto |
| Expedição | Iniciar separação | `StatusDialog`/menu | `ProcessPage` + `StatusDialog` | Parcial | Sim | Média | Alto |
| Expedição | Registrar separação | `StatusDialog`/itens | `StatusDialog` + service | Parcial | Sim | Média | Alto |
| Expedição | Retirada do cliente | Card → seleção de itens | `ItemSelectionDialog` delivery | Não | Sim, com cuidado | Média | Alto |
| Expedição | Remanejamento | Botão direto | `EarlyRemanagementDeliveryDialog` | Não | Não necessariamente | Alta | Alto |
| Fiscal | Registrar emissão | Menu contextual/botão | `FiscalEmissionDialog` | Não | Não como status genérico | Média | Alto |
| Fiscal | Cancelar emissão | Menu contextual | `FiscalPage` + API fiscal | Não | Não como status genérico | Média | Alto |
| Parciais | Abrir pendência | Detalhes/menu | `ProcessPage`/relatórios | Não uniforme | Sim, como roteamento | Média | Médio |
| Almoxarifado | Confirmar/entregar | `StatusDialog` cards | `StatusDialog` | Parcial | Sim | Baixa/Média | Alto |

## 5. Fluxo técnico das ações

### Ações genéricas de proposta

```text
ProcessPage.change_status_for_id()
→ StatusDialog(service, process_id, area)
→ BackendAdapter.process_actions()
→ BackendAdapter.update_status()
→ ApiProposalStorage / OfficialProposalStorage
→ proposals_client.py
→ API oficial
→ transação, histórico e auditoria no backend
```

### Produção

```text
StatusDialog card REGISTER_PRODUCTION
→ ProductionRegistrationDialog
→ proposal_items() / next_status_options()
→ revalidação
→ update_status(PRODUCAO, FINALIZADO ou FINALIZADO_PARCIAL, item_ids)
→ complete_production_items()
→ POST /production/proposals/{id}/complete-items
```

### Fluxo e pesos

```text
StatusDialog card
→ FlowReviewDialog / ItemWeightDialog
→ BackendAdapter.flow_review_data() ou update_item_weights()
→ ApiProposalStorage.update_production_item_flow()
  ou update_production_item_weights()
→ API oficial
```

### Galvanização

```text
StatusDialog MANAGE_LOAD
→ GalvanizationLoadManagerDialog
→ candidatos/carga
→ API de cargas
```

```text
menu de carga
→ GalvanizationLoadDetailsDialog / GalvanizationReturnDialog
→ release/return de carga
→ API de galvanização
```

### Fiscal

```text
FiscalPage menu
→ FiscalEmissionDialog
→ BackendAdapter.register_fiscal_emission()
→ ApiProposalStorage.register_fiscal_emission()
→ API fiscal
```

### Correção administrativa

```text
StatusDialog
→ ManualStatusDialog
→ administrative_correction_options()
→ preview_administrative_correction()
→ motivo + idempotency_key
→ administrative_correction()
→ API administrativa auditada
```

## 6. Regras duplicadas ou espalhadas na UI

1. A decisão de disponibilidade é calculada no backend em `process_actions()`,
   mas a UI também faz verificações específicas para pausar, cancelar, entrega,
   itens sem fluxo e produção pausada.
2. A produção possui disponibilidade em `process_actions()`, opções em
   `next_status_options()`, validação de lote em `validate_batch_selection()` e
   revalidação própria em `ProductionRegistrationDialog`.
3. A classificação `FINALIZADO` versus `FINALIZADO_PARCIAL` aparece na nova mesa,
   no `BatchStatusDialog` histórico e na camada `BackendAdapter`.
4. Expedição possui disponibilidade em `process_actions()`, seleção em
   `ItemSelectionDialog` e condições adicionais em `ProductionItemsPage`.
5. Galvanização mantém ações de proposta em `BackendAdapter`, mas ações de carga
   em múltiplos menus (`GalvanizationLoadDialog`, `GalvanizationLoadDetailsDialog`
   e `GalvanizationItemsPage`).
6. Fiscal decide a disponibilidade diretamente no menu de `FiscalPage`, usando
   permissões e status fiscal.
7. `StatusDialog` e `ProcessPage` são portas paralelas para a mesma família de
   ações individuais; o menu contextual também replica essa entrada.

Essas duplicações são inventário, não correções desta fase.

## 7. Telas candidatas à substituição futura

| Arquivo/classe | Uso atual | Candidato? |
|---|---|---|
| `app/ui/status_dialog.py::StatusDialog` | Padrão atual de ações individuais | Tornar genérico na Fase 2 |
| `app/ui/process_page.py::ProcessPage` | Botões/menu contextual por área | Fazer `Ações` abrir o centro |
| `app/ui/item_selection_dialog.py::ItemSelectionDialog` | Retirada e remanejamento de itens | Não remover; especializar por operação |
| `app/ui/galvanization_load_manager_dialog.py`* | Gestão de cargas | Não substituir por Action Center de proposta |
| `app/ui/galvanization_load_details_dialog.py` | Ações da carga | Criar, se necessário, Action Center de carga |
| `app/ui/early_remanagement_dialog.py` | Remanejamento compensado | Manter domínio específico |
| `app/ui/fiscal_page.py::FiscalEmissionDialog` | Emissão fiscal | Manter fiscal; apenas possível atalho contextual |
| `app/ui/production_registration_dialog.py` | Mesa única de produção | Reutilizar como operação especializada |
| `app/ui/flow_review_dialog.py` | Definição de fluxo | Reutilizar como operação especializada |
| `app/ui/item_weight_dialog.py` | Pesos | Reutilizar como operação especializada |

\* A classe está definida em `app/ui/galvanization_load_dialog.py` como
`GalvanizationLoadManagerDialog`.

## 8. Operações que devem permanecer separadas

- gestão, liberação e retorno de **carga de galvanização**;
- emissão e cancelamento de **nota/processo fiscal**;
- remanejamento compensado entre propostas;
- manutenção de usuários e permissões;
- configurações globais e integração Nomus;
- edição estrutural da proposta;
- ações exclusivas de item quando não representam uma ação da proposta;
- histórico e relatórios somente leitura.

Essas operações podem ser acessadas por navegação contextual, mas não devem
ter suas regras absorvidas pelo Action Center.

## 9. Correção administrativa e observação

Correção administrativa já está integrada ao `StatusDialog` para qualquer área
em que o usuário possua `can_admin()`.

O fluxo atual é seguro para futura reutilização porque:

- opções são buscadas pela API;
- há versão esperada;
- existe prévia antes da gravação;
- exige justificativa;
- usa `idempotency_key`;
- chama API administrativa específica;
- a auditoria é responsabilidade do backend.

O campo `Observacao (opcional)` está no `StatusDialog` e é repassado para
`update_status()` ou para os diálogos especializados. A semântica varia por
ação: pausa exige motivo; cancelamento exige observação; algumas ações não
usam o texto. Não há evidência nesta fase de que o campo seja uma entidade
global separada da operação; ele é payload de cada chamada.

## 10. Ícones, cards, responsividade e temas

- Cards: `ActionCardButton` em `app/ui/components/action_card_button.py`.
- Criação: `StatusDialog._build()` recebe título, descrição, ícone, tipo e
  paleta; callback chama `run_action()`.
- Ícones: `AppIcons`/registro oficial, com alguns overrides visuais em
  `status_dialog.py`.
- Cores: tokens da paleta e cores por área.
- Responsividade: grade de duas colunas, mínimo de 720 px, altura baseada no
  conteúdo; não existe scroll específico do grid.
- Tema: `style_dialog_from_parent()`, `service.palette`, `StatusBadge` e tokens.
- Ponto de atenção futuro: quantidade elevada de ações pode exigir scroll ou
  `QScrollArea`; a tela atual não foi desenhada para dezenas de cards.

## 11. Ações em lote versus ações individuais

São fluxos distintos.

Individual:

```text
linha selecionada
→ Ações da proposta
→ StatusDialog
```

Lote:

```text
ProcessPage
→ BatchSelectionController
→ BatchStatusDialog ou FlowReviewDialog
```

O lote reutiliza `BackendAdapter.validate_batch_selection()`,
`next_status_options()`, `process_actions()` e `update_status()`, mas possui
revalidação e composição próprias. O Action Center futuro não deve misturar o
estado temporário de seleção em lote com a ação individual.

## 12. Testes que protegem uma futura migração

Testes relevantes encontrados:

- `tests/test_status_dialog.py` — cards primários, ações disponíveis e pausa;
- `tests/test_process_batch_selection.py` — seleção persistente e integração
  das ações em lote;
- `tests/test_batch_selection_validation.py` — compatibilidade de ações;
- `tests/test_production_registration_dialog.py` — agrupamento, tri-state,
  busca, revalidação e ausência de gravação antecipada;
- `tests/test_backend_official_proposals.py` — actions/status/services oficiais;
- `tests/test_api_proposal_storage.py` — mapeamento de itens e chamadas oficiais;
- `tests/test_desktop_api_client.py` — rotas de produção, fluxo, pesos e
  complete-items;
- `tests/test_flow_review_state.py` e `tests/test_flow_review_dialog.py` — fluxo;
- `tests/test_galvanization_load_manager_dialog.py` e
  `tests/test_galvanization_load_details_dialog.py` — cargas/retorno;
- `tests/test_api_user_permission_mapping.py` — permissões API;
- `tests/test_administrative_correction_rules.py` — regras administrativas;
- `tests/test_status_icons.py` e `tests/test_status_badge_colors.py` — estados
  visuais.

## 13. Contrato futuro do Action Center

Contrato conceitual recomendado:

```python
ProposalActionContext(
    proposal_id: int,
    area: str,
    current_status: str,
    proposal: dict,
    permissions: dict,
    available_actions: list[ActionDescriptor],
)
```

`ActionDescriptor` deveria conter apenas dados de apresentação/roteamento:

```python
ActionDescriptor(
    id: str,
    label: str,
    description: str,
    icon: str,
    kind: str,
    area: str,
    status: str | None,
)
```

O futuro Action Center deve:

- exibir cabeçalho, área, status e ações;
- receber observação;
- respeitar disponibilidade fornecida pelo domínio;
- encaminhar para o handler oficial;
- manter navegação e aparência uniforme.

Não deve:

- calcular transição de status;
- executar SQL;
- duplicar RBAC;
- decidir regras de item, peso ou carga;
- substituir transações, histórico ou auditoria.

Arquitetura futura:

```text
ProcessPage
→ ProposalActionCenter
→ ActionProvider/Registry por domínio
→ ActionDescriptor
→ handler especializado
→ BackendAdapter
→ ApiProposalStorage / API oficial
```

O Registry não deve ser criado nesta Fase 1.

## 14. Ordem recomendada das próximas fases

1. **Fase 2 — extrair contrato visual**, sem mudar regras: separar o modelo de
   apresentação do `StatusDialog` e criar testes de contrato.
2. **Fase 3 — migrar Controle Geral**, começando por detalhes/liberação e
   deixando cancelamento sob confirmação específica.
3. **Fase 4 — consolidar Produção**, transformando o `StatusDialog` atual em
   implementação do componente genérico, sem mudar seus handlers.
4. **Fase 5 — Almoxarifado**, por ter ações de proposta relativamente diretas.
5. **Fase 6 — Expedição**, após separar claramente proposta, item, entrega e
   remanejamento.
6. **Fase 7 — Galvanização de proposta**, mantendo cargas em tela própria.
7. **Fase 8 — atalhos contextuais do Fiscal**, sem mover emissão/cancelamento
   para o Action Center operacional.
8. **Fase 9 — desativar entradas duplicadas**, somente após testes de regressão,
   telemetria/logs e validação operacional.

## 15. Respostas objetivas

1. Padrões encontrados: **seis** padrões principais.
2. Eles aparecem em Controle Geral, Produção, Galvanização, Expedição, Fiscal,
   Parciais, Almoxarifado, cargas e relatórios.
3. A referência atual é `StatusDialog` em Produção, com a nova
   `ProductionRegistrationDialog` para registro.
4. Podem migrar sem backend novo: Controle Geral, Almoxarifado e parte da
   Expedição, desde que handlers oficiais sejam preservados.
5. Regras mais misturadas à UI: emissão Fiscal, seleção/entrega, pausa,
   remanejamento e roteamento de carga.
6. Candidatos: `StatusDialog` como base visual, menus de `ProcessPage` e parte
   dos detalhes de proposta.
7. Menus/botões de `ProcessPage` que abrem `StatusDialog` podem futuramente
   tornar-se apenas a entrada do Action Center.
8. Não devem entrar: ações de carga, Fiscal, usuários/configuração, relatórios
   somente leitura e operações exclusivamente de item.

## 16. Limitações da Fase 1

Esta auditoria não alterou código funcional, banco, services, permissões,
status ou testes. A classificação de “não utilizado” foi evitada quando uma
referência dinâmica ou fluxo secundário impedia prova conclusiva; esses casos
foram classificados como ativos ou candidatos, nunca removidos.
