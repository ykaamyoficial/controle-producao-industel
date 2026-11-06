# Edicao de teste do Desktop

Instalador separado, para instalar **em paralelo** ao programa oficial no mesmo computador, sem um interferir no outro. Nao e uma release: nao entra em `release/latest.json`, `release/manifest.json` nem nos instaladores oficiais.

## Como funciona

`app/edition.py` e a fonte unica. A edicao vem da variavel `CONTROLE_PRODUCAO_EDITION=teste` ou do arquivo empacotado `app/config/edition.json` (so existe no build de teste, em `build_teste/`). Sem nenhum dos dois a edicao e **producao**, com caminhos e nomes identicos aos de sempre. Os tres `.spec` leem as mesmas variaveis; sem elas geram o build oficial.

## O que e isolado

| Item | Oficial | Teste |
|---|---|---|
| AppId do Inno | `{A70CE0BD-...}` | `{5B3F8E2A-7C41-4D9E-A6B0-3E7D12C94F58}` |
| Pasta de instalacao | `Program Files\Industel\Controle de Producao` | `...\Controle de Producao TESTE` |
| Grupo/atalhos | Controle de Producao Industel | Controle de Producao Industel TESTE |
| Executaveis | `ControleProducao.exe` / `ControleProducaoApp.exe` / `Updater.exe` | `ControleProducaoTeste.exe` / `ControleProducaoTesteApp.exe` / `UpdaterTeste.exe` |
| taskkill do instalador/desinstalador | nomes oficiais | **so** os nomes de teste |
| Dados (config, updates, diagnostics, tokens) | `ProgramData\Industel\ControleProducao` | `ProgramData\Industel\ControleProducaoTeste` |
| Logs | `%APPDATA%\ControleProducao\logs` | `%APPDATA%\ControleProducaoTeste\logs` |
| Replica e credencial do agente | `%LOCALAPPDATA%\ControleProducao\...` | `%LOCALAPPDATA%\ControleProducaoTeste\...` |
| Cache de anexos do chat | `ControleProducaoIndustel` | `ControleProducaoIndustelTeste` |
| Mutex (app e agente de bandeja) | `Global\ControleProducaoIndustel_*` | `Global\ControleProducaoIndustelTeste_*` |
| Chave Run (agente `--notifier`) | `ControleProducaoIndustelNotificacoes` | `ControleProducaoIndustelTesteNotificacoes` |
| AppUserModelID / ID de toast | `Industel.ControleProducao.2` / nome do app | `Industel.ControleProducaoTeste.2` / nome do app + TESTE |
| Saida do build | `dist/`, `build/`, `release/` | `dist_teste/`, `build_teste/`, `release/teste/` |

Alem disso, na edicao de teste: logo/icone recoloridos (laranja, matiz 28 graus; gerados por `scripts/build_test_installer.py`, os originais de `app/assets` nao sao alterados), titulo da janela e barra superior com `[TESTE]`, e a etiqueta "AMBIENTE DE TESTE · API dev <host>:<porta>" na barra superior, com o host:porta configurado (token `warning`, regra QSS em `app/ui/styles.py`).

## API e atualizacao

- A URL da API e **editavel**: vem da configuracao salva (`controle_producao_config.json` em `ProgramData\Industel\ControleProducaoTeste`). O instalador de teste usa por padrao `https://producaodev.ykora.com.br` (integracao sempre habilitada). `DESKTOP_API_BASE_URL` e **ignorada** na edicao de teste; so a configuracao salva vale.
- **Protecao contra a oficial**: `normalize_api_base_url` (usada por todo salvar/testar) recusa na edicao de teste qualquer URL com porta **8000** e URLs que nao sejam http(s) validas, com mensagem em portugues. Config salva com 8000 (editada a mao) cai no padrao 8001. A edicao de producao nao muda.
- A faixa da barra superior mostra o endereco configurado: `AMBIENTE DE TESTE · API dev <host>:<porta>` (lida ao abrir o programa).
- Atualizacao automatica **desligada por codigo**: `update_distribution_client.check_for_updates`, `update_checker.check_for_updates` (GitHub) e `UpdateCoordinator.start_update/start_required_update` retornam "sem atualizacao"/falha sem tocar a rede nem o Updater.
- Versao: a mesma base (`app/version.py`, hoje 2.9.0, intacta); o sufixo `-teste` aparece so em `AppVersion` do Inno e nos nomes. `versions\2.9.0` e `current.json` seguem semver puro, entao nenhum parsing quebra. A API de dev 0.11.0 passa no gate de compatibilidade (minimo 0.11.0).

