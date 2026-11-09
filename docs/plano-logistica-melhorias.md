# Plano: melhorias na aba Logística

Especificação aprovada: [spec-logistica-melhorias.md](spec-logistica-melhorias.md) (decisões L1 a L10, 2026-11-09).

**Objetivo.** Igualar a Logística à Inspeção (janela "Registrar andamento" com data escolhida), deixar entrar no LOG pedido ainda em inspeção, gerar relatório PDF do LOG e da Carga, exportar a lista em XLSX e consertar o painel e o contador de dias.

**Arquitetura.** A API (`api/app/modules/logistics/`) guarda as regras novas: a inclusão sem DOC BIM passa a pedir confirmação em vez de recusar, e cada andamento grava a data real. O Desktop (`app/ui/logistics_*.py`) ganha a janela de andamento, as etiquetas de inspeção, os filtros, a exportação e os PDFs. O PDF usa `QPrinter` em formato PDF, como `app/ui/process_page.py`. O XLSX usa `openpyxl`.

**Restrições globais (valem para todas as tarefas).**
- Só a API de dev (porta 8001). Nada na oficial (8000) sem autorização explícita do Henrique.
- O sistema nunca trava: toda regra nova de data ou de inspeção só avisa, com "Marcar mesmo assim" / "Incluir mesmo assim". Único impedimento: data que não existe (31/02).
- O Desktop nunca fala com o banco.
- Migration nova exige entrada em `api/alembic/migration_risk_registry.json` (skill `migration-check`).
- Telas seguem a skill `qt-industrial-ui`: um botão primário por tela, cor só por token.
- Branch nova `logistica-melhorias`, saindo de `inspecao-datas`. Commit local por subsistema ao fim de cada tarefa (skill `commit-by-subsystem`), sem push. Os arquivos `.claude/agents/*` modificados e `output/`, `nao_existe.json` e o atalho `.lnk` não entram nos commits.
- Teste Qt travado costuma ser `QMessageBox` real de um Fake incompleto. Rodar com o timeout do `pytest.ini`.

## Equipe e modelos

Regra do Henrique (2026-11-08): sonnet coordena e revisa, haiku faz o trabalho, opus só escreve os prompts dos agentes. Todo agente é chamado com `model` fixado.

| Papel | Agente | Modelo | Faz |
|---|---|---|---|
| Coordenador | `maestro` | sonnet | Reparte as tarefas, passa a regra "só dev 8001" em cada prompt, consolida. Não escreve código. |
| Redator de prompts | chamada direta, uma vez | opus | Escreve os prompts curtos dos implementadores a partir deste plano. |
| Backend | `feature-backend-implementer` | haiku | T1, T2, T3 e T4 (API, migration, testes de API). |
| Desktop, diálogos | `feature-frontend-implementer` (A) | haiku | T5, T6, T7 e T8 (cliente, serviço, `logistics_dialogs.py`, janela nova). |
| Desktop, lista e relatórios | `feature-frontend-implementer` (B) | haiku | T9 e T10 (`logistics_page.py`, XLSX, PDFs). |
| Testes travados | `test-doctor` | haiku | Só se a suíte Desktop travar ou estourar o timeout. |
| Auditor | `general-purpose` (somente leitura, outro agente que não escreveu o código) | sonnet | Audita o fim de cada bloco: B1 (T1 a T4), B2 (T5 a T8), B3 (T9 e T10). Relatório curto, achados por gravidade. |

Aviso de risco: T1 e T2 mexem em regra de negócio e migration, e o implementador é haiku. Por isso o auditor sonnet olha o bloco B1 antes de o Desktop começar. Se o auditor achar falha de gravidade ALTA em T1 ou T2, refazer aquela tarefa com sonnet.

## Ordem

```
T0 -> B1: T1 -> T2 -> T3 -> T4 -> auditoria B1
        -> B2 (A): T5 -> T6 -> T7 -> T8 -> auditoria B2
        -> B3 (B, em paralelo com B2 depois da T5): T9 -> T10 -> auditoria B3
        -> T11 (fechamento)
```

