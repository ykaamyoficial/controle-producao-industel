# Integração com o Almox+ (estoque)

O Almox+ é o sistema de controle de estoque industrial. Ele precisa saber **quais propostas estão
liberadas para a produção** para somar, por material, a demanda de matéria-prima. A produção é
a fonte dessa informação; esta integração só **informa** (nunca recebe ordens do Almox+).

Duas vias, as duas assinadas com o mesmo segredo:

1. **Webhook (produção → Almox+)**: a cada mudança de estado de uma proposta.
2. **Conciliação (Almox+ → produção)**: o Almox+ consulta o estado quando quiser (rotina horária e
   ao abrir a tela). Corrige qualquer webhook que se perdeu — por isso o webhook não precisa de fila.

Desligada por padrão: sem `ALMOX_INTEGRATION_SECRET` a conciliação responde 503; sem
`ALMOX_WEBHOOK_URL` nenhum webhook é enviado.

## Estados

| Estado | Quando | Efeito no Almox+ |
|---|---|---|
| `LIBERADA` | a proposta saiu de `AGUARDANDO_LIBERACAO` e a produção ainda não terminou | soma na demanda |
| `CONCLUIDA` | `production_status = FINALIZADO` ou `is_completed` | sai da demanda |
| `RETIRADA` | proposta cancelada (`is_cancelled` ou `CANCELADA`) | sai da demanda |
| *(nenhum)* | aguardando liberação, ou proposta **parcial** | não conta |

Propostas parciais (`is_partial`) ficam de fora: o pai já está na demanda. A regra única está em
`api/app/modules/almox_integration/state.py`. "Concluída" é o **fim da produção**, não a entrega:
é nesse ponto que o material deixa de ser demanda.

## Webhook

`POST ${ALMOX_WEBHOOK_URL}` (hoje: `/api/v1/integracoes/producao/webhook` do Almox+).

```json
{
  "event_id": "9f0c...",
  "tipo": "LIBERADA",
  "numero_proposta_nomus": "CP 05637",
  "ocorrido_em": "2026-10-16T12:00:00+00:00"
}
```

- `tipo`: `LIBERADA`, `RETIRADA` ou `CONCLUIDA`.
- `event_id`: único por evento e **o mesmo em todas as tentativas** de envio; o Almox+ ignora repetição.
- `ocorrido_em`: horário (UTC) em que a transição foi detectada; o Almox+ usa a ordem por esse
  horário, não a de chegada.
- Cabeçalhos: `X-Timestamp` (segundos Unix) e `X-Signature` (`sha256=<hex>`).
- Até 3 tentativas (1 s, 2 s de espera). Falha final só vai para o log: o Almox+ se corrige na conciliação.
- Só é enviado o que **mudou de estado** na transação (edição sem mudança e rollback não enviam).

## Conciliação

`GET /api/v1/integrations/almox/proposals` com **um** dos filtros:

- `estado=LIBERADA|RETIRADA|CONCLUIDA`: propostas nesse estado (até 5.000, mais recentes primeiro);
- `numero=CP 05637` (repetível, até 200): estado de cada número — `DESCONHECIDA` se a produção não
  tem a proposta, `NAO_LIBERADA` se ainda não foi liberada.

```json
{"gerado_em": "...", "items": [{"numero_proposta_nomus": "CP 05637", "estado": "LIBERADA", "atualizado_em": "..."}]}
```

Sem permissão de usuário: quem chama é o outro sistema, autenticado pela assinatura. O caminho
`/api/v1/integrations/almox` é isento da checagem de versão do cliente Desktop.

## Assinatura

`X-Signature = "sha256=" + HMAC_SHA256(segredo, X-Timestamp + "." + corpo)`.

- Webhook: `corpo` = bytes exatos do JSON enviado.
- Conciliação: `corpo` = **query string crua** (para a assinatura valer só para aquele filtro).
- Mensagem fora de ±300 s do relógio do receptor é recusada, mesmo com assinatura válida.
- Comparação em tempo constante. Segredo só no `.env` (`ALMOX_INTEGRATION_SECRET`), mínimo
  recomendado de 32 caracteres; o **mesmo valor** nos dois sistemas.

## Como funciona o gancho

`tracker.py` escuta `after_flush`/`after_commit`/`after_rollback` da `Session`. No flush compara o
estado da proposta antes e depois (pelo histórico do ORM); no commit envia, em segundo plano, só as
transições líquidas. Nenhum arquivo de `proposals/` foi alterado e **não há migration**.

## Desfazer a liberação

Desfazer a última ação de uma proposta (`POST /proposals/{id}/undo`) pode voltar a proposta de `LIBERADA` para
`AGUARDANDO_LIBERACAO`. Isso **não envia webhook**: o gancho só envia transição *para* `LIBERADA`, `RETIRADA` ou
`CONCLUIDA`, e voltar para "sem estado" nunca gera evento. Então o Almox+ continua somando a proposta na demanda
até a próxima conciliação horária (ou ao abrir a tela). O diálogo de desfazer avisa isso em `side_effects`
(`ALMOX_NOT_NOTIFIED`: "O Almox+ nao e avisado; a conciliacao horaria acerta."). Desfazer o início, a pausa ou a
retomada da produção não muda o estado do Almox+ (continua `LIBERADA`). Nenhum arquivo de `almox_integration/`
foi alterado por esse recurso.

## Limites conhecidos

- Sem fila persistente: um webhook perdido (processo reiniciado entre o commit e o envio) só é
  corrigido pela conciliação do Almox+.
- O horário `ocorrido_em` é o da detecção, não o do evento de negócio original.
- O Almox+ identifica a proposta pelo número Nomus; propostas com numeração diferente da do Nomus
  aparecem lá como "sem proposta importada".

## Ativação

```
ALMOX_INTEGRATION_SECRET=<mesmo segredo do Almox+>
ALMOX_WEBHOOK_URL=https://almox.ykora.com.br/api/v1/integracoes/producao/webhook
```

Reiniciar a API (a imagem Docker precisa conter este código). Testes: `api/tests/test_almox_integration.py`.
