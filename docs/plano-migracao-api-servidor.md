# Plano: migração da API de produção para o SERVIDOR

**Objetivo:** API, banco e túnel de produção passam deste PC para o Docker do SERVIDOR, sem perda de dados e sem alterar nenhum Desktop.

**Arquitetura (2-3 frases):** o SERVIDOR (`192.168.2.128`, Windows 10 + Docker Desktop, engine Linux) roda o mesmo `docker-compose.prod.yml` de hoje (só `postgres` e `api`, sem Caddy), com a API publicada apenas em `127.0.0.1:8000`. O `cloudflared` passa a ser um container no mesmo compose, com a credencial do túnel atual, e entrega `api.ykora.com.br` direto para `http://api:8000`. O banco (103 MB) vai por `pg_dump -Fc` e `pg_restore`.

**Tecnologias:** Docker Compose, PostgreSQL 16, cloudflared, OpenSSH (chave `~/.ssh/id_servidor`), PowerShell no SERVIDOR, Agendador de Tarefas do Windows.

**Especificação:** [spec-migracao-api-servidor.md](spec-migracao-api-servidor.md) (aprovada em 2026-11-04). Decisões D1 a D13 valem aqui.

## Restrições globais

- Nada é apagado neste PC (D11). Só `docker stop`.
- Nenhum segredo é impresso, commitado ou colado em chat. `.env` e credencial do túnel só vão por `scp`, com permissão restrita.
- **Nunca dois `cloudflared` do túnel `controle-producao` ligados ao mesmo tempo**, exceto os segundos da troca.
- **Arquivos binários (dump, imagem) nunca passam por redirecionamento do PowerShell (`>`, `|`)**, que corrompe bytes. Sempre gerar o arquivo dentro do container, `docker cp`, `scp` e conferir `sha256`.
- Comandos remotos longos viram um arquivo `.ps1` copiado por `scp`, em vez de string com aspas dentro do `ssh` (o shell remoto quebrou as aspas antes).
- Cada tarefa tem critério de pronto. Passo que apaga, para a produção ou altera DNS/túnel pede confirmação do Henrique antes.
- Caminho de trabalho no SERVIDOR: `C:\ControleProducao\`.

## Mapa de arquivos

| Arquivo | Onde | Papel |
|---|---|---|
| `docker-compose.servidor.yml` | repositório (novo) | só o serviço `cloudflared`, usado como 2º `-f` junto do `docker-compose.prod.yml` |
| `scripts/servidor/backup_db.ps1` | repositório (novo) | dump diário, retenção de 14 dias, cópia para a pasta compartilhada |
| `C:\ControleProducao\.env` | SERVIDOR | cópia do `.env.production` ajustada (nunca commitada) |
| `C:\ControleProducao\cloudflared\` | SERVIDOR | `config.yml` e `<tunnel-id>.json` (credencial) |
| `C:\ControleProducao\backups\` | SERVIDOR | dumps locais |

**Decisão do Claude:** reutilizar o `docker-compose.prod.yml` sem copiá-lo, para não divergir do compose já testado por `api/tests/test_release_compose_policy.py`. As variáveis `CADDY_*` são obrigatórias nesse arquivo mesmo sem subir o Caddy, então o `.env` do SERVIDOR leva valores fictícios e o Caddy nunca é iniciado (os comandos sempre citam `postgres api` por nome).

---

## Tarefa 0: Preparar o SERVIDOR (D12)

**Consome:** acesso SSH funcionando. **Produz:** SERVIDOR que se recupera sozinho depois de reiniciar.

Passos (comandos entregues em `.ps1`, executados por SSH, exceto os marcados "no SERVIDOR", que o Henrique faz por Área de Trabalho Remota):

- [ ] Criar `C:\ControleProducao\{cloudflared,backups}`.
- [ ] Energia: `powercfg /change standby-timeout-ac 0`, `powercfg /change monitor-timeout-ac 0`, `powercfg -h off`.
- [ ] Docker Desktop: ligar "Start Docker Desktop when you sign in". Conferir também "Resource Saver" desligado.
- [ ] **No SERVIDOR (Henrique):** login automático com Sysinternals **Autologon** (guarda a senha criptografada; o Henrique digita a senha lá, nunca no chat). Não usar `DefaultPassword` em texto puro no registro.
- [ ] Windows Update: horas ativas cobrindo o expediente.
- [ ] Conferir RAM livre antes e depois de subir a stack (alerta se < 1 GB livre).

**Pronto quando:** `powercfg /query` mostra suspensão 0, o Autologon está configurado, e o Docker Desktop está marcado para iniciar com o login. A prova real é a Tarefa 7.

## Tarefa 1: Compose do túnel no repositório

**Arquivo:** `docker-compose.servidor.yml` (novo). **Produz:** serviço `cloudflared`.

```yaml
# Servico do tunel Cloudflare para o SERVIDOR. Usado junto do docker-compose.prod.yml:
#   docker compose -f docker-compose.prod.yml -f docker-compose.servidor.yml ...
services:
  cloudflared:
    image: cloudflare/cloudflared:2026.9.3
    container_name: controle_producao_cloudflared
    restart: unless-stopped
    profiles: ["tunel"]
    depends_on:
      api:
        condition: service_healthy
    command: tunnel --no-autoupdate --config /etc/cloudflared/config.yml run
    volumes:
      - ./cloudflared:/etc/cloudflared:ro
