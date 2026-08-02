# Desktop API Client

## Objetivo

Esta etapa adiciona ao desktop um cliente HTTP experimental para validar a API REST sem substituir o login oficial, sem migrar dados e sem mudar a autoridade atual do SQLite.

## Arquitetura

```text
Desktop PySide6
  -> cliente HTTP isolado
  -> API REST FastAPI
  -> PostgreSQL
```

O desktop nao conhece credenciais do PostgreSQL e nao acessa o banco diretamente.

## Limites da Etapa

- Login legado permanece oficial.
- SQLite permanece oficial.
- Nenhuma proposta, usuario legado ou modulo produtivo foi migrado.
- Permissoes da API sao usadas somente para diagnostico.
- Integracao fica desabilitada por padrao.

## Estrutura do Cliente

```text
app/integrations/api/
  client.py
  config.py
  exceptions.py
  models.py
  auth_client.py
  system_client.py
  token_store.py
  compatibility.py
  session.py
```

As telas nao chamam HTTP diretamente; elas usam os clientes e a sessao experimental.

## Configuracao

Configuracao local em `desktop_api` no JSON do aplicativo:

```json
{
  "enabled": false,
  "base_url": "http://127.0.0.1:8000",
  "connect_timeout": 3,
  "read_timeout": 10
}
```

HTTP e permitido apenas para `localhost`, `127.0.0.1` e `::1`. Servidores reais devem usar HTTPS.

## Timeouts

O cliente usa timeouts separados de conexao e leitura via `httpx.Timeout`.

## Retries

Retries curtos existem apenas para GETs idempotentes:

- `/api/v1/system/health`
- `/api/v1/system/ready`
- `/api/v1/system/version`
- `/api/v1/auth/me`

POSTs de login, refresh e logout nao sao repetidos automaticamente.

## Request ID

Cada chamada envia `X-Request-ID`. O ID retornado pela API e mantido no resultado e usado em mensagens de suporte quando ha erro.

## Tratamento de Erros

Erros sao convertidos para excecoes locais:

- `ApiConnectionError`
- `ApiTimeoutError`
- `ApiUnavailableError`
- `ApiCompatibilityError`
- `ApiAuthenticationError`
- `ApiPermissionError`
- `ApiSessionExpiredError`
- `ApiValidationError`
- `ApiUnexpectedResponseError`

Mensagens tecnicas sao sanitizadas para nao registrar tokens ou senhas.

## Compatibilidade

`/api/v1/system/version` agora informa:

- `minimum_desktop_version`
- `maximum_desktop_version`
- `supported_features`

O desktop valida recursos obrigatorios sem exigir igualdade exata de versao.

## DPAPI

O refresh token experimental e salvo em `desktop_api_refresh_token.dpapi`, usando a mesma abordagem DPAPI da integracao Nomus. O blob protegido e vinculado ao usuario do Windows. Em outro perfil do Windows, a descriptografia pode falhar e a sessao local deve ser limpa.

## Sessao em Memoria

A sessao experimental guarda apenas:

- access token;
- expiracao do access token;
- usuario autenticado;
- perfis;
- permissoes;
- indicador de sessao ativa.

O refresh token nao fica exposto no objeto de sessao; ele e acessado via `ApiTokenStore`.

## Login Experimental

O dialogo `Diagnostico da API` permite login experimental com usuario/senha da API. A senha nao e salva e o campo e limpo ao final. Esse login nao altera o usuario legado atual.

## Refresh

`ExperimentalApiSession.refresh_if_needed` renova quando o access token esta proximo do vencimento ou quando for forcado pelo diagnostico. Um lock impede refresh simultaneo.

## Logout

O diagnostico permite logout e logout-all. Mesmo em falha remota, a limpeza local pode ser feita por `Limpar local`.

## Permissoes

`has_api_permission("users.view")` existe somente na sessao experimental. Nesta etapa ele serve para diagnostico e testes, nao para liberar acoes do desktop.

## Threads

A tela usa `start_worker`, baseado em `QThread`, para manter chamadas HTTP fora da thread principal do PySide6.

## Logs

Logs registram metodo, rota, status, duracao e request ID. Nao registram Authorization, senha, access token, refresh token nem corpo completo de login.

## Feature Flag

`desktop_api.enabled` fica `false` por padrao. Apenas administrador legado ve a tela de diagnostico e pode ativar a integracao experimental.

## Diagnostico

Tela adicionada:

```text
Configuracoes -> Integracao com API do sistema -> Diagnostico da API
```

Exibe URL, flag, timeouts, status do ultimo teste, health, readiness, compatibilidade, usuario autenticado e permissoes. Nao exibe tokens.

## Testes

Foram criados testes unitarios para configuracao, URL, headers, request ID, timeouts, conexao recusada, mapeamento HTTP, resposta invalida, DPAPI mockado, refresh token substituido, sessao e compatibilidade.

Tambem ha teste de integracao opcional `tests/test_desktop_api_integration.py`, habilitado por:

```bat
set DESKTOP_API_INTEGRATION=1
set DESKTOP_API_BASE_URL=http://127.0.0.1:8000
set DESKTOP_API_USERNAME=admin
set DESKTOP_API_PASSWORD=...
python -m pytest tests/test_desktop_api_integration.py
```

## Offline

API indisponivel nao bloqueia o desktop. A falha aparece apenas no diagnostico e nao inicia loops em segundo plano.

## Limitacoes

- Sem substituicao do login.
- Sem migracao de usuarios.
- Sem monitoramento continuo.
- Sem configuracao de servidor corporativo em instalador.
- Sem alta disponibilidade validada em rede local.

## Riscos

- Maquinas antigas podem nao ter a mesma configuracao de rede.
- DPAPI depende do perfil do Windows.
- API local Docker nao representa ainda o servidor final da empresa.

## Criterios Para Substituir o Login Legado

Antes de substituir o login, sera necessario validar alta disponibilidade da API, armazenamento seguro em todos os computadores, migracao de usuarios, rollback, recuperacao administrativa, configuracao por instalador e plano de indisponibilidade.

## Proxima Etapa Recomendada

Decidir entre migrar usuarios legados e trocar o login, ou migrar primeiro um modulo somente leitura de baixo risco.
