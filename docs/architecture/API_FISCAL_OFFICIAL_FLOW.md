# Fluxo oficial Fiscal na API

## Escopo

A Etapa 13 migra o modulo Fiscal para o fluxo oficial:

```text
Desktop -> API -> PostgreSQL
```

A API passa a ser a autoridade para fila fiscal, registro manual de nota, emissao parcial, emissao total, vinculos por item, cancelamento interno, indicadores, historico, permissoes e concorrencia.

Nao fazem parte desta etapa: NF-e real, SEFAZ, XML, DANFE, assinatura digital, calculo tributario, financeiro, migracao de registros fiscais antigos do SQLite, sincronizacao bidirecional e integracao Nomus em producao.

## Diagnostico legado

Arquivos principais analisados:

- `app/services/production_repository.py`
- `app/ui/fiscal_page.py`
- `app/ui/fiscal_emission_dialog.py`
- `app/models/fiscal_table_model.py`

Tabelas SQLite equivalentes:

- `fiscal_processos`
- `fiscal_itens`
- `fiscal_emissoes`
- `fiscal_emissao_itens`
- `fiscal_movimentacoes`

Funcoes relevantes encontradas:

- `ensure_fiscal_entry_for_process`
- `ensure_fiscal_entries_for_all_processes`
- `create_fiscal_items_from_process_items`
- `list_fiscal_processes`
- `list_fiscal_items`
- `list_fiscal_emissions`
- `list_fiscal_movements`
- `fiscal_indicators`
- `fiscal_report_rows`
- `register_fiscal_emission`
- `mark_fiscal_invoice_withdrawn`

## Modelagem PostgreSQL

Migration oficial:

```text
20260721_0008_create_fiscal_records.py
```

Tabelas criadas:

- `fiscal_records`: controle fiscal por proposta.
- `fiscal_items`: saldo fiscal por item da proposta.
- `fiscal_invoices`: registro operacional de notas fiscais.
- `fiscal_invoice_items`: vinculo entre nota, proposta e item.
- `fiscal_events`: historico/auditoria fiscal.

O modulo nao armazena valores comerciais ou financeiros.

## Estados fiscais

Estados persistidos em `status_fiscal`:

```text
FALTA_EMITIR_NOTA_FISCAL
NOTA_FISCAL_PARCIAL
NOTA_FISCAL_EMITIDA
FISCAL_CANCELADO
```

Situacoes calculadas/exibidas em `fiscal_situation`:

```text
AGUARDANDO_NF
CP_EM_PROCESSAMENTO
NF_EM_PROCESSAMENTO
DISPONIVEL_PARA_EMISSAO
PENDENCIA_FISCAL_CRITICA
NF_PARCIAL
NF_EMITIDA
NF_RETIRADA_CLIENTE
FISCAL_CANCELADO
```

Estados por item:

```text
PENDENTE
PARCIAL
FATURADO
CANCELADO
```

## Entrada no Fiscal

A fila fiscal oficial e sincronizada pela API a partir das propostas oficiais ativas e nao canceladas. Isso preserva o acompanhamento global que existia no legado por `ensure_fiscal_entries_for_all_processes`, mantendo o estado fiscal independente da area operacional.

Essa sincronizacao cria registros fiscais e itens faltantes no PostgreSQL. Nao existe escrita no SQLite em modo oficial.

## Emissao manual

A emissao manual cria uma nota operacional e vinculos por item:

```text
POST /api/v1/fiscal/records/{fiscal_record_id}/invoices
```

Validacoes:

- permissao `fiscal.register_emission`;
- versao atual do registro fiscal;
- numero/serie duplicados;
- item existente e pertencente a proposta;
- quantidade e peso positivos;
- saldo fiscal suficiente;
- transacao atomica.

Quando todos os itens ficam cobertos, a API marca `NOTA_FISCAL_EMITIDA`. Quando resta saldo pendente, marca `NOTA_FISCAL_PARCIAL`.

## Cancelamento interno

O cancelamento e somente administrativo, sem efeito SEFAZ:

```text
POST /api/v1/fiscal/invoice-items/{invoice_item_id}/cancel
```

Ele exige permissao `fiscal.cancel_link`, justificativa e versao atual. O vinculo fica inativo, o saldo volta para pendencia, a situacao fiscal e recalculada e um evento e registrado.

## Endpoints

```text
GET  /api/v1/fiscal/records
GET  /api/v1/fiscal/records/{fiscal_record_id}
GET  /api/v1/fiscal/indicators
GET  /api/v1/fiscal/indicator-rows/{indicator}
POST /api/v1/fiscal/records/{fiscal_record_id}/invoices
POST /api/v1/fiscal/invoice-items/{invoice_item_id}/cancel
POST /api/v1/fiscal/records/{fiscal_record_id}/withdrawal
```

## Permissoes

Permissoes oficiais:

- `fiscal.view`
- `fiscal.register_emission`
- `fiscal.cancel_link`

As permissoes sao criadas pela migration e vinculadas ao perfil administrador.

## Eventos

Eventos fiscais minimos:

- `FISCAL_INVOICE_REGISTERED`
- `FISCAL_INVOICE_ITEM_CANCELLED`
- `FISCAL_INVOICE_WITHDRAWN`

Os eventos preservam proposta, item, nota, status anterior, status novo, usuario, data e metadados.

## Desktop

Com `postgresql_official_proposals_enabled=true`:

- a tela Fiscal le a fila pela API;
- detalhes, itens, notas, historico e indicadores vem da API;
- registro de nota e retirada de nota chamam a API;
- erros de negocio preservam `error_code`;
- nao ha fallback para SQLite.

Com a flag desligada, o legado permanece isolado apenas para rollback controlado.

## Concorrencia

Mutacoes fiscais usam versionamento otimista do registro fiscal e dos itens quando informado. Em conflito, a API retorna `FISCAL_VERSION_CONFLICT` e nenhuma escrita parcial deve permanecer.

