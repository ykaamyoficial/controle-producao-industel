from __future__ import annotations

from decimal import Decimal

from scripts.corrigir_quantidades_nomus import (
    BLOQUEADO, OK, RISCO, SEGURO, SEM_NOMUS, ItemFacts, classify, item_key, may_apply,
)

D = Decimal


def test_item_ja_igual_ao_nomus_esta_ok():
    assert classify(ItemFacts(D("1800")), D("1800")) == (OK, [])


def test_item_fracionado_sem_historico_e_seguro():
    assert classify(ItemFacts(D("1.8000")), D("1800")) == (SEGURO, [])


def test_item_faturado_ou_com_progresso_e_risco():
    assert classify(ItemFacts(D("1.8"), billed_quantity=D("1")), D("1800")) == (RISCO, ["FATURADO"])
    assert classify(ItemFacts(D("2.696"), has_progress=True), D("2696")) == (RISCO, ["COM_PROGRESSO"])
    assert classify(ItemFacts(D("1.8"), D("1"), True), D("1800")) == (RISCO, ["FATURADO", "COM_PROGRESSO"])


def test_quantidade_nova_menor_que_faturada_e_bloqueada():
    assert classify(ItemFacts(D("5"), billed_quantity=D("3")), D("2")) == (BLOQUEADO, ["NOVA_MENOR_QUE_FATURADA"])


def test_item_sem_correspondencia_no_nomus():
    assert classify(ItemFacts(D("1.8")), None)[0] == SEM_NOMUS


def test_so_grava_seguro_ou_risco_com_flag():
    assert may_apply(SEGURO, False) and may_apply(SEGURO, True)
    assert not may_apply(RISCO, False) and may_apply(RISCO, True)
    assert not may_apply(BLOQUEADO, True) and not may_apply(SEM_NOMUS, True) and not may_apply(OK, True)


def test_item_key_ignora_zeros_a_esquerda():
    assert item_key("001") == 1 and item_key(22) == 22 and item_key("") is None