T5 vem antes porque cliente e serviço do Desktop são a base dos dois blocos. A e B não editam o mesmo arquivo: A é dono de `logistics_dialogs.py`, B é dono de `logistics_page.py` e dos arquivos novos. O botão "Gerar relatório" dentro dos diálogos é feito por A na T8, chamando a função que B entrega na T10 (A deixa o botão ligado a um gancho, B liga).

## Tarefas

### T0. Preparar a branch
- Conferir `git status`, criar `logistica-melhorias` a partir de `inspecao-datas`, rodar a suíte de Logística para ter a linha de base (`python -m pytest api/tests -q -k logistics` e `python -m pytest tests -q -k logistics`).
- Pronto quando: branch criada, linha de base anotada (quantos passam).

### T1. API: pedido em inspeção entra no LOG (L1, L2, L10)
Arquivos: `api/app/modules/logistics/service.py`, `schemas.py`, `proposal_links.py`, `router.py`, `api/app/core/error_codes.py` (ou onde `LOGISTICS_INSPECTION_NOT_FINISHED` mora).
- `_eligible_proposals` deixa de lançar `LOGISTICS_INSPECTION_NOT_FINISHED`. Se algum pedido não tem DOC BIM, devolve 409 com o código novo `LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED` e `details` com, por proposta, `proposal_number`, `pd_code`, `inspection_stage`. O corpo reenviado com `confirm_inspection: true` passa. Mesmo padrão do `confirm_dates` já existente em `LogCreate` e `AddProposalsPayload`.
- `list_eligible`: troca `Inspection.stage == "fim"` por qualquer inspeção existente do PD. `EligibleProposalOut` ganha `inspection_stage: str` e `inspection_finished: bool`. Decisão do Claude: pedido sem PD ou sem inspeção cadastrada continua fora da lista (L1 fala de "pedido que está na inspeção").
- `LogItemOut` ganha `inspection_stage: str | None` e `inspection_finished: bool`. `LogOut` ganha `without_doc_count: int`.
- `proposal_links.py`: `impact`, `require_confirmation` e `apply_order_change` deixam de tirar a proposta do LOG (L10). Mudar o PD para um sem inspeção finalizada, ou cancelar, só registra evento no histórico do LOG ("PD alterado, inspeção em <etapa>"). Cancelar a proposta continua tirando do LOG (a proposta deixa de existir no fluxo). O construtor confere os dois casos e preserva o de cancelamento.
- Testes: reescrever os que esperam a recusa e a saída automática; novos para: 409 de confirmação, reenvio com `confirm_inspection`, `without_doc_count`, PD alterado mantém no LOG.
- Pronto quando: os testes de `api/tests` de logística passam e nenhum teste antigo ficou só "desligado".

### T2. API: andamento com data real (L3)
Arquivos: migration nova `api/alembic/versions/20261109_0043_*.py`, `migration_risk_registry.json`, `models.py`, `schemas.py`, `service.py`, `router.py`.
- Migration ADDITIVE: `logistics_logs.stage_occurred_on` (Date, nulo); `logistics_events.occurred_on` (Date, nulo) e `logistics_events.note` (Text, nulo). Número da revision conferido com o último de `api/alembic/versions/` (o construtor confirma o encadeamento).
- `DocsPayload` ganha `occurred_on: date | None` e `note: str | None` (máx. 1000), com `confirm_dates: bool = False`. `POST /logs/{id}/approve` passa a aceitar um corpo opcional `ApprovePayload` com os mesmos três campos (sem corpo continua funcionando). `LogDeliveryPayload` ganha `note`; a data é `delivered_on`.
- `_move` grava `stage_occurred_on`, e o evento recebe `occurred_on` e `note`. Sem `occurred_on`, vale hoje (comportamento atual).
- Avisos de data pelo mesmo mecanismo de `calendar_rules` e do 409 `DATE_CONFIRMATION_REQUIRED` já usado em `update_log_dates`: data futura, data anterior à etapa anterior e dia não útil só avisam. Data inexistente é 422.
- `EventOut` ganha `occurred_on` e `note`. `LogOut` ganha `stage_since_date: date` ("desde"), como na Inspeção.
- Pronto quando: testes novos cobrem avançar com data de ontem, data futura com aviso e reenvio confirmado, 422 em 31/02, e sem corpo no `approve`. `scripts/check_migration_safety.py` passa.

