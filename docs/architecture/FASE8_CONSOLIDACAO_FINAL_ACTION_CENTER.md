# Fase 8 — Consolidação Final da Central de Ações

Data: 2026-08-13
Escopo: auditoria final, consolidação da abertura, remoção de duplicidade
comprovada, testes de contrato entre áreas e documentação. Fase final do
projeto de padronização das ações individuais da proposta. Nenhuma regra
operacional, status, permissão, migration ou domínio (Parciais, Fiscal,
Carga, Lote) foi alterado.

## 1. Auditoria inicial (antes de qualquer remoção)

1. **Pontos que abrem `ProposalActionCenter`**: um único ponto real —
   `StatusDialog` (`app/ui/status_dialog.py`), subclasse de
   `ProposalActionCenter` com provider/registry pré-configurados para as
   cinco áreas migradas.
2. **Pontos que ainda instanciavam `StatusDialog` diretamente**: dois —
   `ProcessPage.change_status_for_id()` (`app/ui/process_page.py:538`) e
   `ProcessDetailDialog.change_status()` (`app/ui/process_detail_dialog.py:313`).
   Ambos resolviam a área preferida contra `service.visible_areas()` **de
   forma duplicada** antes de instanciar o diálogo — a única duplicação
   comprovada de código de abertura encontrada nesta auditoria (nenhuma
   regra de negócio duplicada, só a resolução de área). Consolidada nesta
   fase (seção 2).
3. **Usos de `LegacyActionHandler`**: um — `REGISTER_GALVANIZATION_RETURN`
   (`app/ui/status_dialog.py`), decisão da Fase 6 reafirmada aqui (seção 4).
4. **Menus contextuais relacionados a proposta**: um, em
   `ProcessPage.open_context_menu()`. Contém apenas: `Ver detalhes da
   proposta`, `Editar proposta` (Controle Geral, estrutural — fora da
   Central por design, seção 58), `Ações da proposta (N)` (mesma
   `change_status()` do botão "Ações" — não é uma segunda Central),
   `Ações em lote...` (mecanismo separado), `Definir fluxo em lote (N)`
   (Produção, lote), `Histórico da proposta` (mesmo `show_details()`),
   `Exportar seleção Excel/PDF` (utilitário) e `Duplicar proposta`
   (Controle Geral, criação). Nenhum item do menu executa uma transição de
   status diretamente — todos navegam ou abrem a Central.
5. **Botões diretos de mudança de status**: nenhum encontrado fora da
   Central. `grep` por `.update_status(` em `app/ui/` mostrou apenas
   chamadas dentro dos handlers do Action Center, de
   `BatchStatusDialog` (lote, esperado) e de `ProductionRegistrationDialog`/
   `production_actions.py` (os diálogos especializados abertos pelo próprio
   handler de produção — fluxo oficial documentado, não um atalho paralelo).
6. **Callbacks que executam ação de proposta diretamente**: nenhum
   encontrado fora do padrão handler → service.
7. **Diálogos antigos**: nenhum diálogo monolítico pré-Action-Center
   sobrevivendo fora do padrão atual — as Fases 2-6 já haviam extinto essa
   camada.
8. **Handlers atuais**: `RegisterProductionHandler`, `DefineItemFlowHandler`,
   `EditItemWeightsHandler`, `ProductionStatusHandler`,
   `ControlGeneralStatusHandler`, `WarehouseStatusHandler`,
   `ExpeditionStatusHandler`, `RegisterDeliveryHandler`,
   `ManageGalvanizationLoadHandler`, `OpenRelatedGalvanizationLoadHandler`,
   `LegacyActionHandler` (só para `REGISTER_GALVANIZATION_RETURN`).
9. **Providers**: `BackendActionProvider` (genérico) e
   `GalvanizationActionProvider` (envolve o genérico por composição, só
   para `GALVANIZACAO`). Nenhum provider por ação, nenhum provider gigante
   com ramificação por área.
10. **Action IDs**: `STATUS`, `DEFINE_ITEM_FLOW`, `EDIT_ITEM_WEIGHTS`,
    `REGISTER_PRODUCTION`, `REGISTER_DELIVERY`, `MANAGE_LOAD`,
    `REGISTER_GALVANIZATION_RETURN`, `OPEN_RELATED_GALVANIZATION_LOAD`
    (UI-only, navegação). Nenhum par semanticamente duplicado (ex.:
    `REGISTER_PRODUCTION` vs. `PRODUCTION_REGISTER`) — nada para consolidar.
