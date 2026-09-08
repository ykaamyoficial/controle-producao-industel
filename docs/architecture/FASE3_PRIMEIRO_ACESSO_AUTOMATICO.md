# Fase 3 - Primeiro Acesso Automatico

## Objetivo

Fazer o Desktop tratar corretamente a inicializacao em um computador que
ainda nao possui configuracao valida da API: usar automaticamente um
endereco oficial quando disponivel, e oferecer uma recuperacao simples
(testar/salvar) somente quando a conexao automatica falhar -- sem editar
arquivos tecnicos e sem expor o PostgreSQL.

## Diagnostico inicial

O fluxo de abertura (`app/main.py:main()`) ja continha um "gate" pre-login
equivalente em espirito (`run_startup_compatibility_check`, de uma fase
interna anterior do projeto — "Fase 03" da numeracao propria do repositorio,
nao a desta Fase 3), mas ele resolve **compatibilidade de versao**, nao
**endereco/conectividade**, e parte do pressuposto de que a API ja e
alcancavel. Ao investigar o caminho real de um computador novo, dois
problemas concretos foram encontrados:

1. **Fallback silencioso para localhost.** `run_startup_compatibility_check()`
   roda antes de `MainWindow`/`BackendService` existirem e le a configuracao
   via `DesktopApiConfigStore` (default em memoria `enabled=False`, portanto
   a checagem e pulada quando nao ha nada salvo ainda). Mas assim que
   `MainWindow()` e construida, `BackendService.__init__` chama
   `load_app_config()`, que tinha `data.setdefault('desktop_api', {'enabled':
   True, 'base_url': 'http://127.0.0.1:8000', ...})` -- e persiste isso
   imediatamente no `config.json`. Em uma maquina nova, sem API local
   nenhuma, isso grava um "servidor validado" falso (`127.0.0.1:8000`,
   `enabled=True`) sem qualquer teste real, exatamente o que a Secao 21 do
   prompt tecnico proibe.
2. **Nenhuma recuperacao quando a conexao automatica falha.** Se a API nao
   respondesse (situacao normal em um computador novo), o unico sintoma era
   uma falha de login mais adiante, sem nenhuma tela para informar o
   endereco correto do servidor -- o usuario ficaria travado.

Pontos ja adequados e reaproveitados sem alteracao:

- `DesktopApiConfigStore`/`normalize_api_base_url` (Fase 2): fonte central e
  validacao de URL.
- `/api/v1/system/health` (Fase 1): endpoint somente leitura reaproveitado
  para o probe do bootstrap.
- `start_worker` (QThread + signal/slot): mesmo mecanismo assincrono ja usado
  por `CompatibilityGateDialog`/`ApiDiagnosticDialog`, reaproveitado para o
  novo dialogo sem travar a UI.
- `ApiTokenStore`: reaproveitado para invalidar sessao ao trocar de servidor.

## Arquivos alterados/criados

- `app/services/bootstrap_service.py` (novo) -- logica pura do bootstrap
  (`run_bootstrap`, `probe_health`, estados/codigos de erro).
- `app/ui/first_access_dialog.py` (novo) -- dialogo de primeiro
  acesso/recuperacao.
- `app/main.py` -- nova funcao `run_startup_bootstrap()`, chamada em
  `main()` logo apos criar o `QApplication`, antes de qualquer outra
  verificacao de startup.
- `app/integrations/api/config.py` -- `DesktopApiConfigStore.is_configured()`
  (distingue "nunca configurado" de "default em memoria"); `save_settings()`
  agora limpa a sessao local quando o `base_url` efetivamente muda de um
  host para outro.
- `app/services/backend_adapter.py` -- default de `desktop_api` em
  `load_app_config()` corrigido para `enabled: False` (era `True`),
  eliminando o fallback silencioso descrito acima.
- Testes novos: `tests/test_bootstrap_service.py`,
  `tests/test_first_access_dialog.py`, `tests/test_startup_bootstrap.py`;
  testes adicionados em `tests/test_desktop_api_config.py`.

## Fluxo de bootstrap implementado

