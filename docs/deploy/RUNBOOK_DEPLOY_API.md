# Runbook: deploy da API 0.12.0 no SERVIDOR

Escrito em 2026-11-19, branch `logistica-melhorias`. Este documento só descreve; nada aqui foi executado. Fontes: `docs/auditoria-deploy/03_migracoes.md`, `05_seguranca.md`, `06_operacao_api.md`, `docs/plano-migracao-api-servidor.md` e o código dos commits desta rodada.

Marcação: **[AUT]** = exige autorização explícita do Henrique antes de rodar (qualquer coisa no SERVIDOR 192.168.2.128, na API oficial (porta 8000), em `api.ykora.com.br`, no GitHub, push). Sem [AUT] = acontece neste PC, só com arquivos locais.

Antes de começar, rode o `CHECKLIST_ANTES_DE_RODAR.md` inteiro. Sem ele fechado, este runbook não começa.

## 0. Resumo do que muda

| Item | Antes (produção) | Depois |
|---|---|---|
| API | 0.11.0, imagem `local/controle-producao-api:0.11.0` | 0.12.0, imagem `local/controle-producao-api:0.12.0` (tag nova; a 0.11.0 fica no SERVIDOR como imagem de rollback) |
| Banco | `20261014_0038` (a confirmar no SERVIDOR, em leitura) | `20261109_0047` (migrações 0039 a 0047) |
| Desktop exigido pelo preflight | 2.5.2 | **2.10.0** |
| Anexos | dentro da camada do container (perdem-se ao recriar) | volume `api_data` em `/app/data` |
| `/docs`, `/redoc`, `/openapi.json` | abertos | fechados (404) com `APP_ENV=production` |
| Login | só bloqueio por conta | + limite por IP (ver aviso do túnel, seção 8) |

Deploy é pelo **runbook manual** (docker save/load + docker compose). **Não usar** o pipeline `docker_control` / `.github/workflows/release-server.yml` (não serve ao SERVIDOR, achado B3 da auditoria 06).

### AVISO: MINIMUM_DESKTOP_VERSION = 2.10.0 bloqueia todo Desktop abaixo de 2.10.0

`api/app/core/config.py` define `MINIMUM_DESKTOP_VERSION = "2.10.0"`. No startup o Desktop consulta `GET /api/v1/system/compatibility`; se a versão dele for menor que o mínimo, o estado é `UPDATE_REQUIRED` e o app **não passa do diálogo de compatibilidade** (`app/main.py:174-211`). Motivo: o Almoxarifado do 2.9.0 fica degradado com a visibilidade nova da migração 0044.

Consequências práticas:

1. A partir do instante em que a API 0.12.0 sobe, **todo PC com Desktop 2.9.0 ou menor fica travado** até atualizar.
2. O diálogo oferece "Atualizar agora" **somente se** o servidor indicar uma release autorizada para o canal daquela instalação. Se a release 2.10.0 ainda não está AUTHORIZED para o canal da máquina, não há caminho de atualização pelo app.
3. Máquinas em 2.8.x ou menor **não atualizam pelo feed** (layout versionado): precisam reinstalar pelo `ControleProducaoSetup-2.10.0.exe`.
4. Ordem obrigatória: a API 0.12.0 sobe primeiro (a API recusa autorizar uma release cujo `minimum_server_version` seja maior que a versão em execução, `api/app/updates/service.py:222-227`), e a release 2.10.0 é sincronizada e autorizada logo em seguida. Planeje a janela para que o intervalo entre "API no ar" e "release 2.10.0 autorizada para todos" seja o menor possível, de preferência fora do expediente. Ver `RUNBOOK_DEPLOY_DESKTOP.md`, seção "Decisão: piloto ou direto".
5. `CLIENT_VERSION_ENFORCEMENT_ENABLED` continua `false`: o 426 do middleware não vale; o bloqueio é só o preflight do cliente. Uma chamada direta de um Desktop antigo a rotas de negócio não é barrada pelo servidor.

## 1. Janela sugerida

- Duração estimada da parada: **cerca de 15 a 25 minutos** (dump + migração + subida; a migração em banco quase vazio leva menos de 1 s e o banco de produção tem cerca de 103 MB, então espere segundos; o resto é backup, cópia de anexos e conferências). A medir no ensaio.
- Horário sugerido: fim de tarde depois do expediente, ou sábado de manhã. **Evitar 01:30 a 03:00** (o backup agendado roda às 02:00) e evitar quando o Desktop 2.10.0 não puder ser distribuído no mesmo dia.
- O Henrique precisa estar disponível durante toda a janela (decisões de rollback são dele).
- Avisar a equipe antes: "sistema fora do ar das X às Y; ao abrir, o programa vai pedir atualização".

