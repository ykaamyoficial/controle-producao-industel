# Contrato futuro - Integracao Fiscal com Nomus

## Objetivo

Preparar uma etapa futura para reconciliar notas fiscais vindas do Nomus com o Fiscal oficial da API, sem implementar sincronizacao nesta etapa.

## Principios

- A API continua sendo a autoridade do dominio fiscal.
- O desktop nao conversa diretamente com o Nomus.
- Nenhuma chave Nomus deve ser salva no banco.
- Segredos devem usar o mecanismo oficial ja adotado, como DPAPI no Windows.
- Nao gravar valores financeiros desnecessarios.
- Nao executar busca silenciosa sem etapa aprovada.

## Propostas elegiveis futuras

Busca futura pode considerar propostas:

- em Producao;
- em Galvanizacao;
- no Fiscal com `FALTA_EMITIR_NOTA_FISCAL`;
- com entrega operacional e sem nota registrada.

## Identificadores

Campos de reconciliacao permitidos:

- numero da proposta;
- ID oficial da proposta;
- numero da nota;
- serie;
- chave de acesso, se disponivel;
- codigo ou numero do item;
- quantidade e peso quando existirem no retorno.

## Deduplicacao

A integracao deve evitar duplicidade por:

- numero da nota + serie;
- chave de acesso, quando informada;
- origem `NOMUS`;
- itens ja vinculados ao mesmo documento.

## Reconciliacao

Cenarios previstos:

- nota cobre todos os itens pendentes;
- nota cobre parte dos itens;
- nota cobre quantidade parcial de um item;
- nota ja existe manualmente;
- nota retornada sem item suficiente para conciliacao;
- proposta sem nota encontrada;
- cancelamento ou correcao apenas administrativa no sistema.

## Auditoria

Toda importacao futura deve registrar evento fiscal com:

- origem `NOMUS`;
- usuario ou servico executor;
- proposta;
- nota;
- itens afetados;
- estado anterior;
- estado novo;
- payload minimo nao sensivel;
- correlation ID.

## Erros

Erros futuros devem ser explicitos:

- credencial ausente;
- credencial invalida;
- nota duplicada;
- proposta nao encontrada;
- item nao conciliado;
- quantidade excedida;
- conflito de versao;
- indisponibilidade do Nomus.

## Fora do escopo atual

Nao implementar nesta etapa:

- worker;
- timer;
- busca silenciosa;
- consulta real ao Nomus;
- importacao automatica;
- SEFAZ;
- XML;
- DANFE;
- calculo tributario;
- financeiro.

