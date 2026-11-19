# Checklist antes de rodar o deploy (só o Henrique pode fazer)

Escrito em 2026-11-19, branch `logistica-melhorias`. Tudo aqui é **[AUT]**: exige o Henrique, porque mexe ou olha o SERVIDOR (192.168.2.128), a produção, o GitHub ou push. Os comandos de **leitura** estão prontos para colar no SERVIDOR (PowerShell, na pasta `C:\ControleProducao`). Nenhum deles altera nada, e nenhum imprime credencial. Cole o resultado de volta no chat sem o conteúdo de `.env` (não existe comando aqui que o imprima).

Os runbooks que dependem deste checklist: `RUNBOOK_DEPLOY_API.md` e `RUNBOOK_DEPLOY_DESKTOP.md`.

Commits locais desta rodada (confirmados com `git log`): `3472d0c` admin por `BOOTSTRAP_ADMIN_PASSWORD`; `6ea5fd8` versões Desktop 2.10.0, API 0.12.0 e política de compatibilidade; `9e3d8d5` compose de produção; `61947e7` backup; `d3e8bc0` rollback exige revisão igual; `9b46cbf` hardening (/docs fechado, heartbeat com Bearer, senha mínima 10); `8120360` limite de login por IP; `bd73992` edição de teste recusa hosts de produção; `e4242ea` empacotamento; `a64ae9b` segredos de dev fora do repositório; `2945d9e` anonimização de fixtures; `87b5965` smoke de deploy. Branch `logistica-melhorias`, 114 commits à frente da `main` (a `main` é ancestral: merge fast-forward).

## A. Leituras no SERVIDOR (cole e me devolva a saída)

### A1. Revisão do banco, tabelas novas e números que a migração vai mexer

Cria um arquivo SQL (só `SELECT`) e roda dentro do container do Postgres:

```powershell
Set-Location C:\ControleProducao
@'
SELECT version_num AS revisao_alembic FROM alembic_version;
SELECT to_regclass('inspections') AS inspections, to_regclass('logistics_logs') AS logistics_logs;
SELECT count(*) AS perfis_admin FROM roles WHERE code = 'admin';
SELECT count(*) AS nf_canceladas_hoje FROM fiscal_invoices WHERE status = 'CANCELADA';
SELECT count(*) AS nf_que_a_0043_vai_cancelar FROM fiscal_invoices fi
 WHERE fi.status = 'REGISTRADA'
   AND EXISTS (SELECT 1 FROM fiscal_invoice_items i WHERE i.fiscal_invoice_id = fi.id AND NOT i.active)
   AND NOT EXISTS (SELECT 1 FROM fiscal_invoice_items i WHERE i.fiscal_invoice_id = fi.id AND i.active);
SELECT count(*) AS propostas_entregues_almox FROM proposals WHERE warehouse_status = 'ALMOXARIFADO_ENTREGUE';
SELECT count(*) AS usuarios, count(*) FILTER (WHERE active) AS ativos FROM users;
'@ | Set-Content C:\ControleProducao\leitura.sql -Encoding ascii
docker cp C:\ControleProducao\leitura.sql controle_producao_postgres:/tmp/leitura.sql
docker exec controle_producao_postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -f /tmp/leitura.sql'
docker exec controle_producao_postgres rm -f /tmp/leitura.sql
```
Esperado: revisão `20261014_0038`; `inspections` e `logistics_logs` vazios (NULL); 1 perfil admin. **Se a revisão for outra, pare e me avise** (os runbooks assumem 0038; a auditoria 03/06 a leu de docs, não do SERVIDOR). Anote `nf_que_a_0043_vai_cancelar` e `propostas_entregues_almox`: são a prova depois da migração.

### A2. Versão da imagem em execução e imagens disponíveis

```powershell
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker image ls local/controle-producao-api
Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/version
```
Esperado: `local/controle-producao-api:0.11.0` em execução; a `0.11.0` presente na lista (será a imagem de rollback; **não pode ser sobrescrita**).

### A3. Volumes Docker (confirmar os nomes assumidos)

```powershell
docker volume ls
docker inspect controle_producao_api --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{println}}{{end}}'
```
Assumidos: `controle_producao_industel_postgres_prod_data`, `controle_producao_industel_update_repository_data` e (novo, ainda não existe) `controle_producao_industel_api_data`. Se os nomes reais forem outros, o `backup_db.ps1` precisa de `-VolumeStorage`/`-VolumeUpdates` com os reais. Hoje a API deve mostrar **só** o volume de updates (os anexos estão na camada do container).

