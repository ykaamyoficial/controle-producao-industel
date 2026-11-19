# Auditoria de empacotamento e distribuição do Desktop (somente leitura) - 2026-11-19

Branch `logistica-melhorias` (HEAD c1d31a3). Nada foi editado, buildado, publicado nem instalado. Produção (API 8000 / SERVIDOR) não foi tocada; o que depende do estado do SERVIDOR aparece como pergunta no fim.

Severidade: **B** = bloqueia deploy, **C** = corrigir antes, **P** = pode depois.

## Resumo

1. O caminho oficial é um só: `Updater.spec` + `ControleProducao.spec` + `Launcher.spec` -> `installer\ControleProducao.iss` -> `scripts\build_update_package.py` -> `scripts\generate_release_manifest.py` -> `scripts\sync_release_to_server.py`. O app atualiza pela **API** (`/api/v1/updates/desktop`), nunca pelo GitHub.
2. A versão `2.9.0` está em `app/version.py`, nos dois `.iss`, no manifest e nos artefatos de `release/`. Está coerente, mas **o código novo (47 commits em `app/` desde 168ca86, Inspeção/Logística) ainda se chama 2.9.0**. Os artefatos em `release/` foram buildados em 14/10 e **não contêm** a Logística. Buildar agora gera um 2.9.0 diferente do 2.9.0 já distribuído.
3. `3.0.0` é só o rótulo da baseline arquitetural (Desktop -> API -> PostgreSQL, congelada em 27/07). Não é versão de produto. A verdade de produto é Desktop 2.9.0 / API 0.11.0.
4. Nenhum gate de compatibilidade distingue a API 0.11.0 antiga (SERVIDOR, migration 0038) da nova (0.11.0 com migrations até 0047). Precisa subir as duas versões antes do deploy.

## Achados