```

- [ ] Escrever o arquivo.
- [ ] Validar: `docker compose -f docker-compose.prod.yml -f docker-compose.servidor.yml config -q` (com `.env` de teste) sem erro.
- [ ] Rodar `python -m pytest api/tests/test_release_compose_policy.py -q` e confirmar que continua verde (o arquivo novo não pode ser pego por regra de `:latest` ou de build).
- [ ] Commit em português, pela skill `commit-by-subsystem` (área: infra de release).

**Decisões do Claude:** versão do `cloudflared` fixa em `2026.9.3` (a mesma do túnel do Almox neste PC, já testada); `profiles: ["tunel"]` evita que ele suba junto com a API durante o ensaio.

**Pronto quando:** o `config -q` passa e o teste de política do compose está verde.

## Tarefa 2: Transferir a imagem

**Consome:** imagem `local/controle-producao-api:0.11.0` (neste PC). **Produz:** a mesma imagem no SERVIDOR.

- [ ] Neste PC: `docker save local/controle-producao-api:0.11.0 -o <scratchpad>\api-0.11.0.tar` e `sha256`.
- [ ] `scp` para `C:\ControleProducao\api-0.11.0.tar` no SERVIDOR; conferir `sha256` igual (`Get-FileHash`).
- [ ] No SERVIDOR: `docker load -i C:\ControleProducao\api-0.11.0.tar`.
- [ ] Comparar `docker image inspect --format '{{.Id}}'` nos dois lados.
- [ ] Baixar também `postgres:16` e `cloudflare/cloudflared:2026.9.3` no SERVIDOR (`docker pull`). O SERVIDOR tem internet, e a Tarefa 3 confirma.

**Pronto quando:** o ID da imagem é idêntico nos dois lados e `docker pull` das duas imagens públicas termina sem erro.

## Tarefa 3: `.env` do SERVIDOR

**Consome:** `.env.production` deste PC. **Produz:** `C:\ControleProducao\.env`.

- [ ] `scp` do `.env.production` para `C:\ControleProducao\.env`, sem exibir conteúdo.
- [ ] Ajustar só estas chaves (por script que imprime apenas os **nomes** alterados): `API_BIND_HOST=127.0.0.1`, `CADDY_HOSTNAME=nao-usado`, `CADDY_TLS_CERT_PATH=./nao-usado.crt`, `CADDY_TLS_KEY_PATH=./nao-usado.key`.
- [ ] Manter **idênticos**: `POSTGRES_*`, `SECRET_KEY`, `PROVISIONING_SECRET`, `NOMUS_ENCRYPTION_KEY`, `OPERATIONAL_*`, `SERVER_VERSION=0.11.0`, `IMAGE_REGISTRY=local`.
- [ ] Permissão: remover herança e dar acesso só a `industel`, `SYSTEM` e Administradores, usando **SIDs** (`*S-1-5-18`, `*S-1-5-32-544`) porque o Windows está em português (o `icacls ... Administrators` falhou antes).
- [ ] Conferir chaves faltando: o `docker compose ... config -q` roda sem erro de variável obrigatória.

**Pronto quando:** o `config -q` passa no SERVIDOR e só três contas têm acesso ao `.env`.

## Tarefa 4: Credencial e configuração do túnel (sem ligar)

**Consome:** `C:\Users\Industel\.cloudflared\f4b0db5b-d3ff-4d5e-a00a-cb126b94bfcd.json` e `config.yml` (neste PC). **Produz:** `C:\ControleProducao\cloudflared\`.

- [ ] `scp` da credencial `f4b0db5b-....json` para `C:\ControleProducao\cloudflared\` (sem exibir conteúdo) e permissão restrita como na Tarefa 3.
- [ ] Criar lá o `config.yml`:
  ```yaml
  tunnel: f4b0db5b-d3ff-4d5e-a00a-cb126b94bfcd
  credentials-file: /etc/cloudflared/f4b0db5b-d3ff-4d5e-a00a-cb126b94bfcd.json
  ingress:
    - hostname: api.ykora.com.br
      service: http://api:8000
    - service: http_status:404
  ```
- [ ] **Não iniciar o container.** O perfil `tunel` o mantém desligado.
- [ ] **Neste PC (Henrique, PowerShell como administrador):** identificar quem inicia o `cloudflared` nativo, **só leitura**: `Get-CimInstance Win32_Service | ? ProcessId -eq (Get-Process cloudflared).Id` e `Get-ScheduledTask | ? Actions -match cloudflared`. Anotar o nome, para a Tarefa 8 saber **o que parar e desativar**.

**Pronto quando:** os arquivos estão no SERVIDOR com permissão restrita, o túnel continua só aqui (Cloudflare mostra conexões somente do conector antigo), e o nome do serviço que inicia o túnel antigo está anotado.

## Tarefa 5: Ensaio completo (produção continua no ar)

**Consome:** Tarefas 1 a 4. **Produz:** prova de que a restauração e a API funcionam no SERVIDOR, e o tempo real de cada etapa.

Passos:

- [ ] **Dump a quente neste PC**, sem parar nada, gerado dentro do container:
  `docker exec controle_producao_postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/ensaio.dump'`, depois `docker cp controle_producao_postgres:/tmp/ensaio.dump <scratchpad>\ensaio.dump`, `sha256`, e `docker exec ... rm /tmp/ensaio.dump`.
