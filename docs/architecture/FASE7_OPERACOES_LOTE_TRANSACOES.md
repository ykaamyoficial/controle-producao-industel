# Fase 7 — Operações em lote e transações

## Execução técnica

### Motor transacional existente

O Fiscal já utiliza `register_fiscal_batch` como motor único: as propostas são validadas antes da gravação, o lote é confirmado em uma única transação e o `operation_id` permite reprocessamento idempotente após timeout.

### Proteção da interface

As ações em lote usam o worker da Fase 2, bloqueiam o botão durante a execução e agora exibem progresso `n/total` em operações longas. O resumo final mantém quantidade processada e falhas individualizadas por proposta.

### Falha parcial

Quando uma operação de lote contém transições independentes, o resultado retorna `changed` e a lista de falhas sem esconder o que foi processado. A interface informa o resumo e atualiza a tela somente após o worker terminar.

### Idempotência e duplicação

O Fiscal mantém `operation_id` no contrato e a API rejeita/reproduz com segurança uma operação já confirmada. Nas demais transições, a versão otimista da proposta e o estado atual da API impedem reaplicação cega; o fingerprint de requisição continua sendo registrado pelas métricas.

## Limite atual

As ações de status em lote ainda são executadas como transições por proposta dentro de um único worker, pois não existe um endpoint batch operacional comum para todas as áreas. Criar esse endpoint exige consolidar regras de Produção, Galvanização e Expedição em um contrato transacional único; não foi inventado um endpoint genérico que pudesse alterar a semântica existente.

## Validação

- Compilação da API e desktop aprovada.
- Progresso visual adicionado ao `BatchStatusDialog`.
- Testes existentes devem ser executados com o conjunto de regressão da API antes do deploy.