### T3. API: contador para na entrega e etapa "Entregue" (L8)
Arquivos: `service.py` (`_log_dict`, `list_logs`), `schemas.py`.
- Decisão do Claude (spec, seção 5): etapa derivada, sem migration. `LogOut` ganha `display_stage` (os valores atuais mais `entregue`, quando `delivered_on` existe). `days_in_stage` e `business_days_in_stage` de LOG entregue passam a contar de `stage_since_date` até `delivered_on` e param ali (dias úteis via `calendar_rules.business_days_between`).
- `list_logs` com `stage=entregue` filtra por `delivered_on IS NOT NULL`. Os outros filtros de etapa passam a excluir os entregues.
- Pronto quando: teste com LOG entregue há 5 dias mostra os mesmos dias hoje e daqui a 10 dias (congelado com data simulada), e LOG sem `delivered_on` continua contando.

### T4. API: filtros da lista (L9)
Arquivos: `service.py` (`list_logs`), `router.py`.
- `GET /logistics/logs` ganha `state: str | None` (estado da Equatorial, comparação sem diferença de caixa) e `load_id: int | None`. Já existem `stage`, `search` e `in_load`.
- Também uma rota `GET /logistics/log-states` devolvendo os estados distintos, para o filtro do Desktop. O construtor pode devolver isso dentro do `LogList` se ficar mais simples.
- Pronto quando: testes combinam `stage + state + search` e conferem `total`.

### Auditoria B1 (sonnet, somente leitura)
Foco: ver a seção "Foco de revisão". Só passa para o Desktop sem achado ALTA.

### T5. Desktop: cliente e serviço
Arquivos: `app/integrations/api/logistics_client.py`, `app/services/logistics_service.py`, testes em `tests/`.
- `send_docs`, `approve_log` e `log_delivery` passam a aceitar `occurred_on`, `note` e `confirm_dates` (mesmo padrão de `update_log_dates`). `add_proposals` e `create_log` aceitam `confirm_inspection`. `list_logs` aceita `state` e `load_id`.
- O cliente deixa passar o 409 de confirmação até a tela, como já faz com `DATE_CONFIRMATION_REQUIRED` (o construtor segue `app/ui/date_warnings.py`).
- Pronto quando: testes do serviço (com Fake do cliente completo) passam.

### T6. Desktop: janela "Registrar andamento" do LOG (L3)
Arquivos novos: `app/ui/logistics_progress.py`. Edita `app/ui/logistics_dialogs.py`.
- `RecordLogProgressDialog`, no mesmo desenho de `RecordProgressDialog` (`app/ui/inspection_progress.py`), reaproveitando `DateQuickField`, `PathField`, `DateWarningPanel`, `date_warning_messages` e `dialog_shell`. `OutcomeForm` da Inspeção é amarrado a `OUTCOMES` da Inspeção; não generalizar, criar um irmão pequeno só com os resultados do LOG.
- Resultados por etapa: `reservada` → "Documentação enviada" (campos NF, XML, BIM); `docs` → "Aprovada para entrega"; `aprovada` → "Entregue no CD" (campo link do comprovante). "Entregue no CD" também aparece nas etapas anteriores, porque hoje o botão existe em qualquer etapa. Campos comuns: "Aconteceu em" (Hoje/Ontem) e "Observação".
- `LogDetailDialog`: botão primário único "Registrar andamento" (some quando já entregue). Saem os botões "Documentação enviada", "Tudo ok: data aprovada" e "Entregue no CD em". "Editar datas" fica como secundário.
- Avisos de data (409) aparecem no painel da janela, com "Marcar mesmo assim" e "Escolher outra data".
- Pronto quando: testes de diálogo (com `QMessageBox` patchado no módulo certo) cobrem: avançar com data de ontem, aviso e reenvio, etapa desatualizada recarrega, entrega com link, aprovado sem permissão de edição não mostra o botão.

