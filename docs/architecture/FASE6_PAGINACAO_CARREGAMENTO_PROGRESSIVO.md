# Fase 6 — Paginação e carregamento progressivo

## Execução técnica

### Contrato paginado

Os adaptadores de propostas, produção, expedição, galvanização, fiscal e chat agora expõem métodos `*_page` que preservam `items` e `total` retornados pela API. Os métodos legados continuam retornando apenas a lista para não quebrar as telas existentes.

Também foi adicionado `BackendService.process_rows_page(area, filters, limit, offset)`, centralizando a futura paginação por área e mantendo os filtros no servidor.

### API

Os endpoints oficiais já trabalham com `limit` e `offset`, com limites máximos definidos no router. A camada desktop agora encaminha esses parâmetros nos métodos paginados, inclusive no Fiscal, que anteriormente fixava `limit=200` e `offset=0`.

### Áreas cobertas pelo contrato

- Controle Geral;
- Produção;
- Expedição;
- Galvanização;
- Fiscal;
- Chat.

### Compatibilidade

Nenhuma tela legada foi quebrada: chamadas existentes continuam recebendo listas. A migração visual para botão “Carregar mais”/paginação inferior deve consumir `process_rows_page` e os métodos `*_page`, preservando seleção e posição já tratados na Fase 3.

## Validação

- `compileall` de desktop e API aprovado.
- 27 testes aprovados.
- Testes que exigem banco externo foram ignorados quando o ambiente não estava disponível.
