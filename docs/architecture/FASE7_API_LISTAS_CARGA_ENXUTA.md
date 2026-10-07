# Fase 7 — API: listas de Produção, Galvanização, Almoxarifado e Parciais com carga enxuta

## Objetivo

Acelerar as telas que a API deixava em 0,5–1 s, **sem copiar regra de negócio
para o Desktop** (diretriz do responsável, `FASE6_REPLICA_SQLITE_REGRAS_SO_NA_API.md`).
Contrato HTTP, resultado, ordenação e totais ficam idênticos aos de antes.

## Diagnóstico

Medido dentro da API de homologação (cópia dos dados de produção, 267
propostas), para cada lista: tempo total, nº de consultas e tempo no banco.

| Lista | Total | Consultas | No banco | No Python |
|---|---:|---:|---:|---:|
| `/production/proposals` | 1 020 ms | 31 | 164 ms | 857 ms |
| `/production/items` | 685 ms | 31 | 106 ms | 579 ms |
| `/galvanization/candidates` | 649 ms | 35 | 136 ms | 514 ms |
| `/galvanization/loads` | 732 ms | 36 | 138 ms | 594 ms |
| `/warehouse/proposals` | 583 ms | 31 | 117 ms | 466 ms |
| `/partials/proposals` | 916 ms | 66 | 166 ms | 750 ms |

Cerca de 80% do tempo era Python, não banco. A causa é o modelo: `Proposal` e
`ProposalItem` carregam por padrão (`lazy="selectin"`) uma cascata de relações
(itens, eventos, itens de carga e de expedição, registro fiscal com itens,
faturas e eventos, alocações). Só a lista do Almoxarifado, que lê propostas e
seus itens, criava ~8 000 objetos ORM e fazia 31 consultas. Além disso, três
listas carregavam todas as propostas ativas e descartavam a maioria em Python.

A hipótese inicial, de um laço de duas consultas por item na galvanização, só
explicava uma parte pequena; o grosso era a cascata de carga.

## Implementação (`api/app/modules/proposals/service.py`)

- **Carga enxuta:** `_lean_items(...)` e `lazyload("*")` em cada lista carregam
  só as relações que ela usa. O que ficou de fora é `lazyload`: numa sessão
  assíncrona, acessá-lo **levanta erro** (nunca devolve vazio), então um campo
  esquecido aparece como falha nos testes, não como dado errado.
- **Produção** (`list_production_proposals`, `list_production_items`):
  `_production_active_status_clause()` aplica no banco o status de produção
  ativo (superconjunto exato dos apelidos de `ProductionStateMachine`); o filtro
  exato em Python continua depois.
- **Galvanização, candidatos:** pré-filtro `EXISTS` de item elegível (mesmos
  critérios de `_eligible_galvanization_items`) e `_galvanization_quantities`,
  uma consulta agrupada com enviado e ainda fora de todos os itens, no lugar de
  duas consultas por item.
- **Galvanização, cargas:** sem busca, contagem e página no banco (só a página é
  carregada); com busca, carrega proposta e item para o texto de busca, como antes.
- **Parciais:** `_partial_movement_clause()` espelha em SQL cada ramo de
  `_proposal_has_partial_movement`; o filtro exato continua em Python.
- **Almoxarifado:** só propostas e itens, sem a cascata.

## Garantias

1. Cada tela devolve exatamente a mesma resposta de antes (mesmas linhas, ordem
   e totais), comprovada contra a resposta gravada antes da mudança.
2. Cada filtro novo no banco é igual (ou, nos casos de superconjunto, contém) à
   regra Python correspondente, proposta por proposta.
3. Nenhum campo não carregado é lido em silêncio: ou está carregado, ou levanta erro.
4. Nenhuma regra de negócio foi movida ou copiada; sem migration e sem mudança de contrato.

## Validação

```
python -m compileall -q api/app
python -m pytest api/tests/test_list_query_optimizations.py -q
python -m pytest api/tests -q --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py
```

- `compileall`: sem erros.
- `test_list_query_optimizations.py`: `6 passed`. Monta um cenário com propostas
  parciais, em vários status de produção, itens elegíveis à galvanização com
  carga parcial e total, expedição e fiscal, e compara: cada filtro SQL com a
  regra Python em todas as propostas; cada tela com o algoritmo antigo
  reimplementado como referência (carrega tudo, filtra em Python).
- Suíte da API (PostgreSQL 17 descartável): `3 failed, 1010 passed, 2 skipped`.
  As 3 falhas são as já registradas nas fases anteriores (dois 503 de
  inicialização e um de auditoria de atualização); os dois arquivos de build
  Docker não foram executados.

Homologação, 44 combinações de filtro e paginação gravadas antes e comparadas
depois (todas idênticas), mediana de 3 chamadas, máquina livre:

| Chamada | Antes | Depois |
|---|---:|---:|
| `/galvanization/candidates` | 793 ms | ~20 ms |
| `/galvanization/loads` | 704 ms | ~33 ms |
| `/partials/proposals` | 981 ms | ~45 ms |
| `/production/items` | 736 ms | ~40 ms |
| `/production/proposals` | 457 ms | ~38 ms |
| `/warehouse/proposals` | 723 ms | ~70 ms |

Na comparação direta com os dados reais, o filtro SQL de parciais e o Python
coincidem nas 267 propostas (5 parciais), o de produção ativa nas 27, e o de
item elegível nas 2.

## Índices (medido, sem alteração)

Combinado na Fase 6: medir `auth_sessions.user_id` e `security_events.target_user_id`.
Com a máquina pouco carregada:

- `revoke_user_sessions` (`auth_sessions` por `user_id`, 15 868 linhas):
  2,3 ms, só roda em troca de senha e encerramento de sessões.
- `security_events` filtrada por usuário, com `ORDER BY created_at DESC LIMIT`:
  2,7 ms (usa o índice de `created_at`); a contagem do mesmo filtro: 14 ms.

Nenhum índice novo se justifica hoje. O ponto de atenção é o volume sem limpeza:
**87 335 eventos de segurança e 15 868 sessões para 8 usuários**, só crescendo.

## Pendência encontrada

- **Retenção de dados:** `auth_sessions` e `security_events` acumulam sem
  expurgo; vale definir uma política (por exemplo, apagar sessões expiradas
  após N dias) antes de o volume pesar.
- **Tela dos Detalhes e das listas não medidas no programa** depois da mudança;
  os tempos acima são da API.
- **Tempo restante das telas:** ainda há as chamadas de chat na primeira
  abertura e o tempo de rede; a API agora responde em dezenas de milissegundos.
- **Outras listas com a mesma cascata** (Expedição, Fiscal e Controle Geral já
  foram otimizadas nas Fases 0 e 6; `get_*` de detalhe e rotinas de escrita
  continuam carregando a árvore completa, de propósito, por precisarem dela).
- **A API precisa subir antes do desktop** no release (parâmetros `search` e
  `proposal_id` novos nas Fases 6 e 7).
