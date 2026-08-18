# Fase 2 — Proteção da interface e operações críticas

## Objetivo

Evitar congelamentos durante gravações e ações administrativas sem mudar as regras de negócio. A interface continua no thread principal; chamadas de escrita e operações potencialmente demoradas executam em `QThread` pelo padrão único de `start_worker`.

## Padrão aplicado

1. Validar seleção e confirmação no thread da interface.
2. Capturar os valores dos controles antes de iniciar o worker.
3. Desabilitar somente a tela/controles envolvidos.
4. Executar a chamada de serviço no worker com nome operacional e correlação de métricas.
5. Tratar sucesso e erro em callbacks no thread da interface.
6. Atualizar a tela somente depois da conclusão.
7. Impedir o fechamento do diálogo enquanto a gravação crítica estiver em andamento.

## Operações migradas

- Produção: iniciar produção, registrar produção e preparação automática de itens para montagem de carga.
- Galvanização: adicionar itens a carga, salvar/montar carga, liberar carga e registrar retorno parcial.
- Expedição: aplicação das alterações em lote.
- Fiscal: registro de emissão fiscal individual.

## Limite de bloqueio visual

O bloqueio é local: tabela, filtros e botões da operação corrente ficam desabilitados, enquanto a janela principal permanece responsiva. O fechamento é recusado apenas nos diálogos que possuem gravação crítica em andamento.

## Critérios de aceite

- Nenhuma chamada de escrita migrada é executada diretamente pelo callback de clique.
- Toda operação possui nome de métrica `performance_operation`.
- Sucesso, falha e atualização visual acontecem no thread da interface.
- Repetição acidental do botão fica impedida enquanto a operação está em andamento.
- Compilação e testes de métricas, cliente API e seleção fiscal passam.

## Próxima etapa

Instrumentar e migrar os diálogos administrativos restantes de menor prioridade, além de validar manualmente os fluxos com API real e falhas de rede.