11. **Descriptors**: contrato único em `app/ui/action_center/descriptor.py`,
    sem campos adicionados nesta fase (nenhuma necessidade real).
12. **Caminhos de ações em lote**: `BatchSelectionController` +
    `BatchStatusDialog` + `FlowReviewDialog` (lote), inteiramente separados
    da Central individual — confirmado que não compartilham estado visual,
    só Action ID/service/validação quando aplicável.
13. **Pontos de duplo clique**: `ProcessPage._handle_table_double_click()`
    → sempre `show_details()` → `ProcessDetailDialog`. Nunca executa ação.
14. **Pontos de abertura de detalhes**: `ProcessDetailDialog`, aberto por
    duplo clique, "Ver detalhes da proposta" e "Histórico da proposta".
15. **Exceções justificadas**: `REGISTER_GALVANIZATION_RETURN` em
    `LegacyActionHandler` (seção 4); `Editar proposta`/`Duplicar proposta`
    fora da Central (edição estrutural, seção 58); `Definir fluxo em lote`/
    `Ações em lote` fora da Central (lote, seção 55).

## 2. Matriz de consolidação

| Área | Ação | Entrada atual | Entrada oficial | Legado ainda usado? | Pode remover? |
|---|---|---|---|---|---|
| Todas as 5 áreas | Ações individuais | Botão "Ações", menu contextual "Ações da proposta (N)", atalho de tabela, botão "Ações" de `ProcessDetailDialog` | `open_proposal_action_center()` → `StatusDialog` (`ProposalActionCenter`) | Não | — (já era a entrada oficial; consolidada a resolução de área duplicada) |
| Controle Geral | Liberar produção / Cancelar | Central | Central | Não | — |
| Produção | Iniciar/Pausar/Retomar/Fluxo/Pesos/Registrar | Central | Central | Não | — |
| Almoxarifado | 5 transições | Central | Central | Não | — |
| Expedição | Separação/Retirada | Central | Central | Não | — |
| Galvanização | `MANAGE_LOAD` | Central (`ManageGalvanizationLoadHandler`, Fase 6) | Central | Não | — |
| Galvanização | `REGISTER_GALVANIZATION_RETURN` | Central (`LegacyActionHandler`) | Central (mesmo handler) | **Sim, deliberado** | Não — aguardando comprovação de uso real da navegação `OPEN_RELATED_GALVANIZATION_LOAD` (Fase 6) |
| Galvanização | `OPEN_RELATED_GALVANIZATION_LOAD` | Central (Fase 6) | Central | Não | — |
| Qualquer área | Detalhes/histórico | Duplo clique, menu | `ProcessDetailDialog` | N/A | Não deve migrar (seção 57) |
| Controle Geral | Editar/Duplicar proposta | Menu contextual | `ProcessFormDialog` | N/A | Não deve migrar (seção 58) |
| Produção | Ações em lote | Botão/menu de lote | `BatchStatusDialog`/`BatchSelectionController` | N/A | Não deve migrar (seção 55) |
| Galvanização (carga) | Editar/Liberar/Retorno/Histórico da carga | Menu próprio da carga | `GalvanizationLoadDetailsDialog` | N/A | Não deve migrar (seção 59) |
| Parciais | Índice de pendências | `ProcessPage` genérico, sem branch própria | Inalterado | N/A | Fora de escopo — não tocar |

## 3. Consolidação implementada

### 3.1 Arquivos alterados

- `app/ui/status_dialog.py`: adicionada `open_proposal_action_center(service,
  process_id, parent, area=None)` — ponto único de abertura. Resolve
  `area` contra `service.visible_areas()` (mesma checagem que existia
  duplicada nos dois chamadores); quando `area` não é fornecida ou não é
  visível, delega o auto-detect para o próprio `ProposalActionCenter`
  (`current_location()`), comportamento que já existia e não mudou.
- `app/ui/process_page.py`: `change_status_for_id()` passa a chamar
  `open_proposal_action_center(self.service, process_id, self,
  area=self.area)` em vez de resolver a área e instanciar `StatusDialog`
  diretamente. Nenhuma outra linha de `change_status_for_id`/`change_status`
  foi alterada (a checagem de permissão `_can_edit_area` antes de abrir
  continua exatamente igual).
