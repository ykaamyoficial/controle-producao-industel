# Release API 0.10.0 e Desktop 2.8.0 (07/10/2026)

## O que entrou

- **API 0.10.0** (migration `20261006_0034`, ADDITIVE): endpoints `/sync/*` e
  WebSocket `/sync/ws` (base da réplica local), busca em `GET /proposals`,
  listas de Produção, Galvanização, Almoxarifado e Parciais com carga enxuta
  (`FASE7`), reuso de refresh token registrado uma vez por família e retenção
  diária dos dados de login (`FASE8`).
- **Desktop 2.8.0**: paginação do Controle Geral com busca em todas as propostas,
  cache dos indicadores de chat, agente de notificações que esquece o login
  recusado, correção do `QThread` destruído, réplica local **desligada por
  padrão** (`FASE2` a `FASE6`).
- Compatibilidade: `MINIMUM_DESKTOP_VERSION` (2.5.2) e `MINIMUM_API_VERSION`
  (0.8.1) inalterados. Desktops antigos operam contra a API nova; o Desktop novo
  opera contra a API antiga (sem a busca em todas as propostas).

## Defeito evitado pelo ensaio

A primeira imagem 0.10.0 não subia: `No module named 'greenlet'`. Causa:
`requirements.txt` declara faixas (`SQLAlchemy>=2.0,<3`) e uma construção nova
resolveu SQLAlchemy 2.1.3 (que não traz mais o `greenlet` sozinho) e mais ~15
bibliotecas diferentes das da imagem 0.9.0 em produção. Correção (`b9241d8`):
`api/requirements-lock.txt` (freeze da 0.9.0) usado como constraints no
Dockerfile e `SQLAlchemy[asyncio]` em `requirements.txt`. A imagem final tem
exatamente o mesmo conjunto de bibliotecas da 0.9.0.

## Execução (PRECHECK, DEPLOY, VERIFY)

| Etapa | Resultado |
|---|---|
| Versões | API 0.10.0 (`config.py`), Desktop 2.8.0 (`version.py`, `.iss`) |
| Imagem | `local/controle-producao-api:0.10.0`, commit `b9241d8`, identidade validada |
| Ensaio descartável com dados reais | downgrade/upgrade da migration sem perda (267 propostas); API saudável; 44 respostas de tela idênticas; `validate_release_image`: PASS (4 testes) |
| Backup de produção | `backups/prod_antes_0.10.0_20261007_1227.dump` (5 748 077 B, sha256 `d8eb5168…ba97`); restaurado em banco de teste com as 14 contagens idênticas à produção |
| Migration em produção | `20260908_0033 -> 20261006_0034`, `change_log` criada, 285 propostas intactas |
| Troca do contêiner | 12:29:03 a 12:29:21 (≈18 s), só a API; banco não reiniciado |
| VERIFY | `HEALTHY`, `server_version=0.10.0`, revisão `0034`, commit `b9241d8`; 0 erros no log; rotas novas respondem 401 sem login; desktops já atendidos (200 em renovação de login e contadores de chat) |
| Desktop 2.8.0 | `release/ControleProducao-2.8.0-update.zip` (sha256 `e1db512c…5ae82f84d` ) e `ControleProducaoSetup-2.8.0.exe`; sincronizado ao servidor em `READY` |

## Estado deixado

- **Desktop 2.8.0 NÃO autorizado.** O último autorizado continua sendo o 2.7.2;
  nenhum usuário recebe a atualização automática até autorizar:
  `authorize_release("2.8.0")` (`scripts/sync_release_to_server.py --authorize`
  roda no host do servidor; em produção, executar a chamada de serviço dentro do
  contêiner da API).
- `.env.production` (fora do git) com `SERVER_VERSION=0.10.0`.
- A imagem `local/controle-producao-api:0.9.0` segue disponível para rollback.

## Rollback da API (só se necessário)

1. Reverter a migration com a imagem **nova**, que tem o código da migration:
   `docker run --rm --network controle_producao_industel_default --env-file <DATABASE_URL> local/controle-producao-api:0.10.0 sh -c "cd /app/api && python -m alembic downgrade 20260908_0033"`
   (apenas apaga `change_log`; testado no ensaio, sem perda de dados).
2. `SERVER_VERSION=0.9.0` em `.env.production` e
   `docker compose --env-file .env.production -f docker-compose.prod.yml up -d --no-deps api`.
3. Sem o passo 1 a API 0.9.0 sobe, mas se declara `UNHEALTHY` (a revisão do banco,
   `0034`, é mais nova do que ela conhece).
4. Em último caso, restaurar `backups/prod_antes_0.10.0_*.dump`.

## Pendências

- Autorizar o Desktop 2.8.0 depois de conferido em um computador.
- Primeira passada da retenção diária, 5 minutos após o início da API; conferir
  `auth_retention_concluida` no log.
- Acompanhar `TOKEN_REUSE_DETECTED` por dia: deve cair para perto de zero com o
  servidor novo (repetições deixam de gravar) e, depois, com o agente novo.
- Os usuários continuam com a versão 2.7.x do agente de notificações até
  atualizarem.
- Imagem local (`local/`), sem registro remoto: não há digest imutável.
- A suíte da API precisa de `-o timeout=120` e dos 3 testes antigos que falham
  (dois 503 de inicialização e um de auditoria) seguem abertos.
