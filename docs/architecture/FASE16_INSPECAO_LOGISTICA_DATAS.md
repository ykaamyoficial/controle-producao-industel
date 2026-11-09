# Fase 16 — Datas na Inspeção e na Logística

Spec: `docs/spec-inspecao-logistica.md` (D1 a D18 seguem valendo; seção "Datas (decisões de 2026-11-08)"). Fase 7 do spec fica fora do escopo. Desenvolvido e testado só no ambiente de dev (API 8001); **nada foi aplicado na API oficial (8000)**.

## Objetivo

- Tratar datas da Inspeção e da Logística com aviso e nunca com bloqueio: a pessoa sempre pode marcar mesmo assim ou escolher outra data.
- Dia útil de Goiás/Goiânia (seg a sex, menos feriados) e "hoje" no fuso America/Sao_Paulo.
- Reserva do LOG e entrega no CD como a mesma data; saída da carga como carregamento.
- Correção de data gravada com histórico "de X para Y" e motivo; histórico nunca é apagado.

## Implementação

- API: LOG vazio não entra em carga (código `LOGISTICS_LOG_EMPTY`, HTTP 409) e é excluído ao sair dela, com histórico na auditoria (`125f2ec`). A auditoria do LOG excluído passou a guardar datas e links (`bbeb04c`).
- Desktop: avisos de data em painel na própria janela, com "Marcar mesmo assim" e "Escolher outra data" (`c569074`, `d354339`); aviso de data rola para a vista; trocar a etapa no primeiro passo recarrega a tela; reprovar a última proposta pede confirmação (`b2b3c65`).
- Desktop: "hoje" calculado no fuso America/Sao_Paulo (`f615467`). `tzdata` incluído em `requirements.txt` e em `ControleProducao.spec` (`69c1119`).
- API: feriados nacionais e de GO/Goiânia pela biblioteca `holidays` (`fc33022`), base do dia útil.
- API: revisão esperada do banco (`EXPECTED_DATABASE_REVISION`) atualizada para `20261108_0046` (`606ee18`).
- Testes: catch-up de inspeção usa PD semeada e NQT/visita próprios (`504d150`); testes de histórico na auditoria da exclusão de LOG vazio e da carga (`fa59f34`) e de entrega/comprovante (`6734696`).
- Séries anteriores da fase: F1 a F5 de datas, carga e entrega real (`f4c82ed`, `b17c353`, `a3f8dd4`, `39f0a26`, `5deeabf`; Desktop em `d354339`, `9cef0e3`, `6abf8d9`, `393ae8c`; API em `51f7a48`).

## Garantias

1. Nenhuma regra de data bloqueia. Só avisa, com "Marcar mesmo assim" ou "Escolher outra data". Únicos impedimentos: data inexistente (ex.: 31/02) e campo obrigatório vazio.
2. Sem alerta de prazo (D7). Os dias na etapa são só contagem.
3. Dia útil: segunda a sexta, menos feriados nacionais, de GO e de Goiânia. Carnaval e Corpus Christi não param a fábrica. Sábado não é dia útil.
4. Sem folga mínima: só conflito no mesmo dia gera aviso.
5. Data reservada do LOG = entrega no CD; saída da carga = carregamento. A tela preenche igual; a API avisa (`RESERVED_DIFFERS_FROM_DELIVERY`) se divergir, sem bloquear.
6. Nenhum campo extra além de observação livre (ver pendência sobre o link do comprovante).
7. Data gravada pode ser corrigida depois, com histórico "de X para Y" e motivo. Histórico nunca é apagado.
8. "Hoje" é calculado no fuso America/Sao_Paulo.
9. D1 a D18 do spec continuam valendo; Fase 7 fora do escopo.

## Validação

Desktop:

```
python -m pytest tests -q -rs -p no:cacheprovider --timeout=25 --timeout-method=thread
```

Resultado: **2349 passed, 0 failed, 21 skipped, 511,5 s**. Skips: 13 + 6 de PDF modelo ausente, 1 de PDFs reais locais ausentes, 1 com `DESKTOP_API_INTEGRATION=1` ausente.

API:

```
APP_ENV=test POSTGRES_TEST_DATABASE_URL=<banco de teste em 127.0.0.1:55440> python -m pytest api/tests -q -rs -p no:cacheprovider --timeout=25 --timeout-method=thread
```

