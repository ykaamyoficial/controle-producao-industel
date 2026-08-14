# Fase 2 - Configuracao Central do Desktop

## Objetivo

Garantir que todo o Desktop conheça o endereço da API oficial do sistema por
uma única fonte de verdade (`API_BASE_URL`), em vez de constantes espalhadas
por módulos, preparando o terreno para a Fase 3 (primeiro acesso automático).

## Diagnóstico encontrado (antes desta fase)

Diferente do cenário "ANTES" hipotético do prompt técnico (Login, Produção,
Fiscal e Relatórios cada um com sua própria constante), a auditoria mostrou
que o Desktop **já era** arquiteturalmente centralizado, de fases anteriores
do projeto:

- `app/integrations/api/config.py` — `DesktopApiConfigStore` já é a única
  classe que lê/grava o endereço da API (`load_settings()`/`save_settings()`),
  persistido na chave `desktop_api.base_url` do config.json via
  `ConfigurationService`.
- `app/services/api_proposal_storage.py` (usado por **todos** os módulos de
  negócio — propostas, produção, galvanização, expedição, fiscal, chat,
  almoxarifado) já obtém a URL exclusivamente de
  `self.config_store.load_settings()`, sem nenhuma constante própria.
- Login (`BackendService.authenticate`) usa o mesmo `official_proposal_storage`
  — não existe uma URL separada para autenticação.
- WebSocket de chat (`app/ui/chat_realtime.py`) já deriva `ws://`/`wss://` a
  partir da mesma `DesktopApiConfigStore().load_settings().base_url`.
- Persistência já fica fora de `Program Files` e fora da pasta que o
  atualizador substitui: em instalação empacotada,
  `C:\ProgramData\Industel\ControleProducao\controle_producao_config.json`
  (`app/services/app_paths.py`); em desenvolvimento,
  `app/config/controle_producao_config.json`.
- O arquivo de configuração já não guarda segredos — `save_settings()` grava
  apenas `enabled`, `base_url`, timeouts e resultado do último teste.

**Gaps reais encontrados** (os únicos pontos alterados nesta fase):

1. `normalize_api_base_url()` exigia HTTPS para qualquer host que não fosse
   `localhost`/`127.0.0.1`/`::1`. Isso rejeitaria exatamente o endereço LAN
   oficial definido na Fase 1 (`http://<IP_DO_SERVIDOR>:8000`), contrariando
   o exemplo "VÁLIDO" explícito do prompt técnico da Fase 2 (seção 8).
2. `0.0.0.0` não era rejeitado de forma confiável: só era bloqueado
   incidentalmente sob `http` (pela mesma regra acima) e continuava aceito
   sob `https://0.0.0.0`.
3. Não existia a camada de override por variável de ambiente prevista na
   precedência recomendada (seção 6) — só existia dentro de um teste de
   integração isolado (`tests/test_desktop_api_integration.py`), sem afetar
   o fluxo real do aplicativo.

Não havia URLs da API interna hardcoded em telas/serviços de negócio: as
únicas ocorrências de `127.0.0.1:8000` no repositório são defaults
declarados centralmente (ver "Auditoria final de hardcodes").

## Alterações realizadas

`app/integrations/api/config.py`:

- `normalize_api_base_url(value)` — assinatura simplificada (removido o
  parâmetro `allow_http_local`, que nenhum chamador real usava com `False`).
  Agora aceita `http`/`https` para qualquer host válido (IP de LAN ou nome
  DNS interno), e rejeita explicitamente `0.0.0.0` em qualquer esquema, com
  mensagem clara ("endereço de bind do servidor").
- `DesktopApiConfigStore.load_settings()` — passa a checar a variável de
  ambiente `DESKTOP_API_BASE_URL` (mesmo nome já usado pelo teste de
  integração) e, se definida e não vazia, sobrescreve apenas `base_url` (o
  restante da configuração persistida — `enabled`, timeouts — não muda). O
  uso do override é logado, sem nunca logar credenciais.

## Regra de precedência (documentada e testada)

1. Configuração persistente oficial (`desktop_api.base_url` no
   `controle_producao_config.json`), com default de fábrica
   `http://127.0.0.1:8000` quando a chave ainda não existe.
2. Override explícito de ambiente `DESKTOP_API_BASE_URL`, apenas para
   desenvolvimento/testes/suporte técnico — substitui somente a URL, nunca o
   restante da configuração persistida.

