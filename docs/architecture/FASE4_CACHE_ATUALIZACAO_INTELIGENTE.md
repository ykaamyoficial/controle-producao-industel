# Fase 4 — Cache e atualização inteligente

## Planejamento técnico executado

### Cache curto e isolado

Foi criado `ShortLivedCache`, com TTL curto, cópia profunda dos valores e proteção por `RLock`. A cópia evita que a tela altere acidentalmente o valor armazenado.

### Leituras cobertas

- Listas de propostas por área.
- Itens em produção.
- Itens e cargas da galvanização.
- Listas fiscais.
- Indicadores e linhas de indicadores fiscais.
- Contador global de mensagens não lidas.

As listas usam TTL de 2 segundos; indicadores e contadores usam TTL de 1 segundo. Esses valores reduzem chamadas repetidas sem transformar o cache em fonte permanente de verdade.

### Invalidação operacional

Gravações de status, produção, cargas, retorno da galvanização e emissão fiscal invalidam o cache operacional antes da alteração. O próximo refresh busca o estado atualizado da API.

### Atualização em segundo plano

O cache é acessado dentro dos workers da Fase 3. A interface continua responsiva e o refresh coordenado decide quando aplicar o resultado. O modelo de tabela também evita reset quando os dados recebidos são idênticos.

## Limites deliberados

O cache não é usado para autorizar ações, validar versões ou substituir a API. Toda gravação continua consultando a fonte oficial e a invalidação ocorre antes da operação.

## Validação

- Compilação do pacote `app` aprovada.
- 25 testes existentes aprovados.
- 57 testes de integração dependentes de ambiente externo foram ignorados automaticamente.
- Testes unitários do cache adicionados em `tests/test_short_cache.py`.
