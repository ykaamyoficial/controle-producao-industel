# Isolamento operacional por empresa

## Objetivo

Cada empresa cliente deve operar com uma API operacional e um banco PostgreSQL proprios.
O Admin Platform fica separado e atua como painel de cadastro, descoberta, monitoramento e administracao dos ambientes.

## Arquitetura alvo

```text
Admin Platform Web
        |
        v
Admin Platform API + PostgreSQL administrativo
        |
        | registra/monitora
        v
Empresa cliente
  - API operacional propria
  - PostgreSQL operacional proprio
  - usuarios operacionais proprios
```

## Regra oficial

- O banco administrativo do Admin Platform nao guarda propostas, producao, expedicao ou dados operacionais.
- Cada API operacional acessa somente o PostgreSQL da sua empresa.
- O desktop nao escolhe banco diretamente.
- O desktop usa o codigo de acesso da empresa para descobrir a API operacional correta.
- Depois da descoberta, o login acontece diretamente na API operacional daquela empresa.

## Fluxo de cadastro de empresa

1. O operador cadastra a empresa no Admin Platform.
2. O sistema gera um `access_code` unico.
3. Um ambiente operacional deve ser provisionado para essa empresa.
4. O ambiente recebe:
   - `OPERATIONAL_COMPANY_CODE`
   - `OPERATIONAL_COMPANY_NAME`
   - `OPERATIONAL_INSTANCE_ID`
   - `DATABASE_URL` do PostgreSQL isolado
   - `PROVISIONING_SECRET`
5. O Admin Platform registra a URL da API operacional no ambiente da empresa.
6. O Admin Platform cria o admin inicial chamando `/api/v1/provisioning/initial-admin` na API operacional.
7. No desktop, o usuario informa o codigo de acesso.
8. O desktop resolve esse codigo no Admin Platform e salva a API operacional correspondente.
9. O login do usuario passa a ocorrer na API operacional da empresa.

## Provisionamento

O Admin Platform nao deve executar Docker ou criar bancos diretamente dentro da propria API.
Isso evita que uma falha no painel administrativo tenha permissao para controlar toda a infraestrutura.

O modelo recomendado e:

- Admin Platform registra a empresa e o estado desejado.
- Um provisionador controlado no servidor cria API e PostgreSQL por empresa.
- O provisionador atualiza o ambiente no Admin Platform com URL, alias do banco e status.

Para desenvolvimento local e homologacao simples, o script abaixo gera uma stack isolada:

```powershell
.\scripts\provision_company_environment.ps1 `
  -CompanyCode empresa01 `
  -CompanyName "Empresa 01" `
  -ApiPort 8010 `
  -PostgresPort 55440
```

Para subir a stack imediatamente:

```powershell
.\scripts\provision_company_environment.ps1 `
  -CompanyCode empresa01 `
  -CompanyName "Empresa 01" `
  -ApiPort 8010 `
  -PostgresPort 55440 `
  -Start
```

## Campos usados no Admin Platform

- Empresa:
  - `name`
  - `slug`
  - `access_code`
  - dados de contato
  - status administrativo
- Ambiente:
  - `company_id`
  - `name`
  - `environment_type`
  - `status`
  - `operational_api_url`
  - `database_alias`
  - `operational_instance_id`
  - status da ultima checagem
  - revisao do banco
  - `provisioning_status`
  - `provisioning_step`
  - `provisioning_message`
  - `provisioning_requested_at`
  - `provisioning_completed_at`

## Estados de provisionamento

- `not_requested`: ambiente cadastrado manualmente, sem solicitacao de criacao automatizada.
- `pending`: aguardando provisionador iniciar.
- `creating_database`: PostgreSQL da empresa sendo criado.
- `starting_api`: API operacional sendo criada/iniciada.
- `running_migrations`: migrations da API operacional em execucao.
- `creating_initial_admin`: admin inicial sendo criado.
- `ready`: API e banco prontos para uso.
- `failed`: provisionamento falhou e precisa de correcao.

## Atualizacao de status pelo provisionador

O provisionador deve chamar o Admin Platform usando o segredo `OPERATIONAL_PROVISIONING_SECRET`:

```http
PATCH /api/v1/environments/{environment_id}/provisioning
X-Provisioning-Secret: <segredo>
Content-Type: application/json

{
  "provisioning_status": "running_migrations",
  "provisioning_step": "migrations",
  "provisioning_message": "Executando migrations Alembic."
}
```

Quando concluir:

```json
{
  "provisioning_status": "ready",
  "provisioning_step": "validation",
  "provisioning_message": "Ambiente operacional pronto.",
  "operational_api_url": "http://127.0.0.1:8010",
  "database_alias": "controle_empresa01",
  "operational_instance_id": "id-da-instancia",
  "last_database_status": "current"
}
```

## Estado atual implementado

- O Admin Platform cadastra empresas.
- O Admin Platform gera `access_code`.
- O desktop resolve o codigo de acesso e configura a API correta.
- O Admin Platform cria admin inicial quando a API operacional ja existe.
- O script `scripts/provision_company_environment.ps1` gera uma API e um PostgreSQL isolados por empresa.
- O Admin Platform possui campos e endpoint seguro para acompanhar o status do provisionamento.

## Proximo passo recomendado

Criar um modulo de provisionamento no Admin Platform para controlar fila/status:

- `pending`
- `creating_database`
- `starting_api`
- `running_migrations`
- `creating_initial_admin`
- `ready`
- `failed`

Esse modulo deve conversar com um provisionador externo ou script autorizado no servidor.