### A4. Variáveis do container: só os NOMES

```powershell
docker exec controle_producao_api printenv | ForEach-Object { ($_ -split '=', 2)[0] } | Sort-Object
```
Imprime nomes, nunca valores. O que procuramos: `ALMOX_INTEGRATION_SECRET`/`ALMOX_WEBHOOK_URL` ausentes (na 0.11.0 o compose não as repassava, o que significa que Almox+ não funciona hoje se estava planejado), `CLIENT_VERSION_ENFORCEMENT_ENABLED` presente ou ausente, `PASSWORD_MIN_LENGTH` ausente (então vale o default antigo).

### A5. Os anexos existem hoje? (define a urgência da cópia de `/app/data`)

```powershell
docker exec controle_producao_api sh -c 'ls -la /app/data; du -sh /app/data/storage /app/data/audit_spool /app/data/system_state 2>&1'
docker exec controle_producao_api sh -c 'find /app/data/storage -type f | wc -l'
```
Se `/app/data/storage` tiver arquivos, a cópia dos Passos 4 e 9 do runbook é **obrigatória**. Se der "No such file", ninguém anexou nada até hoje.

### A6. Espaço em disco e memória

```powershell
Get-PSDrive C | Select-Object @{n='UsadoGB';e={[math]::Round($_.Used/1GB,1)}}, @{n='LivreGB';e={[math]::Round($_.Free/1GB,1)}}
Get-CimInstance Win32_OperatingSystem | Select-Object @{n='RamLivreGB';e={[math]::Round($_.FreePhysicalMemory/1MB,1)}}
docker system df
```
Mínimo: 5 GB livres em `C:` (imagem nova ~ centenas de MB, dump, tar do volume de updates de 1,3 GB e cópia de anexos).

### A7. Último backup e última validação

```powershell
Get-ChildItem C:\ControleProducao\backups | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name, Length, LastWriteTime
Get-Content C:\ControleProducao\backups\backup.log -Tail 20
Get-ScheduledTaskInfo -TaskName ControleProducaoBackup | Select-Object LastRunTime, LastTaskResult, NextRunTime
(Get-ScheduledTask -TaskName ControleProducaoBackup).Actions | Select-Object Execute, Arguments
```
Esperado: dump com data de hoje ou de ontem, `LastTaskResult` 0, sem linha `ERRO` no log. O backup agendado antigo (`backup_db.ps1` da época da virada) valida só o tamanho (acima de 100 KB), não confere `pg_restore --list` nem sha256; os arquivos `cp_*.dump` dele nunca tiveram **teste de restauração registrado** (achado C2). O script novo faz as duas validações. Confira nos `Arguments` se a tarefa passa `-Destino` (cópia externa); a auditoria diz que não passa e que a cópia externa está pendente (credencial recusada).

### A8. Saúde da stack e relógio

```powershell
docker ps --format 'table {{.Names}}\t{{.Status}}'
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready
w32tm /query /status | Select-String 'Source|Last Successful Sync'
docker ps -a --format 'table {{.Names}}\t{{.Status}}'   # o cloudflared deve estar ligado; nenhum "caddy"
```
Esperado: postgres e api `healthy`, `ready` 200, cloudflared `Up`. O relógio importa para o Almox+ (a assinatura vale ±300 s).

### A9. Compose atual no SERVIDOR