| # | Sev | Achado | Evidência |
|---|---|---|---|
| 1 | **B** | Versão do Desktop não foi subida. O build de hoje sairia como 2.9.0 com conteúdo diferente do 2.9.0 em `release/`. O Updater recusa instalar versão igual (`release_version == current`), então ninguém receberia o código novo. | `app/version.py:10` `APP_VERSION = "2.9.0"`; `app/updater/manifest_policy.py:49-50`; `git diff --stat 168ca86..HEAD -- app` = 89 arquivos, +8268 |
| 2 | **B** | Versão da API não foi subida (0.11.0) apesar das migrations 0039-0047 e dos módulos Inspeção/Logística. O gate do Desktop (`MINIMUM_API_VERSION = "0.11.0"`) deixa um Desktop novo operar contra a API antiga do SERVIDOR (que estava em `20261014_0038` em 06/11): telas de LOG/NQT dariam 404. | `api/app/core/config.py:10,14`; `app/version.py:25`; `app/services/compatibility_check.py:78-88`; memória `controle-producao-migracao-servidor` |
| 3 | **B** | Não há tag `v2.9.0` nem commit que corresponda ao que foi buildado em 14/10 às 21:31 (a tag é `v2.9.0-padrao-janelas`, commit de 15/10). `release/latest.json` cita `tag: v2.9.0`. Para rollback e auditoria, o próximo release precisa de tag própria. | `release/latest.json:4`; `git tag`; achado 3 de `01_git.md` |
| 4 | **C** | Quatro lugares a editar à mão por versão: `APP_VERSION`, `#define MyAppVersion` e `OutputBaseFilename=ControleProducaoSetup-X` no `.iss` oficial, e os mesmos dois no `.iss` de teste. Há teste que pega divergência do oficial e do de teste. Rodar a suíte antes do build é obrigatório. | `installer/ControleProducao.iss:2,20`; `installer/ControleProducaoTeste.iss:6,23`; `tests/test_installer_version_consistency.py:34`; `tests/test_edition.py:152-153` |
| 5 | **C** | A edição de teste **não testa a atualização**: `updates_enabled()` é falso nela, então `UpdateCoordinator` e `check_for_updates` retornam sem tocar a rede. O fluxo stage/activate/rollback só se prova com a edição oficial. Usar `DESKTOP_API_BASE_URL` (aceita só na oficial) apontando para a API de dev. | `app/edition.py:120-121`; `app/services/update_coordinator.py:107,147`; `app/integrations/api/config.py:120-127` |
| 6 | **C** | Dependências do build do Desktop sem trava (`PySide6>=6.7`, `pyinstaller>=6.0`, etc.). A API já teve um build quebrado por isso (greenlet) e ganhou `requirements-lock.txt`; o Desktop não. Hoje o ambiente é PyInstaller 6.20.0 + PySide6 6.11.0 (Python 3.11 em `%LOCALAPPDATA%\Programs\Python\Python311`). `python` do PATH é 3.14.6 e `.python-version` diz 3.12: buildar com o interpretador errado é fácil. | `requirements.txt:1-2`; `docs/architecture/RELEASE_API_0_10_0_DESKTOP_2_8_0.md:20-26`; `gerar_exe_setup.bat:10` |
| 7 | **C** | O `.iss` oficial não limpa `versions\<v>` antes de copiar. Reinstalar a **mesma** versão por cima mantém DLLs antigas. O `.iss` de teste já tem esse `InstallDelete` porque uma DLL velha (`icuuc.dll`) quebrou o import do QtWidgets. Só afeta reinstalação da mesma versão (ex.: reparo). | `installer/ControleProducaoTeste.iss:54-55` vs `installer/ControleProducao.iss:45-50` |
| 8 | **C** | Manifest e pacote não são assinados. O SHA-256 vem do próprio manifest, servido pela mesma API. Protege contra download corrompido, não contra servidor/canal comprometido. Em IP de LAN o download é HTTP puro; pelo túnel é HTTPS. `PUBLICAR_RELEASE_GITHUB.md` e o `UPDATER_DESKTOP.md` falam em "manifesto assinado", mas `app/updater` não tem verificação de assinatura. Risco aceitável em rede interna; registrar a decisão. | `app/updater/artifact_verification.py:64`; `app/updater/manifest_provider.py:20`; grep "signature" em `app/updater` sem resultado |
| 9 | **C** | Sem assinatura de código (decisão documentada). `Get-AuthenticodeSignature` do instalador 2.9.0 = `NotSigned`. Launcher/Updater/Setup podem cair no SmartScreen/antivírus. Mitigação documentada: exclusão por GPO e envio de falso positivo. Nunca testado contra antivírus real. | `docs/architecture/UPDATER_DESKTOP.md:414-419`; `release/ControleProducaoSetup-2.9.0.exe` |
| 10 | **C** | README e `INSTRUCOES_GERADOR_EXE.txt` mandam buildar por specs que **não** são os oficiais: README -> `gerar_exe_pyside6.bat` (usa `Controle Producao 2.0.spec`); instruções -> `setup.py` / `gerar_exe_setup.bat` (usa `Controle Producao Industel Telecom.spec`). Ambos geram layout plano, sem launcher, sem Updater, sem tzdata/winrt/certifi, e empacotam `app\config` inteiro (que localmente contém `installation_identity` e config de Nomus; copiar essa config para todas as máquinas duplicaria a identidade da instalação). O próprio `.bat` e o `.spec` avisam, o README não. | `README.md:71`; `INSTRUCOES_GERADOR_EXE.txt:4`; `gerar_exe_pyside6.bat:2-6`; `Controle Producao 2.0.spec:27`; `Controle Producao Industel Telecom.spec:8` |
| 11 | **C** | Máquinas ainda em 2.8.x não podem receber atualização do layout versionado pelo feed (falham e voltam). Se o feed autorizar 2.10.0 para quem ainda não reinstalou pelo instalador 2.9.0, essas máquinas tentam e dão rollback. Precisa confirmar que a frota toda está em 2.9.0 antes de autorizar. | `docs/architecture/UPDATER_DESKTOP.md:396-403` |
| 12 | **C** | `scripts/build_test_installer.py` procura `ISCC.exe` em `%LOCALAPPDATA%\Programs\Inno Setup 6`, que não existe nesta máquina. Existe `C:\Program Files\Inno Setup 7\ISCC.exe` (o que `PUBLICAR_RELEASE_GITHUB.md` usa). O instalador oficial não tem script próprio: ISCC é chamado à mão. Definir `ISCC_PATH`. | `scripts/build_test_installer.py:24,99-101` |
| 13 | P | `Updater.spec` diz no cabeçalho "NAO build-verificado", mas o doc registra build real em 08/10. Cabeçalho desatualizado. Também usa `upx=True` e `console=True` (UPX aumenta falso positivo de antivírus; o app principal já usa `upx=False`). | `Updater.spec:7-9,49-50`; `ControleProducao.spec:78-81` |
| 14 | P | `release/latest.json`, `.sha256` e `create_release_files.py` são do fluxo GitHub antigo e o Desktop não os lê. Notas fixas no script ("Primeira versao instalavel oficial") e `channel: stable` (vocabulário diferente do manifest: `production`). Úteis só como conferência do hash do instalador para distribuição manual. | `scripts/create_release_files.py:57-64`; `release/latest.json`; `app/services/update_checker.py:16` (legado) |
| 15 | P | `.iss` oficial não limpa `HKCU\...\Run` (agente `--notifier`) na desinstalação; o de teste limpa. Fica uma entrada apontando para launcher removido. | `installer/ControleProducaoTeste.iss:47-51` |
| 16 | P | Primeiro acesso numa máquina nova exige digitar a URL da API (o instalador não define `BOOTSTRAP_API_BASE_URL`). Risco de digitar errado. Placeholder do diálogo é `http://192.168.1.50:8000`, endereço de exemplo. | `app/services/bootstrap_service.py:31,60-69`; `app/ui/first_access_dialog.py:100` |
| 17 | P | Specs e scripts legados continuam na raiz e rastreados: `Controle Producao 2.0.spec`, `Controle Producao Industel Telecom.spec`, `setup.py`, `setup_cxfreeze.py` (aponta para `gerados\` e versão 2.0.0), `gerar_exe_*.bat`, `abrir_pyside6.bat` (caminho absoluto do Python). Mover para `legado/` ou apagar. | `git ls-files` |

### Conferido e ok

- Hashes: `ControleProducaoSetup-2.9.0.exe` = `0fff1cd8...e625` (igual a `latest.json:9` e ao `.sha256`); `ControleProducao-2.9.0-update.zip` = `f783ee19...c2b7` (igual a `manifest.json`). Conferido por hash real.
- Spec oficial (`ControleProducao.spec`) empacota o necessário: assets, migrations, só o `controle_producao_config.example.json` (não vaza config local), certifi, tzdata, winrt/windows_toasts/winotify, PySide6 (Widgets/Core/Gui/PrintSupport/Network/WebSockets), pdfplumber/pdfminer/PIL/openpyxl. `pymupdf` não está listado, mas aparece em `dist\ControleProducao\_internal` (hook do PyInstaller). Ícone `Logo_Industel_Icone.ico` no exe, no launcher e no setup.
- Launcher mínimo, sem PySide6/rede (`Launcher.spec:26`); `current.json` gravável por usuários comuns, `versions\` só admin (`ControleProducao.iss:106-122`).
- Nada de build rastreado pelo git: `build/`, `dist/`, `release/`, `build_teste/`, `dist_teste/`, `*.exe`, `*.zip` estão no `.gitignore:34-60` e `git ls-files` não lista nenhum binário (confirmado também em `01_git.md`).
- Desinstalar não apaga dados: `[UninstallDelete]` remove só `versions\`, `_internal\` e `current.json`; config, backups e updates ficam em `%ProgramData%\Industel\ControleProducao`. Instalar por cima usa o mesmo `AppId` (upgrade no lugar) e migra o layout plano antigo (`InstallDelete` de `_internal` e `Updater.exe` da raiz).
- `atualizador-versionado` (tip 880a3b3, 13/10) **está mesclada em `main`** (`merge-base --is-ancestor` = verdadeiro, 0 commits exclusivos) e em HEAD. O layout versionado faz parte do que é entregue e já estava no build 2.9.0.
- URL da API: o app oficial **não tem URL de produção embutida**. Vale a config salva em `%ProgramData%\Industel\ControleProducao\controle_producao_config.json`; sem ela, abre o diálogo de primeiro acesso. A variável `DESKTOP_API_BASE_URL` sobrescreve só na edição oficial. A edição de teste ignora a variável, recusa porta 8000 e usa `https://producaodev.ykora.com.br` por padrão; nunca aponta para 8001 local nem para produção (`app/edition.py:20,124-134`). O `release/teste` foi buildado com `base_url` de dev.
- Produção usa hostname do túnel (migração para o SERVIDOR "sem alterar nenhum Desktop"), então as instalações existentes seguem apontando para o lugar certo. Não verifiquei isso no SERVIDOR.

## 1. Caminho oficial de build

| O que | Vigente | Gera |
|---|---|---|
| Spec do app | `ControleProducao.spec` | `dist\ControleProducao\ControleProducaoApp.exe` + `_internal` |
| Spec do launcher | `Launcher.spec` | `dist\Launcher\ControleProducao.exe` (é o exe da raiz da instalação) |
| Spec do Updater | `Updater.spec` | `dist\Updater\Updater.exe` |
| Instalador | `installer\ControleProducao.iss` (ISCC) | `release\ControleProducaoSetup-<v>.exe` |
| Pacote de update | `scripts\build_update_package.py` | `release\ControleProducao-<v>-update.zip` (app + Updater, sem launcher, com `VERSION`) |
| Manifest | `scripts\generate_release_manifest.py` | `release\manifest.json` (SHA-256 e tamanho calculados do zip) |
| Publicação no servidor | `scripts\sync_release_to_server.py` | release em `READY` no repositório de updates da API |
| Hash do instalador (opcional) | `scripts\create_release_files.py` | `.sha256` e `latest.json` (legado, o app não lê) |
| Edição de teste | `scripts\build_test_installer.bat` + `installer\ControleProducaoTeste.iss` | `release\teste\ControleProducaoTesteSetup-<v>.exe`, usando `build_teste\` e `dist_teste\` |

Legados (não usar para release): `Controle Producao 2.0.spec`, `Controle Producao Industel Telecom.spec`, `setup.py`, `setup_cxfreeze.py`, `gerar_exe_pyside6.bat`, `gerar_exe_setup.bat`, `abrir_pyside6.bat`, `INSTRUCOES_GERADOR_EXE.txt`, `docs/PUBLICAR_RELEASE_GITHUB.md` (já marcado ARQUIVADO).

## 2. Versionamento

| Onde | Valor | Arquivo:linha |
|---|---|---|
| Desktop | 2.9.0 (build 2026.10.14, canal `stable`) | `app/version.py:10-11,13` |
| Mínimo de API que o Desktop aceita | 0.11.0 | `app/version.py:25` |
| API | 0.11.0 | `api/app/core/config.py:10` |
| Banco esperado | `20261109_0047` | `api/app/core/config.py:14` |
| Desktop mínimo/recomendado exigido pela API | 2.5.2 / 2.7.0 | `api/app/core/config.py:22-23` |
| Instalador | 2.9.0 (duas linhas) | `installer/ControleProducao.iss:2,20` |
| Instalador de teste | 2.9.0 (duas linhas) | `installer/ControleProducaoTeste.iss:6,23` |
| Manifest e `latest.json` | 2.9.0, `minimum_server_version` 0.11.0 | `release/manifest.json`, `release/latest.json` |
| Imagem da API local (não versionada) | `SERVER_VERSION=0.11.0` | `.env.production:2` |

Coerente entre si, mas todos congelados em 2.9.0/0.11.0 enquanto o código avançou. `BASELINE_3.0.0.md` e `README.md:5` falam "Baseline arquitetural 3.0.0": rótulo de arquitetura, não de produto. Sugestão: README dizer "Baseline arquitetural 3.0.0 (Desktop 2.9.0 / API 0.11.0)" para parar a confusão.

**Próxima versão sugerida** (decisão do Henrique): Desktop **2.10.0** (minor: telas novas de Inspeção/Logística/Almox, sem quebra de contrato) e API **0.12.0** (minor: módulos e migrations 0039-0047). No mesmo commit de versão: `MINIMUM_API_VERSION = "0.12.0"` no Desktop, os quatro pontos dos `.iss`, e `--minimum-server-version 0.12.0` no manifest. `API_CONTRACT_VERSION` fica `v1`. `MINIMUM_DESKTOP_VERSION` fica 2.5.2; só subir `RECOMMENDED_DESKTOP_VERSION` para 2.10.0 depois do piloto.

## 3. Distribuição e auto-update

- Desktop pergunta `GET /api/v1/updates/desktop?installation_id=...` na API configurada (`app/services/update_distribution_client.py:80-87`). A API devolve a release elegível ao canal da instalação, com URLs de manifest e pacote já com um grant curto assinado (`api/app/channels/service.py:294-320`).
- Ao clicar "Atualizar agora": `UpdateCoordinator` baixa o manifest, valida schema, baixa o ZIP por streaming e confere SHA-256 e tamanho; falha vai para quarentena e o Updater nem é lançado (`app/services/update_coordinator.py:143-204`). Depois `Updater.exe --stage` (extrai em `versions\<v>.tmp`, valida `ControleProducaoApp.exe` e `VERSION`, renomeia) e `--activate` (troca `current.json`, fecha processos da pasta, abre o launcher e espera o handshake; sem handshake volta para a versão anterior). UAC aparece uma vez, no `--stage`. Ficam a versão ativa e a anterior.
- Hospedagem: repositório de updates da **API**, volume `update_repository_data` (`/var/lib/controle-producao/updates`) em `docker-compose.prod.yml:78,107`. GitHub e pasta de rede **não** são usados pelo app (`update_checker.py` legado, sem uso em `app/main.py:11`). O instalador completo (`Setup-X.exe`) para máquinas novas não passa pela API: onde ele fica hoje é pergunta ao Henrique.
- Verificação: SHA-256 do manifest + tamanho. Sem assinatura (achado 8).
- Canais: `PRODUCTION` é o padrão de toda instalação nova e de qualquer instalação sem `installation_id`/sem banco (`api/app/channels/installations.py:31-42`). `PILOT` só por atribuição explícita de admin (`POST /api/v1/channels/installations/{id}/assign`). Quem decide: usuário com permissão `updates.manage` (`api/app/modules/channels/router.py:127,172`).
- Ciclo: `DRAFT -> PILOT_AUTHORIZED -> PILOT_APPROVED -> PRODUCTION_AUTHORIZED`; de qualquer estágio `REVOKED`; `PILOT_PAUSED`/`PILOT_FAILED` no meio (`api/app/channels/transitions.py:5-25`). Aprovar exige gates (mínimo de clientes piloto atualizados com sucesso, zero `UPDATE_FAILED`/`START_FAILED`, janela de observação); promover reconfere que manifest e artefato têm o mesmo hash do snapshot do piloto (`api/app/channels/gates.py:18-55`, `service.py:156-195`).
- **Armadilha:** release `AUTHORIZED` que nunca entrou no pipeline de canal é visível para **todos** os canais, inclusive produção (`api/app/channels/service.py:282-291,305-310`). Portanto `sync_release_to_server.py --authorize` publica direto para todo mundo. Para usar piloto, sincronizar **sem** `--authorize` e chamar `POST /channels/pilot/{v}/authorize` direto da release `READY`.
- **Rollback:** `POST /channels/pilot/{v}/revoke` (também revoga na Fase 12) só para de oferecer a release. Quem já atualizou **não volta sozinho**: o Updater recusa downgrade (`manifest_policy.py:52-56`). Opções: (a) máquina individual, regravar `current.json` com a versão anterior (a pasta anterior fica) ou reinstalar o Setup da versão anterior; (b) frota, publicar uma versão **maior** (ex. 2.10.1) com o código anterior.

## 4. Compatibilidade com a API

- Desktop envia `X-Client-Version` em toda chamada (`app/integrations/api/client.py:74,100,131,187`). O `ClientVersionMiddleware` rejeita abaixo de `MINIMUM_DESKTOP_VERSION` (2.5.2) com 426, mas **só se `CLIENT_VERSION_ENFORCEMENT_ENABLED=true`**; o padrão é `false` (`api/app/core/config.py:65`, `client_version_middleware.py:64-65`). `.env.example:34` também false. Valor real no SERVIDOR: não verificado (ver perguntas). Portanto hoje a "versão mínima" é só preflight no cliente.
- Checagem real no startup: `GET /system/compatibility` (público). Desktop decide por contrato (`v1`), `MINIMUM_API_VERSION`, mínimo/recomendado de Desktop e manutenção; falha de rede = bloqueio (`CHECK_FAILED`).
- A API devolve 503 `DATABASE_REVISION_INCOMPATIBLE` se a revisão do banco diferir da esperada (`docs/architecture/VERSIONING.md:148-150`). API nova sem migration aplicada derruba o preflight de **todos** os Desktops.
- Proteção que já existe e ajuda na ordem: `authorize_release` recusa se a API em execução for menor que `minimum_server_version` do manifest (`api/app/updates/service.py:222-227`). Isso força "API primeiro", mas só se o manifest tiver o número certo (hoje seria 0.11.0, que não protege nada; ver achado 2).
- **Ordem correta:** (1) backup do banco; (2) migrations até 0047; (3) API 0.12.0 no SERVIDOR; (4) conferir `/system/compatibility`; (5) sincronizar Desktop 2.10.0 (`minimum_server_version 0.12.0`); (6) piloto; (7) produção. Nunca o Desktop antes da API.
- Desktop novo contra API antiga: passa o gate (achado 2) e quebra só nas telas novas. Desktop antigo (2.5.2+) contra API nova: opera, a API foi mantida aditiva (nota de release do 2.8.0 diz o mesmo para aquela versão; para 0.12.0 conferir com a auditoria de migrações).

## 6. Teste em máquina limpa

Existe: edição de teste (`ControleProducaoTeste.iss`, `scripts/build_test_installer.*`), instala em paralelo ao oficial (AppId, pastas, mutex, chave Run, ProgramData e executáveis próprios), laranja, faixa "AMBIENTE DE TESTE", API de dev. `release\teste\ControleProducaoTesteSetup-2.9.0.exe` é de 23/10: não tem a Logística. `build_teste\` e `dist_teste\` são 560 MB de lixo regenerável, ignorados pelo git.

Não cobre: atualização automática (achado 5), SmartScreen/antivírus reais, UAC com usuário não-admin, instalar por cima do oficial 2.8.x, e o instalador **oficial** (nunca foi executado nesta auditoria nem consta como verificado em máquina limpa: `UPDATER_DESKTOP.md:412-414`).

Checklist faltante (VM Windows 10 limpa, sem Python):
1. Instalar o Setup novo como admin, abrir pelo atalho, ver diálogo de primeiro acesso, digitar a URL de **dev**, testar conexão, login.
2. Conferir `current.json`, `versions\<v>\ControleProducaoApp.exe`, `Updater.exe`, pastas em `%ProgramData%\Industel\ControleProducao`.
3. Abrir Inspeção, Logística, imprimir relatório de LOG/carga (PDF), notificação do Windows (balão), agente `--notifier` na bandeja.
4. Instalar por cima de um 2.9.0 já usado: dados e login preservados, mesma `installation_id`, atalhos ok, `--notifier` não bloqueia.
5. Desinstalar: `versions\`, `_internal`, `current.json` somem; `%ProgramData%\Industel\ControleProducao` fica; ver se sobra entrada em `HKCU\...\Run` (achado 15).
6. Atualização real 2.9.0 -> 2.10.0 pela API de dev (edição oficial com `DESKTOP_API_BASE_URL`): UAC uma vez, progresso, reabre, 2.9.0 fica como anterior. Repetir com usuário **não** administrador.
7. Provocar falha: ZIP adulterado (SHA-256 errado) deve ir para quarentena sem instalar; `ControleProducaoApp.exe` inválido deve dar `ROLLED_BACK`.
8. Instalador e launcher com Defender ligado e SmartScreen ativo; anotar avisos.

## 7. Lixo de build

Local, ignorado pelo git (nenhum rastreado): `dist\` 401 MB, `build\` 100 MB, `dist_teste\` 403 MB, `build_teste\` 157 MB, `release\` 517 MB (Setup 168 MB, update.zip 204 MB, teste 169 MB). O `dist\` e o `build\` são de 14/10 e estão **atrás** do código atual: nunca empacotar a partir deles. `output\`, `nao_existe.json` e `Nova pasta - Atalho.lnk` estão soltos e não ignorados (já em `01_git.md`). Cinco `.spec` na raiz, dois deles legados (achado 17). Há dois `.iss`, ambos válidos (oficial e teste).

## Rascunho do runbook de deploy do Desktop

Pré-requisitos: suíte `python -m pytest tests api/tests -q` verde (sem mascarar falha com pipe); auditorias de migração/segurança/operação sem bloqueio; API 0.12.0 pronta para deploy (pré-requisito, não faz parte deste runbook).

**A. Versão e preparo**
1. Decidir a versão (sugestão 2.10.0 / API 0.12.0). Editar `app/version.py` (`APP_VERSION`, `APP_BUILD`, `MINIMUM_API_VERSION`), `api/app/core/config.py` (`API_VERSION`) e os dois `.iss` (2 linhas cada). Rodar `tests/test_installer_version_consistency.py` e `tests/test_edition.py`.
2. Commit local e tag `v2.10.0` no commit exato do build. Push da branch e da tag: [AUTORIZAÇÃO DO HENRIQUE].
3. Copiar `release\*2.9.0*` para uma pasta de arquivo fora do repo (é a base de rollback; build do 2.9.0 não é reproduzível).

**B. Build (máquina de build, Python 3.11, nada no PATH errado)**
4. `pip freeze` do ambiente e guardar junto da release (trava de reprodutibilidade).
5. Na raiz, com `%LOCALAPPDATA%\Programs\Python\Python311\python.exe`:
   - `-m PyInstaller Updater.spec --clean --noconfirm`
   - `-m PyInstaller ControleProducao.spec --clean --noconfirm`
   - `-m PyInstaller Launcher.spec --clean --noconfirm`
   - `"C:\Program Files\Inno Setup 7\ISCC.exe" installer\ControleProducao.iss`
   - `scripts\build_update_package.py`
   - `scripts\generate_release_manifest.py --artifact release\ControleProducao-2.10.0-update.zip --content-type application/zip --minimum-server-version 0.12.0 --api-contract-version v1 --release-notes "<texto>"`
   - opcional: `scripts\create_release_files.py` (hash do instalador para distribuição manual).
6. Conferir: `Get-FileHash` do Setup e do ZIP contra `.sha256` e `manifest.json`; `ControleProducaoApp.exe` presente; tamanhos coerentes (~168 MB e ~204 MB).

**C. Teste antes de publicar (dev e VM, nada de produção)**
7. Subir o release na API de **dev** (8001) com `sync_release_to_server.py` sem `--authorize`; testar checklist da seção 6 na VM, incluindo a atualização real e a falha provocada.
8. Smoke test: instalar o Setup novo em máquina limpa contra a API de dev.

**D. Publicar (só depois da API nova no ar e saudável)**
9. Confirmar com `GET /api/v1/system/compatibility` que o SERVIDOR responde `server_version=0.12.0` e revisão `20261109_0047`. [AUTORIZAÇÃO DO HENRIQUE para qualquer ação no SERVIDOR]
10. Levar `manifest.json` e o ZIP ao SERVIDOR (scp, conferir SHA-256 dos dois lados) e rodar `sync_release_to_server.py --manifest ... --package ... --source manual` **sem `--authorize`** dentro do contêiner da API. Estado `READY`. [AUTORIZAÇÃO DO HENRIQUE]
11. Atribuir 1 a 3 instalações ao canal PILOT (`POST /api/v1/channels/installations/{id}/assign`) e `POST /api/v1/channels/pilot/2.10.0/authorize`. [AUTORIZAÇÃO DO HENRIQUE]
12. Acompanhar `GET /channels/pilot/2.10.0`, `POST .../gates` e os relatórios do piloto; olhar `updater.log` das máquinas piloto e o log da API. Se algo falhar: `POST .../fail` ou `.../pause`.

**E. Promover**
13. `POST /channels/pilot/2.10.0/approve` (gates ok) e depois `.../promote`. [AUTORIZAÇÃO DO HENRIQUE] Só então o restante da frota passa a ver a atualização. Opcional depois de estável: subir `RECOMMENDED_DESKTOP_VERSION`. [AUTORIZAÇÃO DO HENRIQUE]
14. Distribuir o `Setup-2.10.0.exe` para máquinas novas (local a definir) e arquivar Setup, ZIP, manifest, `.sha256` e `pip freeze` da release.

**F. Rollback**
15. Parar de oferecer: `POST /channels/pilot/2.10.0/revoke` com motivo. [AUTORIZAÇÃO DO HENRIQUE]
16. Máquina afetada: fechar o app, restaurar `current.json` para a versão anterior (pasta anterior fica) ou reinstalar o Setup 2.9.0 arquivado; dados em `ProgramData` não são tocados. `scripts\recuperar_atualizacao.bat <setup>` (como admin) encerra processos e abre o instalador.
17. Frota inteira: publicar uma versão maior com o código anterior e repetir D-E. Voltar a API só com o passo de rollback de banco da auditoria de migração (banco volta a 0038 só com backup e decisão consciente).

## Perguntas ao Henrique

1. A frota inteira já está em 2.9.0 (instalada pelo Setup novo, layout versionado)? Qualquer máquina em 2.8.x ou anterior não consegue atualizar pelo feed (achado 11). Quantas máquinas são e quais?
2. O 2.9.0 de 14/10 foi sincronizado e autorizado no SERVIDOR? Qual release está `AUTHORIZED` lá agora (`GET /updates/desktop/admin/releases`)? Eu não consultei produção.
3. O SERVIDOR já está em API 0.11.0 com migration 0047, ou ainda em `20261014_0038`? Isso decide se a ordem "API primeiro" é um passo real ou já foi feito.
4. Aprova 2.10.0 (Desktop) e 0.12.0 (API), ou prefere outro número? Faz sentido manter `3.0.0` só como rótulo de baseline?
5. Existe canal piloto de verdade (quais máquinas/usuários)? Ou vai direto para todos? Se for direto, a release `AUTHORIZED` sem passar pelo pipeline vai para todos de uma vez (armadilha da seção 3).
6. `CLIENT_VERSION_ENFORCEMENT_ENABLED` está ligado no SERVIDOR? Se sim, o mínimo de Desktop passa a valer de verdade (hoje 2.5.2).
7. Onde fica o Setup completo para máquinas novas (pasta de rede, pen drive)? Hoje não há local oficial documentado.
8. Posso mexer em: README (apontar o build oficial), `INSTRUCOES_GERADOR_EXE.txt` (arquivar), mover os specs/bats legados para `legado/`, adicionar `InstallDelete` de `versions\<v>` ao `.iss` oficial e `ISCC_PATH` ao script? Nada disso foi feito agora.
9. Quer comprar certificado de assinatura de código, ou segue com exclusão de antivírus por GPO? E aceita que o manifest não seja assinado (rede interna e túnel HTTPS)?
10. Os 47 commits de `app/` desde o 2.9.0 incluem alguma tela que dependa de endpoint ainda não commitado/mesclado na API? Confirmar com o time de testes antes de fechar a 2.10.0.
