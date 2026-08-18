# Fase 1 — Diagnóstico e métricas de desempenho

## Objetivo

Medir a duração das operações do Desktop e das chamadas HTTP sem alterar as
regras operacionais. A medição deve permitir distinguir processamento em
background, tempo de API e chamadas executadas diretamente no thread visual.

## Contrato de correlação

Cada operação instrumentada recebe um `operation_id` único. Quando a operação
executa uma chamada HTTP, o Desktop envia:

- `X-UI-Operation-ID`: identificador da operação;
- `X-UI-Screen`: tela ou componente de origem;
- `X-UI-Action`: ação medida.

Os dados são apenas de diagnóstico e não contêm payload, token ou informação
de negócio.

## Eventos de log

- `performance_operation_started`
- `performance_operation_finished`
- `performance_api_request`
- `performance_ui_blocking_api_request`

Os eventos incluem duração em milissegundos, status HTTP, request ID, thread,
tela e ação. O limiar inicial de lentidão é `300 ms`.

## Interpretação

- `execution_thread=background`: a API não deveria congelar a janela; a demora
  está na operação externa ou no processamento em background.
- `performance_ui_blocking_api_request`: uma chamada lenta foi executada no
  thread visual e é candidata prioritária à migração para worker.
- `slow=true`: a duração atingiu ou ultrapassou 300 ms.

## Limites desta fase

Esta fase cria medição e correlação. Não altera consultas, paginação, cache,
transações ou regras de negócio. Essas ações ficam para as fases seguintes,
usando os dados coletados aqui.