### T7. Desktop: pedido em inspeção no LOG (L1, L2, L10)
Arquivos: `app/ui/logistics_dialogs.py` (`LogDetailDialog`, `NewLogDialog`, `_Checklist`), `app/ui/logistics_support.py` ou onde mora `proposal_entry_text`.
- A lista de escolha mostra, por pedido, a etiqueta da inspeção ("Inspeção: visita agendada" ou "DOC BIM em mãos"). Texto vazio e dicas deixam de dizer "só entram propostas com inspeção finalizada".
- Ao incluir ou criar com pedidos sem DOC BIM, o 409 abre uma pergunta com a lista deles e o botão "Incluir mesmo assim" (reenvia com `confirm_inspection`).
- Aba Propostas: coluna "Inspeção" com a etapa. Aba Resumo e cabeçalho: aviso "N pedidos ainda sem DOC BIM" quando `without_doc_count > 0`, sem bloquear nada.
- Pronto quando: testes cobrem incluir pedido sem DOC (confirmação, cancelamento, reenvio) e a coluna e o aviso.

### T8. Desktop: painel "Dados do LOG" (L7)
Arquivos: `app/ui/logistics_dialogs.py` (`_summary_page`, `_DetailDialog`).
- Reproduzir primeiro o vazio acima e abaixo do título "Dados do LOG" e a quebra de NF, XML e BIM (print de 2026-11-09) e achar a causa (provável: painel esticado pela altura do vizinho "Situação atual", alinhamento do formulário). Corrigir na causa.
- Caminhos: mostrar só o nome do arquivo ou pasta, botão "Abrir" ao lado, caminho completo na dica (`setToolTip`). O mesmo vale para o comprovante.
- Ligar o botão "Gerar relatório" (secundário) ao gancho da T10 (função `build_log_report`), no `LogDetailDialog`, e o equivalente no `LoadDetailDialog`.
- Pronto quando: teste confere nome curto e dica com o caminho completo, e `tests/` de diálogo passam. Conferência visual na edição de teste feita pelo Henrique.

### Auditoria B2 (sonnet, somente leitura)
Foco: padrão `qt-industrial-ui`, mocks de `QMessageBox` no módulo certo, regressão do que existe hoje (entrega sem etapa, editar datas).

### T9. Desktop: lista com filtros e etapa "Entregue" (L8, L9)
Arquivos: `app/ui/logistics_page.py`, `app/ui/logistics_support.py`, `app/models/` (table model de LOG).
- Coluna "Etapa" e "Dias na etapa" usam `display_stage` e os dias congelados. "Entregue" ganha selo próprio (cor por token).
- Filtros ao lado da busca: Etapa, Estado, Carga (com carga, sem carga). Combinam com a busca. Estados vêm de T4.
- Pronto quando: testes da página filtram e o rodapé "N LOGs" respeita o filtro.

### T10. Desktop: exportar XLSX e relatórios PDF (L5, L6, L9)
Arquivos novos: `app/services/xlsx_export.py`, `app/services/log_report.py`, `app/ui/report_actions.py` (ou o que o construtor achar mais enxuto). Edita `requirements.txt`, spec do PyInstaller e o script de build.
- **XLSX:** botão "Exportar" na lista, com ícone, abre "Salvar como". Exporta o que está filtrado (busca todas as páginas do filtro). Colunas: LOG, Estado, Data pedida, Data reservada, Carregamento, Entrega no CD, Etapa, Dias na etapa, Propostas, Carga, Entregue em. Cabeçalho em negrito, larguras, filtro ligado. `openpyxl` com versão fixada em `requirements.txt` (conferir que a versão tem mais de duas semanas) e incluído no build, como foi feito com `tzdata` na Fase 16.
- **PDF do LOG:** `build_log_report(log: dict, path)` monta HTML e imprime com `QPrinter` em PDF (modelo: `app/ui/process_page.py:948`). Uma página: logo da Industel, "LOG <código>", estado, etapa, datas, carga e a tabela com proposta, pedido (PD), cliente/obra e situação da inspeção. Sem links. O construtor acha o arquivo da logo nos recursos do Desktop; em edição de teste usa a mesma logo (ver `app/edition.py`).
- **PDF da Carga:** `build_load_report(load: dict, path)`, mesmo estilo: código da carga, data de saída, e um bloco por LOG com estado, datas e as propostas.
- Se a tabela passar de uma página, quebra para a seguinte com o cabeçalho repetido. Decisão do Claude: o relatório é "uma página" no caso comum, mas não corta dados.
- "Salvar como" abre o PDF/XLSX depois de gerar (`QDesktopServices.openUrl`), com aviso se falhar.
- Pronto quando: testes geram o XLSX e o PDF em pasta temporária, o XLSX é relido com `openpyxl` conferindo cabeçalho e linhas, o PDF existe e é maior que zero, e uma conferência manual do Henrique na edição de teste.

