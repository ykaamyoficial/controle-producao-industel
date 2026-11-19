# Runbook: build e publicação do Desktop 2.10.0

Escrito em 2026-11-19, branch `logistica-melhorias`. Só descreve; nada aqui foi executado. Fontes: `docs/auditoria-deploy/07_desktop.md`, `docs/architecture/UPDATER_DESKTOP.md` e o código dos scripts citados.

Marcação: **[AUT]** = exige autorização explícita do Henrique (qualquer coisa no SERVIDOR 192.168.2.128, na API oficial (8000), em `api.ykora.com.br`, no GitHub, push).

Este runbook **depende** do `RUNBOOK_DEPLOY_API.md`: a API 0.12.0 precisa estar no ar e saudável antes de publicar a release (seção D).

## 0. Resumo

- Versão: Desktop **2.10.0** (era 2.9.0), `MINIMUM_API_VERSION = 0.12.0` (o Desktop 2.10.0 se recusa a operar contra API menor), manifest gerado com `--minimum-server-version 0.12.0`, `--api-contract-version v1`.
- A API 0.12.0 tem `MINIMUM_DESKTOP_VERSION = 2.10.0`: **todo Desktop abaixo de 2.10.0 fica travado no preflight** `/system/compatibility` (estado `UPDATE_REQUIRED`). O app atualiza pela **API** (`/api/v1/updates/desktop`), nunca pelo GitHub.
- **Build oficial 2.10.0 ainda não foi gerado.** O Python 3.11 de `%LOCALAPPDATA%\Programs\Python\Python311` não tem `windows-toasts>=1.3,<2` nem `winotify>=1.1,<2` (`requirements.txt:15-16`); sem elas o build sai **sem balões do Windows**. Os três PyInstaller (`Updater.spec`, `ControleProducao.spec`, `Launcher.spec`) rodam bem. Instalar as dependências é o primeiro passo.
- Caminho oficial único: 3 specs -> `installer\ControleProducao.iss` (ISCC) -> `scripts\build_update_package.py` -> `scripts\generate_release_manifest.py` -> `scripts\sync_release_to_server.py`. **Não usar** `gerar_exe_pyside6.bat`, `gerar_exe_setup.bat`, `setup.py`, `setup_cxfreeze.py` nem os specs `Controle Producao 2.0.spec` / `Controle Producao Industel Telecom.spec` (legado: layout plano, sem Launcher/Updater, empacotam config local).

## 1. Pré-requisitos

1. Commits da versão 2.10.0 presentes (`6ea5fd8`: `app/version.py` com `APP_VERSION = "2.10.0"`, `MINIMUM_API_VERSION = "0.12.0"`, e os dois `.iss` com 2.10.0). Conferir:
   ```powershell
   git log --oneline -1 6ea5fd8
   Select-String -Path app\version.py -Pattern 'APP_VERSION|MINIMUM_API_VERSION'
   Select-String -Path installer\ControleProducao.iss -Pattern 'MyAppVersion|OutputBaseFilename'
   ```
   Verificação: `2.10.0`, `0.12.0`, `ControleProducaoSetup-2.10.0`.
2. Árvore limpa e suíte verde, sem mascarar falha com pipe: `python -m pytest tests api/tests -q --timeout=300`. Os testes `tests/test_installer_version_consistency.py` e `tests/test_edition.py` pegam divergência entre os `.iss` e `APP_VERSION`.
3. Inno Setup 7 em `C:\Program Files\Inno Setup 7\ISCC.exe`.
4. Tag local `v2.10.0` no commit exato do build (criada pelo maestro; **push de tag é [AUT]**).
5. Python 3.11 de build (o `python` do PATH é 3.14, e `.python-version` diz 3.12: **não buildar com eles**).
6. Frota: confirmar quais máquinas estão em 2.9.0 ou maior. Máquinas em 2.8.x ou menor **não recebem atualização pelo feed** (layout versionado não migra por update; falham e voltam). Essas precisam reinstalar pelo `ControleProducaoSetup-2.10.0.exe`.

## 2. Guardar o que o build sobrescreve

`generate_release_manifest.py` grava `release\manifest.json` e `create_release_files.py` grava `release\latest.json` e `release\*.sha256`, **sobrescrevendo** os do 2.9.0. O build do 2.9.0 não é reproduzível; os artefatos dele são a base de rollback.

