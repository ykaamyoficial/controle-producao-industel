# API Auth Security

## Objetivo

Esta etapa cria a base de autenticacao, autorizacao, sessoes e auditoria de seguranca da API FastAPI usando PostgreSQL. O desktop continua com login legado em SQLite e nao foi integrado nesta etapa.

## Modelagem

A API usa RBAC simples e expansivel:

```text
users
  -> user_roles
roles
  -> role_permissions
permissions
```

Nao foram criadas permissoes avulsas por usuario nesta etapa. O sistema legado possui permissoes por area no SQLite, mas a API precisa primeiro centralizar perfis e permissoes tecnicas estaveis. Permissoes individuais podem ser adicionadas no futuro se houver necessidade real.

## Mapeamento SQLite Futuro

| Atual no SQLite | Futuro na API |
| --- | --- |
| `usuarios.login` | `users.username` normalizado |
| `usuarios.senha_hash` / `senha_salt` | novo `users.password_hash` Argon2id |
| `usuarios.perfil` | `roles` |
| `usuarios.areas_acesso` | futuras permissoes funcionais |
| `usuario_permissoes` por area | `role_permissions` e, se necessario depois, permissoes por usuario |
| sessao em memoria no desktop | access token JWT + refresh token opaco |
| regras administrativas no desktop | regras centralizadas nos services da API |

Senhas legadas nao foram migradas nem copiadas.

## Fluxo de Login

`POST /api/v1/auth/login` recebe usuario e senha. A API normaliza o login, valida senha com Argon2id, aplica bloqueio temporario por falhas, cria sessao persistente e retorna:

- access token JWT curto;
- refresh token opaco;
- dados publicos do usuario;
- perfis e permissoes efetivas.

A resposta de credenciais invalidas e generica para evitar enumeracao de usuarios.

## Fluxo de Refresh

`POST /api/v1/auth/refresh` recebe o refresh token opaco. A API salva apenas o hash SHA-256 desse token, procura a sessao ativa, valida expiracao e usuario ativo, revoga o token antigo e emite um novo par de tokens.

## Fluxo de Logout

`POST /api/v1/auth/logout` revoga a sessao associada ao refresh token informado. `POST /api/v1/auth/logout-all` revoga todas as sessoes ativas do usuario autenticado.

## Rotacao e Reutilizacao

Refresh tokens sao rotativos. Quando um token ja revogado e reutilizado, a API registra `TOKEN_REUSE_DETECTED` e revoga toda a familia do token.

## Hash de Senha

Senhas usam Argon2id via `argon2-cffi`, com salt automatico e suporte a rehash. Senhas nao sao registradas em log, nao retornam em schemas e nao ficam em texto simples.

## Politica de Senha

Politica inicial:

- minimo configuravel (`PASSWORD_MIN_LENGTH`), padrao 10 caracteres; o piso aceito pela configuracao e 4, usado so no compose de dev (`docker-compose.dev.yml`); producao fica em 10 (`docker-compose.prod.yml`);
- maximo configuravel, padrao 256 caracteres;
- permite frases-senha;
- bloqueia senhas evidentemente fracas;
- nao normaliza caixa nem remove espacos internos.

## RBAC e Permissoes

Permissoes criadas nesta etapa:

- `users.view`
- `users.create`
- `users.update`
- `users.disable`
- `users.manage_permissions`
- `roles.view`
- `roles.create`
- `roles.update`
- `roles.manage_permissions`
- `permissions.view`
- `audit.view`
- `system.admin`

Permissoes funcionais de propostas, producao, galvanizacao, expedicao, almoxarifado e fiscal foram apenas planejadas para etapas futuras.

## Sessoes

`auth_sessions` guarda usuario, hash do refresh token, familia do token, expiracao, revogacao, IP e user agent. Alteracao de senha, desativacao e logout podem revogar sessoes.

## Bloqueio de Conta

Falhas de login incrementam contador persistido no usuario. Ao atingir `LOGIN_MAX_FAILED_ATTEMPTS`, a conta recebe `locked_until` por `LOGIN_LOCK_MINUTES`. Login valido limpa contador e bloqueio.

## Limite de Falhas por IP

Alem do bloqueio por conta, `POST /api/v1/auth/login` limita falhas por IP (`api/app/modules/auth/ip_rate_limit.py`): janela deslizante em memoria em que so falhas contam (sucesso nao conta nem zera). Ao passar de `LOGIN_IP_MAX_FAILURES` (padrao 20, `0` desliga) em `LOGIN_IP_WINDOW_SECONDS` (padrao 300), a API responde 429 `LOGIN_RATE_LIMITED` com `Retry-After`. Limites conhecidos: o contador e por processo (reiniciar a API zera; com varias replicas o limite real e multiplo) e, atras do `cloudflared`, o IP visto e o do proxy, entao os clientes do tunel dividem o mesmo balde. O limite por IP real deve ficar no WAF/Cloudflare.

## Superficie Publica em Producao

- `/docs`, `/redoc` e `/openapi.json` so abrem com `APP_ENV` em `development`, `dev`, `test` ou `local` (`Settings.docs_enabled`); qualquer outro valor (`production`, `prod`, `staging`, vazio) fecha (fail-closed, `api/app/main.py`).
- `GET /api/v1/system/compatibility` e de leitura publica (o preflight do Desktop roda antes do login), mas nao registra nada para chamada anonima: o heartbeat e a auditoria da instalacao so acontecem com Bearer valido.

## Auditoria de Seguranca

