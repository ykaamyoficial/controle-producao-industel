# Fase 3 — Controle de refresh

## Planejamento técnico executado

### 1. Coordenador único por tela

`RefreshCoordinator` serializa consultas da tela. Se uma nova solicitação chegar durante outra consulta, a solicitação anterior não atualiza a interface e apenas a última intenção do usuário é executada.

### 2. Invalidação por geração

Cada solicitação recebe uma geração. A resposta só é aplicada quando sua geração ainda é a atual. Isso impede que uma resposta lenta sobrescreva uma pesquisa mais recente.

### 3. Debounce

Consultas acionadas por digitação usam janela de 280 ms. O refresh manual pelos botões continua imediato. O mecanismo também elimina chamadas intermediárias quando o usuário continua digitando.

### 4. Estado visual

Enquanto a consulta está ativa, a tela mantém o estado de carregamento existente. O coordenador não inicia duas consultas simultâneas e agenda a próxima consulta somente após a anterior concluir.

### 5. Preservação da navegação

As páginas de Controle Geral, Produção, Galvanização e Fiscal preservam a posição vertical e horizontal da tabela após a atualização. A seleção em lote continua sendo mantida pelo identificador estável da entidade.

### 6. Reset somente quando há alteração

Os modelos de tabela agora ignoram `set_rows` quando a lista recebida é idêntica à lista atual. Isso evita reset visual, perda de foco e repintura desnecessária.

## Áreas cobertas

- Controle Geral, Produção, Galvanização e Expedição via `ProcessPage`.
- Itens em produção.
- Itens e cargas da galvanização.
- Acompanhamento fiscal.

## Critérios de aceite

- Não existem dois refreshes simultâneos por tela.
- Respostas fora de ordem não alteram mais a tabela.
- Digitação rápida não dispara uma requisição por tecla nas telas com busca remota.
- A posição da lista não volta para o início depois de um refresh.
- Uma lista sem alteração não provoca reset do modelo.

## Validação

`python -m compileall -q app` concluído com sucesso.

Testes automatizados existentes executados: 25 aprovados, com apenas avisos de depreciação do Qt/pytest.
