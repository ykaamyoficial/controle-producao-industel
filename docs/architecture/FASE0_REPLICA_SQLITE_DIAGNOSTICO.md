# Fase 0 — Diagnóstico para a réplica local SQLite

## Objetivo

Medir onde o Desktop perde tempo hoje, antes de construir a réplica SQLite com
sincronização incremental (`change_log` + cursor por computador). Esta fase não
altera código de produto. Entrega: linha de base, inventário e decisões.

## Fonte dos dados

Log real do Desktop (`%APPDATA%\ControleProducao\logs`), eventos
`performance_api_request` (instrumentação da Fase 1 de métricas).
Reproduzível com `python scripts/analyze_performance_log.py`.

Limites da amostra: **1 087 requisições, 1 computador, 02/10 a 06/10/2026**.
Serve para priorizar, não para dimensionar. Repetir em 2–3 outros PCs antes da
Fase 4.

## Linha de base (por endpoint)

| Endpoint | n | p50 ms | p95 ms | Tempo total |
|---|---:|---:|---:|---:|
| `GET /chat/unread-summary` | 843 | 229 | 441 | 229 s |
| `GET /shipping/proposals` | 10 | 3 150 | 6 331 | 43 s |
| `GET /fiscal/records` | 8 | 4 454 | 6 938 | 42 s |
| `GET /fiscal/indicators` | 4 | 4 067 | 4 133 | 17 s |
| `GET /chat/notifications` | 45 | 309 | 565 | 15 s |
| `GET /proposals` (limit 200) | 15 | 711 | 1 703 | 13 s |
| `GET /partials/proposals` | 8 | 996 | 1 106 | 8 s |
| `GET /galvanization/candidates` | 7 | 890 | 1 149 | 7 s |
| `GET /warehouse/proposals` | 3 | 1 037 | 1 360 | 3 s |
| `GET /production/proposals` | 4 | 794 | 831 | 3 s |

Totais: 24,7 % das requisições passam de 300 ms. Nenhuma chamada lenta rodou no
thread da UI (`execution_thread=ui`: 0), então o problema é **espera por dados**,
não congelamento da janela.

## Achados

### 1. Dois problemas distintos, que pedem remédios distintos

- **Volume (polling):** `chat/unread-summary` é 78 % de todas as requisições
  (843 de 1 087), disparado pelo `SessionSyncService` e pelo timer de 20 s em
  `main_window.py:296`. É barato por chamada (229 ms) mas constante.
- **Latência (listas pesadas):** expedição, fiscal, galvanização, almoxarifado e
  propostas levam de 0,7 s a 7 s por abertura de tela.

### 2. A lentidão das listas é do servidor, não da rede

Em `api/app/modules/proposals/service.py`:

- `list_expedition_proposals` (linha ~746) e `list_fiscal_records` (~1985)
  carregam **todas** as propostas ativas com `selectinload` de itens/eventos,
  filtram, ordenam e paginam **em Python**. `limit/offset` só fatiam o resultado
  depois de tudo carregado.
- **Esses `GET` escrevem no banco.** Cada chamada executa
  `_sync_expedition_from_available_items` / `_sync_fiscal_records`, que percorre
  todas as propostas, cria `ExpeditionItem`/`FiscalRecord` faltantes e faz
  `commit()`.

### 3. Consequências para o desenho da réplica

1. **Réplica sozinha esconde, não cura.** O SQLite local deixaria a leitura
   rápida no cliente, mas o custo continuaria em todo `/sync/snapshot`. Vale
   corrigir esses dois caminhos na API (consulta com filtro/paginação no SQL e
   sync de derivados fora do `GET`) **independentemente** da réplica.
2. **Dados derivados.** `expedition_items` e `fiscal_records` são gerados por
   leitura. Se o listener do `change_log` capturar essas escritas, cada abertura
   de tela geraria eventos falsos. Decisão necessária na Fase 1: materializar os
   derivados na escrita da proposta (e então replicá-los), ou replicar só as
   tabelas-base e recalcular a visão localmente.
3. **Sem SQLite ativo no Desktop.** `production_repository.py`,
   `sqlite_safety.py`, `official_proposal_storage.py`, `proposal_sync.py` e
   `sqlite_real_snapshot.py` são stubs de 12–16 linhas (legado desativado).
   Não há réplica nem arquivo `.db` para reaproveitar: parte do zero, sem
   migração de dados antigos. `app/updater/persistence.py` já preserva `*.db`
   nas atualizações, o que ajuda.
