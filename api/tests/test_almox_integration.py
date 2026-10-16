"""Integração com o Almox+ (docs/architecture/ALMOX_INTEGRATION.md): estado da proposta, assinatura,
detecção de transições no commit, envio do webhook e endpoints de conciliação. Sem banco."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import set_committed_value

from api.app.modules.almox_integration import router as almox_router
from api.app.modules.almox_integration.dispatcher import AlmoxDispatcher
from api.app.modules.almox_integration.signing import (
    MAX_SKEW_SECONDS,
    sign,
    verify,
)
from api.app.modules.almox_integration.state import almox_state
from api.app.modules.almox_integration.tracker import (
    PendingTransitions,
    coletar_transicoes,
)
from api.app.modules.proposals.models import Proposal

SECRET = "segredo-de-teste-com-mais-de-32-caracteres"


def _proposta(**campos):
    valores = dict(
        proposal_number="CP 05637",
        is_partial=False,
        is_cancelled=False,
        is_completed=False,
        current_area="PRODUCAO",
        current_status="LIBERADO_PRODUCAO",
        production_status="NAO_INICIADO",
    )
    valores.update(campos)
    return SimpleNamespace(**valores)


# --- estado da proposta ------------------------------------------------------------------


def test_proposta_aguardando_liberacao_nao_tem_estado():
    proposta = _proposta(
        current_area="CONTROLE_GERAL", current_status="AGUARDANDO_LIBERACAO", production_status=None
    )
    assert almox_state(proposta) is None


def test_proposta_liberada_para_producao_esta_liberada():
    assert almox_state(_proposta()) == "LIBERADA"
    assert almox_state(_proposta(production_status="INICIADO")) == "LIBERADA"
    assert almox_state(_proposta(production_status="FINALIZADO_PARCIAL")) == "LIBERADA"


def test_proposta_cancelada_e_retirada_mesmo_se_tinha_producao():
    assert almox_state(_proposta(is_cancelled=True, current_status="CANCELADA")) == "RETIRADA"
    assert almox_state(_proposta(current_status="CANCELADA")) == "RETIRADA"


def test_producao_finalizada_ou_proposta_concluida_e_concluida():
    assert almox_state(_proposta(production_status="FINALIZADO")) == "CONCLUIDA"
    assert almox_state(_proposta(is_completed=True, current_status="ENTREGUE")) == "CONCLUIDA"


def test_proposta_parcial_fica_de_fora_porque_o_pai_ja_conta():
    assert almox_state(_proposta(is_partial=True)) is None


# --- assinatura --------------------------------------------------------------------------


def test_assinatura_valida_confere_e_adulteracao_nao():
    agora = int(time.time())
    corpo = b'{"a":1}'
    assinatura = sign(SECRET, agora, corpo)

    assert assinatura.startswith("sha256=")
    assert verify(SECRET, str(agora), assinatura, corpo, agora=agora)
    assert not verify(SECRET, str(agora), assinatura, b'{"a":2}', agora=agora)
    assert not verify("outro-segredo-com-mais-de-32-caracteres!!", str(agora), assinatura, corpo, agora=agora)
    assert not verify(SECRET, str(agora + 1), assinatura, corpo, agora=agora)


def test_mensagem_antiga_ou_do_futuro_e_recusada_mesmo_com_assinatura_valida():
    agora = 1_800_000_000
    corpo = b""
    velha = agora - MAX_SKEW_SECONDS - 1
    futura = agora + MAX_SKEW_SECONDS + 1

    assert not verify(SECRET, str(velha), sign(SECRET, velha, corpo), corpo, agora=agora)
    assert not verify(SECRET, str(futura), sign(SECRET, futura, corpo), corpo, agora=agora)
    assert verify(SECRET, str(agora - MAX_SKEW_SECONDS), sign(SECRET, agora - MAX_SKEW_SECONDS, corpo), corpo, agora=agora)


@pytest.mark.parametrize("timestamp", ["", "abc", "1.5"])
def test_timestamp_invalido_e_recusado(timestamp):
    assert not verify(SECRET, timestamp, "sha256=00", b"", agora=1_800_000_000)


def test_assinatura_sem_prefixo_ou_vazia_e_recusada():
    agora = int(time.time())
    assinatura = sign(SECRET, agora, b"x")
    assert not verify(SECRET, str(agora), assinatura.removeprefix("sha256="), b"x", agora=agora)
    assert not verify(SECRET, str(agora), "", b"x", agora=agora)


# --- transições detectadas no flush ------------------------------------------------------


def _sessao(novas=(), sujas=()):
    return SimpleNamespace(new=set(novas), dirty=set(sujas), info={})


def _carregada(**campos) -> Proposal:
    """Proposta como se tivesse sido lida do banco (valores confirmados, sem alteração)."""
    proposta = Proposal()
    base = dict(
        proposal_number="CP 05637",
        is_partial=False,
        is_cancelled=False,
        is_completed=False,
        current_area="CONTROLE_GERAL",
        current_status="AGUARDANDO_LIBERACAO",
        production_status=None,
    )
    base.update(campos)
    for nome, valor in base.items():
        set_committed_value(proposta, nome, valor)
    return proposta


def _liberar(proposta: Proposal) -> None:
    proposta.current_area = "PRODUCAO"
    proposta.current_status = "LIBERADO_PRODUCAO"
    proposta.production_status = "NAO_INICIADO"


def test_liberar_proposta_existente_registra_a_transicao():
    proposta = _carregada()
    _liberar(proposta)
    sessao = _sessao(sujas=[proposta])

    coletar_transicoes(sessao)

    pendentes = PendingTransitions.da_sessao(sessao).transicoes()
    assert [(t.numero, t.estado) for t in pendentes] == [("CP 05637", "LIBERADA")]


def test_proposta_nova_ja_liberada_registra_e_nova_aguardando_nao():
    liberada = Proposal(**{**_dados_novos(), "current_area": "PRODUCAO", "current_status": "LIBERADO_PRODUCAO"})
    aguardando = Proposal(**{**_dados_novos(), "proposal_number": "CP 9"})
    sessao = _sessao(novas=[liberada, aguardando])

    coletar_transicoes(sessao)

    pendentes = PendingTransitions.da_sessao(sessao).transicoes()
    assert [(t.numero, t.estado) for t in pendentes] == [("CP 05637", "LIBERADA")]


def _dados_novos():
    return dict(
        proposal_number="CP 05637",
        customer_name="Cliente",
        is_partial=False,
        is_cancelled=False,
        is_completed=False,
        current_area="CONTROLE_GERAL",
        current_status="AGUARDANDO_LIBERACAO",
        production_status=None,
    )


def test_edicao_que_nao_muda_o_estado_nao_registra():
    proposta = _carregada(
        current_area="PRODUCAO", current_status="LIBERADO_PRODUCAO", production_status="INICIADO"
    )
    proposta.notes = "observação nova"
    proposta.production_status = "PARADO"
    sessao = _sessao(sujas=[proposta])

    coletar_transicoes(sessao)

    assert PendingTransitions.da_sessao(sessao).transicoes() == []


def test_cancelar_e_concluir_registram_retirada_e_concluida():
    cancelada = _carregada(
        proposal_number="CP 1", current_area="PRODUCAO", current_status="LIBERADO_PRODUCAO"
    )
    cancelada.is_cancelled = True
    cancelada.current_status = "CANCELADA"
    concluida = _carregada(
        proposal_number="CP 2", current_area="PRODUCAO", current_status="LIBERADO_PRODUCAO"
    )
    concluida.production_status = "FINALIZADO"
    sessao = _sessao(sujas=[cancelada, concluida])

    coletar_transicoes(sessao)

    pendentes = PendingTransitions.da_sessao(sessao).transicoes()
    assert sorted((t.numero, t.estado) for t in pendentes) == [
        ("CP 1", "RETIRADA"),
        ("CP 2", "CONCLUIDA"),
    ]


def test_varios_flushes_na_mesma_transacao_ficam_com_o_ultimo_estado():
    proposta = _carregada()
    _liberar(proposta)
    sessao = _sessao(sujas=[proposta])
    coletar_transicoes(sessao)
    # Depois do primeiro flush o ORM confirma os valores; o segundo flush parte deles.
    for nome in ("current_area", "current_status", "production_status"):
        set_committed_value(proposta, nome, getattr(proposta, nome))
    proposta.production_status = "FINALIZADO"

    coletar_transicoes(sessao)

    pendentes = PendingTransitions.da_sessao(sessao).transicoes()
    assert [(t.numero, t.estado) for t in pendentes] == [("CP 05637", "CONCLUIDA")]


def test_proposta_que_volta_ao_estado_original_na_mesma_transacao_nao_registra():
    proposta = _carregada(
        current_area="PRODUCAO", current_status="LIBERADO_PRODUCAO", production_status="NAO_INICIADO"
    )
    sessao = _sessao(sujas=[proposta])
    proposta.is_cancelled = True
    coletar_transicoes(sessao)
    for nome in ("is_cancelled",):
        set_committed_value(proposta, nome, getattr(proposta, nome))
    proposta.is_cancelled = False
    coletar_transicoes(sessao)

    assert PendingTransitions.da_sessao(sessao).transicoes() == []


# --- envio do webhook --------------------------------------------------------------------


class _Servidor:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.recebidos: list[dict] = []
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                tamanho = int(self.headers.get("Content-Length", 0))
                corpo = self.rfile.read(tamanho)
                servidor.recebidos.append(
                    {"corpo": corpo, "headers": dict(self.headers), "caminho": self.path}
                )
                codigo = servidor.respostas.pop(0) if servidor.respostas else 200
                self.send_response(codigo)
                self.end_headers()

            def log_message(self, *args):
                return

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}/webhook"
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.http.shutdown()
        self.http.server_close()


@pytest.mark.asyncio
async def test_webhook_envia_evento_assinado_com_os_campos_do_contrato():
    with _Servidor([200]) as servidor:
        dispatcher = AlmoxDispatcher(servidor.url, SECRET, tentativas=1, espera_s=0)

        enviados = await dispatcher.enviar_transicao("CP 05637", "LIBERADA", "2026-10-16T12:00:00+00:00")

    assert enviados is True
    [recebido] = servidor.recebidos
    evento = json.loads(recebido["corpo"])
    assert evento["tipo"] == "LIBERADA"
    assert evento["numero_proposta_nomus"] == "CP 05637"
    assert evento["ocorrido_em"] == "2026-10-16T12:00:00+00:00"
    assert len(evento["event_id"]) >= 16
    headers = {chave.lower(): valor for chave, valor in recebido["headers"].items()}
    assert verify(
        SECRET, headers["x-timestamp"], headers["x-signature"], recebido["corpo"]
    )


@pytest.mark.asyncio
async def test_webhook_repete_com_o_mesmo_event_id_quando_o_almox_falha():
    with _Servidor([500, 503, 200]) as servidor:
        dispatcher = AlmoxDispatcher(servidor.url, SECRET, tentativas=3, espera_s=0)

        enviados = await dispatcher.enviar_transicao("CP 1", "RETIRADA", "2026-10-16T12:00:00+00:00")

    assert enviados is True
    ids = {json.loads(r["corpo"])["event_id"] for r in servidor.recebidos}
    assert len(servidor.recebidos) == 3
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_webhook_desiste_sem_levantar_excecao_quando_o_almox_esta_fora():
    dispatcher = AlmoxDispatcher("http://127.0.0.1:9/webhook", SECRET, tentativas=2, espera_s=0)

    assert await dispatcher.enviar_transicao("CP 1", "LIBERADA", "2026-10-16T12:00:00+00:00") is False


@pytest.mark.asyncio
async def test_sem_url_ou_segredo_o_dispatcher_fica_desligado():
    assert AlmoxDispatcher("", SECRET).ativo is False
    assert AlmoxDispatcher("http://x", "").ativo is False
    assert await AlmoxDispatcher("", "").enviar_transicao("CP 1", "LIBERADA", "t") is False


# --- endpoints de conciliação ------------------------------------------------------------


@pytest.fixture
def cliente(monkeypatch):
    chamadas: list[tuple] = []

    async def listar(session, *, estado, numeros):
        chamadas.append((estado, numeros))
        return [{"numero_proposta_nomus": "CP 05637", "estado": "LIBERADA", "atualizado_em": None}]

    monkeypatch.setattr(almox_router, "listar_estados", listar)
    monkeypatch.setattr(
        almox_router, "_segredo", lambda: SECRET
    )
    from api.app.database.session import get_db_session
    from api.app.main import create_app

    app = create_app()

    async def sessao_falsa():
        yield None

    app.dependency_overrides[get_db_session] = sessao_falsa
    return TestClient(app), chamadas


def _assinar(query: str, segredo: str = SECRET, agora: int | None = None) -> dict[str, str]:
    agora = int(time.time()) if agora is None else agora
    return {"X-Timestamp": str(agora), "X-Signature": sign(segredo, agora, query.encode())}


def test_conciliacao_exige_assinatura_valida_sobre_a_query(cliente):
    http, chamadas = cliente
    query = "estado=LIBERADA"

    sem = http.get(f"/api/v1/integrations/almox/proposals?{query}")
    errada = http.get(
        f"/api/v1/integrations/almox/proposals?{query}",
        headers=_assinar(query, "outro-segredo-com-mais-de-32-caracteres!!"),
    )
    outra_query = http.get(
        "/api/v1/integrations/almox/proposals?estado=CONCLUIDA", headers=_assinar(query)
    )
    velha = http.get(
        f"/api/v1/integrations/almox/proposals?{query}",
        headers=_assinar(query, agora=int(time.time()) - 3600),
    )

    assert [r.status_code for r in (sem, errada, outra_query, velha)] == [401, 401, 401, 401]
    assert chamadas == []


def test_conciliacao_assinada_devolve_os_estados(cliente):
    http, chamadas = cliente
    query = "estado=LIBERADA"

    resposta = http.get(
        f"/api/v1/integrations/almox/proposals?{query}", headers=_assinar(query)
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["items"][0]["numero_proposta_nomus"] == "CP 05637"
    assert chamadas == [("LIBERADA", [])]


def test_conciliacao_aceita_varios_numeros(cliente):
    http, chamadas = cliente
    query = "numero=CP%2005637&numero=CP%2005640"

    resposta = http.get(
        f"/api/v1/integrations/almox/proposals?{query}", headers=_assinar(query)
    )

    assert resposta.status_code == 200
    assert chamadas == [(None, ["CP 05637", "CP 05640"])]


def test_conciliacao_sem_filtro_ou_com_estado_invalido_e_recusada(cliente):
    http, chamadas = cliente

    vazio = http.get("/api/v1/integrations/almox/proposals", headers=_assinar(""))
    invalido = http.get(
        "/api/v1/integrations/almox/proposals?estado=QUALQUER",
        headers=_assinar("estado=QUALQUER"),
    )

    assert vazio.status_code == 422
    assert invalido.status_code == 422
    assert chamadas == []


def test_conciliacao_fica_desligada_sem_segredo_configurado(cliente, monkeypatch):
    http, chamadas = cliente
    monkeypatch.setattr(almox_router, "_segredo", lambda: "")
    query = "estado=LIBERADA"

    resposta = http.get(
        f"/api/v1/integrations/almox/proposals?{query}", headers=_assinar(query)
    )

    assert resposta.status_code == 503
    assert chamadas == []


# --- depois do commit --------------------------------------------------------------------


class _DispatcherFalso:
    def __init__(self, ativo=True):
        self.ativo = ativo
        self.enviados: list[tuple[str, str, str]] = []

    async def enviar_transicao(self, numero, estado, ocorrido_em):
        self.enviados.append((numero, estado, ocorrido_em))
        return True


@pytest.mark.asyncio
async def test_depois_do_commit_envia_so_as_transicoes_e_limpa_a_fila(monkeypatch):
    import asyncio

    from api.app.modules.almox_integration import tracker

    dispatcher = _DispatcherFalso()
    monkeypatch.setattr(tracker, "_dispatcher", dispatcher)
    proposta = _carregada()
    _liberar(proposta)
    sem_mudanca = _carregada(proposal_number="CP 2")
    sem_mudanca.notes = "x"
    sessao = _sessao(sujas=[proposta, sem_mudanca])
    coletar_transicoes(sessao)

    tracker._apos_commit(sessao)
    await asyncio.gather(*list(tracker._tarefas))

    assert [(n, e) for n, e, _ in dispatcher.enviados] == [("CP 05637", "LIBERADA")]
    assert sessao.info == {}


@pytest.mark.asyncio
async def test_dispatcher_desativado_ou_ausente_nao_envia_e_ainda_limpa_a_fila(monkeypatch):
    from api.app.modules.almox_integration import tracker

    proposta = _carregada()
    _liberar(proposta)
    for dispatcher in (_DispatcherFalso(ativo=False), None):
        monkeypatch.setattr(tracker, "_dispatcher", dispatcher)
        sessao = _sessao(sujas=[proposta])
        coletar_transicoes(sessao)

        tracker._apos_commit(sessao)

        assert sessao.info == {}
        assert not tracker._tarefas


def test_commit_sem_loop_em_execucao_nao_levanta_erro(monkeypatch):
    from api.app.modules.almox_integration import tracker

    dispatcher = _DispatcherFalso()
    monkeypatch.setattr(tracker, "_dispatcher", dispatcher)
    proposta = _carregada()
    _liberar(proposta)
    sessao = _sessao(sujas=[proposta])
    coletar_transicoes(sessao)

    tracker._apos_commit(sessao)

    assert dispatcher.enviados == []


def test_instalar_registra_os_tres_listeners_uma_unica_vez(monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from api.app.modules.almox_integration import tracker

    monkeypatch.setattr(tracker, "_instalado", False)
    dispatcher = _DispatcherFalso()
    tracker.instalar(dispatcher)
    tracker.instalar(dispatcher)

    ouvintes = (
        ("after_flush", tracker._apos_flush),
        ("after_commit", tracker._apos_commit),
        ("after_rollback", tracker._apos_rollback),
    )
    try:
        assert all(event.contains(Session, nome, funcao) for nome, funcao in ouvintes)
        assert tracker._dispatcher is dispatcher
    finally:
        for nome, funcao in ouvintes:
            event.remove(Session, nome, funcao)