```powershell
New-Item -ItemType Directory -Force C:\Users\Industel\deploy\arquivo_2.9.0 | Out-Null
Copy-Item release\manifest.json, release\latest.json, release\ControleProducaoSetup-2.9.0.sha256, release\ControleProducaoSetup-2.9.0.exe, release\ControleProducao-2.9.0-update.zip C:\Users\Industel\deploy\arquivo_2.9.0\
Get-FileHash C:\Users\Industel\deploy\arquivo_2.9.0\* -Algorithm SHA256
```
Verificação: hashes conferem com `ControleProducaoSetup-2.9.0.sha256` e com o `manifest.json` (`0fff1cd8...e625` o Setup, `f783ee19...c2b7` o ZIP, segundo a auditoria 07).

## 3. Build (máquina de build)

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
& $py --version                                   # 3.11.x
& $py -m pip install -r requirements.txt          # traz windows-toasts e winotify, que faltavam
& $py -c "import winotify, windows_toasts; print('toasts ok')"
& $py -m pip freeze > C:\Users\Industel\deploy\pip_freeze_2.10.0.txt
```
Verificação: imprime `toasts ok`. Sem isso, **pare**: o build sairia sem notificação do Windows. (`pip freeze` com `>` é texto; o aviso de redirecionamento é só para binários.) Guarde o `pip_freeze` junto da release.

Depois, na raiz do repositório:

```powershell
& $py -m PyInstaller Updater.spec --clean --noconfirm
& $py -m PyInstaller ControleProducao.spec --clean --noconfirm
& $py -m PyInstaller Launcher.spec --clean --noconfirm
& "C:\Program Files\Inno Setup 7\ISCC.exe" installer\ControleProducao.iss
& $py scripts\build_update_package.py
& $py scripts\generate_release_manifest.py --artifact release\ControleProducao-2.10.0-update.zip --release-version 2.10.0 --content-type application/zip --minimum-server-version 0.12.0 --api-contract-version v1 --release-notes "<TEXTO_DAS_NOVIDADES>"
& $py scripts\create_release_files.py
```

Observações:

- `--release-version 2.10.0` é opcional; se informado precisa coincidir com `APP_VERSION` (barra erro de versão).
- `--channel` fica no padrão `production`. O manifest é gravado em `release\manifest.json`.
- `create_release_files.py` gera `release\ControleProducaoSetup-2.10.0.sha256` e `release\latest.json` com `tag: v2.10.0`. O app **não lê** `latest.json`; ele só serve de conferência do hash do Setup para distribuição manual (e traz notas fixas do script, ignore-as).
- O `dist\` e o `build\` antigos (14/10) estão atrás do código: os `--clean` regeneram; nunca empacote a partir de uma pasta antiga.

### Conferência

```powershell
Get-FileHash release\ControleProducaoSetup-2.10.0.exe, release\ControleProducao-2.10.0-update.zip -Algorithm SHA256
Get-Content release\ControleProducaoSetup-2.10.0.sha256
Get-Content release\manifest.json
```
Verificação: o sha256 do Setup bate com o `.sha256`; o do ZIP bate com `artifact.sha256` do `manifest.json`; o manifest tem `release_version` 2.10.0 e `minimum_server_version` 0.12.0; tamanhos coerentes (cerca de 160 a 170 MB o Setup e 190 a 205 MB o ZIP). Confira que `dist\ControleProducao\ControleProducaoApp.exe` existe. Arquive Setup, ZIP, manifest, `.sha256` e `pip_freeze` em `C:\Users\Industel\deploy\arquivo_2.10.0\`.

## 4. Teste antes de publicar (dev e máquina limpa, sem produção)

Nada de produção aqui. Checklist mínimo em Windows 10 limpo:

1. Instalar o Setup novo como admin, abrir pelo atalho, digitar a URL da API de **dev** no primeiro acesso, login.
2. Conferir `current.json`, `versions\2.10.0\ControleProducaoApp.exe`, `Updater.exe` e as pastas em `%ProgramData%\Industel\ControleProducao`.
3. Abrir Inspeção, Logística, imprimir um relatório de LOG/carga (PDF), ver o balão do Windows (valida as dependências de toast) e o agente `--notifier`.
4. Instalar por cima de um 2.9.0 já usado: dados e login preservados, mesma `installation_id`.
5. Atualização real 2.9.0 -> 2.10.0 pela API de dev: edição **oficial** com `DESKTOP_API_BASE_URL` apontando para a dev (a edição de teste não atualiza). UAC aparece uma vez no `--stage`. Repetir com usuário **não administrador**.
6. Falhas provocadas: ZIP adulterado (sha256 errado) vai para quarentena sem instalar; `ControleProducaoApp.exe` inválido dá `ROLLED_BACK`.
7. Desinstalar: `versions\`, `_internal` e `current.json` somem, `%ProgramData%\Industel\ControleProducao` fica, não sobra entrada em `HKCU\...\Run` (o `.iss` oficial agora limpa, commit e4242ea).

Subir o release na API de **dev** (8001) com `sync_release_to_server.py` (sem `--authorize`) para o item 5. Não aponte nada para a 8000.

Sem esse teste em máquina limpa, o instalador oficial nunca foi verificado fora do ambiente de build. Registre o que foi e o que não foi testado.

## 5. Decisão: piloto ou direto

O estado da release e o canal decidem quem vê a atualização:

- `PRODUCTION` é o canal padrão de toda instalação; `PILOT` só por atribuição explícita de admin com `updates.manage`.
- Uma release `AUTHORIZED` que **nunca entrou no pipeline de canal** é visível para **todos** os canais, inclusive produção (`api/app/channels/service.py:294-335`). Portanto `sync_release_to_server.py --authorize` publica direto para todo mundo.
- O piloto passa por `PILOT_AUTHORIZED -> PILOT_APPROVED -> PRODUCTION_AUTHORIZED` e exige os gates: mínimo de clientes piloto atualizados com sucesso, zero `UPDATE_FAILED`/`START_FAILED` e janela de observação (`observation_minutes`). Os valores vêm da configuração dos gates (`POST /api/v1/channels/pilot/2.10.0/gates` avalia sem aprovar).

**Efeito do MINIMUM_DESKTOP_VERSION:** no piloto, enquanto a release não é promovida, **o restante da frota (fora do PILOT) está travado sem caminho de atualização** (o diálogo só oferece "Atualizar agora" para quem enxerga uma release autorizada). No modo direto, a frota inteira enxerga a release no mesmo instante e cada máquina atualiza ao abrir. Escolha, [AUT]:

- **A. Direto** (`--authorize`): sem observação, mas sem rede de segurança. O mais curto para a frota. Faça só depois de testar a fundo na máquina limpa.
- **B. Piloto primeiro** (recomendado se a observação for curta, ou se a janela for à noite): atribuir 1 a 3 instalações ao PILOT **antes da janela da API** (`POST /api/v1/channels/installations/{id}/assign`, com `GET /api/v1/channels/installations` para achar os ids), autorizar o piloto, validar, aprovar, promover. Se `observation_minutes` for grande, a frota fica travada o tempo todo; nesse caso prefira A, ou configure os gates com observação curta antes.

## 6. Publicar (só depois da API 0.12.0 no ar e saudável)

### D1. Confirmar a API [AUT, leitura]

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/compatibility     # no SERVIDOR
```
Verificação: `server_version` 0.12.0, revisão `20261109_0047`. Qualquer ação no SERVIDOR é [AUT].

