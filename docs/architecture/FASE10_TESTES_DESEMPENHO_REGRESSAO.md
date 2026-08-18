# Fase 10 — Testes de desempenho e regressão

## Escopo validado

Foram executadas validações para métricas, cliente HTTP, resiliência, Chat,
diagnóstico, produção, galvanização, seleção e sincronização. Também foi
corrigido o ciclo de callbacks de `start_worker`: resultados e erros agora
chegam ao thread da interface antes de executar qualquer código Qt.

## Resultados reproduzíveis

- Compilação `app` e `api/app`: aprovada.
- Métricas/rede/estabilidade/Chat/sincronização: **34 testes aprovados**.
- Chat/diagnóstico/galvanização isolados: **27 testes aprovados**.
- Fase 10 específica: **2 testes aprovados**, incluindo P95 e retry seguro.

## Metas cobertas por teste

- P50/P95 e contagem de operações lentas disponíveis em `performance_snapshot()`.
- GET seguro pode repetir uma falha transitória.
- POST não é repetido após timeout/conexão.
- Eventos realtime e sincronização não aplicam respostas antigas.
- Paginação e Chat continuam funcionais.
- Erros de worker não executam callbacks Qt no thread de trabalho.
- Resiliência preserva telas e oferece retry.

## Pendência encontrada

A suíte completa do repositório não pode ser declarada totalmente verde neste
ambiente. Um teste legado de `ProductionRegistrationDialog` espera que o
callback assíncrono execute de forma síncrona imediatamente após `_review()`;
isso conflita com a correção de segurança que entrega o callback no thread da
interface. Em execução isolada, os testes das telas e do Chat passam; o teste
deve ser atualizado para aguardar o evento Qt antes de afirmar o QMessageBox.

Também houve access violation durante a primeira suíte ampla, causado por
callbacks Qt executados no worker. A correção foi aplicada em
`app/ui/background_worker.py` e as rodadas isoladas posteriores não repetiram o
crash.

## Conclusão

As melhorias foram implementadas e validadas por blocos. A aprovação final
absoluta da Fase 10 depende apenas da atualização do teste legado síncrono e de
uma execução completa em ambiente com os serviços de integração disponíveis.
