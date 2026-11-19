# Plano de execução do deploy por SSH, com equipe de agentes

Escrito em 2026-11-19. Complementa `CHECKLIST_ANTES_DE_RODAR.md`, `RUNBOOK_DEPLOY_API.md` e `RUNBOOK_DEPLOY_DESKTOP.md`: aqui está quem faz cada coisa, em que ordem e onde o Henrique precisa autorizar. Os comandos exatos ficam nos runbooks e no checklist; este plano não os repete.

## 1. Acesso e regras

- Acesso: `ssh -i ~/.ssh/id_servidor industel@192.168.2.128` (testado em 2026-11-19, devolve o hostname `SERVIDOR`). A API fica em `C:\ControleProducao`.
- Um único agente por vez escreve no SERVIDOR. Leituras podem ser paralelas.
- Cada passo marcado [AUT] segue este ritual: o agente descreve o comando exato, o efeito, como desfazer e devolve ao Claude principal. O Claude principal pergunta ao Henrique e só executa depois do "sim" dele. Uma autorização vale para aquele passo, não para o seguinte.
- Nenhum agente imprime, grava ou envia ao chat senha, chave, token, `.env` ou conteúdo de `SECRET_KEY`. Saídas de `printenv` mostram só os nomes.
- Docker via SSH: `docker pull` falha (cofre de credenciais sem sessão), então a imagem vai com `docker save`, `scp` e `docker load`. Dump nunca por redirecionamento do PowerShell: gerar dentro do container e usar `docker cp`.
- Nunca dois conectores do mesmo túnel Cloudflare ao mesmo tempo. Ninguém mexe no `cloudflared` sem [AUT].
- Parada imediata e aviso ao Henrique se: a revisão do banco não for `20261014_0038`; houver menos de 5 GB livres em `C:`; o backup não validar; qualquer comando de escrita falhar pela metade.
- Todo passo executado vai para `docs/deploy/LOG_EXECUCAO.md` (hora, passo, resultado, sem segredos).

## 2. Equipe

| Papel | Modelo | Faz |
|---|---|---|
| Coordenador (`maestro`) | opus | Ordena as fases, aplica o ritual [AUT], decide quando parar. Não escreve código. |
| Leitor do SERVIDOR | haiku | Roda só leituras (A1 a A9, B1) e devolve os resultados resumidos e sem segredos. |
| Operador de deploy | sonnet | Executa os passos de escrita no SERVIDOR, um por vez, depois do [AUT]. |
| Verificador | haiku | Smoke test, conferência dos números antes e depois da migração, `/docs` fechado. |
| Revisor de segurança | opus | Plano do admin e do superusuário alternativo, e revisão do que vai ser feito antes do passo que mexe em contas. |
| Escriba | haiku | Mantém `LOG_EXECUCAO.md` e atualiza o checklist. |

## 3. Fases

### Fase 0. Ler o SERVIDOR (sem [AUT], só leitura)
Leitor roda A1 a A9 do checklist e B1 (eventos de login do admin). Entrega `docs/auditoria-deploy/08_estado_servidor.md`.
**Gate:** a revisão é `20261014_0038`? Os volumes e o compose têm os nomes assumidos? Há anexos em `/app/data/storage`? Há 5 GB livres? Se alguma resposta divergir dos runbooks, o Coordenador ajusta os runbooks antes de seguir.

### Fase 1. Decisões do Henrique (ninguém executa nada)
Com o resultado da Fase 0 em mãos, o Henrique responde: D1 mínimo do desktop (manter 2.10.0 ou baixar), D2 piloto ou direto e quais máquinas, D3 perfis que recebem Inspeção e Logística, D4 corrigir para frente ou voltar o dump, D6 repositório privado antes de qualquer push, quem é o superusuário alternativo ao `admin`, local da cópia externa do backup e a janela. Se D1 mudar para baixar o mínimo, a API vira 0.12.1 e a imagem é refeita antes da Fase 3.

