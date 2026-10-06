# Fase 2 — Réplica local SQLite: banco e sincronização no Desktop

## Objetivo

Dar ao Desktop um arquivo SQLite por usuário, mantido em dia com a API pelos
endpoints `/sync` da Fase 1 (`FASE1_REPLICA_SQLITE_SYNC_API.md`). Nenhuma tela
lê da réplica ainda (Fase 4) e o recurso fica **desligado por padrão**.

## Implementação

- `app/replica/replica_db.py` — `ReplicaDatabase`: arquivo SQLite em WAL, uma
  conexão curta por operação (seguro entre threads). Cada entidade é uma tabela
  `(id, <colunas indexadas>, data)`; `data` guarda a linha inteira em JSON e
  `INDEXED_COLUMNS` define as colunas de filtro/junção. Escrita só por
  `replace_all` (troca atômica da carga inicial) e `apply_changes` (página de
  mudanças + cursor na mesma transação). Leitura por `get`, `find`, `count`.
- `app/replica/sync_engine.py` — `ReplicaSyncEngine.sync_once()` (sem Qt):
  decide entre carga inicial e incremental, segue `has_more`, refaz a carga
  quando o servidor pede (`resync_required`) e devolve `SyncResult` com as
  entidades alteradas. `SyncApiClient` encapsula as três rotas.
- `app/replica/sync_agent.py` — `ReplicaSyncAgent` (Qt): roda `sync_once` em
  worker thread via `start_worker`, um sync por vez, poll de 30 s, sinais
  `data_changed`, `sync_finished`, `sync_failed`, `state_changed`.
- `app/replica/factory.py` — flag `local_replica.enabled`, pasta da réplica
  (`%LOCALAPPDATA%\ControleProducao\replica` no app instalado, `app/data/replica`
  em desenvolvimento, `CONTROLE_PRODUCAO_REPLICA_DIR` para sobrescrever) e um
  arquivo por servidor + usuário (`replica_<hash>.db`).
- `app/services/api_proposal_storage.py` — `sync_get_json` e `api_base_url`.
- `app/ui/main_window.py` — `_start_replica_sync`/`_stop_replica_sync`: liga o
  agente no login se a flag estiver ativa; para no logout e no fechamento.
  Falha ao preparar a réplica é registrada e o app segue sem ela.
- Testes: `tests/test_replica_db.py`, `tests/test_replica_sync_engine.py`,
  `tests/test_replica_sync_agent.py`, `tests/test_replica_factory.py` e o
  servidor falso `tests/replica_fakes.py`.

Para ligar em uma máquina: `"local_replica": {"enabled": true}` no
`controle_producao_config.json`.

## Garantias

1. A réplica nunca é fonte da verdade nem recebe escrita das telas: só o motor
   de sincronização grava nela; toda gravação de negócio continua indo à API.
2. Página de mudanças e cursor são gravados na mesma transação: queda no meio
   não deixa cursor adiantado nem dado pela metade.
3. Reaplicar a mesma página não altera o resultado (idempotência) e o cursor
   nunca regride.
4. A carga inicial troca o conteúdo inteiro de uma vez; quem lê vê o estado
   anterior até o commit. Escritas ocorridas no servidor durante a carga são
   recuperadas pelo incremental que vem logo depois.
5. Um Desktop atrasado (cursor N, servidor em M) recebe exatamente o que veio
   depois de N, sem nova carga inicial.
6. A réplica é descartada e refeita quando muda: o layout local, o
   `schema_version` do servidor, o servidor/usuário, o conjunto de entidades
   permitidas, ou quando o servidor responde `resync_required`. Arquivo
   corrompido é recriado.
7. Entidade que o usuário deixou de poder ver some da réplica na recarga.
8. Falha de rede não invalida a réplica: o último estado bom continua legível
   e o próximo ciclo tenta de novo.
9. Com a flag desligada (padrão), nenhum arquivo é criado e nenhuma chamada
   `/sync` é feita.

## Validação

```
python -m compileall -q app api/app
python -m pytest tests/test_replica_db.py tests/test_replica_sync_engine.py tests/test_replica_sync_agent.py tests/test_replica_factory.py -q
python -m pytest tests -q
```

- `compileall`: sem erros.
- Testes da réplica: `43 passed` (3 execuções seguidas).
- Suíte completa do Desktop: `1 failed, 1567 passed, 21 skipped` (2 execuções
  seguidas, sem queda do processo).

Ponta a ponta contra a homologação (`controle_producao_industel_dev`, cópia dos
dados de produção), usando `ReplicaDatabase` + `ReplicaSyncEngine` reais:

| Passo | Resultado |
|---|---|
| Carga inicial (9 entidades, 5 803 linhas) | 2,0 s, arquivo de 3,6 MB |
| Sincronização sem novidade | 73 ms |
| Alteração gravada no servidor → réplica | incremental, 1 mudança, 77 ms |
| Réplica × snapshot do servidor, linha a linha | idênticos nas 9 entidades |

## Pendência encontrada

- **1 falha anterior a esta fase:**
  `test_official_user_management_uses_api_without_legacy_sqlite` espera o
  payload de usuário sem o campo `email` (introduzido na 2.7.1).
- **Falha de segmentação intermitente da suíte do Desktop** (QThread) não
  apareceu nestas duas execuções, mas não foi corrigida.
- **Não validado na interface real:** o agente foi testado com `QApplication`
  de teste e o motor contra a homologação; o app completo com a flag ligada não
  foi aberto nesta fase.
- **Atraso de até 30 s:** sem aviso em tempo real, uma alteração de outro
  usuário chega no próximo poll. O push por WebSocket é a Fase 3.
- **Duas instâncias do app no mesmo usuário** compartilham o arquivo; funciona
  (WAL, cursor que não regride), mas cada uma faz o próprio poll.
- **Sem indicador visual** de estado da réplica (sincronizado/offline).
