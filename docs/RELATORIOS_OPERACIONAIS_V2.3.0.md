# Relatorios Operacionais por Area - v2.3.0

Esta versao adiciona uma area propria para relatorios operacionais do Controle de Producao Industel 2.0. O modulo e somente leitura: nao altera status, nao cria historico, nao grava auditoria e nao modifica dados do banco.

## Areas disponiveis

- Producao
- Galvanizacao
- Expedicao
- Almoxarifado
- Remanejamentos

## Filtros

A tela permite filtrar os relatorios por:

- Area
- Tipo de relatorio
- Data inicial
- Data final
- Proposta
- Cliente
- Obra/Site
- Lote
- Status

Os filtros sao enviados para a camada de consultas somente leitura em `app/services/operational_reports.py`.

## Cards e indicadores

Cada relatorio retorna cards de resumo conforme a area selecionada. Os cards mostram indicadores operacionais e permitem drill-down: ao clicar em um card, o sistema abre uma lista filtrada com os registros relacionados.

Exemplos:

- Producao: producao completa, producao parcial e pendencias.
- Galvanizacao: cargas abertas, cargas finalizadas e pendencias.
- Expedicao: entregues, entregas parciais e pendentes.
- Almoxarifado: pendentes, separadas e sem parafusos.
- Remanejamentos: origem, destino e pendencias.

## Tabela detalhada

A tabela principal mostra as linhas retornadas pelo relatorio selecionado. As colunas mudam conforme a area, usando apenas dados operacionais como proposta, cliente, obra/site, lote, status, datas, peso e itens.

Nao sao exibidos valores financeiros.

## Navegacao e drill-down

A v2.3.0 adiciona navegacao operacional:

- Clique em card para abrir a lista relacionada.
- Duplo clique em uma linha para abrir detalhes da proposta.
- Botao direito na linha para abrir o menu de contexto.

O menu de contexto oferece:

- Ver detalhes da proposta
- Ver itens
- Ver historico
- Ver remanejamentos
- Ver carga de galvanizacao
- Ver situacao da expedicao
- Copiar numero da proposta

Em relatorios de remanejamento, tambem e possivel abrir diretamente a proposta de origem e a proposta de destino.

Todas as janelas abertas por essa navegacao sao somente leitura.

## Exportacao CSV

A tela permite exportar o relatorio atual para CSV.

Regras da exportacao:

- Nao grava no banco.
- Nao inclui valores financeiros.
- Nao inclui preco, valor, subtotal, imposto, pagamento ou frete.
- Exporta apenas as colunas operacionais visiveis no relatorio.

A exportacao PDF permanece planejada para versao futura.

## Confiabilidade dos dados

Cada relatorio retorna um indicador de confiabilidade:

- Alta: dados atuais e estruturados suficientes.
- Media: dados utilizaveis, mas com alguma limitacao historica.
- Baixa: dados incompletos ou dependentes de campos antigos.

Avisos tecnicos sao exibidos quando algum relatorio depende de informacoes historicas limitadas ou quando ha risco de interpretacao parcial.

## Limitacoes atuais

- PDF operacional ainda nao foi implementado.
- Dashboard executivo mensal ainda nao foi implementado.
- Notificacoes ainda nao foram implementadas.
- Alguns relatorios por periodo dependem da qualidade das datas e historicos ja existentes.
- Almoxarifado ainda nao possui controle detalhado por item em todos os cenarios.

## Seguranca

O modulo foi validado como somente leitura. As consultas usam apenas dados operacionais e os testes garantem que:

- Gerar relatorio nao altera banco.
- Exportar CSV nao altera banco.
- Drill-down nao altera banco.
- Menus de contexto nao alteram status.
- Nenhum valor financeiro e retornado ou exportado.

## Validacao da versao

Validacoes executadas antes do merge:

- Testes automatizados completos.
- Compilacao de `app` e `tests`.
- Integridade SQLite.
- Verificacao de chaves estrangeiras.
- Conferencia de migracoes aplicadas.
