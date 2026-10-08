# Updater do Desktop (Fase 10)

## Objetivo

Um componente **separado** do Desktop principal (`app/updater/`, empacotável
como `Updater.exe` via `Updater.spec`) capaz de: receber um pacote de
atualização já autorizado, baixá-lo com segurança, validar sua integridade,
esperar o Desktop encerrar, trocar os arquivos de forma quase-atômica,
validar a instalação nova, reabrir o Desktop e confirmar que ele realmente
iniciou -- com journal de recuperação e rollback local em qualquer ponto de
falha.

**Regra de ouro**: o Desktop nunca substitui os próprios arquivos. A troca só
acontece depois que o processo principal encerrou, sob controle exclusivo do
Updater.

## Mecanismo de atualização já existente (inventário obrigatório)

O repositório **já tinha** um mecanismo de atualização funcional antes desta
fase: `app/services/update_checker.py` (consulta a API de Releases do
GitHub), `update_downloader.py` (baixa o instalador `.exe` + `.sha256`,
inteiro em memória), `update_installer.py` (gera um script PowerShell que
espera o PID atual encerrar e roda o instalador Inno Setup em modo silencioso)
e `app/ui/update_dialog.py`, todos already wired em `app/main.py`
(`run_startup_update_check`) e em `app/ui/main_window.py`/`settings_page.py`.