## 2. Pré-requisitos

Neste PC (sem tocar produção):

1. Árvore limpa na branch de release, commits locais presentes. Conferir `git log --oneline -3` e `git status`.
2. Suíte verde, sem mascarar falha com pipe: `python -m pytest tests api/tests -q --timeout=300`.
3. `python scripts/check_migration_checksums.py` e `python scripts/check_migration_safety.py` (ambos precisam sair com código 0).
4. `python -m pytest api/tests/test_release_compose_policy.py -q`.
5. **Ensaio da migração** 0038 para 0047 em cópia do banco de produção (na dev, 8001, banco temporário a partir de um dump). A auditoria 03 testou em banco descartável vazio; o ensaio com dados reais ainda não foi feito.
6. Construir a imagem e exportar:
   ```powershell
   python scripts/build_release_image.py --registry local --tag 0.12.0
   docker save local/controle-producao-api:0.12.0 -o C:\Users\Industel\deploy\api-0.12.0.tar
   Get-FileHash C:\Users\Industel\deploy\api-0.12.0.tar -Algorithm SHA256
   ```
   Verificação: o script termina sem erro e a label `org.opencontainers.image.version` da imagem é `0.12.0`. Anotar o sha256 e o `docker image inspect local/controle-producao-api:0.12.0 --format '{{.Id}}'`.
7. Ter em mãos, na pasta de deploy deste PC: `docker-compose.prod.yml`, `docker-compose.servidor.yml` e `scripts\servidor\backup_db.ps1` desta branch.
8. Release do Desktop 2.10.0 já buildada e testada (ver `RUNBOOK_DEPLOY_DESKTOP.md`), para sincronizar logo depois da API.

No SERVIDOR (tudo [AUT], só leitura, listado em detalhe no checklist): revisão alembic atual, versão da imagem em execução, nomes dos volumes, nomes das variáveis do container, espaço em disco, último backup.

## 3. Passos da janela

Convenção: os comandos do SERVIDOR rodam em PowerShell com diretório `C:\ControleProducao`. Comandos longos vão num `.ps1` copiado por `scp` (nunca string com aspas aninhadas pelo `ssh`, regra do plano de migração). Estado do shell não persiste entre chamadas por SSH: repita a função abaixo em cada `.ps1`.

```powershell
Set-Location C:\ControleProducao
function dc { docker compose --env-file C:\ControleProducao\.env -f docker-compose.prod.yml -f docker-compose.servidor.yml @args }
```

Nunca imprimir o `.env`. Nunca rodar `docker compose up -d` sem citar serviços (o `cloudflared` e o `caddy` ficam fora por perfil, mas cite sempre `postgres api`).

### Passo 1. Levar imagem e arquivos ao SERVIDOR [AUT]

```powershell
# neste PC
scp C:\Users\Industel\deploy\api-0.12.0.tar <USUARIO>@192.168.2.128:C:/ControleProducao/
scp docker-compose.prod.yml docker-compose.servidor.yml scripts/servidor/backup_db.ps1 <USUARIO>@192.168.2.128:C:/ControleProducao/novo/
```
No SERVIDOR:
```powershell
Get-FileHash C:\ControleProducao\api-0.12.0.tar -Algorithm SHA256       # igual ao do PC
docker load -i C:\ControleProducao\api-0.12.0.tar
docker image inspect local/controle-producao-api:0.12.0 --format '{{.Id}}'   # igual ao do PC
docker image ls local/controle-producao-api                                   # 0.11.0 E 0.12.0 listadas
```
Verificação: sha256 e Id idênticos aos do PC; a `0.11.0` continua listada. **Se a 0.11.0 sumiu, pare**: não há imagem de rollback.

