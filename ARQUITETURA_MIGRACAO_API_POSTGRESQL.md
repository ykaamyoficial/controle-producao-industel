# Documento de Arquitetura - Migracao para API e PostgreSQL

## Objetivo

Evoluir o Sistema de Controle de Producao para uma arquitetura Cliente/Servidor, substituindo o acesso direto ao SQLite por uma API REST responsavel por toda a comunicacao com o banco de dados PostgreSQL.

O objetivo e aumentar a seguranca, a escalabilidade, a facilidade de manutencao e preparar o sistema para futuras versoes Web, Mobile e integracoes externas.

## Arquitetura Oficial

```text
Aplicativo Desktop
        |
        | HTTPS / REST
        v
API do Sistema (FastAPI)
        |
        v
PostgreSQL
```

## Regras Obrigatorias

- O aplicativo desktop nao podera acessar o banco de dados diretamente.
- Todo acesso aos dados devera passar pela API.
- Somente a API podera possuir credenciais do PostgreSQL.
- Toda regra de negocio devera ficar centralizada na API.

## Objetivos Tecnicos

- Centralizar todas as regras de negocio.
- Eliminar SQL espalhado pelo sistema.
- Melhorar seguranca.
- Facilitar futuras integracoes.
- Permitir multiplos usuarios simultaneamente.
- Preparar o sistema para crescimento.

## Stack Oficial

### Backend

- Python 3.12+
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Pydantic
- Uvicorn

### Banco

- PostgreSQL

### Cliente

- Aplicativo Desktop existente, mantido durante a migracao.

## Organizacao Inicial da API

```text
api/
 |-- app/
 |   |-- main.py
 |   |-- core/
 |   |-- database/
 |   |-- modules/
 |   |-- shared/
 |   `-- services/
 |-- alembic/
 |-- migrations/
 |-- tests/
 `-- docs/
```

Cada modulo devera conter, sempre que aplicavel:

- router
- service
- repository
- schemas
- models
- permissions

## Comunicacao

O Desktop devera consumir apenas endpoints REST.

Exemplos:

```text
Desktop
    |
    v
POST /login

GET /proposals

POST /production/start

PATCH /loads/{id}

GET /notifications
```

O Desktop nunca executara comandos SQL diretamente.

## Migracoes

Toda alteracao estrutural do banco devera ocorrer atraves de migrations versionadas utilizando Alembic.

E proibido alterar manualmente o banco de producao.

Cada nova funcionalidade que modificar a estrutura do banco devera possuir sua respectiva migration.

## Ambientes

### Dev

- API local
- PostgreSQL local

### Homologacao

- API de testes
- PostgreSQL de testes

### Producao

- API no servidor
- PostgreSQL oficial

Nunca utilizar o banco de producao para desenvolvimento.

## Seguranca

A API sera responsavel por:

- autenticacao;
- autorizacao;
- validacao de permissoes;
- validacao das regras de negocio;
- auditoria;
- controle de transacoes.

O PostgreSQL ficara acessivel apenas para a API.

## Integracoes

Toda integracao externa devera ocorrer pela API.

Exemplos:

- Nomus
- Atualizacoes automaticas
- Chat
- Notificacoes
- Futuras integracoes

Nenhuma integracao externa devera ser realizada diretamente pelo aplicativo Desktop.

## Ordem Oficial de Desenvolvimento

1. Auditoria da arquitetura atual.
2. Estrutura base da API.
3. Configuracao do PostgreSQL.
4. Sistema de autenticacao.
5. Camada de acesso ao banco.
6. Migracoes com Alembic.
7. Migracao gradual dos modulos.
8. Ferramenta de migracao SQLite para PostgreSQL.
9. Testes automatizados.
10. Implantacao em homologacao.
11. Implantacao em producao.

## Diretrizes para o Codex

Durante todo o desenvolvimento:

- Nao alterar regras de negocio existentes sem necessidade.
- Priorizar arquitetura limpa e modular.
- Evitar codigo duplicado.
- Manter alta cobertura de testes.
- Criar documentacao tecnica das decisoes importantes.
- Nao realizar alteracoes grandes em uma unica etapa.
- Cada etapa devera ser pequena, validada e reversivel.
- Antes de implementar novas funcionalidades, analisar a arquitetura existente e propor a solucao mais adequada.
- Sempre preservar compatibilidade com futuras expansoes do sistema.

## Resultado Esperado

Ao final da migracao, o sistema devera possuir:

- API REST centralizada.
- PostgreSQL como banco oficial.
- Aplicativo Desktop consumindo exclusivamente a API.
- Regras de negocio centralizadas.
- Banco protegido contra acesso direto.
- Arquitetura preparada para futuras versoes Web, Mobile e integracoes empresariais.
