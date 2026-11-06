# Especificação: como as propostas entram na Inspeção

Status: aguardando aprovação do Henrique. Nada foi construído.
Data: 2026-10-21.
Complementa `docs/spec-inspecao-logistica.md` (a área Inspeção já está implementada na API de dev).

## 1. Intenção e porquê

Hoje a inspeção exige que o PD exista como Pedido (`proposals.order_reference`) de uma proposta ativa. Na base de dev, só 2 de 271 propostas têm esse campo preenchido. O número do pedido de compra costuma vir no campo Obra/Site (`proposals.project_name`) quando a proposta é importada. Sem uma regra de entrada, quase nenhuma proposta consegue entrar na aba Inspeção.

## 2. Objetivos

- Duas formas de levar uma proposta para a Inspeção: a marcação "precisa de inspeção" no cadastro e o botão "Adicionar à inspeção" nas Ações do Controle Geral.
- Identificar o PD da proposta: usar o campo Pedido e, se estiver vazio, extrair o número do campo Obra/Site com uma regra conservadora.
- Nunca chutar: se o número não for identificado com segurança, a pessoa digita o PD.

## 3. Não-objetivos

- Não alterar o Pedido já preenchido de nenhuma proposta.
- Não normalizar textos de Pedido que já existem (ex.: um Pedido preenchido com "PEDIDO COMPRA 700..." continua como está; a extração só vale para o fallback do Obra/Site).
- Sem ação em lote por enquanto (um PD por vez).
- Sem migração em massa das 271 propostas atuais: todas ficam desmarcadas.

## 4. Decisões do Henrique

| ID | Tema | Decisão |
|----|------|---------|
| E1 | Entrada | Os dois caminhos: marcação no cadastro e botão nas Ações do Controle Geral. |
| E2 | Fallback do PD | Pedido vazio: usar o número do Obra/Site. Regra conservadora: só extrai quando o campo é só o número ou vem depois de PEDIDO, PEDIDO COMPRA ou OC. Não achando, a pessoa digita. |
| E3 | Proposta marcada | Aparece na aba Inspeção como linha "A solicitar". O botão "Iniciar inspeção" abre o diálogo que confirma o PD e pergunta se o PD já está cadastrado no portal; só então cria a inspeção. |
| E4 | Padrão | A marcação nasce desmarcada, em proposta nova, importada e nas 271 atuais. |
| E5 | Onde grava o PD | No campo Pedido da proposta, com registro no histórico da proposta. Nunca sobrescreve um Pedido já preenchido. |
| E6 | Mínimo de dígitos | 6 dígitos serve para reconhecer o número do pedido (confirmado em 2026-10-21). |
| E7 | Lote | A ação existe só uma proposta por vez. Lote fica fora do escopo. |

## 5. Regra de extração do PD (decisão do Claude nos detalhes)

Roda na API (um só lugar, com testes); o Desktop só exibe a sugestão.

1. Se `order_reference` está preenchido: usa-o como está.
2. Senão, olha `project_name` (Obra/Site) e aceita apenas:
   - o campo inteiro é só dígitos (espaços nas pontas ignorados), ou
   - o texto contém PEDIDO, PEDIDO COMPRA, PEDIDO DE COMPRA, ORDEM DE COMPRA ou OC seguido de `:`, `#`, `-` ou espaço e depois a sequência de dígitos.
3. A sequência precisa ter **no mínimo 6 dígitos** (decisão do Claude). O resultado guarda só os dígitos.
4. Qualquer outro texto não gera sugestão, e a pessoa digita o PD.

Casos de teste, com dados reais da dev:

| Obra/Site | PD extraído |
|-----------|-------------|
| PEDIDO COMPRA 5400120719 | 5400120719 |
| PEDIDO COMPRA 7000053481 | 7000053481 |
| 7000053018 | 7000053018 |
| 5400125858 | 5400125858 |
| MSRTD004_A | nenhum |
| SITE - IHS 12060032 - SITTE64 | nenhum |
| 1101085506 - SMSEE67 | nenhum |
| 64060060 - GOCZK03 GF | nenhum |
| SUBESTAÇÃO BURITIZEIRO | nenhum |
| DADOS DO CLIENTE ENERTEL INDUSTRIA METALURGICA | nenhum |
| (vazio) | nenhum |

## 6. Fluxos

### 6.1 Marcação no cadastro
1. No formulário da proposta há a opção "Precisa de inspeção" (desmarcada por padrão).
2. Marcada, a proposta aparece na aba Inspeção como "A solicitar", se o PD dela ainda não tem inspeção.
3. Desmarcar só é possível enquanto não existe inspeção para o PD (decisão do Claude).

