# Especificação: Inspeção (NQT) e Logística / Agendamento (LOG)

Status: aguardando aprovação do Henrique. Nada foi construído.
Data: 2026-10-20.

## 1. Intenção e porquê

A Industel hoje faz, nos portais da Equatorial, dois processos por fora do sistema: pedir a inspeção do pedido (gera o código NQT) e agendar a entrega (gera o código LOG). Não há controle de em que etapa cada pedido está nem há quantos dias está parado nela. O sistema passa a acompanhar os dois processos. A pessoa continua operando os portais e registra aqui o andamento.

## 2. Objetivos

- Registrar, por PD principal, o ciclo de inspeção até a aprovação ou dispensa, com o código NQT.
- Registrar LOGs (criados no portal) com o código, as propostas vinculadas, as datas e as etapas.
- Mostrar em cada etapa há quantos dias o item está nela.
- Manter histórico completo (quem, quando, motivo) de toda mudança de etapa, tentativa e vínculo.

## 3. Não-objetivos e anti-objetivos

- Não integrar com os portais (sem API, sem automação de navegador). Só passa a existir integração com API oficial e autorização da Equatorial, como fase futura.
- Não guardar arquivos (PIT, DOC, NF, XML, BIM): só link ou caminho.
- Não alertar prazo nem calcular SLA. Os 10 e 7 dias do desenho são tempos do portal e não são regra do sistema.
- Não guardar credenciais de portal.
- Não registrar o nome da empresa que monta a logística da Equatorial.
- Nada na API oficial (8000). Só na API de dev (8001) até autorização explícita.

## 4. Decisões do Henrique

| ID | Tema | Decisão |
|----|------|---------|
| D1 | Operação | O sistema só acompanha. A pessoa faz os passos nos portais e registra aqui. |
| D2 | Integração | Decidido em 2026-10-20: modelo manual definitivo. Os portais são ServiceNow (acesso por login) e Microsoft Forms, sem API pública. Integração só se a Equatorial oferecer API oficial no futuro, e isso seria um novo pedido. |
| D3 | Entidades | CP = proposta, PD = pedido principal. Ambos já existem no sistema. |
| D4 | Cardinalidade | 1 NQT por PD. 1 LOG reúne várias propostas, e podem entrar mais depois. |
| D5 | Dependência | A proposta só entra em LOG com a inspeção finalizada, ou seja, com o DOC BIM em PDF em mãos. Vale para dispensa e para inspeção in loco (corrigido em 2026-10-20). |
| D6 | Quem usa | Um setor opera as duas áreas. Permissão por área (ver e editar), atribuível aos perfis. |
| D7 | Prazos | Mostrar quantos dias o pedido está na etapa atual. Sem alerta. |
| D8 | Reprovação | Reprovada volta ao início com novo ciclo. O histórico guarda cada tentativa, com motivo. |
| D9 | Documentos | Só link ou caminho. Cada etapa tem a lista de documentos exigidos. |
| D10 | LOG | Criado no portal. Aqui se cadastra o código e se vinculam as propostas. É possível adicionar mais depois. |
| D11 | Telas | Duas páginas novas (Inspeção, Logística) e uma seção nos detalhes da proposta. |
| D12 | Remover do LOG | Exige motivo. A proposta volta a ficar disponível. O vínculo antigo fica no histórico. |
| D13 | Aprovador do LOG | A empresa que monta a logística não entra no processo. Sem campo nem rótulo. |
| D14 | Código de inspeção | O código é **NQT** (não NAT). |
| D15 | Fim da inspeção | Finaliza quando o pedido tem o DOC BIM em PDF, na dispensa e no in loco. |
| D16 | Código LOG | Formato `LOG000`. É gerado no portal ao escolher a data de entrega. Data disponível fica reservada. Com a documentação ok, vira aprovada. Sem data disponível, escolhe-se a mais próxima. |
| D17 | Carga | Pode-se montar uma carga com vários LOGs de vários estados no mesmo caminhão, porque a entrega é por conta da Industel. |
| D18 | Carga: dados e tela | A pessoa escolhe os LOGs da carga. A carga guarda a data de saída e mostra os LOGs e as propostas de cada um, com a logística completa. As cargas ficam numa aba "Cargas" dentro da página Logística. |