Resultado: **1462 passed, 6 failed, 2 skipped, 4574 s (1h16)**. O banco de teste é o Postgres local do container `cp_test_pg_tmp`; credenciais não são registradas aqui.

- As 6 falhas são conhecidas e anteriores à fase: `test_deployment_rollback_integration` (2, "container inicial nao ficou healthy"), `test_docker_release_integration` (1, "container nao ficou healthy"), `test_replica_views_parity` (2, dict sem `requires_inspection`), `test_update_audit_router` (1, `0 != 1`).
- Skips: backup/restore real sem `pg_dump`/`pg_restore` (1) e dump manual (1).

Targeted, com banco:

```
APP_ENV=test POSTGRES_TEST_DATABASE_URL=<banco de teste em 127.0.0.1:55440> python -m pytest api/tests/test_inspection.py api/tests/test_logistics.py -q -p no:cacheprovider --timeout=25 --timeout-method=thread
```

Resultado: **53 passed, 0 skipped**. Depois dos dois últimos commits, `api/tests/test_logistics.py` sozinho: **33 passed, 0 skipped**.

```
python -m pytest tests/test_local_today.py -q -p no:cacheprovider --timeout=25 --timeout-method=thread
```

Resultado: **1 passed**.

Migrations:

```
python scripts/check_migration_safety.py      # EXIT=0
python scripts/check_migration_checksums.py   # EXIT=0
```

Observação: a suíte completa foi rodada **antes** de `69c1119` e `6734696` (mudaram `requirements.txt`/`ControleProducao.spec` e um teste). Esses dois foram verificados só pelos testes citados acima.

Nota: no Windows, usar `127.0.0.1` e não `localhost` na URL do banco. `localhost` custou cerca de 2 s por conexão e estourou o timeout de 25 s.

## Auditoria

Auditoria independente (Sonnet), em 2 rodadas: 0 ALTA.

- MÉDIA corrigidas: fuso do Desktop (`f615467`); asserts de histórico (`fa59f34`).
- MÉDIA da re-auditoria corrigida: `tzdata` ausente (`69c1119`).
- BAIXAS corrigidas: auditoria do LOG excluído sem datas (`bbeb04c`); assert incompleto (`6734696`).
- Achado e corrigido: revisão esperada do banco desatualizada, com 18 testes falhando (`606ee18`).

## Pendência encontrada

Não corrigidas nesta fase:

- (a) Novo LOG com "data pedida estava disponível" não envia a reservada e pode avisar `RESERVED_DIFFERS_FROM_DELIVERY` sem o usuário ter escolhido divergir.
- (b) `POST /loads/{id}/logs` com `confirm_dates` não tem tela no Desktop.
- (c) `LOGISTICS_LOG_EMPTY` não tem tratamento nem teste próprios no Desktop (aparece a mensagem da API). A tela Nova carga ainda lista LOG aprovado sem propostas.
- (d) `date.today()` restante fora do escopo: `historico_tab.py`, `galvanization_load_dialog.py`, `backend_adapter.py`, `api_reports.py`, `modern_table.py`.

Outras pendências:

- Testes que pulam: ver Validação (21 no Desktop, 2 na API).
- Feriados municipais de Goiânia: o código cobre 24/05 (Nossa Senhora Auxiliadora) e 24/10 (aniversário/pedra fundamental). Não foi conferido com lei oficial. Feriados do município do CD não estão cobertos.
- Fuso conferido só em teste.
- Nenhuma tela aberta na dev (8001) com dados reais.
- Build do PyInstaller com `tzdata` não rodado.
- Decisões para o Henrique:
  - O campo `delivery_proof_link` (link do comprovante) é extra além da observação livre (princípio 6).
  - 26/07 "Fundação da cidade de Goiás" vem da lib `holidays` para GO e hoje conta como dia parado.
  - Reenviar a mesma data devolve 422 "não mudou". É uma recusa: hoje não vira 200 sem alteração.

## Conclusão

Datas da Inspeção e da Logística tratadas como aviso, com dia útil de GO/Goiânia, "hoje" no fuso de São Paulo e correção com histórico. Validado só na API de dev e em testes. Falta conferir a tela com dados reais antes de qualquer uso, e nada vai à oficial sem autorização.