- `app/ui/process_detail_dialog.py`: `change_status()` passa a chamar
  `open_proposal_action_center(self.service, self.process_id, self)` (sem
  área preferida, mesma semântica de auto-detect que a chamada manual a
  `current_location()` já produzia).

### 3.2 Arquivos criados

- `tests/test_action_center_consolidation.py` — 13 testes (seção 5).
- `docs/proposal_action_center.md` — documentação oficial da arquitetura
  (seção 6).
- `docs/architecture/FASE8_CONSOLIDACAO_FINAL_ACTION_CENTER.md` — este
  relatório.

### 3.3 Classes/handlers/registry/providers

Nenhuma classe removida — a auditoria (seção 1) não encontrou código morto
comprovado: as Fases 2-6 já haviam eliminado diálogos monolíticos antigos e
callbacks paralelos. Nenhum handler novo foi necessário (a única
duplicação real era a resolução de área na camada de abertura, não uma
regra de ação). Registry e providers permanecem exatamente como ao final
da Fase 6 (listados na seção 1, itens 8-9) — revisados e confirmados
corretos, sem alteração.

## 4. `StatusDialog` — decisão final

- **Consumidores antes**: `ProcessPage` e `ProcessDetailDialog`, cada um
  resolvendo a área preferida por conta própria antes de instanciar.
- **Consumidores depois**: os mesmos dois, agora via
  `open_proposal_action_center()` — nenhuma lógica de resolução de área
  fora dessa função.
- **Decisão final**: **mantido**, classificado como **necessário** (não
  migrável, não legado). `StatusDialog` não é um wrapper vazio: é a única
  configuração real de `ProviderActionCenter` com o `ActionRegistry`
  completo das cinco áreas migradas (`_build_registry()`). Removê-lo
  significaria inlinear esse registry em cada chamador — estritamente
  pior. Não possui lógica de negócio duplicada, não possui handlers
  paralelos aos do registry, e está agora documentado como tal tanto no
  docstring da classe quanto em `docs/proposal_action_center.md`.

## 5. `LegacyActionHandler` — auditoria

| Action ID | Área | Motivo do legado | Handler moderno existe? | Pode migrar agora? |
|---|---|---|---|---|
| `REGISTER_GALVANIZATION_RETURN` | GALVANIZACAO | Fluxo preferencial passou a ser navegar até a carga (Fase 6); a entrada direta pela proposta é compatibilidade temporária até essa navegação estar comprovada em produção | Não (por decisão, não por lacuna técnica) | Não — manter até telemetria/uso real confirmar que a navegação supre a necessidade |

- **Usos antes desta fase**: 1.
- **Usos depois desta fase**: 1 (inalterado).
- **Ações migradas nesta fase**: 0 (nenhuma ação nova ficou apta a migrar
  desde o fim da Fase 6 — `MANAGE_LOAD` já havia migrado lá).
