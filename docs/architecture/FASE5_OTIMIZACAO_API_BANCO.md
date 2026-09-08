# Fase 5 — Otimização da API e banco

## Planejamento técnico executado

### Medição de SQL lento

O engine assíncrono agora registra consultas acima de 300 ms com duração, fingerprint SHA-1 da instrução e indicação de `executemany`. Parâmetros e conteúdo de negócio não são gravados no log. Isso permite agrupar as consultas lentas sem expor dados sensíveis.

### Índices operacionais

Foi criada a migration `20260817_0024_operational_query_indexes` com índices para:

- área atual e status da proposta;
- cliente combinado com status;
- prazo/data limite;
- relacionamento mãe–filha;
- proposta/item produzido;
- carga/status da carga;
- proposta/status da expedição;
- status/data de entrada fiscal.

Os mesmos índices foram declarados nos modelos SQLAlchemy para manter o schema de desenvolvimento alinhado ao banco.

### Redução de leituras repetidas

O diagnóstico confirmou que a camada oficial já usa `selectinload` para carregar coleções operacionais em lotes, evitando lazy loading item a item nos principais endpoints. O logging de SQL passa a revelar os casos restantes de N+1 antes de alterações adicionais.

### Limites e agregações

Nesta etapa não foram reduzidos limites de paginação de forma arbitrária nem removidos carregamentos necessários às regras de parciais. A API mantém o contrato atual enquanto os fingerprints reais de produção são coletados; a próxima otimização deve usar esses dados para aplicar agregações e paginação no banco sem perder itens.

## Validação

- `python -m compileall -q api/app`: aprovado.
- Teste de migration/integração: 1 aprovado; testes dependentes de PostgreSQL/Docker foram ignorados por indisponibilidade do ambiente.