```powershell
Get-ChildItem C:\ControleProducao -File | Select-Object Name, Length, LastWriteTime
Select-String -Path C:\ControleProducao\docker-compose.prod.yml -Pattern 'api_data' -SimpleMatch -Quiet
```
Confirma onde os compose vivem (os runbooks assumem `C:\ControleProducao\`) e que o atual ainda **não** tem `api_data` (esperado: `False`).

## B. Segurança: admin (fazer logo depois do deploy, preparar agora)

### B1. Eventos de login do `admin` desde que o túnel foi aberto (somente leitura)

Troque `<DATA_ABERTURA_TUNEL>` pela data (formato `2026-10-01`); se não souber, use uma data bem antiga. IPs vão aparecer como o do proxy; olhe horário e `user_agent`.

```powershell
@'
SELECT e.created_at, e.event_type, e.success, e.ip_address, left(e.user_agent, 60) AS user_agent
  FROM security_events e
  JOIN users u ON u.id = e.actor_user_id OR u.id = e.target_user_id
 WHERE lower(u.username) = 'admin'
   AND e.event_type IN ('LOGIN_SUCCESS', 'LOGIN_FAILED', 'ACCOUNT_LOCKED')
   AND e.created_at >= TIMESTAMPTZ '<DATA_ABERTURA_TUNEL>'
 ORDER BY e.created_at;
SELECT date_trunc('day', e.created_at) AS dia, count(*) AS logins_ok, count(DISTINCT e.user_agent) AS agentes
  FROM security_events e JOIN users u ON u.id = e.actor_user_id
 WHERE lower(u.username) = 'admin' AND e.event_type = 'LOGIN_SUCCESS'
 GROUP BY 1 ORDER BY 1;
'@ | Set-Content C:\ControleProducao\leitura_admin.sql -Encoding ascii
docker cp C:\ControleProducao\leitura_admin.sql controle_producao_postgres:/tmp/leitura_admin.sql
docker exec controle_producao_postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -f /tmp/leitura_admin.sql'
docker exec controle_producao_postgres rm -f /tmp/leitura_admin.sql
```
Procure `LOGIN_SUCCESS` do admin em horários ou `user_agent` que não sejam os seus. O login normal do Desktop e de outras ferramentas também aparece. Fatos que explicam o risco: a API 0.11.0 (a que roda hoje) **redefine a senha do `admin` para a senha pública do código a cada reinício** e a escreve no log; o repositório é público e a API está publicada na internet pelo túnel.

### B2. O que fazer com o resultado

- Decidir **antes** da janela quem será o superusuário alternativo com senha própria (pergunta Q3 da auditoria 05). Sem outro superusuário, ao trocar a senha do `admin` você pode se trancar para fora.
- Logo depois do deploy: trocar a senha do `admin` (ou desativá-lo) pelo Desktop. A 0.12.0 **não** redefine mais a senha no startup, mas também **não** troca a que já existe: a senha pública continua valendo até você trocar.
- `SECRET_KEY`: trocar invalida os tokens de acesso (JWT) mas **não** as sessões de refresh no banco. Se houver suspeita real, trocar a `SECRET_KEY` (exige recriar a API) **e** revogar as sessões do admin (SQL de escrita, opcional, só com sua decisão):
  ```sql
  UPDATE auth_sessions SET revoked_at = now(), revoke_reason = 'incidente_admin'
   WHERE revoked_at IS NULL AND user_id IN (SELECT id FROM users WHERE lower(username) = 'admin');
  ```
- `password_must_change` não é imposto pelo servidor nem pelo Desktop (pendência): a troca é manual e voluntária.

## C. Antes da janela: o que fazer neste PC e no SERVIDOR

- [ ] **Escolher a janela** (fim de tarde ou sábado; evitar 01:30 a 03:00, backup das 02:00) e avisar a equipe.
- [ ] **Cópia dos anexos / `/app/data`**: se A5 mostrou arquivos, o runbook faz a cópia (`docker cp` do container parado, Passo 4) e a devolução (Passo 9). Decisão sua: autorizar esses dois passos. Nunca recriar o container antes da cópia.
- [ ] **Backup pré-deploy com teste de restauração** em banco descartável (Passo 3 do runbook) e **uma cópia fora do SERVIDOR**. Sem cópia externa o backup está só no disco que será mexido. Registrar a decisão se for seguir só com o backup local.
- [ ] **Ensaio da migração 0038 -> 0047** com um dump real, na dev (8001), em banco temporário, medindo o tempo (a auditoria 03 só testou banco descartável vazio).
- [ ] **Ensaiar** na dev o `sync_release_to_server.py` dentro do container (comando em `RUNBOOK_DEPLOY_DESKTOP.md` D2, ainda não ensaiado) e o smoke de dentro do container.
- [ ] **Usuário de smoke**: criar um usuário dedicado, só leitura (Logística, Inspeção, Almoxarifado), para o `scripts\smoke_deploy.py` (nunca usar o `admin`).
- [ ] **Instalar as dependências de toast** no Python 3.11 de build e **gerar o Desktop 2.10.0** (`RUNBOOK_DEPLOY_DESKTOP.md`, seção 3) e testar em máquina limpa.
- [ ] **Canal PILOT** (ver D abaixo): decidir e, se for usar, **atribuir as máquinas piloto antes da janela**.
- [ ] **Conferir a frota**: quais PCs estão em 2.9.0 ou maior e quais em 2.8.x ou menor (estas reinstalam pelo Setup 2.10.0; não atualizam pelo feed).
- [ ] **PDF de LOG/carga grande**: conferir no dev (auditoria 02, T3).
- [ ] Rodar a suíte inteira verde (`python -m pytest tests api/tests -q --timeout=300`) e os checks de migração (`scripts/check_migration_checksums.py`, `scripts/check_migration_safety.py`).

## D. Decisões que são suas

### D1. MINIMUM_DESKTOP_VERSION = 2.10.0

O código novo trava no preflight todo Desktop abaixo de 2.10.0 (estado `UPDATE_REQUIRED`) assim que a API 0.12.0 sobe, porque o Almoxarifado do 2.9.0 fica degradado com a visibilidade nova da migração 0044. Opções:

1. **Manter 2.10.0** (o que está nos commits). Toda a frota precisa atualizar; só quem enxerga a release 2.10.0 autorizada vê "Atualizar agora". Máquinas em 2.8.x ou menor precisam do Setup. Exige a release publicada logo após a API.
2. **Baixar o mínimo** (por exemplo para 2.9.0) e deixar o Almoxarifado degradado nas máquinas 2.9.0 até a atualização. Isso é mudança de código (nova versão da API, por exemplo 0.12.1) e re-build da imagem; não é um ajuste de `.env`. Se for a sua escolha, avise **antes** de construir a imagem.

`CLIENT_VERSION_ENFORCEMENT_ENABLED` continua desligado: o mínimo vale só como preflight do cliente.

### D2. Piloto ou direto

Com o mínimo em 2.10.0, durante o piloto a frota fora do PILOT fica travada (sem caminho de atualização) até a promoção. Escolha: **direto** (`--authorize`, todos veem na hora) ou **piloto** (1 a 3 máquinas, depois promover). Confira a janela de observação dos gates antes de escolher o piloto (`RUNBOOK_DEPLOY_DESKTOP.md`, seção 5). Autorizar o canal PILOT e a atribuição das instalações é [AUT].

### D3. Quem recebe as permissões novas

A migração concede `inspection.*` e `logistics.*` só ao perfil `admin`; a sincronização do catálogo cria as permissões mas **não** as concede a outros perfis. Diga quais perfis precisam de `inspection.view`, `inspection.edit`, `logistics.view`, `logistics.edit` no primeiro dia (pergunta P7 da auditoria 03).

### D4. Corrigir para frente ou voltar o backup

Se algo der errado depois que o pessoal lançou dados de Inspeção/Logística: **corrigir para frente** (mantém os dados) ou **restaurar o dump** (perde tudo desde o deploy)? O runbook usa o restore do dump como rollback de referência; a auditoria 03 recomenda corrigir para frente quando já entrou dado novo.

### D5. Migração 0043 e 0044

- 0043 cancela NF `REGISTRADA` sem linha ativa (irreversível na prática, o downgrade não devolve o status). Você disse que é o comportamento desejado; o número exato vem de A1 (`nf_que_a_0043_vai_cancelar`).
- 0044 grava a baixa de estoque das propostas já entregues com a data do deploy, não a data real.

### D6. Repositório público ou privado

O repositório é **PÚBLICO**. O histórico contém: valores de dev "queimados" (segredos de dev que já estiveram em `api/.env.example` e `scripts/load_dev_env.bat`; os commits novos os trocam por placeholders, mas o histórico continua com eles), fixtures antigas com dados de cliente (nome, CNPJ, inscrição estadual, contatos; os commits novos anonimizam o estado atual, **não o histórico**) e docs com hostname, ID do túnel e IPs internos. Tornar privado resolve a exposição de uma vez; mantê-lo público exige reescrever o histórico. **Antes de qualquer `push`**, decida isso: publicar os 114 commits num repositório público replica esses dados e as correções que descrevem a falha de segurança do admin. Se for ficar público, a recomendação é privar temporariamente até concluir o deploy e a troca de senha.

### D7. Local do Setup completo

Onde fica o `ControleProducaoSetup-2.10.0.exe` para máquinas novas (pasta de rede, pen drive)? Hoje não há local oficial.

### D8. Máquina antiga e túnel antigo

A janela de rollback da máquina antiga venceu em 2026-11-11 e o banco de lá é de 2026-11-04. Decida desativar de vez a tarefa `CloudflaredTunnel` e a limpeza de lá. Reativar o túnel antigo com o `cloudflared` do SERVIDOR ligado cria dois conectores no mesmo túnel.

### D9. Rate limit do túnel

Atrás do `cloudflared`, o IP visto pela API é o do proxy: o limite de login por IP (20 falhas em 300 s) é compartilhado por todos. Definir uma regra de rate limit no WAF/Cloudflare para `/api/v1/auth/*` e decidir se sobe o limite (`LOGIN_IP_MAX_FAILURES`) ou o desliga (`0`) no `.env`.

## E. Git e GitHub (tudo [AUT])

Nenhum `push` foi feito. Só você autoriza:

- [ ] **Decidir D6 antes de qualquer push.**
- [ ] `git push origin logistica-melhorias` (a branch).
- [ ] Merge em `main`: a `main` é ancestral da branch, então é **fast-forward** com 114 commits (`git rev-list --count main..HEAD`). Por exemplo, `git checkout main` e `git merge --ff-only logistica-melhorias`, depois `git push origin main`. Pelo GitHub: PR e "Rebase and merge"/fast-forward.
- [ ] Tags: `git tag` (locais, a criar pelo maestro: `api-v0.12.0` e `v2.10.0`), depois `git push origin api-v0.12.0 v2.10.0`. **Push de tag é [AUT]**. As tags existentes não mudam. Já existem `api-v0.11.0` (commit `1c18459`, a imagem hoje em produção) e `v2.9.0-padrao-janelas`; **não existe** tag `v2.9.0` pura (o `release/latest.json` do 2.9.0 cita `v2.9.0`, que não existe no git).
- [ ] **Proteção do ambiente `production` no GitHub**: fora do escopo desta rodada; só lembrete. Hoje o ambiente existe sem regra de proteção e não há runner registrado. Exigir revisor no ambiente e aprovação para workflows de fork antes de registrar qualquer runner (auditoria 05, item 8). Este deploy **não usa** o pipeline `release-server.yml`.

## F. Perguntas abertas

1. A produção está mesmo em `20261014_0038`? (A1.)
2. O Almox+ recebia webhook/conciliação da produção antes da virada? Se sim, como o segredo chegava ao container, já que o compose antigo não o repassava? (A4.)
3. Os anexos de foto e vídeo estão em uso? (A5.)
4. Quem é o superusuário alternativo ao `admin`? (B2.)
5. Quantas máquinas estão em 2.8.x ou menor? A frota inteira está em 2.9.0+?
6. Existe canal piloto de fato (quais máquinas)? Piloto ou direto? (D2.)
7. Quais perfis recebem as permissões de Inspeção e Logística? (D3.)
8. Qual PC/pasta recebe a cópia externa do backup, e quem digita a credencial (`cred_backup.xml`)?
9. A tarefa agendada de backup passa `-Destino`? (A7.)
10. O repositório pode ficar privado? (D6.)
11. Mínimo de Desktop: manter 2.10.0 ou baixar? (D1.)
12. Usuários comuns dos PCs têm administrador local para o UAC do atualizador (aparece uma vez no `--stage`)?
13. Os 47 commits de `app/` desde o 2.9.0 incluem alguma tela que dependa de endpoint ainda não mesclado na API? (auditoria 07, pergunta 10.)
14. `CLIENT_VERSION_ENFORCEMENT_ENABLED` está ligado hoje no container? (A4 mostra só o nome; para o valor, pergunte e eu te digo o comando.)

## G. Fatos que não consegui confirmar no código

- Revisão real do banco de produção, versão real em execução e existência de anexos: só pelo SERVIDOR (A1, A2, A5).
- Nomes reais dos volumes Docker e local dos compose no SERVIDOR (A3, A9).
- Se a tela de perfis do Desktop permite conceder permissões (a API permite: `POST /api/v1/roles/{role_id}/permissions`).
- Se a política persistida (`PUT /api/v1/updates/policy`) altera o `minimum_desktop_version` que `/system/compatibility` devolve; leia o valor real depois do deploy.
- Os valores padrão dos gates do piloto (mínimo de clientes e `observation_minutes`).
- O comando `sync_release_to_server.py` dentro do container (`PYTHONPATH=/app`) e o smoke dentro do container não foram executados.