- [ ] `scp` do dump, conferir `sha256` e `docker cp` para dentro do container do SERVIDOR.
- [ ] No SERVIDOR: `docker compose --env-file C:\ControleProducao\.env -f docker-compose.prod.yml up -d postgres` e esperar `healthy`.
- [ ] Restaurar: `pg_restore --no-owner --clean --if-exists -U $POSTGRES_USER -d $POSTGRES_DB /tmp/ensaio.dump`.
- [ ] Subir `up -d api` e esperar `healthy` (healthcheck da imagem usa `/api/v1/health/ready`).
- [ ] Testes por túnel SSH (`ssh -L 18000:127.0.0.1:8000`), sem abrir porta na rede: `/api/v1/health/ready` 200, login de um usuário real **de teste**, listagem de propostas.
- [ ] Comparar contagem de linhas das tabelas (script único que lista `pg_stat_user_tables.n_live_tup` mais `count(*)` nas 8 maiores) entre origem e destino, e `alembic_version = 20261014_0038` nos dois.
- [ ] Cronometrar: dump, `scp`, restore, subida da API.
- [ ] Desmontar o ensaio: `docker compose ... down -v` no SERVIDOR (o volume de teste, **não** neste PC), e conferir que o SERVIDOR está vazio de novo.

**Pronto quando:** contagens e `alembic_version` iguais, saúde 200 e login funcionando. O tempo total estimado da virada fica registrado (meta ≤ 30 min).

## Tarefa 6: Backup agendado (D10)

