# Migracao SQLite -> PostgreSQL Finalizada

Data de conclusao: 2026-07-27

Este documento registra o encerramento da migracao do Sistema de Controle de Producao Industel para a arquitetura oficial Desktop -> API -> PostgreSQL.

## Escopo da migracao

A migracao substituiu o modelo anterior, baseado em acesso local ao SQLite pelo desktop, por uma arquitetura cliente/servidor:

```text
Desktop PySide6 -> API FastAPI -> PostgreSQL
```

O objetivo foi centralizar regras de negocio, seguranca, permissoes, historico, auditoria e acesso aos dados na API.

## Etapas executadas

1. Auditoria da arquitetura anterior.
2. Criacao da estrutura base da API.
3. Configuracao do PostgreSQL de desenvolvimento.
4. Padronizacao do runtime da API.
5. Autenticacao, usuarios, roles e permissoes.
6. Cliente HTTP no desktop.
7. Propostas e itens oficiais pela API.
8. Cadastro e edicao de propostas no desktop via API.
9. Homologacao PostgreSQL.
10. Producao e fluxo por item.
11. Galvanizacao, cargas e retorno parcial.
12. Expedicao, separacao, entrega parcial e remanejamento.
13. Fiscal.
14. Usuarios e permissoes.
15. Controle Geral.
16. Historico operacional.
17. Parciais.
18. Almoxarifado.
19. Correcao administrativa pela API.
20. Auditoria final de dependencias SQLite.
21. Remocao controlada do legado operacional.
22. Homologacao final.
23. Estabilizacao do ambiente de desenvolvimento.
24. Atualizacao da suite oficial de testes.
25. Congelamento da baseline 3.0.0.

## Principais mudancas

- PostgreSQL passou a ser o banco oficial.
- FastAPI passou a ser a camada central de regras e persistencia.
- Desktop passou a consumir endpoints REST.
- Login deixou de depender de banco local.
- Usuarios, roles e permissoes passaram a ser carregados pela API.
- Propostas, itens e operacoes setoriais passaram para PostgreSQL.
- Historico e auditoria passaram a ser persistidos no banco oficial.
- SQLite saiu do fluxo operacional.
- Testes legados SQLite foram arquivados fora da suite oficial.
- Admin Platform foi separado do fluxo operacional atual.

## Modulos migrados

- Autenticacao.
- Usuarios e permissoes.
- Propostas.
- Itens de propostas.
- Controle Geral.
- Producao.
- Galvanizacao.
- Cargas.
- Retornos.
- Almoxarifado.
- Expedicao.
- Fiscal.
- Historico.
- Parciais.
- Correcao administrativa.
- Diagnostico API/PostgreSQL.

## Itens arquivados

SQLite legado:

- Runtime antigo: `tools/legacy_sqlite_runtime/`
- Ferramentas de migracao: `tools/legacy_sqlite_migration/`
- Testes legados: `tools/legacy_sqlite_runtime/archived_tests/`
- Migrations historicas do desktop antigo: `app/migrations/`

Admin Platform:

- `admin-platform/` permanece separado e nao integra a suite principal nem o fluxo operacional atual.

Documentacao historica:

- Documentos antigos foram preservados em `docs/architecture/` para rastreabilidade.

## Riscos conhecidos

- Documentos historicos ainda citam SQLite porque registram a evolucao do projeto.
- Ferramentas antigas de migracao ainda existem arquivadas, mas nao fazem parte do runtime oficial.
- O versionamento do aplicativo desktop permanece em `2.5.2`; a baseline `3.0.0` representa o marco arquitetural consolidado.
- A API esta na versao `0.8.0`; novas versoes devem preservar a arquitetura oficial.

Nenhum risco acima impede o uso operacional sobre API/PostgreSQL.

## Evidencias de validacao

Versoes registradas:

- API: 0.8.0
- API stage: official-fiscal
- Revisao Alembic: 20260727_0010
- Desktop: 2.5.2
- PostgreSQL validado: 16.14
- Docker validado: 29.6.1

Suite oficial:

- Comando: `python -m pytest tests api/tests -q`
- Resultado: 330 passed, 35 skipped, 0 failed

## Conclusao

A migracao SQLite -> PostgreSQL esta finalizada para o fluxo operacional oficial.

A partir da baseline 3.0.0, o sistema deve evoluir sempre sobre Desktop -> API -> PostgreSQL. O SQLite permanece apenas como legado arquivado, referencia historica ou ferramenta de migracao fora do runtime oficial.
