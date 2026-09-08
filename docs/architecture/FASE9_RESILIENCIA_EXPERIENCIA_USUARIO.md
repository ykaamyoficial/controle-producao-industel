# Fase 9 — Resiliência e experiência do usuário

## Regras técnicas

- `DesktopApiClient` usa timeout por perfil: consultas comuns, Chat/notificações e gravações possuem limites separados.
- Apenas requisições `GET` sem efeito colateral recebem uma retentativa curta. O timeline do Chat e todas as operações de escrita ficam fora da política automática.
- Erros de transporte, timeout e indisponibilidade são classificados como transitórios. Conflitos, validações, permissões e autenticação não são repetidos automaticamente.
- `Worker` registra operação, tipo técnico e traceback no log sem expor segredo; a exceção chega à UI sem encerrar a aplicação.
- `show_operation_error` apresenta mensagem amigável e botão `Tentar novamente` somente para falhas transitórias.
- As telas de Controle Geral, Produção, Galvanização, Fiscal e Chat preservam os dados já exibidos durante falha de refresh.
- O retry reutiliza a operação da tela, sem reiniciar a janela, perder filtros ou apagar seleção.

## Critérios de segurança

1. Nenhuma gravação POST/PATCH/DELETE é repetida automaticamente.
2. Uma falha de rede não chama `close()`, `quit()` nem limpa a sessão.
3. Detalhes técnicos ficam no log; a mensagem ao usuário não mostra stack trace, token ou corpo da API.
4. Consultas continuam em worker; timeout não bloqueia o event loop do Qt.

## Validação

- `python -m compileall -q app api/app`
- `python -m pytest -q tests/test_desktop_api_client.py tests/test_chat_realtime_routing.py tests/test_session_sync_service.py tests/test_chat_timeline_layout.py`
- Resultado: 33 testes aprovados.

