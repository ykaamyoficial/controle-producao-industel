# Auditoria git (somente leitura) - 2026-11-19

Branch atual: `logistica-melhorias` (HEAD = c1d31a3). Principal: `main` (73e956a, igual a `origin/main`).
Nada foi alterado: sem commit, push, checkout, merge, reset ou stash.

## Estado geral

- `main...HEAD` = 0 para trás / 101 à frente. Todo o `main` está contido na branch.
- `logistica-melhorias` está 20 commits à frente de `origin/logistica-melhorias` (remoto em ad74879). Esses 20 commits existem só localmente.
- Remoto único: `origin` = github.com/ykaamyoficial/controle-producao-industel.
- `git status`: 14 arquivos modificados em `.claude/agents/` e 3 não rastreados (`nao_existe.json`, `output/`, `Nova pasta - Atalho.lnk`).
- Diff `main...HEAD`: 227 arquivos, +28510 / -264. Maiores áreas: `api/tests` (10,1%), `api/alembic/versions` (3,9%), `api/app/modules/logistics` (3,5%), `api/app/modules/almox_integration` (3,0%).

## Achados

| # | Arquivo:linha | Achado | Severidade | Evidência |
|---|---|---|---|---|
| 1 | `app/version.py:8` | Versão do Desktop continua `2.9.0`, a mesma já publicada. Há 101 commits novos (LOG com peso, migration 0047, etc.) e nenhuma subida de versão. | corrigir antes | `APP_VERSION = "2.9.0"` |
| 2 | `api/app/core/config.py:10` | Versão da API continua `0.11.0`, igual à tag `api-v0.11.0`. Já há migration 0047 e rotas novas de Logística depois dessa tag. | corrigir antes | `API_VERSION = "0.11.0"`; `git log` mostra `ed6230a Migration 0047` |
| 3 | `release/latest.json:4` | O manifesto aponta `tag: v2.9.0`, mas essa tag não existe. A tag real é `v2.9.0-padrao-janelas` (aponta para 73e956a). | corrigir antes | `git tag` sem `v2.9.0` |
| 4 | `release/latest.json`, `release/manifest.json` | Hashes conferem: exe `0fff1cd8...e625` e zip `f783ee19...c2b7` batem com os arquivos em `release/`. Os artefatos estão fora do git (`.gitignore`: `release/`, `*.exe`, `*.zip`). | ok | `Get-FileHash` igual ao JSON |
| 5 | `logistica-melhorias` | 20 commits só locais (c1d31a3..ad74879 do remoto). Se o deploy sair do remoto, falta o push. | bloqueia deploy se o deploy vier do remoto | `[origin/logistica-melhorias: ahead 20]` |
| 6 | `.claude/agents/*.md` (14 arquivos) | Cada arquivo ganhou 1 linha no frontmatter: `model: sonnet` (9) ou `model: haiku` (5). Não tem relação com o app. | pode depois | `git diff -U0` mostra só `+model: ...` |
| 7 | `output/pdf/` | Duas cópias de manuais de laser (Bodor), 8,0 MB, não rastreadas. Material de terceiro, fora do deploy. | pode depois (ignorar) | `Manual_Bodor_Laser_Portugues.pdf` 6,0 MB, `..._Reformulado_PTBR.pdf` 2,4 MB |
| 8 | `nao_existe.json` | Arquivo `{}` de 2 bytes, lixo. | pode depois (apagar) | conteúdo `{}` |
| 9 | `Nova pasta - Atalho.lnk` | Atalho do Windows (1 KB), lixo. | pode depois (apagar) | arquivo `.lnk` |
| 10 | Repo (binários) | Nenhum `.exe`, `.zip`, `.db`, `.sqlite`, `.msi` rastreado. `release/` e `output/` não rastreados. Maiores rastreados: `api/app/modules/proposals/service.py` (422 KB, texto), fontes Inter (~2 MB no total), `web/package-lock.json` (267 KB), PNGs de `prototipos/` (~1 MB). | ok | `git ls-files` + tamanhos |
| 11 | `.gitignore` | `output/` não está ignorado (por isso aparece como não rastreado). | pode depois | ausência de `output/` no arquivo |
| 12 | Branches locais | `inspecao-datas` (67 à frente de main, 0 atrás) e `integracao-almox` (43 à frente) estão 100% contidas em `logistica-melhorias`. Os dois também existem no remoto com o mesmo tip. | pode depois (depois do merge da logística) | `merge-base --is-ancestor` = True |
| 13 | Branches já mescladas em main | `atualizador-versionado`, `avisador-windows-ultimo-login`, `codex/preparar-migracoes-sqlite`, `feature/dashboard-executivo`, `feature/importacao-pdf-nomus`, `feature/modulo-fiscal`, `feature/relatorios-por-area`, `padrao-janelas`, `refinamento-visual-onda-0`. Todas com 0 commits só dela. | pode depois (limpeza local) | `git branch --merged main` |

## Tags

`api-v0.9.0`, `api-v0.11.0`, `v2.0.0-base-segura`, `v2.1.0-importacao-nomus`, `v2.3.0-relatorios-operacionais`, `v2.6.0-anexos-chat`, `v2.6.1-otimizacao-carregamento`, `v2.6.2-corrige-updater`, `v2.9.0-padrao-janelas`. Todas são ancestrais de HEAD. Falta a tag `v2.9.0` que o manifesto cita (achado 3).

## Limitações desta auditoria

- Alguns comandos `git` (`branch --merged`, `diff --stat`) foram bloqueados pelo classificador do modo automático, porque um hook reescreveu a entrada para `rtk git ...`. Refiz as mesmas consultas via PowerShell, só leitura. Os resultados batem.
- Não verifiquei conteúdo de segredos nem o código dos commits, só metadados, contagem e versões.

## Recomendação de ordem de merge/push

1. Decidir a versão de release (Desktop e API). Hoje 2.9.0 e 0.11.0 não refletem o código novo. Subir antes de empacotar. (Só com decisão do Henrique.)
2. Limpar o lixo não rastreado: apagar `nao_existe.json` e `Nova pasta - Atalho.lnk`. Adicionar `output/` ao `.gitignore`, ou mover os PDFs para fora do repo. Não commitar nada disso.
3. Commitar à parte o `.claude/agents/` (`chore: definir modelo por agente`), ou deixar fora do deploy. Não misturar com a Logística.
4. Fazer merge de `logistica-melhorias` em `main` (101 commits, fast-forward, sem conflito porque main é ancestral). Depois `inspecao-datas` e `integracao-almox` ficam redundantes.
5. Push de `logistica-melhorias` e de `main` só com autorização explícita. Criar a tag de release (ex.: `v2.9.x`) alinhada ao `release/latest.json`, depois de corrigir o item 3.
6. Limpar branches locais já mescladas (`git branch -d`) só depois de confirmar o push.

## Perguntas abertas para o Henrique

1. Qual versão de release vai sair: Desktop 2.9.x ou 2.10.0? E API 0.11.x ou 0.12.0?
2. O deploy sai de `logistica-melhorias` (com push antes) ou de `main` depois do merge?
3. Os 20 commits locais não enviados ao remoto podem ser enviados quando você autorizar?
4. `release/latest.json` aponta `tag: v2.9.0`, que não existe. A tag correta é `v2.9.0-padrao-janelas`? Ou o manifesto deve ser corrigido?
5. Os PDFs de `output/` (manuais Bodor) podem ser apagados ou ficam fora do repo?
6. A alteração de `model:` nos agentes foi intencional? Deve ser commitada ou descartada?