**Arquivo:** `scripts/servidor/backup_db.ps1` (novo, vai para `C:\ControleProducao\`).

- [ ] Dump dentro do container (`pg_dump -Fc -f /tmp/...`), `docker cp` para `C:\ControleProducao\backups\cp_AAAAMMDD_HHmm.dump`, remover o temporário do container.
- [ ] Retenção: apagar dumps locais com mais de 14 dias.
- [ ] Cópia para `\\<PC-DO-BACKUP>\<pasta>`; falha na cópia grava no log e **não** apaga o dump local.
- [ ] Log em `C:\ControleProducao\backups\backup.log` (sem segredos).
- [ ] Agendar: `schtasks /Create /SC DAILY /ST 02:00 /TN ControleProducaoBackup /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\ControleProducao\backup_db.ps1" /RU industel`.
- [ ] **No SERVIDOR (Henrique):** `cmdkey /add:<PC-DO-BACKUP> /user:<usuario> /pass:*` para guardar a credencial da pasta, digitada lá (nunca no chat).
- [ ] **Teste de restauração:** restaurar o dump gerado em um banco temporário (`createdb`/`pg_restore`/`dropdb` dentro do container) e comparar contagens.

**Pendência:** qual é o outro PC sempre ligado e a pasta compartilhada (Q6). Sem isso a cópia externa não é configurada, e o plano segue com backup só local até o Henrique informar.

**Pronto quando:** um dump agendado manualmente (`schtasks /Run`) aparece localmente e na pasta externa, e o teste de restauração passa.

## Tarefa 7: Prova do reinício do SERVIDOR (aceite D12)

**Faça antes da virada**, com a API de ensaio já desmontada (Tarefa 5), para não derrubar a produção.

- [ ] Subir temporariamente `postgres` e `api` no SERVIDOR (banco vazio de ensaio serve).
- [ ] Reiniciar o SERVIDOR (`shutdown /r /t 0`), sem ninguém logar manualmente.
- [ ] Cronometrar até `docker ps` mostrar `postgres` e `api` `healthy`. **Meta ≤ 5 minutos.**
- [ ] Se não subir: voltar à Tarefa 0 e revisar o Autologon e o Docker Desktop.
- [ ] Desmontar de novo (`down -v`).

**Pronto quando:** depois de um reinício, a stack sobe sozinha em até 5 minutos.

## Tarefa 8: Virada

**Pré-condições:** Tarefas 1 a 7 verdes; equipe avisada pelo Henrique; o Henrique presente neste PC com **PowerShell como administrador já aberto**; o SERVIDOR sem containers do ensaio.

| Passo | Onde | Ação | Confirma? |
|---|---|---|---|
| 8.1 | este PC | `docker stop controle_producao_api` (o Postgres **continua ligado**). **Início da parada.** | **sim** |
| 8.2 | este PC | Dump final (mesmo método seguro da Tarefa 5), `sha256`. | não |
| 8.3 | este PC → SERVIDOR | `scp` do dump + cópia do volume `update_repository_data` por arquivo `.tar` (container `alpine` com `tar`), conferindo `sha256`. | não |
| 8.4 | SERVIDOR | `up -d postgres`, `pg_restore`, restaurar o volume de updates, `up -d api`, esperar `healthy`. | não |
| 8.5 | SERVIDOR | Comparar contagens e `alembic_version` com a origem (que está parada, então os números são finais). | não |
| 8.6 | este PC (admin) | Parar **e desativar** o serviço/tarefa do `cloudflared` nativo identificado na Tarefa 4. Confirmar que o processo sumiu. | **sim** |
| 8.7 | SERVIDOR | `docker compose ... --profile tunel up -d cloudflared`. | **sim** |
| 8.8 | qualquer | `https://api.ykora.com.br/api/v1/health/ready` 200. Ler (somente leitura, via Cloudflare) as conexões do túnel `controle-producao`: só devem existir conexões do conector novo. | não |
| 8.9 | um Desktop | Login e abrir uma proposta pelo Desktop de **outro** PC. **Fim da parada.** | não |

**Se qualquer verificação das etapas 8.4 a 8.9 falhar:** executar o rollback da Tarefa 9 e investigar depois.

**Pronto quando:** a seção "Critérios de aceite" da especificação passa nos itens 1 a 5 e 7.

## Tarefa 9: Rollback (comandos conferidos antes da virada)

Escrever e conferir estes comandos na Tarefa 5 (sem executar o rollback de verdade).

**Rollback imediato (nos primeiros minutos, sem dado novo no SERVIDOR):**
- [ ] SERVIDOR: `docker compose ... --profile tunel stop cloudflared api`.
- [ ] Este PC (admin): iniciar o `cloudflared` nativo (o mesmo serviço da Tarefa 4).
- [ ] Este PC: `docker start controle_producao_api`.
- [ ] Conferir `https://api.ykora.com.br/api/v1/health/ready` 200.

**Rollback tardio (já entrou dado novo no SERVIDOR):** primeiro `pg_dump` do SERVIDOR e restaurar **aqui** em `controle_producao_postgres`, senão os lançamentos feitos desde a virada se perdem. Isso exige parar a API do SERVIDOR antes do dump. **Decisão com o Henrique nessa hora**, não automática.

**Pronto quando:** os comandos estão escritos e foram conferidos contra os nomes reais de containers e serviços.

## Tarefa 10: Pós-virada

- [ ] Primeiras 24 h: olhar `docker logs` da API a cada algumas horas e o `backup.log`.
- [ ] Teste da cópia externa do backup (Tarefa 6) confirmado.
- [ ] Dia 7: o Henrique decide a limpeza deste PC (containers e volumes de produção). **Não apagar sem confirmação.**
- [ ] Henrique: remover `sudo` sem senha e a chave da VM Ubuntu (Q7) e trocar as senhas expostas (Q8).
- [ ] `fase-report` com o fechamento em `docs/architecture/` (skill do projeto), mais atualização do `CLAUDE.md`/memória com o novo endereço do servidor.

---

## Foco de revisão (cinco falhas que a especificação implica e nenhum teste cobre)

1. **Dump corrompido por redirecionamento do PowerShell:** só o `sha256` e o `pg_restore` com contagem acusam. Por isso a regra "gerar dentro do container + `docker cp`".
2. **Reinício do SERVIDOR com o Docker Desktop ainda subindo:** o `cloudflared` pode tentar iniciar antes da API ficar saudável. O `depends_on: service_healthy` e o `restart: unless-stopped` cobrem, mas só a Tarefa 7 prova.
3. **Dois conectores do túnel ao mesmo tempo:** metade dos usuários cai em um servidor com banco desatualizado. A verificação 8.8 lê as conexões na Cloudflare.
4. **Falta de RAM no SERVIDOR (2,2 GB livres de 15,4 GB):** o Docker Desktop pode ter a API ou o Postgres encerrados (OOM). Medir na Tarefa 0 e ficar atento nas primeiras 24 h.
5. **Dado novo depois da virada e rollback tardio:** o rollback "simples" volta a um banco desatualizado. O plano trata isso como decisão consciente, não como automática.

## Autorrevisão

- **Cobertura da especificação:** objetivos 1 e 2 (Tarefas 5 e 8), 3 (Tarefa 8, nenhuma alteração em Desktop), 4 (Tarefa 5 mede, Tarefa 8 executa), 5 (Tarefa 9), 6 (Tarefas 0, 6 e 7). D1 a D13 aparecem em tarefas. Q5 e Q6 viram pré-condições explícitas.
- **Nomes consistentes:** `controle_producao_api`, `controle_producao_postgres`, `controle_producao_cloudflared`, perfil `tunel`, caminho `C:\ControleProducao\`, tunnel `f4b0db5b-d3ff-4d5e-a00a-cb126b94bfcd`.
- **Fora do plano por decisão:** Caddy/HTTPS interno, migrations 0039 a 0041, Almox+, ambiente de dev.
- **Ressalva:** o plano traz decisões e comandos-chave, não todo o código dos scripts. Os `.ps1` serão escritos durante a execução de cada tarefa e mostrados antes de rodar.