### 6.2 Botão "Adicionar à inspeção" (Ações do Controle Geral)
1. A ação aparece para quem tem permissão de editar proposta e de editar inspeção (`inspection.edit`). Fica desabilitada para proposta cancelada.
2. Abre o mesmo diálogo "Iniciar inspeção" da seção 6.3, para uma proposta por vez.
3. Se já existe inspeção para o PD da proposta, o botão leva à inspeção existente em vez de criar outra (decisão do Claude).

### 6.3 Diálogo "Iniciar inspeção"
1. Mostra a proposta e o PD sugerido (Pedido, ou extraído do Obra/Site, ou vazio).
2. A pessoa confirma ou digita o PD e informa se ele já está cadastrado no portal de cadastro.
3. Se o PD já é Pedido de outra proposta de cliente diferente, o diálogo avisa e pede confirmação (decisão do Claude).
4. Ao confirmar: grava o PD no campo Pedido da proposta, se estiver vazio, com evento no histórico da proposta; e cria a inspeção na etapa `cadastro` (PD não cadastrado) ou `solicitada` (PD cadastrado), como já faz a API.
5. **Decisão 2026-10-21 (substitui os itens 2 e 4 no que diz respeito a "PD já cadastrado" e à etapa inicial; o texto acima fica como histórico):** o diálogo não pergunta mais se o PD está cadastrado no portal, e a inspeção sempre nasce na etapa `pendente` ("Solicitação pendente"). A API continua aceitando `pd_registered` em `POST /inspections` e `POST /inspections/from-proposal`, mas o ignora. A pergunta é feita depois, ao sair de `pendente` (`POST /inspections/{id}/request`): cadastrado vai para `solicitada`, não cadastrado vai para `cadastro`.

### 6.4 Linha "A solicitar" na aba Inspeção
- Aparece para proposta marcada cujo PD (ou, se não houver PD, a própria proposta) ainda não tem inspeção.
- Selo "A solicitar" e botão "Iniciar inspeção".
- Várias propostas com o mesmo PD geram uma só linha, porque a inspeção é por PD.

## 7. Dados

- `proposals.requires_inspection boolean not null default false`. Migration `ADDITIVE`, com entrada em `migration_risk_registry.json`.
- Sem mudança em `inspections`: a ligação continua por `pd_code = order_reference`.
- O campo entra no schema da proposta (API), no formulário e na edição do Desktop. A importação do Nomus não o preenche.
- O endpoint de sugestão de PD fica na API do módulo `inspection`.

## 8. Segurança e permissões

- Marcar no cadastro exige a permissão de editar proposta que já existe.
- O botão e a criação da inspeção exigem `inspection.edit`, e a gravação do Pedido exige também a permissão de editar proposta.
- O texto digitado como PD é validado (tamanho e caracteres) e vai sempre por parâmetro, sem montar SQL.

## 9. Premissas e riscos

- Premissa: o Pedido, quando preenchido, é o PD correto.
- Risco: um número de 6 ou mais dígitos depois de "OC" ou "PEDIDO" que não seja o pedido de compra. A confirmação no diálogo cobre esse caso.
- Risco: proposta marcada sem PD identificável fica como "A solicitar" até alguém digitar o PD.

## 10. Critérios de aceite

- A tabela de casos da seção 5 passa como teste automatizado da API.
- Marcar uma proposta com Pedido vazio e Obra/Site "PEDIDO COMPRA 5400120719" a mostra em "A solicitar"; iniciar a inspeção grava 5400120719 no Pedido e cria a inspeção.
- Proposta com Obra/Site "MSRTD004_A" não gera sugestão e o diálogo exige digitar o PD.
- Um Pedido já preenchido nunca é alterado.
- Duas propostas com o mesmo PD geram uma só linha e uma só inspeção.
- O botão nas Ações fica desabilitado para proposta cancelada e sem a permissão.
- A suíte `python -m pytest tests api/tests -q` passa, exceto as falhas pré-existentes já conhecidas.

## 11. Ordem de implementação

1. API: função de extração com os testes, coluna `requires_inspection` com migration, endpoint de sugestão e de início da inspeção a partir da proposta.
2. Desktop: marcação no formulário da proposta e linha "A solicitar" com o diálogo.
3. Desktop: botão "Adicionar à inspeção" no Action Center. Usar o agente `action-center-reviewer` nessa etapa.

## 12. Perguntas em aberto

| Pergunta | Dono |
|----------|------|
Nenhuma pergunta em aberto.