Registro de duas visões: nenhuma divergência até agora.

## 5. Fluxos

### 5.1 Inspeção (NQT), por PD principal

1. Aguardando cadastro do PD no portal de cadastro (só se o PD não está cadastrado).
2. Inspeção solicitada no portal.
3. NQT gerado (a pessoa registra o código).
4. Decisão da Equatorial: Dispensada ou Inspeção in loco (um engenheiro da Equatorial vem à fábrica fazer a inspeção pessoalmente).
5. Dispensada: documentação anexada (PIT), depois a Equatorial gera o DOC.
6. In loco: visita agendada (data), depois Aprovada ou Reprovada. Aprovada: a Equatorial gera o DOC.
7. Reprovada: motivo registrado e nova tentativa reinicia no passo 2. O histórico guarda a anterior.
8. **A inspeção só está finalizada quando o pedido tem o DOC BIM em PDF (link registrado).** Vale para os dois caminhos, dispensa e in loco. Sem o DOC, a inspeção continua aberta e o pedido não segue para a Logística.

**Decisão 2026-10-21 (substitui a entrada nos passos 1, 2 e 7 acima, que ficam como histórico):** toda inspeção nova nasce na etapa inicial `pendente` ("Solicitação pendente"): ninguém pediu no portal ainda. A pergunta "PD já cadastrado no portal?" sai da criação e passa para a ação de sair de `pendente` (`POST /inspections/{id}/request`, `pd_registered`): sim vai para `solicitada` ("Inspeção solicitada no portal"); não vai para `cadastro` ("Aguardando cadastro do PD no portal"), que segue o fluxo antigo (`register-pd` para `solicitada`). A reprovação in loco (passo 7) agora volta para `pendente` em vez de `solicitada` (decisão do orquestrador). Inspeções já existentes não mudam de etapa. Migration `20261021_0042` (TRANSITIONAL) amplia o CHECK de `stage`.

### 5.2 Logística (LOG)

1. Pré-requisito: os PDs/propostas escolhidos têm a inspeção finalizada (DOC BIM em PDF).
2. No portal, a pessoa escolhe a data de entrega. Se a data está disponível, o portal a reserva e gera o código LOG (formato `LOG000`, ex.: LOG123). Se não está, a pessoa escolhe a data disponível mais próxima.
3. Aqui ela registra: código LOG, estado da Equatorial, data pedida, data reservada, dia de carregamento no pátio da Industel e dia de entrega no CD da Equatorial (a entrega no CD é a mesma data reservada; ver Datas). Vincula as propostas/pedidos ao LOG.
4. Etapas: Data reservada → Documentação enviada (NF, XML, BIM como links) → Aprovada para entrega (quando a documentação está toda ok).
5. Depois do LOG criado, é possível incluir novos pedidos. Cada inclusão tem resultado Aprovada ou Reprovada.
6. Remover proposta do LOG exige motivo (D12).

### 5.3 Carga (montagem do caminhão)

A entrega é por conta da Industel. Uma carga reúne vários LOGs, inclusive de estados diferentes, no mesmo caminhão.

- A pessoa escolhe quais LOGs entram na carga.
- A carga tem data de saída (e identificador).
- Na tela da carga aparecem os LOGs e, dentro de cada LOG, as propostas, com a logística completa (estado, datas de carregamento e entrega, etapa do LOG).
- As cargas montadas ficam numa **aba "Cargas" dentro da página Logística**.
- Só entram em carga LOGs com data aprovada para entrega (decisão do Claude, ajustável).

## 6. Dados (esboço, o construtor refina)

