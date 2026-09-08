# Alembic

Estrutura preparada para as futuras migrations PostgreSQL da API.

Nesta etapa de fundacao nenhuma tabela funcional foi criada, nenhuma migration inicial foi gerada e nenhum banco foi alterado.

Comandos previstos para etapas futuras:

```bash
alembic revision --autogenerate -m "descricao"
alembic upgrade head
alembic downgrade -1
alembic current
alembic history
```

As migrations de producao devem ser executadas de forma controlada no servidor. Elas nunca devem ser disparadas automaticamente por cada computador desktop.
