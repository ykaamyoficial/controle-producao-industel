# Importacao PDF Nomus

Esta funcionalidade permite ler uma proposta Nomus em PDF, conferir os dados
operacionais e preencher o cadastro de proposta do sistema.

## Fluxo de uso

1. Abra o **Controle Geral**.
2. Clique em **Novo processo**.
3. Clique em **Conferir PDF Nomus**.
4. Selecione o PDF da proposta Nomus.
5. Confira os campos extraidos e corrija o que estiver pendente.
6. Clique em **Usar dados no cadastro**.
7. Revise o formulario preenchido.
8. Clique em **Salvar** para gravar o processo.

O botao **Usar dados no cadastro** nao grava nada no banco. Ele apenas
transfere os dados conferidos para o formulario.

## Campos importados

- Numero da proposta.
- Cliente.
- Obra/Site.
- Data da proposta.
- Prazo, somente quando estiver confirmado como data.
- Pedido/OC, quando existir.
- Lote, quando existir.
- Itens da proposta.
- Descricao dos itens.
- Quantidade.
- Peso em kg, somente quando identificado ou corrigido pelo usuario.

## Campos que nao sao importados

Dados financeiros sao ignorados completamente. O sistema nao exibe, transfere
nem salva:

- Valor total.
- Valor unitario.
- Subtotal.
- Impostos.
- Descontos.
- Frete.
- Condicoes de pagamento.
- Dados bancarios.
- Qualquer valor monetario em R$.

## Conferencia obrigatoria

O usuario deve revisar antes de salvar. Alguns dados podem exigir confirmacao:

- Prazo relativo, como `7 DIAS`.
- Peso ausente no PDF.
- Campos nao identificados pelo leitor.

Quando o prazo ainda e relativo, ele nao e transferido para o campo de prazo do
cadastro. O usuario deve informar uma data definitiva manualmente.

## Duplicidade e seguranca

Ao salvar o cadastro importado, o sistema registra apenas metadados seguros:

- Origem da importacao: `NOMUS_PDF`.
- Nome do arquivo.
- Hash SHA-256 do PDF.
- Usuario e data da importacao.
- Observacoes de confirmacao.

O PDF original nao e copiado nesta versao. O texto bruto da proposta tambem nao
e armazenado.

O hash SHA-256 evita que o mesmo PDF seja usado mais de uma vez. A numeracao da
proposta tambem continua protegida contra duplicidade.

## Historico e auditoria

Quando o processo e salvo, o sistema registra:

- Historico: `Processo criado a partir de importacao PDF Nomus`.
- Auditoria: acao `IMPORTACAO_PDF_NOMUS`.

Se o usuario cancelar o cadastro antes de salvar, nada e registrado.