```text
QApplication criado
  v
run_startup_bootstrap()
  v
FirstAccessDialog.__init__ -> _start_bootstrap() (QThread, nao trava a UI)
  v
run_bootstrap(config_store, client_factory, bootstrap_url_provider)
  |
  +-- config ja persistida e valida?
  |     +-- sim -> GET /api/v1/system/health
  |     |     +-- OK -> READY_FOR_LOGIN (dialogo fecha sozinho, silencioso)
  |     |     +-- falha -> API_UNREACHABLE (mantem config, mostra formulario
  |     |                  pre-preenchido + "Tentar novamente")
  |     +-- nao -> existe BOOTSTRAP_API_BASE_URL (env)?
  |           +-- sim -> GET /health
  |           |     +-- OK -> salva via DesktopApiConfigStore.save_settings()
  |           |     |         -> READY_FOR_LOGIN (silencioso)
  |           |     +-- falha -> NEEDS_CONFIGURATION (formulario vazio)
  |           +-- nao -> NEEDS_CONFIGURATION (formulario vazio)
  v
NEEDS_CONFIGURATION / API_UNREACHABLE -> dialogo vira formulario interativo
  (campo + Testar conexao + Salvar e continuar + Tentar novamente + Sair)
  v
Salvar bem-sucedido -> DesktopApiConfigStore.save_settings() -> proceed=True
  v
run_startup_bootstrap() retorna True -> segue para
run_startup_compatibility_check() -> run_startup_update_check() -> MainWindow -> Login
```

Se o usuario clicar "Sair", `run_startup_bootstrap()` retorna `False` e
`main()` encerra o processo sem construir `MainWindow` (mesmo padrao ja
usado pelo gate de compatibilidade).

## Fontes de configuracao (sem inventar valores)

1. **Configuracao persistente oficial** (Fase 2) -- `desktop_api.base_url`
   no `config.json`, gravado exclusivamente por
   `DesktopApiConfigStore.save_settings()` (nunca mais por um default
   silencioso de `load_app_config()`).
2. **Endereco de bootstrap** -- variavel de ambiente
   `BOOTSTRAP_API_BASE_URL`. Hoje **nao ha valor definido em lugar nenhum do
   projeto** (a Fase 7/instalador ainda nao existe, e o IP oficial do
   servidor da Fase 1 continua pendente de definicao). Isso e esperado: sem
   essa variavel, o bootstrap simplesmente nao encontra endereco e abre o
   formulario de primeiro acesso -- comportamento correto e previsto pelo
   prompt tecnico (Cenario C).

## Estados e erros implementados

| Estado (`BootstrapState`) | Significado | Acao da UI |
|---|---|---|
| `READY_FOR_LOGIN` | Endereco valido e API respondeu saudavel | Fecha o dialogo automaticamente, segue para login |
| `NEEDS_CONFIGURATION` | Sem configuracao persistida e sem bootstrap utilizavel | Mostra formulario vazio |
| `API_UNREACHABLE` | Configuracao persistida existe, mas a API nao respondeu agora | Mostra formulario pre-preenchido com o endereco conhecido + mensagem distinta ("servidor configurado") |

`BootstrapErrorCode` (Secao 19): `CONFIG_MISSING`, `CONFIG_INVALID`,
`DNS_OR_CONNECT_ERROR`, `TIMEOUT`, `HEALTH_HTTP_ERROR`, `API_UNHEALTHY`,
`READY`. Nenhum deles expõe stack trace ao usuario -- cada um mapeia para
uma frase curta em `first_access_dialog._ERROR_DETAILS`.

Falha de `/health` (conectividade) e falha de autenticacao (401 no login)
permanecem estados diferentes: o bootstrap nunca chama `/auth/login`, so
`/system/health`; a distincao exigida na Secao 9 ja e estrutural (dois
codigos distintos em duas camadas distintas do sistema).

## Interface de primeiro acesso

`FirstAccessDialog` (`app/ui/first_access_dialog.py`) e um unico dialogo
reaproveitado nos dois cenarios (config ausente / config inalcancavel), para
nao duplicar uma segunda tela:

- Ao abrir, tenta o bootstrap automaticamente (mensagem "Conectando ao
  servidor..."), sem exibir formulario nenhum se a checagem for rapida e
  bem-sucedida.
- Se falhar, revela: titulo, explicacao curta, campo de endereco, botao
  "Testar conexao" (roda em thread separada), indicador de status, botao
  "Salvar e continuar" (so habilita apos um teste bem-sucedido do valor
  **atual** do campo -- editar o campo depois de testar desabilita o Salvar
  de novo, ate testar novamente) e "Sair".
- Quando ja existe configuracao (cenario "servidor configurado offline"), o
  campo vem pre-preenchido com o endereco conhecido e um botao extra
  "Tentar novamente" reexecuta o teste nesse mesmo valor.
- Validacao sintatica (via `normalize_api_base_url`, Fase 2) acontece antes
  de qualquer chamada HTTP -- um valor invalido nunca dispara rede.
- Uma tentativa de teste que falha nunca sobrescreve a configuracao
  existente: `save_settings()` so e chamado no clique de "Salvar e
  continuar", e so fica habilitado apos sucesso do valor exato em tela.
- Nao exibe nada relacionado a PostgreSQL (usuario, senha, connection
  string).

## Sessao/autenticacao

`DesktopApiConfigStore.save_settings()` agora compara o `base_url`
persistido anterior com o novo antes de gravar: se ambos existirem e forem
diferentes, chama `ApiTokenStore().clear()` (removendo o refresh token
protegido por DPAPI) e registra o evento no log. Como isso acontece dentro
da propria camada central de configuracao (nao em cada tela que a usa), a
regra vale tanto para o fluxo de bootstrap quanto para o diagnostico
administrativo (`ApiDiagnosticDialog`), sem duplicacao. Nenhum token e
reenviado automaticamente para um host diferente daquele que o emitiu.

## Concorrencia

O probe inicial e cada "Testar conexao"/"Tentar novamente" rodam em uma
`QThread` via `start_worker` (mesmo utilitario ja usado por
`CompatibilityGateDialog`), com sinais `succeeded`/`failed` atualizando a UI
na thread principal. A interface nunca fica bloqueada esperando rede; os
testes automatizados (`test_first_access_dialog.py`) usam
`QApplication.processEvents()` em loop com timeout para aguardar o worker
sem travar a suite.

## Testes

Comandos executados:

```bash
python -m unittest tests.test_bootstrap_service -v            # 14 testes
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_first_access_dialog -v   # 8 testes
python -m unittest tests.test_startup_bootstrap -v             # 3 testes
python -m unittest tests.test_desktop_api_config -v             # 10 testes (7 pre-existentes + 3 novos)
```

Regressao direcionada (modulos afetados por Fase 2 + Fase 3, 139 testes):

```bash
QT_QPA_PLATFORM=offscreen python -m unittest \
  tests.test_postgresql_only_config tests.test_settings_dialog \
  tests.test_desktop_api_config tests.test_api_proposal_storage \
  tests.test_desktop_api_client tests.test_update_audit_client \
  tests.test_update_distribution_client tests.test_startup_compatibility_check \
  tests.test_startup_bootstrap tests.test_system_api_client_compatibility \
  tests.test_update_coordinator tests.test_api_session_concurrency \
  tests.test_bootstrap_service tests.test_first_access_dialog -v
# Ran 139 tests -- OK
```

Cobertura da lista minima do prompt tecnico (Secao 28): configuracao valida
+ health OK libera login; configuracao ausente + bootstrap valido salva e
libera login; configuracao e bootstrap ausentes pedem configuracao;
configuracao invalida nao dispara HTTP; timeout e connection-refused
retornam estados controlados sem apagar configuracao; HTTP 500 e API
unhealthy nao liberam login; falha de teste nao sobrescreve configuracao
anterior; salvamento e lido de volta pela mesma camada central; mudanca real
de servidor limpa a sessao local. Nenhum teste toca PostgreSQL (todos usam
`httpx.MockTransport`/arquivos temporarios).

## Teste em ambiente real

**Teste de primeiro acesso real pendente.** Nao ha, neste momento, um
segundo computador nem um servidor físico com o endereco definido pela Fase
1 para validar o fluxo fora de mocks/ambiente de desenvolvimento local.

## Pendencias para a Fase 7 (instalador)

- Definir e fornecer `BOOTSTRAP_API_BASE_URL` no ambiente/instalador quando
  o IP oficial do servidor (Fase 1) for definido, para que computadores
  novos configurem-se sem interacao manual.

## Confirmacao de escopo

Nao foram implementados: painel de diagnostico completo (Fase 4), HTTPS
(Fase 5), controle de compatibilidade de versao (ja existente de uma fase
interna anterior, nao alterado por esta tarefa), instalador/atualizador
(Fase 7), descoberta por varredura de rede, modo offline ou qualquer
alteracao de regra de negocio/tabela PostgreSQL.