### Auditoria B3 (sonnet, somente leitura)
Foco: XLSX respeita filtros, nada de link no PDF, dependência nova entra no build.

### T11. Fechamento
- Suíte oficial inteira: `python -m pytest tests api/tests -q` (sem esconder falha com pipe). Se travar, `test-doctor`.
- Doc `docs/architecture/FASE17_LOGISTICA_MELHORIAS.md` pela skill `fase-report`, com números reais da suíte.
- Commits locais por subsistema (migration/API, cliente/serviço, diálogos, página, relatórios e exportação, docs).
- Atualizar a memória do segundo cérebro (`project/controle-producao-inspecao-logistica.md`) e o `MEMORY.md`.
- Pedir ao Henrique que teste na edição de teste (build com `scripts/build_test_installer.py`, contra a dev 8001) e decidir push.
- Pronto quando: suíte verde, doc escrito, commits feitos, nada na oficial.

## Foco de revisão (falhas que a spec implica e nenhum teste cobre ainda)

1. **Proposta cancelada dentro do LOG.** Com L10, mudar PD só avisa. Cancelar tem que continuar tirando do LOG. Testar os dois caminhos no mesmo teste.
2. **Pedido sem DOC na Carga.** `Carga` só aceita LOG aprovado. Conferir que um LOG com pedido sem DOC BIM aprovado entra na carga e o PDF da Carga mostra a etiqueta de inspeção do pedido.
3. **Etapa desatualizada.** Dois usuários na mesma janela: o segundo registra a mesma etapa. A API responde 409 `LOGISTICS_INVALID_STAGE` e a janela recarrega, sem perder o que foi digitado em "Observação".
4. **LOG entregue e depois com data corrigida.** O contador congelado tem que acompanhar a correção de `delivered_on` (já permitida com motivo), sem ficar negativo se a entrega for anterior ao início da etapa.
5. **XLSX com muitos LOGs e caracteres.** Filtro com mais de uma página de resultados, código com acento e célula começando com `=` (injeção de fórmula): gravar como texto.

## Autorrevisão do plano

- Toda decisão L1 a L10 tem tarefa: L1/L2/L10 em T1 e T7; L3 em T2 e T6; L4 não tem tarefa por ser exclusão; L5 e L6 em T10; L7 em T8; L8 em T3 e T9; L9 em T4, T9 e T10.
- Nomes: `confirm_inspection`, `inspection_stage`, `inspection_finished`, `without_doc_count`, `display_stage`, `stage_since_date`, `occurred_on`, `note`, `build_log_report`, `build_load_report` e `RecordLogProgressDialog` são usados com o mesmo nome em todas as tarefas.
- Os nomes de colunas e a revision da migration ficam para o construtor conferir contra o código; o plano só fixa o contrato.
- O plano não transcreve código: dá arquivos, contrato e critério de pronto.

## Perguntas em aberto

| Pergunta | Dono |
|---|---|
| Onde fica o arquivo da logo para o PDF? | Construtor (acha nos recursos do Desktop; se não houver arquivo utilizável, pergunta ao Henrique) |
| Se o haiku errar T1 ou T2, refazer com sonnet? Sugestão: sim. | Henrique |