### D2. Levar ao SERVIDOR e sincronizar [AUT]

Os artefatos precisam estar **dentro do container da API**; a imagem não traz a pasta `scripts/` (o Dockerfile só copia `api/`), então leve o script junto:

```powershell
# neste PC
scp release\manifest.json release\ControleProducao-2.10.0-update.zip scripts\sync_release_to_server.py <USUARIO>@192.168.2.128:C:/ControleProducao/release_2.10.0/
```
No SERVIDOR:
```powershell
Set-Location C:\ControleProducao
Get-FileHash release_2.10.0\* -Algorithm SHA256                  # iguais aos do PC
docker cp release_2.10.0\manifest.json controle_producao_api:/tmp/manifest.json
docker cp release_2.10.0\ControleProducao-2.10.0-update.zip controle_producao_api:/tmp/ControleProducao-2.10.0-update.zip
docker cp release_2.10.0\sync_release_to_server.py controle_producao_api:/tmp/sync_release_to_server.py
docker exec -e PYTHONPATH=/app controle_producao_api python /tmp/sync_release_to_server.py --manifest /tmp/manifest.json --package /tmp/ControleProducao-2.10.0-update.zip --source manual
```
(Modo A: acrescente `--authorize` ao último comando. Modo B: **não** acrescente.)

Verificação: imprime `OK: release 2.10.0 sincronizada, estado=READY` (ou `AUTHORIZED` no modo A). Se a API recusar por `minimum_server_version`, confirme a versão em execução. `PYTHONPATH=/app` é necessário porque o script, fora de `/app`, calcula mal a raiz; esse comando exato **não foi ensaiado**, ensaie na dev. A mesma operação existe por API para admin com `updates.manage`: `POST /api/v1/updates/desktop/sync` (aceita `manifest_path` e `package_path` dentro do container).