- **Cenário atingido**: "aceitável" (poucos usos, documentados), não o
  ideal de zero usos — por decisão de segurança operacional explícita nas
  Fases 6 e 8 (seção 15: "se alguma ação ainda depender legitimamente do
  handler legado, manter, documentar").

## 6. UX

- **Clique simples**: seleciona a linha via o modelo de seleção nativo do
  `QTableView` — não existe handler de aplicação para "clique simples" em
  modo normal (`_handle_table_click` só age em modo de seleção em lote).
  Confirmado por teste que nenhuma ação/diálogo abre com um clique simples.
- **Duplo clique**: `_handle_table_double_click()` → sempre
  `show_details()` → `ProcessDetailDialog`. Nunca executa transição.
  Confirmado por teste.
- **Botão "Ações"**: abre a Central via `open_proposal_action_center()`.
- **Menu contextual "Ações da proposta (N)"**: chama o mesmo
  `change_status()` que o botão — mesma Central, não uma segunda
  implementação. Guardado por teste estrutural que falha se algum dos dois
  passar a referenciar um método diferente.
- **Ações em lote**: inalteradas, mecanismo `BatchSelectionController`/
  `BatchStatusDialog` inteiramente separado.

## 7. Escopo

- **Parciais**: nenhum arquivo específico de Parciais existe (a área usa o
  `ProcessPage` genérico sem branch própria) e nenhuma linha de
  comportamento específico de Parciais foi tocada. O único ponto de
  contato é que `change_status_for_id()` — compartilhado por todas as
  áreas, inclusive Parciais — foi refatorado; o comportamento para
  Parciais é **comprovadamente idêntico** porque `"PARCIAIS"` nunca esteve
  em `service.visible_areas()` antes ou depois (confirmado em
  `OFFICIAL_AREAS` de `backend_adapter.py`, que nunca incluiu essa chave),
  então a área sempre foi resolvida por auto-detect
  (`current_location()`) tanto antes quanto depois desta fase — testado
  explicitamente em
  `test_preferred_area_outside_visible_areas_falls_back_to_auto_detect`.
- **Fiscal**: nenhum arquivo do módulo Fiscal foi tocado.
- **Carga de Galvanização**: `GalvanizationLoadDetailsDialog`,
  `GalvanizationLoadManagerDialog` e `GalvanizationReturnDialog`
  permanecem exclusivamente no contexto da carga; a fronteira criada na
  Fase 6 não foi desfeita.
- **Ações em lote**: `BatchSelectionController`/`BatchStatusDialog`
  inalterados.

## 8. Banco/API

- Migrations criadas: 0.
- Endpoints criados: 0.
- Services alterados: 0.
- SQL na UI: nenhum (confirmado — nenhuma alteração tocou services/API).

## 9. Testes

- Arquivo novo: `tests/test_action_center_consolidation.py` (13 testes):
  contrato entre as 5 áreas (identidade, action IDs com handler resolvido,
  erro controlado para ID desconhecido, zero escrita ao abrir/fechar em
  cada área), `open_proposal_action_center()` (área preferida visível,
  área preferida não-visível cai para auto-detect — regressão de Parciais
  — e ausência de área), delegação única (`ProcessPage`/
  `ProcessDetailDialog` chamam a mesma função, guarda estrutural
  botão/menu), e comportamento de clique/duplo-clique.
- Suíte completa (`pytest tests/`): **1007 passed, 2 skipped, 2 failed**
  (994 + 13 novos = 1007; nenhum teste pré-existente quebrou).
- Falhas remanescentes (pré-existentes, não relacionadas a esta fase):
  `tests/test_notification_bell.py::NotificationBellShakeTests::test_badge_text_hides_at_zero_and_caps_at_99_plus`
  e `tests/test_title_bar.py::TitleBarTests::test_chat_unread_badge_hidden_when_zero`
  — já documentadas e reproduzidas independentemente das mudanças desta
  fase em `docs/architecture/FASE6_GALVANIZACAO_ACTION_CENTER.md` (seção
  8); reconfirmadas aqui com o mesmo resultado, sem qualquer relação com
  `ProcessPage`, `ProcessDetailDialog` ou `status_dialog.py`.

## 10. Documentação

- Criada: `docs/proposal_action_center.md` — responsabilidades de cada
  camada (`ProposalActionCenter`, `ProposalActionContext`,
  `ActionProvider`, `ActionRegistry`, `ActionHandler`, Service/API), o que
  não pertence à Central (lote, carga, Fiscal, Parciais, edição
  estrutural, detalhes, operações de item) e a regra oficial para
  desenvolvimentos futuros ("Isto é uma ação individual da proposta?").
- Regra oficial registrada para novas ações: se for uma ação individual da
  proposta, sempre `ActionDescriptor` + `ActionHandler` +
  `ProposalActionCenter` (com diálogo especializado quando a entrada for
  complexa); caso contrário, implementar no contexto próprio da entidade
  responsável (carga, lote, Fiscal, item, edição estrutural) — nunca um
  botão operacional isolado na tabela de propostas.

## 11. Critérios de aceitação

Todos os itens das seções 91-93 do prompt técnico foram verificados:
clique simples seleciona; duplo clique abre detalhes; botão "Ações" e menu
contextual abrem a mesma Central; lote permanece separado; padrão visual
único (`ActionCardButton`, sem subclasses por área); estados vazios
consistentes; existe uma única infraestrutura de Central (sem cópia por
área); `LegacyActionHandler` reduzido a um uso documentado;
`StatusDialog` tem destino definido (mantido, justificado); nenhum código
morto comprovado sobrou para remover; Parciais/Fiscal/Carga/Lote
intocados; zero migrations; zero regra operacional nova; regressão zero
(1007 passed, as únicas 2 falhas são pré-existentes e documentadas).
