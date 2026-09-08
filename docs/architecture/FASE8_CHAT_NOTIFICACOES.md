# Fase 8 — Chat e notificações

## Objetivo

Manter o Chat fluido quando o usuário troca de tela, recebe mensagens ou abre uma conversa com histórico grande, sem transformar cada evento em um refresh completo.

## Implementação

- O `ChatRealtimeClient` mantém uma única conexão `QWebSocket` por janela, com backoff progressivo de 1 a 30 segundos, renovação do token a cada tentativa e deduplicação por `event_id`.
- Eventos em tempo real são gatilhos de invalidação. O resumo de não lidas é reconciliado pelo `SessionSyncService`; o painel aberto é atualizado somente quando o evento pertence à conversa visível.
- A Central de Chats possui refresh serializado/coalescido: enquanto uma consulta está em andamento, novos pedidos ficam pendentes e resultam em no máximo uma nova consulta.
- A busca possui debounce de 350 ms e as contagens da aba oposta usam `total` paginado, sem carregar duzentas conversas apenas para contar.
- Um evento de conversa usa `conversation_id` no endpoint de listagem e substitui apenas o card alterado. Uma conversa nova ou mudança de status ainda pode solicitar refresh da página para reposicionar a ordenação.
- O polling do sino tem proteção contra concorrência. Eventos sucessivos não criam múltiplos workers de notificações.
- Mensagens de conversas gerais começam com 50 registros mais recentes. Mensagens antigas são carregadas progressivamente, preservando a posição do scroll. O painel de proposta mantém o cursor temporal existente.
- A API informa `has_more` na listagem de mensagens e aceita `conversation_id` na listagem de conversas para atualizações pontuais.

## Garantias

1. Não há listener WebSocket duplicado por navegação: o cliente pertence à `MainWindow` e é encerrado no logout.
2. Não há dois refreshes de notificações simultâneos.
3. Uma mensagem recebida não reconstrói a lista e o painel inteiro por padrão.
4. Reconexões não duplicam eventos já processados.
5. Histórico antigo não é carregado na abertura inicial.

## Validação

- `python -m compileall -q app api/app`
- `python -m pytest -q tests/test_chat_realtime_routing.py tests/test_session_sync_service.py tests/test_chat_timeline_layout.py`

## Atualização (Fase 11)

A partir da Fase 11 (`FASE11_NOTIFICACOES_MULTICANAL.md`), o chat deixou de ser o único
produtor de notificação: `_insert_notification` continua escrevendo em `chat_notifications`,
mas também **espelha** cada aviso para a camada genérica `api/app/modules/notifications/`
(tabela `notifications`), ao lado dos eventos de negócio. A Central de Notificações do Desktop
e o agente de bandeja passaram a ler `/api/v1/notifications`; o sino do chat e o
`unread_summary` deste módulo continuam funcionando como descrito acima.