## O que e compartilhado

- O codigo-fonte e a versao base; a API de dev e o banco de dev (so 8001); o certificado/UAC do Windows (instalador pede administrador, igual ao oficial); `HKCU\...\Run` e `AppUserModelId` usam chaves com nome proprio.

## Como gerar

```
scripts\build_test_installer.bat
```

Roda o PyInstaller de Updater, App e Launcher com a edicao de teste e depois o ISCC (`C:\Users\Industel\AppData\Local\Programs\Inno Setup 6\ISCC.exe`, ou `ISCC_PATH`). Saida: `release\teste\ControleProducaoTesteSetup-<versao>.exe` e `.sha256`. Precisa de ~1 GB livres no disco C: (dist_teste ~400 MB + work ~100 MB + instalador ~160 MB).

## Configurar a API em outro computador

Use `http://<endereco-do-computador-da-API>:8001` (ex.: `http://192.168.0.20:8001`; o computador da API precisa ter a porta 8001 liberada na rede/firewall).

Para testar computadores fora da rede local, pode-se usar o Cloudflare Tunnel. Com
`cloudflared` instalado no computador que executa a API, rode
`scripts\start_cloudflare_tunnel.bat`. O script sobe a API de dev e mostra uma URL
`https://...trycloudflare.com`; informe essa URL no campo **Endereco da API** do
programa de teste. Esse endereço é temporário e a janela do túnel precisa ficar aberta.

Para uso contínuo, crie um túnel nomeado no painel Zero Trust da Cloudflare, publique
o serviço `http://127.0.0.1:8001`, defina `CLOUDFLARE_TUNNEL_TOKEN` na sessão do Windows
e rode `scripts\start_cloudflare_named_tunnel.bat`. O token não deve ser salvo no Git.

1. Abra o programa de teste. Se nao conectar em `127.0.0.1:8001`, abre sozinha a janela "Conexao com o servidor".
2. Digite o endereco no campo "Endereco da API", clique "Testar conexao" e, com "conexao confirmada", "Salvar e continuar".
3. Alternativa na tela de Login: botao "Configurar servidor" (abre o Diagnostico da API; altere "URL da API", "Salvar" e "Testar conexao"). Depois do login: Configuracoes -> Diagnostico da API.
4. Porta 8000 e recusada ("A edicao de teste nao pode usar a API oficial").

## Instalar e desinstalar

- Instalar: executar o `.exe` (pede administrador). Atalho "Controle de Producao Industel TESTE". O oficial continua intacto.
- Desinstalar: "Aplicativos e recursos" -> "Controle de Producao Industel TESTE". Remove a pasta de instalacao, `ProgramData\Industel\ControleProducaoTeste`, a chave Run e a identidade de toast de teste. Logs em `%APPDATA%\ControleProducaoTeste` e dados de `%LOCALAPPDATA%\ControleProducaoTeste` nao sao apagados.

## Limitacoes

- Precisa de uma API de dev na porta 8001 (ou outra que nao seja 8000) acessivel pela rede.
- Instalador nao assinado: o SmartScreen pode avisar ("Mais informacoes" -> "Executar assim mesmo").
- A faixa so atualiza o endereco ao reabrir o programa depois de trocar a URL.
- Testes da edicao: `tests/test_edition.py`.