### Fase 2. Preparar sem derrubar nada [AUT em cada item que escreve]
1. Levar a imagem 0.12.0 ao SERVIDOR com `docker save`, `scp` e `docker load`, sem tocar na 0.11.0 (é a imagem de rollback). Só adiciona uma imagem.
2. Copiar compose novo, `backup_db.ps1`, `smoke_deploy.py` e a release do desktop para uma pasta de staging no SERVIDOR, sem sobrescrever os arquivos em uso.
3. Cópia preventiva dos anexos de `/app/data` do container que está rodando para o disco do SERVIDOR, e conferência de contagem e tamanho.
4. Backup do banco com validação (`pg_restore --list` e sha256) e cópia para fora do SERVIDOR, no destino que o Henrique escolher.
5. Ensaio da migração 0038 para 0047: restaurar o dump num Postgres descartável dentro do SERVIDOR (os dados não saem de lá), rodar `alembic upgrade head` com a imagem nova, medir o tempo, conferir `nf_que_a_0043_vai_cancelar` e `propostas_entregues_almox`, e remover o banco descartável.
6. Criar o usuário de smoke, só leitura em Logística, Inspeção e Almoxarifado. Senha gerada e entregue só ao Henrique, nunca no chat.
**Gate:** ensaio sem erro, tempo aceitável e backup restaurado com sucesso.

### Fase 3. Janela da API (runbook `RUNBOOK_DEPLOY_API.md`, passos 1 a 13)
Operador executa os passos na ordem do runbook, cada um com [AUT]: parar a API, backup final, ajustar o `.env`, compose novo, migração, subir a API, devolver os anexos, conferir os dados, smoke, atualizar o backup agendado, fechar. Verificador roda o smoke e compara os números da Fase 0 com os de depois.
**Critério de rollback:** o do runbook, seção 5. Falha antes da migração: voltar a imagem 0.11.0. Falha depois, sem dados novos: restaurar o dump. Com dados novos: decisão D4 do Henrique.

### Fase 4. Depois da API no ar
1. Permissões de Inspeção e Logística aos perfis da D3.
2. Troca da senha do `admin` (ou desativação), só depois de o superusuário alternativo ter feito login. Revisor de segurança valida a ordem. A senha nova não aparece no chat: o Henrique a troca pelo Desktop, ou o Operador gera uma e a grava num arquivo local que só o Henrique lê.
3. Revisão dos `LOGIN_SUCCESS` do admin que B1 listou. Se houver suspeita, decidir sobre trocar a `SECRET_KEY` e revogar sessões.
4. Ligar o Almox+ só depois do smoke aprovado e do relógio do SERVIDOR conferido.
5. Regra de rate limit no Cloudflare para `/api/v1/auth/*`. Isso exige que o conector `cloudflare-api` seja autorizado por você; sem isso, a alternativa é ajustar `LOGIN_IP_MAX_FAILURES` no `.env`.

### Fase 5. Desktop (runbook `RUNBOOK_DEPLOY_DESKTOP.md`, seção 6)
Só depois da Fase 3 saudável. D1: confirmar a API. D2: levar a release ao SERVIDOR e sincronizar com `sync_release_to_server.py`. D3 se for piloto: liberar o canal PILOT e atribuir as máquinas. D4: promover depois de alguns dias, com o Henrique autorizando. O Verificador confere `/system/compatibility` e o feed.

### Fase 6. Git (neste PC, não pelo SSH)
Depois de D6. `git push origin logistica-melhorias`, merge fast-forward em `main`, push das tags `api-v0.12.0` e `v2.10.0`. Cada push é [AUT].

## 4. O que fica só com o Henrique

- Instalar o Setup 2.10.0 numa máquina limpa e ver o balão do Windows.
- Conferir as telas com dados reais.
- Todas as decisões da Fase 1.
- Proteção do ambiente `production` no GitHub.
- Digitar a credencial da pasta de rede para a cópia externa do backup (`cred_backup.xml`), no SERVIDOR.
- Avisar a equipe da janela.

## 5. Pronto quando

- API 0.12.0 saudável, schema na revisão `20261109_0047`, smoke verde, `/docs` fechado.
- Backup novo validado e uma cópia fora do SERVIDOR.
- Admin sem a senha pública antiga e sem o log de senha.
- Desktop 2.10.0 no canal certo e as máquinas atualizando.
- Commits e tags publicados, com o histórico do repositório decidido (D6).
- `LOG_EXECUCAO.md` completo.