Limpeza do que foi copiado: `docker exec controle_producao_api rm -f /tmp/manifest.json /tmp/ControleProducao-2.10.0-update.zip /tmp/sync_release_to_server.py`.

Estado das releases: `GET /api/v1/updates/desktop/admin/releases` (Bearer de admin) deve listar 2.10.0, e a 2.9.0 que estava `AUTHORIZED` hoje continua listada.

### D3. Modo B: piloto [AUT]

Com um token de admin (`updates.manage`):

```
POST /api/v1/channels/installations/{installation_id}/assign     # antes da janela, com a máquina PILOT
POST /api/v1/channels/pilot/2.10.0/authorize
GET  /api/v1/channels/pilot/2.10.0
POST /api/v1/channels/pilot/2.10.0/gates
```
Nas máquinas piloto: abrir o app (já travado no 2.9.0), "Atualizar agora", UAC, reabre em 2.10.0, abrir proposta, Inspeção e Logística. Olhar `updater.log` das máquinas e `docker logs controle_producao_api`. Se algo falhar: `POST /api/v1/channels/pilot/2.10.0/fail` ou `.../pause`.

### D4. Promover [AUT]

```
POST /api/v1/channels/pilot/2.10.0/approve      # só com os gates ok
POST /api/v1/channels/pilot/2.10.0/promote
```
A promoção reconfere que manifest e artefato têm o mesmo hash do snapshot do piloto. Só então o resto da frota passa a enxergar a atualização.

### D5. Depois

- Acompanhar `GET /api/v1/channels/installations` e os logs para ver quantas máquinas já estão em 2.10.0.
- Máquinas em 2.8.x ou menor: reinstalar pelo Setup 2.10.0 (UAC de admin local).
- Distribuir o `ControleProducaoSetup-2.10.0.exe` para PCs novos; hoje **não há local oficial documentado** para o Setup completo (ver perguntas do checklist).
- Opcional, depois de estável: subir `RECOMMENDED_DESKTOP_VERSION` (já é 2.10.0 no código). Qualquer mudança de política persistida é [AUT].
- Tag `v2.10.0` local; **push da tag é [AUT]**.

## 7. Rollback de release

Duas regras que não podem ser esquecidas:

1. **`revoke` só para de oferecer a release.** Quem já atualizou **não volta sozinho** (o Updater recusa downgrade, `manifest_policy.py`).
2. **Voltar um Desktop para 2.9.0 enquanto a API for 0.12.0 não adianta:** o preflight trava qualquer Desktop abaixo de 2.10.0. Só dá para operar com 2.9.0 se a API também voltar para a 0.11.0 (ver rollback da API, com perda de dados desde o dump) ou se a API receber uma versão 0.12.x com `MINIMUM_DESKTOP_VERSION` menor. Na prática, o rollback do Desktop é **corrigir para frente**: publicar uma 2.10.1.

Passos:

1. Parar de oferecer [AUT]: `POST /api/v1/channels/pilot/2.10.0/revoke` (se passou por canal) ou `POST /api/v1/updates/desktop/2.10.0/revoke` com `{"reason": "<MOTIVO>"}`.
2. Máquina individual com 2.10.0 quebrada: fechar o app e rodar, como administrador, `scripts\recuperar_atualizacao.bat "<caminho do Setup>"` (encerra `ControleProducao.exe`, `ControleProducaoApp.exe` e `Updater.exe` e abre o instalador). Reinstalar o Setup 2.10.0 (ou, se a API voltou para a 0.11.0, o 2.9.0 arquivado em `deploy\arquivo_2.9.0`). Dados em `%ProgramData%\Industel\ControleProducao` não são tocados. Alternativa: regravar `current.json` com a versão anterior (a pasta anterior fica em `versions\`).
3. Frota inteira: publicar uma versão **maior** com o código corrigido (por exemplo 2.10.1; versão igual ou menor é recusada) e repetir D2 a D4.

## 8. Pendências conhecidas que afetam este runbook

- Build oficial 2.10.0 não gerado (falta instalar as dependências de toast, seção 3).
- Instalador oficial nunca verificado em máquina limpa; sem assinatura de código (SmartScreen/antivírus podem avisar; mitigação documentada: exclusão por GPO).
- Manifest e pacote não são assinados (o sha256 vem do próprio manifest). Rede interna e túnel HTTPS: risco aceito, registrar a decisão.
- `scripts\build_test_installer.py` procura `Inno Setup 6`; use `ISCC_PATH` se for gerar o instalador de teste.
- Primeiro acesso em máquina nova exige digitar a URL da API (não há URL de produção embutida).
- Edição de teste não testa atualização (`updates_enabled()` falso nela).