`security_events` registra eventos administrativos e de autenticacao sem senha, token ou hash. Eventos minimos implementados incluem login, falha, bloqueio, refresh, reutilizacao, logout, usuario, perfil, permissao e bootstrap.

## Bootstrap do Administrador

### Usuario `admin` no startup

No startup a API chama `ensure_default_admin()` (`api/app/modules/auth/bootstrap.py`). Nao existe senha fixa no codigo. Regras:

- se o usuario `admin` ja existe, nao toca em nada, mesmo desativado, sem superusuario ou com senha trocada: nunca redefine senha, nunca reativa, nunca recoloca `is_superuser` nem `password_must_change`;
- se o `admin` nao existe e `BOOTSTRAP_ADMIN_PASSWORD` esta definida, cria o `admin` uma vez, superusuario, com perfil `admin` e `password_must_change=True`;
- se o `admin` nao existe e a variavel esta vazia, nao cria e registra um aviso no log, sem valores;
- a senha nunca vai para o log.

Defina `BOOTSTRAP_ADMIN_PASSWORD` so no `.env` local (fora do git) ou no ambiente do container, com placeholder no `.env.example`. Depois da primeira subida ela pode ser apagada. Hoje `password_must_change` vai na resposta do login e do `/auth/me`, mas nem a API nem o Desktop obrigam a troca: nenhuma rota bloqueia e o Desktop so guarda o valor.

### Criacao manual

O primeiro administrador tambem pode ser criado manualmente:

```bat
scripts\create_api_admin.bat
```

O script executa:

```bash
python -m api.app.cli create-admin
```

Regras:

- nao roda no startup;
- exige `SECRET_KEY` forte;
- exige banco na revisao esperada;
- falha se ja existe administrador ativo;
- solicita senha sem eco no terminal (o script nao tem senha embutida);
- pode usar variaveis (`API_BOOTSTRAP_PASSWORD`) apenas para automacao de testes.

## Endpoints

Autenticacao:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/logout-all`
- `GET /api/v1/auth/me`

Usuarios:

- `GET /api/v1/users`
- `GET /api/v1/users/{id}`
- `POST /api/v1/users`
- `PATCH /api/v1/users/{id}`
- `POST /api/v1/users/{id}/activate`
- `POST /api/v1/users/{id}/deactivate`
- `POST /api/v1/users/{id}/reset-password`
- `POST /api/v1/users/{id}/roles`
- `DELETE /api/v1/users/{id}/roles/{role_id}`

Perfis e permissoes:

- `GET /api/v1/roles`
- `GET /api/v1/roles/{id}`
- `POST /api/v1/roles`
- `PATCH /api/v1/roles/{id}`
- `POST /api/v1/roles/{id}/permissions`
- `DELETE /api/v1/roles/{id}/permissions/{permission_id}`
- `GET /api/v1/permissions`

Auditoria:

- `GET /api/v1/security-events`
- `GET /api/v1/security-events/{id}`

## Variaveis de Ambiente

```env
SECRET_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCK_MINUTES=15
PASSWORD_MIN_LENGTH=10
LOGIN_IP_MAX_FAILURES=20
LOGIN_IP_WINDOW_SECONDS=300
PASSWORD_MAX_LENGTH=256
JWT_ISSUER=controle-producao-api
JWT_AUDIENCE=controle-producao-clients
BOOTSTRAP_ADMIN_PASSWORD=
```

Com banco configurado e revisao compativel, `/api/v1/system/ready` considera a API nao pronta quando `SECRET_KEY` esta ausente ou tem menos de 32 caracteres.

## Migration

Migration criada:

```text
20260720_0002_create_auth_security.py
```

Ela cria `users`, `roles`, `permissions`, `user_roles`, `role_permissions`, `auth_sessions` e `security_events`, alem das permissoes oficiais. Nao usa `create_all()` e nao roda automaticamente no startup.

## Docker

Runtime oficial:

```text
Windows -> HTTP -> API Docker -> PostgreSQL Docker
```

Comandos principais:

```bat
scripts\start_dev_environment.bat
scripts\run_api_migrations.bat
scripts\run_api_tests.bat
scripts\run_api_integration_tests.bat
scripts\create_api_admin.bat
```

## Testes

A etapa inclui testes unitarios para senha/tokens/permissoes e testes HTTP/PostgreSQL para login, refresh, reutilizacao, RBAC, auditoria e protecao do ultimo administrador.

## Limitacoes

- Sem migracao de usuarios SQLite.
- Sem integracao do desktop.
- Sem armazenamento seguro do refresh token no cliente desktop.
- Limite de login por IP e em memoria, por processo, e enxerga o IP do proxy atras do tunel (ver "Limite de Falhas por IP"); sem rate limit distribuido.
- Sem chave assimetrica para JWT.
- Sem modulos produtivos de propostas, producao ou expedicao.

## Futuro Desktop

Quando chegar a hora, o desktop deve consumir `/auth/login`, guardar refresh token usando armazenamento seguro do Windows e chamar apenas endpoints REST. O desktop nao deve receber credenciais do PostgreSQL.

## Futuro Usuarios SQLite

Alternativa recomendada: migrar usuarios sem copiar senha e exigir redefinicao controlada. Rehash progressivo so deve ser considerado se houver decisao formal para validar hash legado na API.

## Proxima Etapa

Recomenda-se integrar primeiro consultas de baixo risco:

- health;
- version;
- sessao autenticada;
- `/auth/me`;
- permissoes efetivas.

Depois disso, planejar substituicao gradual do login legado.