4. **`ShortLivedCache` (TTL 2 s)** existe em `backend_adapter.py:206` e continua
   útil só como cache de memória por cima da réplica.

## Entidades-piloto (ordem recomendada)

| # | Entidade / tela | Motivo | Observação |
|---|---|---|---|
| 0 | Contadores de chat/notificações | 78 % do volume | **Não precisa de SQLite**: usar o WebSocket que já existe (`/chat/ws`, `read_state_updated`) e manter o poll só como rede de segurança com intervalo maior. Ganho imediato, baixo risco. |
| 1 | Expedição | Maior latência (p50 3,1 s) | Exige resolver o item 3.2 antes. |
| 2 | Fiscal (registros + indicadores) | p50 4,4 s / 4,1 s | Indicadores podem ser calculados localmente sobre a réplica. |
| 3 | Propostas (lista) | Tela central, 15 aberturas | Base das demais; `proposals` já tem `version` e `updated_at`. |
| 4 | Galvanização, almoxarifado, produção | 0,4–1,0 s | Após o padrão estar validado. |

Tabelas sincronizáveis candidatas (de 36 mapeadas): `proposals`,
`proposal_items`, `proposal_events`, `expedition_*`, `fiscal_*`,
`galvanization_*`, `product_catalog_entries`. Ficam **fora** da réplica:
`users`/`roles`/`permissions`/`auth_sessions`, `security_events`, anexos e
mensagens de chat (permissão e volume).

## Decisões desta fase

1. Começar pelo **Passo 0** (contadores via WebSocket), que não depende do resto.
2. Abrir, em paralelo, correção na API de `list_expedition_proposals` e
   `list_fiscal_records` (filtro/paginação no SQL, sem escrita em `GET`).
3. A réplica copia a **forma já otimizada** dos dados, não os caminhos lentos.
4. O `seq` global do sync chama-se `change_seq`; a coluna `version` existente é
   lock otimista por linha e não deve ser reutilizada.

## Decisões do responsável (06/10/2026)

- Réplica **somente leitura**; toda gravação continua indo para a API.
- Porte: **10 a 30 computadores** simultâneos. Eventos de sync leves (o cliente busca os dados pelo cursor).
- Dados em disco **sem criptografia**, na pasta do usuário.
- Início: **em paralelo** (A) correção das consultas de Expedição/Fiscal na API e (B) contadores de chat via WebSocket.
- Ainda aberto: medir 2–3 outros PCs para confirmar a linha de base.

## Executado em 06/10/2026 (após o diagnóstico)

- **Contadores de chat:** heartbeat adaptativo (20 s sem WebSocket, 120 s com ele), coalescência de gatilhos (400 ms) e watchdog de ping (30 s, timeout de 10 s) em `app/ui/chat_sync_coordinator.py` e `app/ui/chat_realtime.py`.
- **Expedição/Fiscal na API:** filtro, ordenação e paginação em SQL; `GET` não grava mais. Derivados (`ExpeditionItem`, `FiscalRecord`/`FiscalItem`) são materializados na escrita (`api/app/modules/proposals/derived_sync.py`) e por backfill idempotente no startup.
- **Regra de área:** a proposta não muda mais para `EXPEDICAO` por alguém abrir a tela; só por ação (iniciar separação, retorno de galvanização, conclusão de produção). Na Expedição, proposta mista sem `shipping_status` é exibida e ordenada como `EM_SEPARACAO` (`_expedition_display_status`).
- **Fiscal:** é independente do status da proposta (nota pode ser emitida com material não pronto). A mãe entra no Fiscal na criação e segue como referência; o registro próprio da filha continua surgindo quando ela chega à Expedição. Validar esse ponto em homologação com quem opera o Fiscal.
- **Pendente:** medir ganho real em homologação com dados de produção (`scripts/analyze_performance_log.py`).

## Critério de sucesso (metas a validar na Fase 4)

- Abertura de Expedição e Fiscal: p50 < 300 ms a partir da réplica.
- Requisições de polling de contadores: redução ≥ 80 %.
- Alteração feita em um PC visível em outro em < 2 s.