Esse mecanismo é **arquiteturalmente diferente** do pedido desta fase: ele
consulta "latest" do GitHub diretamente (algo que a Fase 10 proíbe
explicitamente para o novo Updater -- Seção 8: "não consultar latest do
GitHub para escolher versão") e delega toda a troca de arquivos ao instalador
Inno Setup completo, não a um swap de diretório controlado com journal/
rollback.

**Decisão (na época da Fase 10)**: o mecanismo legado foi preservado sem
nenhuma alteração (nenhuma funcionalidade existente foi removida ou
desativada). O novo Updater (`app/updater/`) foi construído como um
componente **paralelo e independente**, seguindo exatamente a arquitetura
pedida nesta fase, sem ainda estar ligado ao fluxo de decisão de versão do
Desktop -- essa ligação (quem decide disparar o Updater e com qual
`target_version`) dependia do manifest oficial da Fase 11 e do servidor
distribuidor da Fase 12, ambos fora do escopo naquele momento. A única
integração feita no Desktop principal era o handshake pós-update (ver
abaixo), que é aditivo e não interfere em nada do fluxo existente quando a
flag `--post-update` não está presente (o caminho comum, sempre).

**Atualização (Fase 07 -- Instalador e Atualização)**: com o manifest (Fase
11) e o servidor distribuidor (Fase 12) já prontos, a lacuna acima deixou de
existir. `app/ui/update_dialog.py` (o diálogo do fluxo opcional/informativo,
mostrado por `run_startup_update_check` quando há uma versão nova mas o
Desktop continua compatível) foi migrado para chamar
`UpdateCoordinator.start_required_update()` -- o mesmo ponto único já usado
pelo fluxo obrigatório (`CompatibilityGateDialog`) -- em vez de
`update_downloader`/`update_installer`. Os dois módulos legados continuam no
repositório, intactos, apenas como utilitário histórico sem chamador em
`app/ui/`; `app/services/update_distribution_client.py` (Fase 12) continua
sendo quem descobre a versão nova, mas a instalação em si agora passa sempre
pelo Updater separado (download/verificação/swap/journal/rollback/handshake),
nunca mais pelo instalador Inno Setup silencioso disparado direto do processo
principal. `app/main.py::main()` só constrói a `MainWindow` quando
`run_startup_update_check()` reporta que nenhuma atualização foi disparada
(`update_launched=False`); quando o usuário confirma a atualização opcional,
o Desktop encerra do mesmo jeito que no fluxo obrigatório, para o Updater
assumir a troca.

## Inventário de empacotamento/instalação

- **Empacotamento**: PyInstaller `onedir` (`ControleProducao.spec`), não
  onefile. `APP_EXECUTABLE_NAME = "ControleProducao.exe"` (`app/version.py`).
- **Instalação nova (primeira vez)**: Inno Setup
  (`installer/ControleProducao.iss`), instala em
  `{autopf}\Industel\Controle de Producao` (requer admin,
  `PrivilegesRequired=admin`).
- **Atualização assistida**: NÃO usa o `.exe` do Inno. O Updater valida o
  pacote como **ZIP** (`verify_package`), extrai e faz swap de diretório. O
  pacote de atualização é gerado por `scripts/build_update_package.py` a
  partir de `dist/ControleProducao/` + `dist/Updater/` (mesma mesclagem que
  o `.iss` faz para `{app}`), com um arquivo `VERSION` na raiz →
  `release/ControleProducao-<versao>-update.zip`. O manifesto (Fase 11)
  precisa apontar para esse ZIP: `generate_release_manifest.py --artifact
  <...>-update.zip --content-type application/zip`. Publicar o `.exe` do
  instalador como pacote de update faz o Updater falhar com
  `INVALID_PACKAGE -- nao e um pacote ZIP valido` (bug corrigido em 2026-09).
- **Dados persistentes**: já externalizados de `install_dir` desde a Fase 01
  (`app/services/app_paths.py`) -- config, logs, cache e a pasta `updates/`
  legada vivem em `%ProgramData%\Industel\ControleProducao` (ou
  `%APPDATA%\ControleProducao\logs` para logs), nunca dentro da pasta de
  instalação. Isso significa que, no layout de produção atual, a pasta que o
  Updater troca (`install_dir`) contém **somente binários/recursos
  substituíveis** -- a allowlist de arquivos protegidos (Seção 16) é uma
  camada de defesa adicional para layouts onde isso não for verdade (ex.:
  modo dev, onde `app/config/` e `app/data/` são pastas irmãs do código).
- **Sem local DB**: o Desktop está totalmente migrado para PostgreSQL via
  API; os módulos de SQLite local foram arquivados em
  `tools/legacy_sqlite_runtime/` (fora do pacote distribuído).
- **Sem updater/helper antigo como executável separado**: a "substituição de
  arquivos" do mecanismo legado é feita pelo próprio instalador Inno Setup
  (`/VERYSILENT`), não por um binário auxiliar dedicado -- o Updater desta
  fase é, portanto, o primeiro componente desse tipo no projeto.

## Arquitetura (`app/updater/`)

```
contract.py        UpdateRequest, UpdateJournal, UpdateState (tipados, JSON)
paths.py            layout de diretorios (staging/backup/downloads/journal/logs)
lock.py              lock de arquivo entre processos Updater (Secao 29)
journal_store.py    persistencia atomica do UpdateJournal
downloader.py        download streaming, .part, retry controlado
validation.py        verify_package (VALID/INVALID_HASH/INVALID_SIZE/MISSING_METADATA/INVALID_PACKAGE)
extraction.py         extracao ZIP segura (protecao contra path traversal)
persistence.py        allowlist de arquivos persistentes + copia para o staging
precheck.py            PRECHECK_LOCAL (Secao 17)
swap.py                 troca por rename (demote_to_backup / promote_staging / rollback_swap)
install_validation.py   validacao pos-troca (Secao 22)
process_control.py     espera/forca encerramento, lanca processo independente
handshake.py            confirmacao pos-update local, sem rede (Secao 24)
orchestrator.py         maquina de estados completa (REQUESTED -> ... -> SUCCESS/ROLLED_BACK/MANUAL_INTERVENTION_REQUIRED)
exceptions.py            ConcurrentUpdateError, UpdateFailedError
__main__.py              entry point (python -m app.updater / Updater.exe)
```

## Contrato Desktop -> Updater (Seção 7)

`UpdateRequest` (dataclass tipada, serializada em um arquivo JSON temporário
-- nunca dezenas de argumentos soltos na linha de comando):

```
request_id, current_version, target_version, package_url_or_source,
install_dir, executable_path, parent_pid,
package_expected_size (opcional), package_expected_hash (opcional),
restart_args (opcional), allow_downgrade (opcional, default False)
```

`validate_update_request()` roda **antes de qualquer alteração em disco**
(inclusive antes de qualquer registro no journal): versões precisam ser
SemVer válidas (reaproveita `app.versioning.parser`, Fase 01), `target_version`
precisa ser estritamente maior que `current_version` a menos que
`allow_downgrade=True` seja explicitado (Seção 8 -- nunca implícito),
`install_dir`/`executable_path` precisam ser absolutos e `executable_path`
precisa estar dentro de `install_dir`.

## Maquina de estados (`UpdateState`)

```
REQUESTED -> DOWNLOADING -> VALIDATED -> WAITING_APP_EXIT -> APPLYING
                                                            -> VALIDATING_INSTALL -> RESTARTING -> SUCCESS
Qualquer etapa antes de APPLYING que falhar -> FAILED (install_dir nunca tocado).
Qualquer etapa a partir de APPLYING que falhar -> rollback automatico -> ROLLED_BACK
(ou MANUAL_INTERVENTION_REQUIRED se o proprio rollback nao puder ser
concluido com seguranca).
```

Persistido a cada transição via `UpdateJournalStore` (mesmo padrão de
arquivo-JSON-atômico já usado pela Fase 08 do lado da API).

## Staging e backup local (Seções 10, 19)

```
updater/downloads/<request_id>/   pacote baixado (fora do staging -- nunca misturado com os arquivos extraidos)
updater/staging/<request_id>/     pacote extraido (a futura instalacao)
updater/backup/<request_id>/       instalacao anterior, apos o primeiro rename do swap
updater/journal/                    UpdateJournal persistido
updater/logs/                       log tecnico proprio do Updater
```

O backup local (Seção 19) **é** o resultado do primeiro `rename` do swap
(`install_dir -> backup_dir`) -- não uma cópia adicional de "centenas de
arquivos" como o texto da fase explicitamente pede para evitar. Um pequeno
`metadata.json` (`request_id`, `current_version`, `target_version`,
`backed_up_at_utc`) é escrito dentro do backup para diagnóstico.

## Download resiliente (Seção 11)

`downloader.py`: streaming em chunks (nunca carrega o pacote inteiro em
memória -- diferente do mecanismo legado, que usa `download_bytes` completo),
arquivo `.part` enquanto incompleto (promovido para o nome final só após
sucesso), limite de tamanho quando `package_expected_size` é conhecido, User-Agent
`ControleProducaoUpdater/<versão>` sem dado pessoal, retry pequeno e
controlado (`max_retries`, padrão 2) **somente** para erros transitórios
(timeout, conexão, HTTP 5xx) -- erros HTTP 4xx nunca são retentados. Aceita
tanto `http(s)://` (validado contra um servidor HTTP local real nos testes,
`http.server.ThreadingHTTPServer`) quanto um caminho/`file://` local (modo
teste/recuperação). Suporte a retomada (resume) não foi implementado --
explicitamente opcional nesta fase.

## Integridade (Seção 13, preparação para a Fase 11)

`verify_package(path, expected_hash=None, expected_size=None)` retorna um dos
cinco resultados tipados (`VALID`, `INVALID_HASH`, `INVALID_SIZE`,
`MISSING_METADATA`, `INVALID_PACKAGE`). Com `expected_hash` fornecido, a
verificação é obrigatória e qualquer divergência bloqueia -- nunca instala um
pacote com hash divergente. Sem hash esperado, `MISSING_METADATA` é aceito
(modo transitório desta fase); a partir do manifest oficial da Fase 11, todo
request deverá trazer hash e esse caminho deixará de ser aceito pelo
orquestrador, sem qualquer mudança de assinatura necessária.

## Extração segura (Seção 15)

`safe_extract_zip`: valida **todas** as entradas do ZIP antes de escrever o
primeiro byte (rejeita `..`, caminhos absolutos, drive letters, separador
`\`, entradas de symlink) -- testado com ZIPs maliciosos reais contendo path
traversal, caminho absoluto e drive letter, todos corretamente rejeitados
sem extrair nada.

## Proteção de arquivos persistentes (Seção 16)

Allowlist documentada (`config/`, `data/`, `logs/`, `cache/`, `certs/`,
`.env*`, `*.db`/`*.sqlite*`) -- `copy_protected_files` copia (nunca move) do
backup (instalação antiga) para o staging antes da segunda renomeação do
swap, para que a instalação promovida já contenha tanto os binários novos
quanto os dados persistentes antigos.

## Swap no Windows (Seção 20)

`Path.rename()` de pasta inteira (operação única do NTFS, evita copiar
centenas de arquivos): `demote_to_backup` (`install_dir -> backup_dir`),
depois `promote_staging` (`staging_dir -> install_dir`). Se a segunda
renomeação falhar, a primeira é desfeita automaticamente (o sistema nunca
fica sem NENHUM `install_dir` válido). Falhas de sharing violation (arquivo
em uso, Seção 21) são detectadas via `PermissionError`/`WinError 32` e
retentadas com backoff antes de desistir.

## Validação da instalação e handshake (Seções 22-24)

`validate_installation`: executável presente, nenhum `.part` sobrou,
arquivos persistentes presentes, e (se o pacote incluir um marcador
`VERSION` na raiz) a versão declarada bate com `target_version`. Depois, o
Updater relança o Desktop com `--post-update <request_id>` e espera (com
timeout) um marcador local em
`updater/handshake/<request_id>.ok` -- escrito pelo próprio Desktop ao
iniciar (`app/main.py::confirm_post_update_handshake`, chamado logo após
`configure_logging()`; não faz nada quando a flag não está presente, o
caminho comum). Sem rede envolvida nesse handshake.

## Rollback local (Seção 25)

Qualquer falha a partir de `APPLYING` (falha no swap, instalação nova
reprovada, falha ao relançar, handshake ausente) aciona
`UpdaterOrchestrator._rollback`: restaura o backup por rename
(`swap.rollback_swap`, que move a instalação com problema para uma pasta de
quarentena antes de restaurar o backup), valida a instalação restaurada, e
tenta reabrir o Desktop anterior. O estado final é `ROLLED_BACK` -- ou
`MANUAL_INTERVENTION_REQUIRED` se o próprio rollback não puder ser concluído
com segurança (backup ausente, restauração falha, ou instalação restaurada
reprovada na validação). O Desktop restaurado usa seu próprio fluxo de
inicialização normal (Fase 03), então o bloqueio de compatibilidade mínima
com a API já se aplica automaticamente sem nenhum código adicional aqui.

## Journal e recuperação (Seções 26-27)

`UpdaterOrchestrator.recover_incomplete_update()`, chamada no início do
Updater antes de processar qualquer novo request: busca o último
`UpdateJournal` não-terminal. Nunca presume que uma troca terminou só porque
existe staging. Decisão determinística e sempre conservadora:
- backup ainda não existe (falha antes de `APPLYING`) -> `install_dir` está
  intacto, nenhuma ação de risco -> marca `FAILED`.
- backup existe (demote já aconteceu, promote pode ou não ter completado) ->
  **sempre** restaura o backup (nunca tenta "completar" uma promoção
  incerta) -> marca `ROLLED_BACK`.
- backup existe mas o `UpdateRequest` original não está disponível (não dá
  para saber onde fica `install_dir` sem inferir) -> escala para
  `MANUAL_INTERVENTION_REQUIRED`, nunca apaga nada.

## Concorrência (Seção 29)

`UpdaterLock` (arquivo `updater/.updater.lock`, criação exclusiva
`O_CREAT|O_EXCL`, mesmo desenho do lock já usado do lado da API na Fase 08 --
reimplementado, não importado, porque Desktop e API são pacotes distribuídos
separadamente) protege toda a execução de `run_update`/`recover_incomplete_update`.
Uma segunda tentativa concorrente levanta `ConcurrentUpdateError` sem tocar
em nada.

## Empacotamento (`Updater.spec`)

Onedir, console (sem UI gráfica nesta fase), depende só de `httpx` + stdlib
(exclui PySide6/pdfplumber/PIL/fastapi/sqlalchemy -- o Updater não precisa de
nada disso). **Build real executado e validado nesta sessão**: `pyinstaller
Updater.spec` produziu um `Updater.exe` funcional, testado tanto com
`--help` quanto em um cenário completo real (request JSON real, pacote ZIP
real, `install_dir` real) -- incluindo um caso de falha genuína (o "novo"
executável de teste não era um binário válido, Windows recusou executá-lo
com `WinError 216`, e o Updater reverteu automaticamente para a versão
anterior, terminando em `ROLLED_BACK`), confirmando o mecanismo de rollback
local funcionando ponta a ponta contra o binário compilado real, não só a
biblioteca Python.

## Testes

164 testes novos, todos com diretórios reais (`tempfile.TemporaryDirectory`)
e, quando aplicável, arquivos ZIP/servidores HTTP reais -- nenhum mock do
sistema de arquivos: `test_updater_contract.py`, `test_updater_downloader.py`
(inclui download HTTP real contra `http.server` local),
`test_updater_validation.py`, `test_updater_extraction.py` (ZIPs maliciosos
reais), `test_updater_persistence.py`, `test_updater_swap.py` (renomeações
reais), `test_updater_journal_store.py`, `test_updater_lock.py`,
`test_updater_process_control.py` (processos reais via `subprocess.Popen`),
`test_updater_install_validation.py`, `test_updater_precheck.py`,
`test_updater_handshake.py`, `test_updater_paths.py`,
`test_updater_orchestrator.py` (21 cenários de integração cobrindo toda a
Seção 29) e `test_main_post_update_handshake.py`.

## Elevação administrativa sob demanda (2.7.2)

Fechada a lacuna anteriormente documentada abaixo como pendência: o
instalador roda com `PrivilegesRequired=admin`, então `install_dir`
(`Program Files\...`) normalmente exige elevação para escrita. Em máquinas
onde o usuário Windows logado não é administrador, toda atualização
silenciosa falhava sempre no PRECHECK_LOCAL, exigindo reinstalação manual --
provavelmente a causa das falhas de atualização relatadas em algumas
estações.

`app/updater/elevation.py` (`is_admin`, `is_writable`, `relaunch_elevated`):
antes de processar qualquer request, `__main__.py` verifica se `install_dir`
é gravável; se não for e o processo atual não for elevado, relança a si
mesmo via `ShellExecuteW` (verbo `"runas"`, prompt UAC) com os mesmos
argumentos e encerra a instância não-elevada (código 0). Se o usuário recusar
o prompt UAC ou a elevação falhar por qualquer motivo, o fluxo normal
continua sem privilégio elevado -- PRECHECK_LOCAL reprova com a mensagem já
existente, preservando o comportamento anterior como rede de segurança.
Testado com `ShellExecuteW` mockado (`tests/test_updater_elevation.py`); o
prompt UAC real não é verificável de forma automatizada.

## Layout versionado (substitui o swap de pasta plana)

**Por que mudou.** No layout plano o Updater renomeava `install_dir` inteiro
(`install_dir -> backup`, `staging -> install_dir`). Qualquer processo vivo
dentro da pasta travava o rename com sharing violation. O Updater só esperava
o `parent_pid` (janela principal); o agente de bandeja (`ControleProducao.exe
--notifier`, iniciado pela pasta Startup) e o próprio `Updater.exe` (que rodava
de dentro de `install_dir`) continuavam segurando arquivos. O instalador Inno
tinha o mesmo defeito: não fechava o `--notifier`. Resultado: a atualização
abortava, fechava o programa sem atualizar, ou o instalador exigia matar
processos pelo Gerenciador de Tarefas.

**Como é agora.**

```
<instalacao>\
  ControleProducao.exe     launcher (Launcher.spec) -- estável, quase nunca muda
  current.json             ponteiro: {"version", "dir", "previous_version", ...}
  versions\<semver>\       árvore completa de cada versão
      ControleProducaoApp.exe, Updater.exe, _internal\
```

- Atalhos, Startup (`--notifier`), toasts e o próprio Updater apontam para o
  launcher (`app_paths.get_launcher_path()`), que lê `current.json` e abre a
  versão ativa. Se o ponteiro estiver corrompido, escolhe a maior versão
  instalada (`versions.resolve_active_version`).
- **Nenhuma pasta em uso é renomeada ou apagada.** Instalar = criar uma pasta
  nova; ativar = regravar `current.json` de forma atômica; desfazer = regravar
  com a versão anterior.
- Dados persistentes continuam em `%ProgramData%\Industel\ControleProducao`
  (a allowlist de `persistence.py` e o backup por rename só existem no fluxo
  legado).

**Duas fases** (`app/updater/versioned.py`, `Updater.exe --request <json> --stage|--activate`):

1. `--stage` roda **com o Desktop aberto**: copia/verifica o pacote
   (SHA-256/tamanho do manifest), extrai para `versions\<v>.tmp`, valida
   (`ControleProducaoApp.exe` presente, `VERSION` confere) e renomeia para
   `versions\<v>`. Escreve `updater/status/<request_id>.json`
   (`UpdateStatus`); o `UpdateCoordinator` lê esse arquivo e alimenta a barra
   de progresso do diálogo, com erros legíveis. Falha aqui não altera nada.
2. `--activate` roda depois que a fase 1 deu `STAGED` (o coordenador encadeia
   as duas após o clique em "Atualizar agora"): grava `current.json`, grava
   `updater/quit.request`, espera a saída cooperativa e **encerra à força todo
   processo cujo executável esteja sob a raiz da instalação**
   (`process_control.stop_processes_under`), abre o launcher com
   `--post-update <id>` e espera o handshake. Sem handshake: ponteiro volta
   para a versão anterior, o processo novo é encerrado e a versão anterior
   reabre (`ROLLED_BACK`).

Como o ponteiro muda antes de os processos antigos saírem, **um processo que
não fecha não impede mais a atualização**. A janela principal e o agente
`--notifier` observam `quit.request` (`app/services/update_quit_watcher.py`) e
saem de forma limpa; o pedido só vale para processos iniciados antes dele e
por 180 s, para um arquivo esquecido nunca fechar uma instância nova.

**Elevação.** `--stage` precisa gravar em `versions\` (pasta da instalação),
então o UAC aparece uma vez, com o diálogo ainda na tela. O instalador deixa só
o `current.json` gravável por usuários (`icacls ... S-1-5-32-545:(M)`), então
`--activate` não pede UAC de novo.

**Retenção.** Após o sucesso ficam a versão ativa e a anterior; as demais e
restos `*.tmp` são removidos (`versions.cleanup_old_versions`); o que ainda
estiver em uso é adiado para a próxima limpeza.

**Instalador (`installer/ControleProducao.iss`).** Instala o launcher na raiz
e o app em `versions\<MyAppVersion>`, remove `_internal` e `Updater.exe` do
layout antigo, escreve `current.json`, e um `[Code]` encerra
`ControleProducao.exe`, `ControleProducaoApp.exe` e `Updater.exe` (inclusive o
`--notifier`) antes de copiar (`PrepareToInstall`) e antes de desinstalar.

**Pacote de atualização** (`scripts/build_update_package.py`): ZIP da árvore de
UMA versão (`ControleProducaoApp.exe` na raiz do ZIP), sem o launcher.

**Migração das máquinas em 2.8.x.** O atualizador antigo dessas máquinas é o
que falha; ele não pode ser corrigido remotamente, e um pacote do layout novo
é reprovado por ele (rollback automático, `ControleProducao.exe` ausente).
Por isso a primeira versão com o layout novo deve ser **instalada uma vez pelo
instalador novo** (que já fecha o `--notifier`) e **não** ser publicada no feed
de atualização (`GET /updates/desktop`) para clientes 2.8.x. Depois disso todas
as atualizações usam o fluxo versionado. `scripts/recuperar_atualizacao.bat`
encerra os processos e abre o instalador para quem falhar mesmo assim.

**Verificação feita (2026-10-08).** Build real (PyInstaller) do launcher,
Updater e app, montados no layout num diretório isolado (dados, APPDATA e
Startup redirecionados) com um processo "teimoso" vivo na pasta antiga: launcher
abre a versão apontada; `--stage` prepara com o app aberto sem fechar nada;
`--activate` conclui `SUCCESS` apesar do processo teimoso (encerrado à força),
ponteiro `2.9.0` com anterior `2.8.0`, nada rodando da pasta antiga; pacote com
executável inválido termina `ROLLED_BACK` com a versão anterior reaberta (15/15
verificações). O `.iss` compila (ISCC). **Não verificado**: instalação real
pelo `.exe` (exige admin e encerraria o programa em uso), UAC real em usuário
não-admin, e antivírus/Defender contra o launcher sem assinatura.

## Riscos/pendências
- **Sem assinatura de código** (decisão: sem certificado): launcher/Updater
  novos podem ser marcados por antivírus ou SmartScreen. Mitigar com exclusão
  da pasta de instalação por GPO e envio de falso positivo à Microsoft.
- **Disco**: ficam a versão ativa e a anterior lado a lado.
- **Launcher**: um bug nele afeta todas as máquinas; é mínimo, testado
  (`tests/test_launcher.py`) e se autorrepara por `resolve_active_version`.
- **Antivírus/EDR**: a detecção de sharing violation existe (retry +
  `SwapError.sharing_violation`), mas o comportamento real contra um
  antivírus específico interceptando o arquivo recém-extraído não pôde ser
  testado neste ambiente.
- **Assinatura digital**: fora de escopo explícito desta fase; nenhum
  certificado/Authenticode foi adicionado.
- **Ligação com o Desktop principal**: o `UpdateRequest` ainda não é
  construído automaticamente por nenhum fluxo do Desktop (isso depende do
  manifest oficial da Fase 11 e da fonte de distribuição da Fase 12) -- o
  Updater é hoje um componente completo e testável de forma independente,
  mas ainda não "ligado" à decisão de atualização do usuário final.
