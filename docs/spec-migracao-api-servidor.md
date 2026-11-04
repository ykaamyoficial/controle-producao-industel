# Especificação: migração da API de produção para o SERVIDOR

Status: **aguardando aprovação do Henrique** (nada foi instalado nem alterado no SERVIDOR até aqui).
Data: 2026-11-04

## 1. Intenção e porquê

A API de produção (Docker `controle_producao_industel`) roda hoje neste PC de trabalho. O Henrique separou o computador **SERVIDOR** só para isso. Objetivo: a API, o banco com os dados reais e o túnel Cloudflare passam a rodar no SERVIDOR, sem perder dados e sem o Desktop de ninguém precisar mudar.

A VM Ubuntu que chegou a ser preparada foi **descartada** (D1).

## 2. Situação atual (levantada em leitura, 2026-11-04)

| Item | Origem (este PC) | Destino (SERVIDOR) |
|---|---|---|
| Computador | PC de trabalho, `192.168.2.190` | `SERVIDOR`, `192.168.2.128`, Windows 10 Pro |
| Docker | Docker Desktop, engine Linux | Docker 29.9.2, engine Linux, 4 CPUs, 8 GB, **vazio** |
| API | `controle_producao_api`, imagem `local/controle-producao-api:0.11.0`, porta 8000 | nada |
| Banco | `controle_producao_postgres`, Postgres 16, **103 MB**, Alembic `20261014_0038` | nada |
| Volumes | `controle_producao_industel_postgres_prod_data`, `controle_producao_industel_update_repository_data` | nada |
| Túnel | `cloudflared` nativo do Windows, tunnel `f4b0db5b-d3ff-4d5e-a00a-cb126b94bfcd`, `api.ykora.com.br -> http://localhost:8000` (config e credencial em `C:\Users\Industel\.cloudflared\`) | nada |
| HTTPS interno (Caddy) | **não está rodando** | não necessário (D8) |
| Acesso remoto | — | SSH por chave, usuário `servidor\industel`, porta 22 só para `192.168.2.0/24` |

Portas 8000, 443, 5432 e 5433 estão livres no SERVIDOR.

## 3. Objetivos

1. API e banco de produção rodando no SERVIDOR, com os dados reais idênticos aos de hoje.
2. `api.ykora.com.br` continua funcionando, apontando para o SERVIDOR.
3. Nenhum Desktop precisa ser alterado ou reinstalado.
4. Parada máxima de ~30 minutos na virada.
5. Se algo der errado, voltar para este PC em minutos (rollback).
6. O SERVIDOR sobe sozinho depois de reiniciar, e há backup diário.

## 4. Não-objetivos e anti-objetivos

- **Fora do escopo:** Almox+ (`sistema-controle-estoque-industrial-*`), Supabase `controle-faccao`, ambiente de dev (`controle_producao_*_dev`, porta 8001), túneis `almox`, `estoque-materia-prima`, `produçãoteste/producaodev`. Eles ficam neste PC.
- Não migrar as migrations pendentes 0039 a 0041 (ainda sem commit): a versão que vai é a **0.11.0 exatamente como roda hoje**.
- Não mexer na API oficial neste PC até a virada, e não apagar nada dela depois (D11).
- Não expor a API ao SERVIDOR inteiro: ela só é alcançada pelo túnel (D8).
- Anti-objetivo: nenhum segredo em chat, em commit ou em arquivo versionado.

## 5. Decisões (registro)

| ID | Tema | Decisão | Quem decidiu | Data |
|---|---|---|---|---|
| D1 | Destino | Docker do computador SERVIDOR (192.168.2.128). A VM Ubuntu está descartada. | Henrique | 2026-11-04 |
| D2 | Escopo | Mover `controle_producao_api`, `controle_producao_postgres`, os 2 volumes de produção e o túnel `controle-producao`. Nada do Almox+, Supabase ou dev. | Claude (a partir do pedido "mover o container"; corrigir se errado) | 2026-11-04 |
| D3 | Dados | Levar o banco real (dump e restore) e o volume `update_repository_data`. | Henrique | 2026-11-04 |
| D4 | Acesso | SSH por chave (`~/.ssh/id_servidor`) como `servidor\industel`, porta 22 só para a LAN. | Henrique | 2026-11-04 |
| D5 | Túnel | **Mover o túnel atual**, sem túnel paralelo de teste. Implementação: `cloudflared` em container no SERVIDOR, com a mesma credencial, `config.yml` apontando para `http://api:8000`, `restart: unless-stopped`. | Henrique (mover) / Claude (como) | 2026-11-04 |
| D6 | Janela | Qualquer hora, com a equipe avisada. Mesmo assim o ensaio (seção 7, etapa 2) é feito antes, sem parar a produção. | Henrique | 2026-11-04 |
| D7 | Endereço | Todos os Desktops usam `api.ykora.com.br`. Nenhum PC é alterado. | Henrique | 2026-11-04 |
| D8 | HTTPS | Sem Caddy: a Cloudflare termina o TLS. API publicada só em `127.0.0.1:8000` do SERVIDOR. Compose próprio do SERVIDOR (sem `CADDY_*`, que no compose de produção são obrigatórios). | Claude (consequência de D7) | 2026-11-04 |
| D9 | Imagem e segredos | Mesma imagem `0.11.0`, transferida por `docker save` e `docker load` (o registry é `local`). Mesmo `.env.production` (`SECRET_KEY`, `NOMUS_ENCRYPTION_KEY`, `PROVISIONING_SECRET`), senão logins e credenciais do Nomus quebram. Copiado por SSH, permissão restrita. | Claude | 2026-11-04 |
| D10 | Backup | `pg_dump` diário agendado no SERVIDOR (Agendador de Tarefas), retenção de 14 dias, mais **cópia externa em uma pasta compartilhada de outro PC da rede**. Qual PC e a credencial da pasta ficam em aberto (Q6). | Henrique (destino) / Claude (rotina) | 2026-11-04 |
| D11 | Rollback | Containers e volumes deste PC ficam **parados, não apagados**, por **7 dias**. Voltar = parar a API no SERVIDOR, subir aqui e devolver o túnel. | Henrique | 2026-11-04 |
| D12 | SERVIDOR sempre ligado | Docker Desktop inicia com o Windows, **login automático** do usuário `industel`, sem suspensão/hibernação, atualização do Windows fora do expediente. | Henrique (aprovou) | 2026-11-04 |
| D13 | Limpeza da VM Ubuntu | Remover o `sudo` sem senha (`/etc/sudoers.d/90-migracao-temp`) e a chave `claude-migracao-servidor` da VM. Autorizado, **mas não executado**: a porta 22 da VM recusa conexão. Henrique faz os 2 comandos na VM (Q7). | Henrique | 2026-11-04 |

## 6. Restrições e riscos

- **Docker Desktop no Windows só sobe após login.** Sem a D12, uma queda de energia deixa a produção fora do ar até alguém logar. Login automático reduz a segurança física do SERVIDOR.
- O SERVIDOR tem pouca RAM livre (2,2 GB de 15,4 GB) e dá 8 GB ao Docker. Suficiente para API + Postgres, a acompanhar.
- Dois conectores do mesmo túnel dividem o tráfego: **nunca** deixar o `cloudflared` daqui e o do SERVIDOR ligados ao mesmo tempo, exceto no instante da troca.
- Parar o `cloudflared` deste PC exige PowerShell como administrador (não está claro qual serviço o inicia; o serviço `Cloudflared` aparece como "Stopped" enquanto o processo roda).
- O `docker` deste PC travou em uma sessão anterior. Se travar na virada, o dump final fica em risco: por isso o dump de teste do ensaio precisa funcionar antes.
- Escrita entre o dump final e a parada da API é perdida: a API precisa estar parada antes do dump final.
- **Segurança:** senhas apareceram em foto e em chat (credencial do Windows/Ubuntu). Devem ser trocadas depois. O `sudo` sem senha e a chave SSH ainda estão ativos na VM Ubuntu e devem ser removidos (Q4).

## 7. Ordem de implementação (a detalhar em `docs/plano-migracao-api-servidor.md`)

0. **Preparar o SERVIDOR:** pasta de trabalho, D12 (login automático, inicialização do Docker, energia), conferir RAM.
1. **Transferir:** imagem `0.11.0` e `.env.production` ajustado, compose do SERVIDOR (D8), config/credencial do túnel.
2. **Ensaio (sem parar a produção):** `pg_dump` a quente do banco atual, restore no SERVIDOR, subir API, testar saúde, login e leitura de dados por SSH. Medir o tempo. Remover o ensaio.
3. **Virada (janela D6):** avisar equipe → parar a API aqui (Postgres fica) → dump final → restore no SERVIDOR → subir API → parar o `cloudflared` daqui → subir o túnel no SERVIDOR → verificar.
4. **Pós-virada:** backup diário, observar 7 dias, depois decidir a limpeza de origem (com confirmação).

## 8. Critérios de aceite

- `api.ykora.com.br` responde saúde OK servida pelo SERVIDOR.
- Contagem de linhas das tabelas principais idêntica entre origem e destino.
- Um usuário real faz login, e um Desktop de outro PC abre e lista propostas (sem alterar nada nele).
- Webhook do Almox+ e os pacotes de atualização do Desktop acessíveis.
- SERVIDOR reiniciado de propósito: Docker, banco, API e túnel sobem sozinhos em até 5 minutos, sem ninguém logar.
- Um backup diário foi gerado e restaurado com sucesso em um banco de teste.
- Rollback ensaiado ou, no mínimo, os comandos registrados e conferidos.

## 9. Perguntas em aberto (dono: Henrique)

- ~~Q1 a Q4~~ respondidas (D10 a D13).
- **Q5:** Quem abre um PowerShell como administrador **neste PC** na hora de parar o túnel antigo? (Henrique)
- **Q6:** Qual outro PC da rede recebe a cópia do backup, e em que pasta compartilhada? A credencial dessa pasta **não** vai por chat. (Henrique)
- **Q7:** Rodar na VM, quando ela estiver ligada: `sudo rm -f /etc/sudoers.d/90-migracao-temp` e depois `sed -i '/claude-migracao-servidor/d' ~/.ssh/authorized_keys`. (Henrique)
- **Q8:** Trocar as senhas que apareceram em foto e chat (Windows do SERVIDOR e usuário `industel` da VM). (Henrique, depois da migração)