- `logistics_load` (carga): identificador, data de saída, etapa.
- `logistics_load_item`: vínculo carga e LOG (um LOG em uma só carga, decisão do Claude).
- `inspection` (por PD): pedido, nqt_code, link do DOC BIM em PDF (a inspeção só finaliza com ele), etapa, tentativa, tipo de decisão, data da visita, motivo de reprovação, links de documentos, etapa_desde.
- `inspection_event`: histórico (quem, quando, etapa, motivo).
- `logistics_log`: código LOG único, estado EQT, data pedida, data obtida, carregamento, entrega CD, etapa, etapa_desde.
- `logistics_log_item`: vínculo proposta/pedido ao LOG, resultado da inclusão, motivo de remoção, removido_em.
- `logistics_event`: histórico.
- Dias na etapa = hoje menos `etapa_desde`, calculado na leitura.

## 7. Segurança e privacidade

- Sem credenciais de portal e sem arquivos fiscais armazenados.
- Permissões novas por área (ver, editar) no módulo `roles`.
- Toda alteração auditada no padrão existente.
- Links de documentos são texto livre: validar tamanho e esquema, e nunca abri-los automaticamente.

## 8. Decisões do Claude (a critério do construtor, ajustáveis)

- Nomes de módulos: `inspection` e `logistics` em `api/app/modules/`, seguindo `router.py`, `service.py`, `schemas.py`, `models.py`.
- Migrations Alembic aditivas (`ADDITIVE`) com entrada em `migration_risk_registry.json`.
- Código NQT e código LOG únicos, com erro claro em duplicidade.
- Sem importação de andamento atual: começa vazio.
- Telas seguem a skill `qt-industrial-ui` e o padrão de "Detalhes da proposta".

## Datas (decisões de 2026-11-08)

Valem para a Inspeção e a Logística. Não mudam D1 a D18.

1. Nenhuma regra de data bloqueia. Só avisa, com "Marcar mesmo assim" ou "Escolher outra data". Único impedimento: data inexistente (ex.: 31/02) ou campo obrigatório vazio.
2. D7 mantida: sem alerta de prazo.
3. Dia útil: segunda a sexta, menos feriados nacionais, de GO e de Goiânia. Carnaval e Corpus Christi não param a fábrica. Sábado não é dia útil.
4. Sem folga mínima: só conflito no mesmo dia gera aviso.
5. Data reservada do LOG = entrega no CD. Saída da carga = carregamento. A tela preenche igual; a API avisa se divergir, sem bloquear.
6. Nenhum campo extra além de observação livre.
7. Data gravada pode ser corrigida depois, com histórico "de X para Y" e motivo. Histórico nunca é apagado.
8. "Hoje" é calculado no fuso America/Sao_Paulo.

## 9. Premissas e riscos

- Premissa: o setor registra no sistema logo depois de agir no portal. Se atrasar, os dias na etapa ficam errados.
- Risco: dado digitado à mão, sem conferência contra o portal.
- Risco: um PD com vários CPs precisa de regra de elegibilidade clara para entrar em LOG (todos com NQT resolvido do seu PD).
- Aberto: qual dos links é qual portal (ver seção 11).

## 10. Critérios de aceite

- Registrar o ciclo completo de uma inspeção, incluindo dispensa, in loco, aprovação e reprovação com nova tentativa.
- Tentar vincular a um LOG uma proposta com NQT não resolvido é recusado com mensagem clara.
- Criar um LOG com 3 propostas, adicionar uma 4ª depois e remover uma com motivo, com histórico correto.
- A lista mostra dias na etapa corretos.
- Sem permissão, a área não aparece e a API recusa.
- Código NQT ou LOG duplicado é recusado.
- Suíte `python -m pytest tests api/tests -q` passa.

## 11. Perguntas em aberto

| Pergunta | Dono |
|----------|------|
| Qual link é qual portal: `equatorialenergia.service-now.com/login.do`, `.../equatorial` e o Microsoft Forms (Inspeção, Cadastro de PD ou PAM)? | Henrique |
| Carga precisa de placa, motorista ou ordem de entrega? (por ora não; acrescenta depois) | Henrique |

## 12. Ordem de implementação

1. API e Desktop de Inspeção (independente).
2. API e Desktop de Logística (depende da elegibilidade do NQT).
3. Carga (aba "Cargas" na página Logística; agrupa LOGs; depende de Logística).
4. Seção nos detalhes da proposta, ligando tudo.
