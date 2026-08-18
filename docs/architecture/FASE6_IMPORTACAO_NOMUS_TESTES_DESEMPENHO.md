# Fase 6 - Testes, desempenho e refinamento da importacao Nomus

Data da medicao: 2026-08-18  
Ambiente: execucao local em Windows, Python 3.14, API Nomus simulada e sem rede externa.

## Escopo validado

- Busca unitaria por pagina estimada e vizinhas.
- Importacao em lote com agrupamento por pagina e cache por execucao.
- Fila com concorrencia limitada, retentativas e cancelamento.
- Conferencia em memoria e gravacao seletiva pela API oficial.
- Idempotencia, isolamento de falhas e bloqueio de campos financeiros.
- Ausencia de consultas de produto/peso no fluxo padrao unitario e em lote.

## Instrumentacao

O coletor central `NomusImportMetricsCollector` usa `time.perf_counter()` e nao armazena payloads, credenciais, clientes ou valores comerciais. As metricas disponiveis sao:

- tempo total, localizacao, dados/itens, conferencia e persistencia;
- requisicoes HTTP, paginas requisitadas totais e unicas;
- acertos de cache, reaproveitamentos por agrupamento e retentativas;
- propostas prontas, existentes, nao encontradas, com falha, gravadas e canceladas;
- chamadas de peso, que permanecem em zero no fluxo padrao.

Os logs finais sao resumidos por lote. Ha alertas para baixa efetividade de agrupamento/cache, busca vizinha excessivamente ampla e referencia mais recente inconsistente, sem registrar dados sensiveis.

## Comparacao controlada

Cenario: 25 propostas na mesma pagina, 50 registros por pagina e latencia simulada de 1 ms por requisicao. A referencia antiga e uma varredura sequencial independente da pagina 1 ate a pagina estimada para cada proposta. Ela existe somente no script de benchmark.

| Estrategia | Requisicoes HTTP | Mediana |
| --- | ---: | ---: |
| Sequencial de referencia | 500 | 687,455 ms |
| Estimada, agrupada e com cache | 2 | 32,323 ms |

Resultado: **99,6% menos requisicoes** e **95,3% menos tempo**. O agrupamento reaproveitou 24 consultas de pagina, com efetividade calculada de 92,31%. Nao houve consulta de peso.

## Concorrencia

Cenario: 20 propostas espalhadas em 20 paginas, com latencia simulada de 5 ms por requisicao.

| Workers | Mediana | Concorrencia maxima observada | Requisicoes |
| ---: | ---: | ---: | ---: |
| 1 | 135,836 ms | 1 | 21 |
| 2 | 81,527 ms | 2 | 21 |
| 4 | 57,501 ms | 4 | 21 |

O limite configurado foi respeitado em todos os casos. Quatro workers apresentaram o melhor tempo do conjunto testado sem aumentar o numero de requisicoes.

## Carga

Todos os cenarios usam propostas em paginas distintas, sem latencia artificial. A memoria foi medida com `tracemalloc`.

| Propostas | Tempo | Pico de memoria | Requisicoes | Prontas | Peso |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3,705 ms | 19,4 KiB | 2 | 1 | 0 |
| 10 | 25,922 ms | 62,1 KiB | 11 | 10 | 0 |
| 25 | 80,553 ms | 143,3 KiB | 26 | 25 | 0 |
| 50 | 224,036 ms | 288,3 KiB | 51 | 50 | 0 |
| 100 | 629,140 ms | 564,8 KiB | 101 | 100 | 0 |
| 200 | 2.086,695 ms | 1.105,8 KiB | 201 | 200 | 0 |

Nao foram observados crescimento descontrolado de memoria, travamento, perda de resultado ou consulta de peso. O teste de interface tambem valida a colagem e a pre-visualizacao local de 200 propostas sem chamada de rede.

## Tolerancia e consistencia

- Timeout e HTTP 429, 500 e 503 sao retentados e contabilizados.
- HTTP 401/403 interrompe o lote como falha global.
- Falhas permanentes permanecem isoladas por proposta/pagina.
- Cancelamento impede novas consultas e marca o restante sem gravacao parcial indevida.
- A persistencia revalida duplicidade imediatamente antes da escrita e trata corrida de duplicidade como resultado idempotente.
- Campos financeiros sao rejeitados antes da gravacao e nao aparecem no resultado preparado.
- Workers de consulta e persistencia encerram suas threads ao concluir, cancelar ou falhar.

## Configuracao final

- Tamanho de pagina: `50`.
- Vizinhas maximas na producao: `6` por direcao, somente quando a pagina estimada nao resolve.
- Varredura de compatibilidade: limitada a `50` paginas e usada apenas sem referencia numerica valida.
- Concorrencia maxima: `4`.
- Tentativas maximas por pagina: `3`.
- Esperas antes da segunda e terceira tentativas: `0,05 s` e `0,15 s`.
- Cache: memoria e ciclo de vida restritos a uma execucao do lote.
- Consulta de produto/peso no fluxo padrao: desativada.

## Reproducao

```powershell
python scripts/benchmark_nomus_import.py
$files = Get-ChildItem tests -Filter 'test_nomus*.py' | ForEach-Object FullName
python -m pytest -q $files
```

O benchmark em `scripts/benchmark_nomus_import.py` e os testes em `tests/test_nomus_phase6_performance.py` usam somente dados simulados e podem ser repetidos sem acesso ao Nomus.

## Resultado da regressao

A regressao ampliada da importacao, interfaces relacionadas, temas, geometria e bloqueio financeiro terminou com **151 testes aprovados**. O `git diff --check` e a compilacao dos modulos alterados tambem passaram.

A suite global avancou por mais de 800 testes e revelou pendencias externas a esta fase, ja existentes no worktree compartilhado:

- quatro testes de galvanizacao ainda esperam execucao sincrona, enquanto a tela atual grava em worker;
- a migration `20260817_0024_operational_query_indexes.py` nao possui checksum nem classificacao no registro de risco;
- um teste de selecao em lote de processos nao aplica o filtro de status/prazo esperado.

Essas pendencias nao atingem o fluxo Nomus e foram mantidas sem alteracao para evitar interferencia em implementacoes paralelas.
