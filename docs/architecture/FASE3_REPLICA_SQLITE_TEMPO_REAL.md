# Fase 3 — Réplica local SQLite: aviso em tempo real

## Objetivo

Reduzir o atraso da réplica local de "até 30 s" (poll da Fase 2) para o tempo de
um aviso por WebSocket: a API avisa os Desktops conectados a cada gravação e
eles buscam o que mudou. Continua desligado por padrão (`local_replica.enabled`)
e nenhuma tela lê da réplica ainda (Fase 4).

## Implementação

- `api/app/modules/sync/notifier.py` — `SyncNotifier`: registro em memória das
  conexões e envio de `{"type": "sync.head", "seq": N}`, com debounce de 200 ms
  (rajada de commits vira um aviso com o maior `seq`).
- `api/app/modules/sync/capture.py` — o INSERT no `change_log` passa a devolver
  o `seq` gravado; novo listener `after_commit` entrega esse `seq` ao
  notificador. Falha ao avisar é registrada e não afeta o commit.
- `api/app/modules/sync/router.py` — `WS /sync/ws`: autentica no handshake
  (`get_current_user_ws`), envia o `seq` atual ao conectar e fecha com 4401
  quando o access token vence, como `/chat/ws`.
- `app/replica/sync_realtime.py` — `ReplicaRealtimeClient` (QWebSocket):
  reconexão com backoff (1 s a 30 s), watchdog de ping (30 s, timeout de 10 s),
  sinais `head_advanced(seq)` e `connection_changed(bool)`.
- `app/replica/sync_agent.py` — `notify_head(seq)` dispara um sync quando a
  réplica não está naquele `seq`; `set_realtime_healthy` alterna o poll entre
  30 s (sem WebSocket) e 300 s (com WebSocket).
- `app/ui/main_window.py` — liga o cliente de tempo real junto com o agente e
  para os dois no logout e no fechamento.
- Testes: `api/tests/test_sync_notifier.py`, casos de WebSocket em
  `api/tests/test_sync_integration.py`, `tests/test_replica_sync_realtime.py` e
  novos casos em `tests/test_replica_sync_agent.py`.

## Garantias

1. Pelo WebSocket só trafega o número da versão; dados continuam saindo apenas
   de `GET /sync/changes`, com as permissões da Fase 1.
2. O aviso só é enviado depois do COMMIT; rollback não avisa.
3. Aviso perdido, atrasado ou repetido não causa perda de dado: o Desktop
   sempre sincroniza pelo cursor, e o poll continua como rede de segurança.
4. WebSocket caído ou sem resposta ao ping devolve o Desktop ao poll de 30 s e
   inicia a reconexão; ao reconectar, o servidor informa o `seq` atual.
5. Conexão sem token válido é recusada (4401); token vencido derruba a conexão.
6. `seq` gravado sem ninguém conectado não é anunciado depois a um cliente novo
   (relevante quando o `seq` volta atrás numa restauração de backup).
7. Aviso com `seq` menor que o da réplica também dispara sincronização.

## Validação

```
python -m compileall -q app api/app
python -m pytest api/tests -q --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py
python -m pytest tests/test_replica_db.py tests/test_replica_sync_engine.py tests/test_replica_sync_agent.py tests/test_replica_sync_realtime.py tests/test_replica_factory.py -q
python -m pytest tests -q
```

- `compileall`: sem erros.
- Suíte da API (PostgreSQL 17 descartável, uma execução só, 16 min):
  `3 failed, 998 passed, 2 skipped`.
- Testes da réplica no Desktop: `58 passed` (2 execuções seguidas).
- Suíte completa do Desktop: `1 failed, 1582 passed, 21 skipped` na primeira
  execução; a segunda caiu por falha de segmentação (ver pendências).

Contra a homologação (`controle_producao_industel_dev`), com `QWebSocket` real:
o cliente conectou em `/api/v1/sync/ws`, recebeu `sync.head` com o `seq` atual do
servidor e a réplica ficou nesse cursor; com token inválido a conexão foi
recusada e uma nova tentativa ficou agendada.

## Pendência encontrada

- **Tempo "gravação → outro computador" não medido na homologação.** O usuário
  de teste só tem permissão de leitura sobre propostas, e uma escrita feita por
  script fora do processo da API não dispara o aviso. O caminho completo
  (escrita pela API → aviso → `seq` correto) está coberto apenas pelo teste de
  integração `test_websocket_announces_head_on_connect_and_after_each_write`.
- **3 falhas da API já registradas nas fases anteriores:** dois testes de
  inicialização que recebem 503 e um de auditoria de atualização.
- **Não executados:** os dois arquivos de teste que constroem imagem Docker.
- **Falha de segmentação intermitente da suíte do Desktop** (QThread), desta vez
  em `test_background_stability.py`, que não usa a réplica. Mais 1 falha fixa
  anterior (`email` no payload de usuário).
- **API em processo único:** o registro de conexões é em memória. Com mais de
  um processo da API, um Desktop conectado a um processo não recebe o aviso de
  uma gravação feita em outro (o poll de 300 s cobre, com atraso). Solução
  futura: `LISTEN/NOTIFY` do PostgreSQL.
- **Dois WebSockets por Desktop** (chat e réplica): canais separados porque o
  do chat exige permissão própria. Unificar é possível, mas mexe no chat.
