---
name: desktop-update-doctor
description: Diagnostica, projeta e valida o mecanismo de atualizacao do Desktop (Updater.exe, instalador Inno Setup, pacote ZIP, manifest, agente --notifier). Use quando a atualizacao parar no meio, fechar o programa sem atualizar, o instalador falhar por processo em execucao, ou antes de liberar qualquer release do Desktop.
---

# Desktop update doctor

Cobre o caminho completo: Desktop -> `UpdateCoordinator` -> `Updater.exe` -> troca
de arquivos -> handshake `--post-update`, mais o caminho alternativo do instalador
Inno Setup (`installer/ControleProducao.iss`). Referencia de arquitetura:
`docs/architecture/UPDATER_DESKTOP.md`. Este skill complementa `release-checklist`
(que cuida da API) e nao o substitui.

Regra de trabalho: **evidencia antes de correcao**. Nunca altere o Updater por
palpite; confirme a causa em log/journal/processos primeiro (secao 1).

## Mapa rapido

| Peca | Arquivo |
|---|---|
| Ponto unico que dispara update | `app/services/update_coordinator.py` |
| Dialogo e progresso | `app/ui/update_dialog.py` |
| Updater (entry, elevacao) | `app/updater/__main__.py`, `elevation.py` |
| Layout versionado (ponteiro, versoes, limpeza) | `app/updater/versions.py` |
| Atualizacao em duas fases (`--stage` / `--activate`) | `app/updater/versioned.py`, `status.py`, `quit_signal.py` |
| Launcher (`ControleProducao.exe` na raiz) | `app/launcher/launcher.py`, `Launcher.spec` |
| Maquina de estados do fluxo plano (legado) | `app/updater/orchestrator.py` |
| Processos (espera, kill, launch) | `app/updater/process_control.py` |
| Troca de pastas | `app/updater/swap.py` |
| Agente de bandeja (mesmo exe, `--notifier`) | `app/services/notifier_agent.py`, `app/main.py` |
| Instalador | `installer/ControleProducao.iss` |
| Pacote ZIP / manifest | `scripts/build_update_package.py`, `scripts/generate_release_manifest.py` |
| Dados do Updater em runtime | `<ProgramData>/updater/{logs,status,handshake,downloads,manifest,quarantine,quit.request}` (`app/updater/paths.py`); `journal/staging/backup` so no fluxo plano legado |
| Arquitetura e verificacao feita | `docs/architecture/UPDATER_DESKTOP.md` (secao "Layout versionado") |

## 1. Diagnostico (somente leitura)

Na maquina que falhou, nesta ordem:

1. **Status**: `updater/status/<request_id>.json` (layout versionado) traz `phase`
   (`STAGING`, `STAGED`, `ACTIVATING`, `RESTARTING`, `SUCCESS`, `FAILED`, `ROLLED_BACK`),
   `message` e `error`. Ausencia de status = o Updater nem chegou a rodar (falha no
   `UpdateCoordinator`, no lancamento, ou UAC recusado). Confira tambem `current.json`
   (versao ativa e `previous_version`) e as pastas em `versions\`. No layout plano
   legado (2.8.x e anteriores) use o journal em `updater/journal/`.
2. **Log do Updater**: `updater/logs/`. Procure `update_elevation_*`,
   `Falha ao mover a instalacao atual para backup`, `sharing_violation`,
   `nao encerrou dentro do timeout`, `handshake`.
3. **Log do Desktop**: procure `update_coordinator_*` (descoberta, manifest, hash, launch).
4. **Quem trava a pasta**: com o app e o Updater parados, liste processos cujo
   executavel esta em `install_dir` (Process Explorer > Find Handle, ou
   `Get-Process | Where Path -like '<install_dir>\*'`). Esperados e problematicos:
   - `ControleProducao.exe --notifier` (bandeja, iniciado pela pasta Startup)
   - `Updater.exe` rodando de dentro de `install_dir`
   - qualquer shell/Explorer com a pasta como diretorio atual
5. **Matriz de sintomas**

| Sintoma | Causa provavel | Confirmar com |
|---|---|---|
| Barra para em 30% e o app fecha | Download/verificacao no processo principal sem progresso real, ou Updater falhou sem tela | journal + log do coordinator |
| Fecha e nao atualiza, versao antiga reabre | Rollback automatico (`ROLLED_BACK`) | estado final no journal |
| Fecha e nada reabre | `MANUAL_INTERVENTION_REQUIRED` ou Updater morreu | journal, existencia de backup |
| Instalador "nao consegue fechar processo" | `--notifier` vivo e sem `CloseApplications` no `.iss` | processos (passo 4) |
| Falha so em usuario sem admin | UAC recusado ou relancamento elevado silencioso | `update_elevation_*` no log |
| `INVALID_PACKAGE` | Manifest apontando para o `.exe` do instalador em vez do `*-update.zip` | `--artifact` usado no manifest |
| `INVALID_HASH` | Artefato trocado apos gerar o manifest, ou proxy alterando o download | quarentena + recalcular SHA-256 |

## 2. Principios de projeto (inspirados em Chrome, Squirrel, Velopack, Omaha)

Aplique ao desenhar ou revisar qualquer mudanca:

1. **Nunca renomear/apagar a pasta em uso.** Instalar a versao nova em pasta
   propria (`versions/<semver>/`) e mudar so um ponteiro (launcher + arquivo
   `current`). A troca vira atomica e independente de processo travando.
2. **Um unico conjunto de processos do app.** Antes de qualquer troca, encerrar
   TODO processo cujo executavel esteja sob `install_dir` (janela principal,
   `--notifier`, helpers), nao so o `parent_pid`. Ordem: pedir saida graciosa
   (evento nomeado / `WM_CLOSE`) -> esperar -> forcar (`TerminateProcess`) como
   politica padrao do fluxo automatico, sempre registrada em log.
3. **O Updater nunca roda de dentro do que vai trocar.** Copiar `Updater.exe`
   para pasta temporaria (ou ao lado, fora de `versions/`) e lancar com `cwd`
   explicito fora de `install_dir`.
4. **Falha nunca e silenciosa.** O usuario sempre ve: etapa atual, erro legivel
   e uma saida ("Tentar novamente", "Abrir instalador manualmente"). O Desktop
   so fecha DEPOIS de o Updater confirmar que assumiu (handshake de partida).
5. **Elevacao pedida antes de fechar o Desktop**, ou eliminada instalando por
   usuario quando possivel. Nunca relancar elevado sem feedback.
6. **Idempotencia e recuperacao**: reexecutar o Updater no meio de qualquer
   estado deve convergir (journal + `recover_incomplete_update`).
7. **Verificacao fim a fim**: hash/tamanho antes de aplicar, handshake depois,
   rollback automatico se o novo nao subir.
8. **Instalador e Updater compartilham a mesma regra de fechamento.** O `.iss`
   deve ter `CloseApplications`/`CloseApplicationsFilter`/`RestartApplications`
   E um `[Code]` que encerra `ControleProducao.exe` (inclusive `--notifier`) e
   `Updater.exe` antes de copiar; sem isso a instalacao manual depende do
   Gerenciador de Tarefas.

## 3. Checklist pre-release (Desktop)

Marque cada item com evidencia (comando + saida), nunca de memoria.

- [ ] `APP_VERSION` (`app/version.py`) == `MyAppVersion` e `OutputBaseFilename` no `.iss`
      (`tests/test_installer_version_consistency.py`).
- [ ] `dist/ControleProducao/` (com `ControleProducaoApp.exe`), `dist/Updater/` e `dist/Launcher/`
      (`python -m PyInstaller Launcher.spec`) construidos da MESMA versao.
- [ ] Use caminhos CURTOS no build (`--distpath`/`--workpath`): o PyInstaller falha com WinError 206
      em pastas profundas.
- [ ] `Updater.exe` presente na raiz do pacote ZIP e em `versions\<v>` na pasta instalada.
- [ ] Pacote de update e ZIP (`scripts/build_update_package.py`), com arquivo `VERSION`.
- [ ] Manifest gerado com `--artifact <...>-update.zip --content-type application/zip`
      (nao o `.exe` do instalador).
- [ ] SHA-256 e tamanho do manifest conferem com o arquivo a publicar.
- [ ] `.iss` fecha processos (principio 8) e compila (`ISCC.exe installer\ControleProducao.iss`).
- [ ] 1a versao com o layout novo NAO esta no feed para clientes 2.8.x (o atualizador antigo
      reprova o pacote); instalar uma vez pelo instalador novo.
- [ ] Suite: `python -m pytest tests/test_updater_*.py tests/test_update_*.py tests/test_manifest_*.py tests/test_installer_version_consistency.py -q`
      (suite Desktop tem timeout; hang = `test-doctor`).

## 4. Matriz de teste manual (maquina limpa ou VM)

Atualizar de N-1 para N em CADA combinacao, registrando resultado final do journal:

| Admin | Bandeja `--notifier` | Janela aberta | Antivirus | Esperado |
|---|---|---|---|---|
| sim | ligada | sim | padrao | SUCCESS, uma unica reabertura |
| nao | ligada | sim | padrao | SUCCESS ou erro claro na tela (nunca silencio) |
| sim | desligada | nao | padrao | SUCCESS |
| sim | ligada | sim | Defender em tempo real | SUCCESS (swap com retry) |
| sim | ligada | sim | pacote corrompido | falha de hash na tela, app antigo intacto |
| sim | ligada | sim | matar Updater no meio | proxima execucao recupera (rollback) |

Para automatizar parte disso, monte o layout num diretorio isolado (dados, `APPDATA`,
`ProgramData`, `CONTROLE_PRODUCAO_DATA_DIR` redirecionados e `QT_QPA_PLATFORM=offscreen`, para nao
tocar no Startup nem na instalacao real) e rode `Updater.exe --request <json> --stage` e `--activate`
com um processo "teimoso" vivo na pasta antiga; esperado `STAGED` e depois `SUCCESS`.

Mais o caminho do instalador: rodar `ControleProducaoSetup-N.exe` por cima, com
bandeja e janela abertas, SEM encerrar nada manualmente.

## 5. Verificacao pos-publicacao

Release so esta pronto quando o feed REALMENTE entrega:

- `GET /api/v1/updates/desktop` devolve `available=true`, `version == APP_VERSION`,
  `manifest_url` e `package_url` resolviveis.
- Baixar `package_url` e recalcular SHA-256 == manifest.
- Um Desktop N-1 de teste enxerga o aviso, baixa, aplica e confirma o handshake.

## 6. Recuperacao manual

Layout versionado:
1. Rode `scripts/recuperar_atualizacao.bat` como administrador (encerra
   `ControleProducao.exe`, `ControleProducaoApp.exe` e `Updater.exe`; opcionalmente abre o instalador).
2. Se o programa nao abre: confira `current.json` e `versions\`. O launcher se autorrepara
   escolhendo a maior versao com `ControleProducaoApp.exe`; se nenhuma existir, rode o instalador.
3. Dados vivem fora da instalacao, em `%ProgramData%\Industel\ControleProducao`.

Layout plano legado (`MANUAL_INTERVENTION_REQUIRED`): pare os processos, confira
`updater/backup/<request_id>/` e a quarentena, restaure o backup por rename ou rode o
instalador da ultima versao conhecida.

Depois registre o ocorrido em `docs/architecture/` (skill `fase-report`).

## 7. Limites

- Leitura e diagnostico sao livres. Mudar `Updater`, `.iss` ou o pipeline de
  pacote exige plano aprovado; publicar release real exige confirmacao explicita
  (mesmo gate do `release-checklist`).
- Nao execute atualizacao real em maquina de producao sem backup e sem janela
  combinada com o usuario.