(Os compose novos ficam em `C:\ControleProducao\novo\` por enquanto; só substituem os atuais no Passo 7.)

### Passo 2. Pré-checagens no SERVIDOR [AUT, leitura]

```powershell
docker ps --format 'table {{.Names}}\t{{.Status}}'
Get-PSDrive C | Select-Object Used, Free
Get-Content C:\ControleProducao\backups\backup.log -Tail 15
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready
```
Verificação: `controle_producao_postgres` e `controle_producao_api` healthy, pelo menos 5 GB livres (imagem nova + dump + tar dos volumes; o repositório de updates sozinho tem cerca de 1,3 GB), backup da noite anterior sem ERRO, `ready` 200.

Rodar também as consultas de leitura do checklist (revisão `20261014_0038`, NFs que virarão CANCELADA, propostas entregues). **Anotar os números**; são a prova do Passo 9.

### Passo 3. Backup pré-deploy do banco [AUT]

O script agendado novo exige o volume `api_data`, que ainda não existe. Por isso o backup pré-deploy é manual e independe da versão do script:

```powershell
$ts = Get-Date -Format 'yyyyMMdd_HHmm'
$nome = "pre_0.12.0_$ts.dump"
docker exec controle_producao_postgres sh -c "pg_dump -U `$POSTGRES_USER -d `$POSTGRES_DB -Fc -f /tmp/$nome"
docker exec controle_producao_postgres sh -c "pg_restore --list /tmp/$nome | wc -l"     # bem acima de 10 linhas
docker exec controle_producao_postgres sh -c "sha256sum /tmp/$nome"
docker cp controle_producao_postgres:/tmp/$nome C:\ControleProducao\backups\$nome
(Get-FileHash C:\ControleProducao\backups\$nome -Algorithm SHA256).Hash.ToLower()         # igual ao sha256sum acima
docker exec controle_producao_postgres rm -f /tmp/$nome
Get-Item C:\ControleProducao\backups\$nome | Select-Object Name, Length                   # acima de 100 KB
```
O prefixo `pre_` fica fora da retenção do `backup_db.ps1` (que só apaga `cp_*`). **Guarde o nome do arquivo**: é o ponto de rollback. Dump nunca passa por redirecionamento do PowerShell (`>` corrompe binário).

Teste de restauração em banco descartável (recomendado; o teste da restauração do backup agendado ainda não tem registro, achado C2):

```powershell
docker cp C:\ControleProducao\backups\$nome controle_producao_postgres:/tmp/t.dump
docker exec controle_producao_postgres sh -c 'createdb -U $POSTGRES_USER teste_restore && pg_restore --no-owner -U $POSTGRES_USER -d teste_restore /tmp/t.dump && psql -U $POSTGRES_USER -d teste_restore -tAc ''select version_num from alembic_version'''
docker exec controle_producao_postgres sh -c 'dropdb -U $POSTGRES_USER teste_restore; rm -f /tmp/t.dump'
```
Verificação: imprime `20261014_0038` (ou a revisão real que o checklist confirmou).

Cópia do dump para fora do SERVIDOR (outro PC) antes de seguir. Sem cópia externa o backup está só no disco que será mexido. Se o Henrique decidir seguir só com o backup local (a cópia externa do backup agendado ainda está pendente), registre a decisão.

### Passo 4. Parar só a API e salvar o estado antigo [AUT]

```powershell
dc stop api
docker ps -a --format 'table {{.Names}}\t{{.Status}}'      # api Exited, postgres Up (healthy)
```
A partir daqui o sistema está fora do ar (o túnel responde erro). Anote o horário.

Salve os anexos e o estado que o container antigo guardava **dentro da camada** (sem volume; se o container for recriado antes disso, perdem-se). O container parado ainda aceita `docker cp`:

```powershell
New-Item -ItemType Directory -Force C:\ControleProducao\pre_deploy | Out-Null
docker cp controle_producao_api:/app/data C:\ControleProducao\pre_deploy\app_data_antigo
Get-ChildItem C:\ControleProducao\pre_deploy\app_data_antigo -Recurse -File | Measure-Object -Property Length -Sum
```
Verificação: a pasta existe. Se há anexos de verdade, a soma de bytes é maior que zero e existe `storage\`. Se o `docker cp` acusar que `/app/data` não existe, ou `app_data_antigo` ficou vazia, ou não há `storage`, ninguém anexou nada até hoje (o checklist já deveria ter dito isso). **Não recrie o container antes de ver este resultado.**

Segundo dump, final, com a API parada (garante zero escrita entre o Passo 3 e a migração; o Passo 3 pode ter sido feito com a API no ar). Repita o bloco do Passo 3 com `$nome = "pre_0.12.0_final_$ts.dump"` e use **este** como ponto de rollback.

### Passo 5. Ajustar o `.env` do SERVIDOR [AUT]

Só a chave `SERVER_VERSION`, sem imprimir o arquivo:

```powershell
(Get-Content C:\ControleProducao\.env) -replace '^SERVER_VERSION=.*','SERVER_VERSION=0.12.0' | Set-Content C:\ControleProducao\.env -Encoding ascii
(Get-Content C:\ControleProducao\.env | Where-Object { $_ -match '^SERVER_VERSION=' })
```
Verificação: imprime só `SERVER_VERSION=0.12.0`. (`Set-Content` num arquivo existente mantém a ACL restrita já configurada; confirme depois com `icacls C:\ControleProducao\.env`, só três contas.)

Chaves **novas** que o compose repassa e que devem ficar **vazias/desligadas neste deploy** (não precisam existir no `.env`; os defaults do compose valem): `ALMOX_INTEGRATION_SECRET`, `ALMOX_WEBHOOK_URL`, `REMANAGEMENT_BY_ROWS_ENABLED=false`, `CLIENT_VERSION_ENFORCEMENT_ENABLED=false`, `BOOTSTRAP_ADMIN_PASSWORD` (vazio), `PASSWORD_MIN_LENGTH` (default 10). Não definir `ALMOX_*` agora.

### Passo 6. Compose novo e validação [AUT]

```powershell
Copy-Item docker-compose.prod.yml docker-compose.prod.yml.bak_0.11.0
Copy-Item docker-compose.servidor.yml docker-compose.servidor.yml.bak_0.11.0
Copy-Item C:\ControleProducao\novo\docker-compose.prod.yml, C:\ControleProducao\novo\docker-compose.servidor.yml C:\ControleProducao\ -Force
dc config -q
```
Verificação: `dc config -q` não imprime nada e sai 0 (nenhuma variável obrigatória faltando). Nunca usar `dc config` sem `-q`: imprime segredos.

### Passo 7. Migração com a imagem nova [AUT]

Com o postgres no ar e a API parada:

```powershell
dc run --rm --no-deps api sh -c "cd /app/api && python -m alembic upgrade head"
docker exec controle_producao_postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc ''select version_num from alembic_version'''
```
A migração roda numa transação única: ou aplica 0039 a 0047, ou nada. Verificação: imprime `20261109_0047`. Este `run` cria o volume `api_data` (vazio, com o dono `apiuser` herdado da imagem).

**Migração 0043 (irreversível na prática):** NFs com status `REGISTRADA` cujas linhas estão todas canceladas viram `CANCELADA` (comportamento desejado pelo Henrique). O downgrade não devolve esse status e ainda aborta se o número da NF tiver sido reutilizado depois. A **migração 0044** grava a baixa de estoque de todas as propostas já `ALMOXARIFADO_ENTREGUE` com a data/hora do deploy (não a data real). O dump do Passo 4 é o seu desfazer. Se a migração falhar (a transação reverte tudo), vá direto aos critérios de rollback (seção 5).

### Passo 8. Subir a API [AUT]

```powershell
dc up -d postgres api
docker ps --format 'table {{.Names}}\t{{.Status}}'
```
Verificação, em até 2 minutos: `controle_producao_api` passa a `healthy` (HEALTHCHECK usa `/api/v1/health/ready`, que exige a revisão do banco igual à esperada). O postgres **não** deve ter sido recriado (`Status` com tempo de atividade antigo). Em seguida faça o Passo 9.

Conferir o volume de fato montado e os nomes reais:
```powershell
docker volume ls
docker inspect controle_producao_api --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{println}}{{end}}'
```
Verificação: aparecem `...api_data -> /app/data` e `...update_repository_data -> /var/lib/controle-producao/updates`. Os nomes assumidos são `controle_producao_industel_api_data` e `controle_producao_industel_update_repository_data`; **se `docker volume ls` mostrar nomes diferentes**, ajuste `-VolumeStorage` e `-VolumeUpdates` do `backup_db.ps1` (Passo 12).

### Passo 9. Colocar de volta os anexos antigos [AUT]

Com a API de pé (Passo 8), copie para dentro do volume (o `docker cp` grava como root; ajuste o dono em seguida):

```powershell
docker cp C:\ControleProducao\pre_deploy\app_data_antigo\. controle_producao_api:/app/data/
docker exec -u root controle_producao_api chown -R apiuser:apiuser /app/data
docker exec controle_producao_api ls -la /app/data /app/data/storage
```
Verificação: `storage` com os mesmos arquivos do `app_data_antigo`. Se o Passo 4 mostrou que não havia anexos, pule este passo.

Observação: o container 0.12.0 já vê `/app/data` como volume; os arquivos aparecem sem reiniciar. Reiniciar a API não é necessário.

### Passo 10. Conferir os dados migrados [AUT, leitura]

```powershell
@'
SELECT version_num AS revisao_alembic FROM alembic_version;
SELECT count(*) AS nf_canceladas_agora FROM fiscal_invoices WHERE status = 'CANCELADA';
SELECT count(*) AS baixas_gravadas FROM proposals WHERE warehouse_stock_deducted_at IS NOT NULL;
SELECT to_regclass('inspections') AS inspections, to_regclass('logistics_logs') AS logistics_logs;
SELECT code FROM permissions WHERE code LIKE 'inspection.%' OR code LIKE 'logistics.%' ORDER BY code;
SELECT r.code AS perfil, count(*) AS permissoes_novas FROM role_permissions rp
  JOIN roles r ON r.id = rp.role_id JOIN permissions p ON p.id = rp.permission_id
 WHERE p.code LIKE 'inspection.%' OR p.code LIKE 'logistics.%' GROUP BY r.code;
'@ | Set-Content C:\ControleProducao\leitura_pos.sql -Encoding ascii
docker cp C:\ControleProducao\leitura_pos.sql controle_producao_postgres:/tmp/leitura_pos.sql
docker exec controle_producao_postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -f /tmp/leitura_pos.sql'
docker exec controle_producao_postgres rm -f /tmp/leitura_pos.sql
```
Verificação: revisão `20261109_0047`; `nf_canceladas_agora` = `nf_canceladas_hoje` + `nf_que_a_0043_vai_cancelar` anotados no Passo 2; `baixas_gravadas` = `propostas_entregues_almox` do Passo 2 (a coluna é nova, então todas as baixas vêm da 0044); `inspections` e `logistics_logs` existem; 4 permissões `inspection.*`/`logistics.*` (view e edit de cada) concedidas só ao perfil `admin`.

### Passo 11. Smoke test [AUT]

De dentro do container (4 GET, sem login, só liveness e compatibilidade):
```powershell
docker exec controle_producao_api python -m api.app.health.smoke --base-url http://127.0.0.1:8000 --expected-server-version 0.12.0
```
Do PC de desenvolvimento, contra a URL pública (prova túnel + API + fechamento do `/docs`), com um usuário de teste dedicado, **só com permissão de leitura** (não use o `admin`):

```powershell
$env:SMOKE_USERNAME = '<USUARIO_DE_TESTE>'      # a senha é pedida no terminal, sem eco, se SMOKE_PASSWORD não estiver definida
python scripts/smoke_deploy.py --base-url https://api.ykora.com.br --expected-server-version 0.12.0 --expect-production-hardening
```
Sem usuário de teste, só as etapas públicas:
```powershell
python scripts/smoke_deploy.py --base-url https://api.ykora.com.br --expected-server-version 0.12.0 --expect-production-hardening --skip-auth
```
O script usa `SMOKE_USERNAME`/`SMOKE_PASSWORD` (ou pergunta), nunca aceita senha em argumento, sempre verifica TLS e sai com 0 só se todas as etapas passarem (2 = credencial ausente). Etapas: live, ready, compatibility, version, descoberta de update, 404 em `/docs`, `/redoc` e `/openapi.json`, e (sem `--skip-auth`) login + leituras de Logística, Inspeção e Almoxarifado.

Conferir também (curl/Invoke-RestMethod, leitura): `GET /api/v1/system/compatibility` deve mostrar `server_version` 0.12.0, revisão `20261109_0047` e `minimum_desktop_version` 2.10.0. (A resposta pode vir da política persistida, `PUT /api/v1/updates/policy`; confira o valor que de fato sai.)

Verificação final: `docker logs --tail 200 controle_producao_api` sem traceback; `docker stats --no-stream` sem estouro de memória (o SERVIDOR tinha só 2,2 GB livres de 15,4 GB).

### Passo 12. Atualizar o script de backup e rodar uma vez [AUT]

```powershell
Copy-Item C:\ControleProducao\novo\backup_db.ps1 C:\ControleProducao\backup_db.ps1 -Force
powershell -NoProfile -ExecutionPolicy Bypass -File C:\ControleProducao\backup_db.ps1
Get-Content C:\ControleProducao\backups\backup.log -Tail 8
Get-ChildItem C:\ControleProducao\backups | Sort-Object LastWriteTime -Descending | Select-Object -First 8 Name, Length
```
Se o nome real do volume diferir do assumido, acrescente `-VolumeStorage <nome> -VolumeUpdates <nome>`. Verificação: o log mostra OK para o dump (com número de itens do `pg_restore --list`), OK para `cp_storage_*.tar` e `cp_updates_*.tar`, e o aviso "sem copia externa" se `-DestinoExterno` não foi passado (a tarefa agendada atual usa `-Destino`, que é alias do mesmo parâmetro; ver se a tarefa passa o destino). Exit 0 sem destino externo é esperado, com aviso. A tarefa `ControleProducaoBackup` das 02:00 continua chamando o mesmo caminho do script, então passa a usar o novo.

### Passo 13. Fechar [AUT]

- Registrar horários (parada, migração, saúde, smoke) e o nome do dump `pre_0.12.0_final_*` num fase-report em `docs/architecture/`.
- Avisar a equipe que a API voltou e que cada PC vai pedir atualização.
- Seguir para `RUNBOOK_DEPLOY_DESKTOP.md` (seção "Publicar") **sem demora**: com a API no ar e a release ainda não autorizada, todo Desktop abaixo de 2.10.0 está travado.

## 4. Critério de sucesso

Todos verdadeiros:

- `alembic_version` = `20261109_0047`.
- `controle_producao_api` healthy; `ready` 200; `system/compatibility` com `server_version` 0.12.0.
- Smoke OK (público e, se houver usuário de teste, autenticado), incluindo 404 em `/docs`.
- NFs CANCELADAS novas e baixas de estoque conferem com os números anotados no Passo 2.
- Anexos antigos presentes em `/app/data/storage`.
- Backup novo gerado com dump, `cp_storage_*.tar` e `cp_updates_*.tar` validados.
- Um login real de Desktop 2.10.0 (a máquina piloto) abre uma proposta.

## 5. Critério de rollback

Decisão do Henrique, não automática. Voltar se **qualquer** um:

- A migração falhou, ou a revisão final é diferente de `20261109_0047`.
- `ready` não fica 200 em 2 minutos depois da subida, ou o container não chega a healthy.
- Smoke falha nas etapas de saúde/compatibilidade, ou login/listagem de propostas dá 5xx.
- Contagens do Passo 10 diferentes do esperado e sem explicação.
- Erro de dados percebido logo depois (propostas sumidas, NFs erradas além das previstas na 0043).

### Quando NÃO vale só trocar a imagem

- **Houve migração (Passo 7 concluído): trocar a imagem para 0.11.0 não funciona.** A imagem antiga exige revisão do banco **igual** a `20261014_0038` (`/health/ready`), então com o banco em `...0047` ela fica unhealthy e o Desktop recebe 503. O avaliador de rollback do código (`evaluate_rollback_schema_compatibility`, commit d3e8bc0) agora também exige revisão igual.
- Rollback só de aplicação (trocar `SERVER_VERSION` de volta e recriar) só vale **se a migração ainda não foi aplicada** (falha antes do Passo 7).

### Rollback de aplicação sem migração (falha antes do Passo 7)

```powershell
dc stop api
(Get-Content C:\ControleProducao\.env) -replace '^SERVER_VERSION=.*','SERVER_VERSION=0.11.0' | Set-Content C:\ControleProducao\.env -Encoding ascii
dc up -d postgres api
```
O compose novo também sobe a imagem 0.11.0 (as variáveis a mais são ignoradas; o volume `api_data` fica montado). Não ensaiado. Se preferir, restaure os `.bak_0.11.0` dos compose.

### Rollback com migração: restaurar o dump pré-deploy [AUT]

Perde tudo que entrou depois do dump (ver aviso). Com a API parada:

```powershell
dc stop api
docker cp C:\ControleProducao\backups\<DUMP_PRE_DEPLOY_FINAL> controle_producao_postgres:/tmp/rollback.dump
docker exec controle_producao_postgres sh -c 'dropdb -U $POSTGRES_USER --force $POSTGRES_DB && createdb -U $POSTGRES_USER $POSTGRES_DB && pg_restore --no-owner -U $POSTGRES_USER -d $POSTGRES_DB /tmp/rollback.dump'
docker exec controle_producao_postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc ''select version_num from alembic_version'''
docker exec controle_producao_postgres rm -f /tmp/rollback.dump
(Get-Content C:\ControleProducao\.env) -replace '^SERVER_VERSION=.*','SERVER_VERSION=0.11.0' | Set-Content C:\ControleProducao\.env -Encoding ascii
dc up -d postgres api
```
Usa-se `dropdb`/`createdb` (e não `pg_restore --clean --if-exists` sobre o banco atual) porque as tabelas de Inspeção e Logística não existem no dump: um `--clean` as deixaria no banco e o próximo `upgrade` falharia com "já existe". Verificação: `alembic_version` volta a `20261014_0038`; API 0.11.0 healthy; smoke com `--expected-server-version 0.11.0` (sem `--expect-production-hardening`, que é do 0.12.0).

Efeitos colaterais do rollback:
- Perde-se o que entrou depois do dump (nada, se ninguém usou).
- A 0.11.0 **volta a redefinir a senha do `admin` para a senha pública antiga a cada startup** (comportamento antigo do bootstrap). Se o rollback ficar mais que algumas horas, desative o túnel ou trate o `admin` como comprometido.
- Todos os Desktops 2.10.0 já atualizados passam a falar com uma API 0.11.0: o Desktop 2.10.0 exige `MINIMUM_API_VERSION` 0.12.0 e fica bloqueado (`SERVER_UPDATE_REQUIRED`). Rollback da API implica reverter as máquinas ou fazer nova API 0.12.x.

### Rollback alternativo, só se ninguém lançou dado novo (minutos)

A auditoria 03 testou, em banco descartável, `alembic downgrade 20261014_0038` **com a imagem nova**, e só depois subir a 0.11.0. Esse caminho: apaga as tabelas de Inspeção/Logística e as permissões `inspection.*`/`logistics.*`; **não** devolve o status das NFs da 0043 (e aborta se um número de NF foi reutilizado); a baixa da 0044 desaparece com a coluna. Só use com decisão explícita do Henrique; o restore do dump continua sendo o caminho de referência. Se já entrou dado novo (Inspeção/Logística, cancelamento de NF), a auditoria recomenda **corrigir para frente** (imagem nova corrigida) em vez de voltar.

## 6. Pós-deploy

### 6.1 Trocar a senha do admin (imediato) [AUT]

A senha pública antiga do `admin` **continua valendo em produção**: o `BOOTSTRAP_ADMIN_PASSWORD` (commit 3472d0c) só cria o admin se ele não existir, e nada o muda automaticamente. O repositório é público e a API está na internet pelo túnel. **Troque a senha ou desative o `admin` agora**, por um superusuário com senha própria (o Desktop, tela de usuários). Depois:

1. Rode a consulta de `LOGIN_SUCCESS` do admin do checklist, desde a data em que o túnel foi aberto. IPs aparecerão como o do proxy/Cloudflare; use `user_agent` e horários.
2. Decida sobre `SECRET_KEY`: trocar invalida os tokens de acesso (JWT) já emitidos, mas **não** revoga as sessões de refresh no banco (o refresh token é opaco, guardado como hash; confirmado em `tokens.py`). Para derrubar sessões é preciso também revogar `auth_sessions` (SQL no checklist, escrita, [AUT]). Trocar `SECRET_KEY` exige recriar a API.
3. `password_must_change` não é imposto pelo servidor nem pelo Desktop (pendência conhecida): não confie nele para forçar a troca.

### 6.2 Conceder permissões de Inspeção e Logística [AUT]

A migração 0039/0040 concede `inspection.*` e `logistics.*` só ao perfil `admin`. A sincronização do catálogo no startup (`sync_official_permissions`, `api/app/modules/auth/bootstrap.py`) **cria** as permissões que faltam em `permissions`, mas **não** as concede a nenhum perfil (só insere linhas do catálogo; confirmado no código). Superusuários passam sem permissão (`is_superuser`); os demais perfis não veem as telas até receberem:

- `inspection.view`, `inspection.edit`
- `logistics.view`, `logistics.edit`

Conceda aos perfis certos (decisão do Henrique, pergunta P7 da auditoria 03) por usuário com `roles.manage_permissions`: pela API, `POST /api/v1/roles/{role_id}/permissions?permission_id=<ID>` (IDs em `GET /api/v1/permissions`); na UI do Desktop só se existir tela de perfis (não confirmei no código do Desktop). O usuário de smoke precisa de `*.view` (e do view de Almoxarifado) para as leituras autenticadas.

### 6.3 Ligar o Almox+ (só depois do smoke) [AUT]

Almox+ e o motor de remanejamento por linhas ficam **desligados** neste deploy. Ligar o Almox+ é um passo separado:

1. Definir no `.env` do SERVIDOR `ALMOX_INTEGRATION_SECRET` (mínimo 32 caracteres, **o mesmo valor** do lado do Almox+; combinar com o Henrique, nunca em chat) e `ALMOX_WEBHOOK_URL` (http/https do Almox+). Só os dois nomes importam aqui; os valores não vão em documento.
2. `dc up -d api` (recria a API; segundos de indisponibilidade).
3. Smoke de novo (Passo 11).
4. Validar a conciliação primeiro (leitura): `GET /api/v1/integrations/almox/proposals?estado=LIBERADA` com `X-Timestamp` e `X-Signature` assinados com o segredo sobre a query crua; sem segredo responde 503. Só depois liberar uma proposta e conferir o webhook. Pré-requisitos: saída do SERVIDOR para o domínio do Almox+ liberada e relógio do Windows certo (a assinatura vale ±300 s).
5. Se algo falhar, esvazie as duas variáveis e `dc up -d api`.

Remanejamento por linhas (`REMANAGEMENT_BY_ROWS_ENABLED`): **continua `false`**, só dev até decisão.

### 6.4 Outros

- Conferir PDF de LOG/carga grande no dev (auditoria 02, T3) antes de o pessoal imprimir em produção.
- Acompanhar `docker logs` e `backup.log` nas primeiras 24 h; confirmar o backup das 02:00 com o schema novo (dump, `cp_storage_*.tar`, `cp_updates_*.tar`).
- Teste de restauração do backup agendado num banco novo ainda **pendente**: use o bloco `createdb`/`pg_restore`/`dropdb` do Passo 3 sobre o `cp_*.dump` mais recente.
- Cópia externa do backup continua pendente (credencial recusada); sem `-DestinoExterno` o script avisa "SEM COPIA EXTERNA".
- Tags locais ao final (feitas pelo maestro): `api-v0.12.0` e `v2.10.0`. **Push das tags é [AUT]**.

## 7. Limpeza

Depois de alguns dias estável, **sem apagar nada antes de confirmação do Henrique [AUT]**: `C:\ControleProducao\pre_deploy\`, o `api-0.12.0.tar`, `docker-compose.*.bak_0.11.0` e `novo\`. A imagem `0.11.0` fica enquanto houver chance de rollback. O dump `pre_0.12.0_final_*` fica guardado fora do SERVIDOR.

## 8. Avisos de comportamento novo

- **Login por IP.** `LOGIN_IP_MAX_FAILURES=20` por `LOGIN_IP_WINDOW_SECONDS=300` (0 desliga) devolve 429 com `Retry-After`. Atrás do túnel `cloudflared` o IP visto é o do proxy, então **todos os usuários dividem um único balde**: um atacante pode travar o login de todos por 5 minutos. Mitigar com regra de rate limit no WAF/Cloudflare para `/api/v1/auth/*` e, se necessário, subir o limite ou colocar 0 por variável de ambiente no `.env` (`dc up -d api` para aplicar).
- `/system/compatibility` só grava heartbeat de instalação com Bearer; sem token só devolve a política.
- `PASSWORD_MIN_LENGTH` 10 vale só para senhas novas; usuários com senha curta continuam entrando.
- Backup de volumes (`cp_storage_*.tar`, `cp_updates_*.tar`) aumenta o uso de disco; a retenção é de 14 dias.

## 9. Limites deste runbook (o que não foi ensaiado)

- Nenhum passo foi executado. O ensaio da migração com dump real de produção não foi feito.
- Local dos compose no SERVIDOR assumido como `C:\ControleProducao\` (o `./cloudflared` relativo do `docker-compose.servidor.yml` indica isso). Confirmar.
- Nomes dos volumes assumidos a partir do `name: controle_producao_industel` do compose; confirmar com `docker volume ls`.
- O smoke de dentro do container usa o módulo `api.app.health.smoke` e `httpx`, presentes na imagem segundo a auditoria 06 (D3); não ensaiado.
- A cópia de anexos (Passos 4 e 9) assume o caminho `/app/data/storage` (default relativo `data/storage` com `WORKDIR /app`). Confirmar no container atual antes (checklist).
