from __future__ import annotations

import pytest

from api.app.modules.logistics.state_resolver import resolve_state


@pytest.mark.parametrize(
    "name,expected",
    [
        ("EQUATORIAL GOIAS DIST. DE ENERGIA S/A", "EQT-GO"),
        ("EQUATORIAL GOIAS DIST. DE", "EQT-GO"),
        ("EQUATORIAL PARÁ DISTRIBUIDORA DE ENERGIA S.A.", "EQT-PA"),
        ("equatorial para distribuidora", "EQT-PA"),
        ("EQUATORIAL PIAUI DISTRIBUIDORA DE ENERGIA S.A", "EQT-PI"),
        ("Equatorial Piauí", "EQT-PI"),
        ("EQUATORIAL MARANHAO DISTRIBUIDORA DE ENERGIA S.A", "EQT-MA"),
        ("EQUATORIAL MARANHAO", "EQT-MA"),
        ("EQUATORIAL MARANHAO CAMILA BUENO DE OLIVEIRA", "EQT-MA"),
        ("EQUATORIAL MARANHÃO CONTRATO TRIENAL", "EQT-MA"),
        ("EQUATORIAL ALAGOAS DISTRIBUIDORA DE ENERGIA S.A.", "EQT-AL"),
        ("EQUATORIAL AMAPÁ", "EQT-AP"),
        ("EQUATORIAL ENERGIA - CEEE", "EQT-RS"),
        ("EQUATORIAL GOIÁS JOSÉ RAIMUNDO R. MARQUES", "EQT-GO"),
        ("EQUATORIAL PARANAPANEMA", None),  # PARA so como palavra inteira
        ("EQUATORIAL PARÁ MARANHAO", None),  # ambiguo
        ("EQUATORIAL ENERGIA", None),
        ("CEMIG DISTRIBUICAO MARANHAO", None),
        ("CEEE SEM A PALAVRA", None),
        ("", None),
        (None, None),
    ],
)
def test_resolve_state(name, expected):
    assert resolve_state(name) == expected
