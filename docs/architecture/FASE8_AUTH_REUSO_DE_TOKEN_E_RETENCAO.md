# Fase 8 — Reuso de refresh token em laço e retenção dos dados de login

## Origem

Ao medir o crescimento de `auth_sessions` e `security_events` (Fase 7, "Índices"),
a cópia dos dados de produção mostrou 87 335 eventos de segurança e 15 868
sessões de login para 8 usuários. A composição dos eventos:

| Tipo | Linhas | Parte |
|---|---:|---:|
| `TOKEN_REUSE_DETECTED` | 68 052 | 78% |
| `TOKEN_REFRESHED` | 15 698 | 18% |
| Todo o resto (logins, ações de produção, galvanização, expedição) | ~3 600 | 4% |

Os eventos de reuso eram 5 000 a 6 600 por dia, de 3 usuários, todos do
`ControleProducaoIndustel/desktop-api-client`, com mediana de **22 s** entre
eventos do mesmo usuário, 24 h por dia. Isso é um laço, não uso humano.

## Causa

O agente de notificações da bandeja (`app/services/notifier_agent.py`) guardava
o refresh token mesmo depois de o servidor recusá-lo (expirado, revogado ou
reutilizado) e o reapresentava em dois laços independentes:

- ciclo de busca, a cada 60 s (`_fetch_notifications`);
- reconexão do websocket, a cada 1–30 s (`_NotifierRealtime._connect`).

`1/30 + 1/60 = 1 tentativa a cada 20 s`, contra os 22 s observados. Cada
tentativa com um token já revogado gerava um evento e revogava de novo a
família. A suposição é inferida do código e dos dados; **não foi reproduzida em
uma máquina de usuário**. Na versão instalada nesta máquina o comportamento é
saudável (11 renovações em 06/10, a cada ~13 min).

## Implementação

- `api/app/modules/auth/service.py` — `refresh`: um token já marcado
  `reuse_detected` é recusado com o mesmo erro (`REFRESH_TOKEN_REUSED`) **sem
  gravar** evento nem reescrever a revogação. O primeiro reuso de cada família
  continua revogando tudo e gerando um evento. Protege o banco dos programas
  antigos em campo, que só param ao atualizar.
- `app/services/notifier_agent.py` — `_refresh_or_forget`: se a renovação for
  recusada (`ApiAuthenticationError`, incluindo `ApiSessionExpiredError`), apaga
  o token local e repassa o erro; usado no ciclo de busca, em "marcar todas como
  lidas" e na reconexão do websocket. Sem token guardado, a reconexão passa a só
  olhar o arquivo a cada 30 s (sem rede), para reconectar depois do próximo
  login. Falhas de rede, tempo esgotado e servidor fora do ar **não** apagam o
  token.
- `api/app/modules/auth/retention.py` — `purge_auth_data` e
  `run_retention_loop`: apaga, em lotes de 1 000 com commit por lote, apenas
  - sessões de login **expiradas** e sem atividade (`coalesce(revogada_em,
    expira_em)`) há mais de 30 dias;
  - eventos `TOKEN_REFRESHED` e `TOKEN_REUSE_DETECTED` com mais de 30 dias.
  Nunca apaga login, logout, troca de senha nem ações de negócio.
- `api/app/main.py` — uma passada por dia, a primeira 5 minutos depois do
  startup; `AUTH_RETENTION_ENABLED=false` desliga.
- `api/app/core/config.py` — `AUTH_RETENTION_ENABLED`,
  `AUTH_SESSION_RETENTION_DAYS` (30, mínimo 7), `SECURITY_TOKEN_EVENT_RETENTION_DAYS`
  (30), `AUTH_RETENTION_INTERVAL_HOURS` (24).
- `api/app/cli.py` — `python -m api.app.cli purge-auth-data [--apply]
  [--session-days N] [--token-event-days N]`: por padrão **só conta**; `--apply`
  apaga.
- Testes: `api/tests/test_auth_retention.py` e `tests/test_notifier_dead_token.py`.

## Garantias

1. O mesmo token morto, apresentado várias vezes, gera no máximo um evento de
   reuso e nenhuma escrita depois do primeiro.
2. O primeiro reuso de uma família continua revogando todas as sessões dela e
   registrando o evento; um novo login depois disso abre uma sessão saudável.
3. O agente de notificações nunca reapresenta um token que o servidor recusou;
   depois da recusa, ciclos e reconexões não fazem requisição.
4. Falha de rede ou servidor não apaga o login guardado.
5. A retenção só apaga sessões já expiradas e eventos de token antigos; sessão
   ativa, sessão revogada mas ainda dentro da validade, e qualquer evento que não
   seja de token ficam, seja qual for a idade.
6. `purge-auth-data` não apaga nada sem `--apply`; a rotina diária é idempotente
   e funciona em lotes.

## Validação

```
python -m compileall -q app api/app
python -m pytest tests/test_notifier_dead_token.py tests/test_notifier_agent.py -q
python -m pytest api/tests/test_auth_retention.py -q
python -m pytest tests -q
python -m pytest api/tests -q --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py
```

- Agente: `26 passed` (8 novos testes e 18 já existentes; os novos incluem "10
  reconexões e 5 ciclos depois da recusa não fazem nenhuma requisição").
- Servidor, reuso e retenção: `9 passed` (PostgreSQL 17 descartável).
- Desktop, suíte completa: `1645 passed, 21 skipped` (sem falhas).
- API, suíte completa (PostgreSQL 17 descartável): `3 failed, 1019 passed, 2 skipped`.
  As 3 falhas são as já registradas nas fases anteriores (dois 503 de
  inicialização e um de auditoria de atualização); os dois arquivos de build
  Docker não foram executados.

## Pendência encontrada

- **Efeito da retenção na primeira passada é pequeno:** na cópia de produção só
  562 eventos (de qualquer tipo) têm mais de 30 dias; o grosso (72 mil com mais de 7 dias) sai
  conforme envelhece. O alívio real vem de parar a geração (servidor + agente).
- **Programas já instalados continuam gerando o ruído** até atualizarem; só a
  correção do servidor os alcança antes disso.
- **Hipótese não reproduzida em campo:** vale conferir, depois do release, se
  `TOKEN_REUSE_DETECTED` por dia cai para perto de zero.
- **`change_log` da réplica** (Fase 6 do plano da réplica) ainda não tem
  expurgo; fica para quando a réplica for ligada em produção.
- **Condição de corrida entre o agente e o app** (os dois renovam o mesmo
  refresh token em processos separados) não foi alterada; só o laço do token
  morto foi tratado.