Não há um terceiro nível de fallback de desenvolvimento além do default de
fábrica acima: como o próprio default já é `127.0.0.1:8000`, ele cumpre esse
papel sem precisar de uma camada extra.

## Local de persistência

Reaproveitado o mecanismo já existente (`app/services/app_paths.py`), sem
alterações:

- Empacotado (`sys.frozen`): `%ProgramData%\Industel\ControleProducao\controle_producao_config.json`.
- Desenvolvimento: `app/config/controle_producao_config.json`.

Ambos ficam fora de `Program Files` e fora de qualquer pasta que o
atualizador substitua.

## Consumidores confirmados na configuração central

- Login/autenticação (`BackendService.authenticate` → `official_proposal_storage` → `ExperimentalApiSession`/`AuthApiClient`).
- Todos os módulos de negócio via `api_proposal_storage.py` (propostas,
  produção, galvanização, cargas, retorno, expedição, fiscal, almoxarifado,
  chat, notificações, usuários/permissões).
- Diagnóstico da API (`app/ui/api_diagnostic_dialog.py`), diálogo de
  propostas somente leitura, diálogo de auditoria de atualizações.
- Verificação de compatibilidade no startup (`app/main.py`).
- Cliente/coordenador de distribuição de atualizações
  (`update_distribution_client.py`, `update_coordinator.py`).
- Notificador em segundo plano (`notifier_agent.py`).
- WebSocket de chat em tempo real (`chat_realtime.py`).

Todos passam por `DesktopApiConfigStore().load_settings()` (diretamente ou
via `config_store_factory` injetável para testes) — nenhum mantém constante
de servidor própria.

## Auditoria final de hardcodes

| Ocorrência | Arquivo | Classificação |
|---|---|---|
| `DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"` | `app/integrations/api/config.py` | Necessária e centralizada — único default de fábrica, usado só quando a chave de config não existe. |
| `data.setdefault('desktop_api', {..., 'base_url': 'http://127.0.0.1:8000', ...})` | `app/services/backend_adapter.py` | Necessária e centralizada — mesma constante conceitual, aplicada na primeira criação do config.json. |
| `"base_url": "http://127.0.0.1:8000"` | `app/config/controle_producao_config.json`, `controle_producao_config.example.json` | Dado persistido/exemplo, não código — reflete o default de desenvolvimento da Fase 1; será substituído pelo endereço real quando definido. |
| `self.base_url.setPlaceholderText("http://127.0.0.1:8000")` | `app/ui/api_diagnostic_dialog.py` | Apenas texto de exemplo (placeholder) no campo de UI, não define o valor usado. |
| `host in {"localhost", "127.0.0.1", "::1"}` | `app/integrations/api/config.py` (antes da correção) | Removida nesta fase — era a causa da rejeição indevida de HTTP em endereços de LAN. |
| `data.setdefault('platform_api', {..., 'base_url': 'http://127.0.0.1:8100', ...})` | `app/services/backend_adapter.py`, `controle_producao_config.json` | Fora do escopo — chave para uma "platform_api" distinta, sem nenhum cliente HTTP ativo consumindo-a no repositório; não é a API interna do sistema tratada nesta fase. |
| `host in {"localhost", "127.0.0.1", "::1"}` | `app/services/nomus_api_config.py`, `api/app/modules/nomus_integration/pipeline/config_types.py` | Serviço externo (Nomus) — fora do escopo desta fase por definição (seção 2 do prompt técnico). |
| `netloc = '127.0.0.1'` em `_desktop_operational_url()` | `app/services/backend_adapter.py` | Função sem nenhum chamador no repositório (código morto); não afeta o fluxo real. Não removida por estar fora do escopo desta fase — registrada aqui para conhecimento. |
| `set DESKTOP_API_BASE_URL=http://127.0.0.1:8000` | `docs/architecture/DESKTOP_API_CLIENT.md`, `tests/test_desktop_api_integration.py` | Documentação/teste — exemplo de uso do override de ambiente, agora também válido para o fluxo real (não só o teste de integração). |

Nenhum consumidor real da API interna ficou ignorando a configuração
central.

## Fora do escopo desta fase

Não foram implementados: tela de primeiro acesso, descoberta automática de
servidor, tentativas entre múltiplos servidores, diagnóstico visual completo,
HTTPS/certificados, acesso pela internet, controle de compatibilidade de
versão (já existe de uma fase anterior e não foi alterado), instalador,
alteração de regra de negócio ou de tabelas PostgreSQL.
