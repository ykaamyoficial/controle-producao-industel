"""Simulador de remanejamento parcial (prototipos/remanejamento_parciais): so o modelo, sem tela."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototipos" / "remanejamento_parciais"))

import modelo as m  # noqa: E402


def ids(estado):
    return {p.numero: p.id for p in estado.propostas.values()}


def linha(estado, numero_proposta, numero_item):
    pid = ids(estado)[numero_proposta]
    return next(l for l in estado.linhas_de(pid) if l.numero == numero_item)


def lugares(estado):
    """{numero da proposta: aparece_em} so das propostas ativas."""
    return {p.numero: estado.aparece_em(p.id) for p in estado.ativas()}


class CenarioUmTests(unittest.TestCase):
    """Itens inteiros: a CP 05493 cede o item 3 para a CP 05640 (o caso da base de teste)."""

    def remanejar(self, modo):
        estado = m.montar_cenario("1", modo)
        estado.remanejar(linha(estado, "CP 05640", "3").id, linha(estado, "CP 05493", "3").id, 1)
        return estado

    def test_today_each_proposal_stays_one_and_shows_in_two_lists(self):
        estado = self.remanejar(m.HOJE)
        self.assertEqual(estado.conferir(), [])
        self.assertEqual(sorted(p.numero for p in estado.ativas()), ["CP 05493", "CP 05640"])
        self.assertEqual(lugares(estado), {"CP 05493": ["Produção", "Expedição"], "CP 05640": ["Produção", "Expedição"]})
        origem = linha(estado, "CP 05493", "3")
        self.assertEqual((origem.pecas[m.PRONTA], origem.pecas[m.A_FABRICAR]), (0, 1))

    def test_proposed_splits_the_source_into_p1_and_p2_and_the_mother_becomes_a_reference(self):
        estado = self.remanejar(m.PROPOSTO)
        self.assertEqual(estado.conferir(), [])
        numeros = ids(estado)
        self.assertTrue(estado.eh_mae_referencia(numeros["CP 05493"]))
        self.assertEqual(lugares(estado)["CP 05493-1"], ["Expedição"])
        self.assertEqual(lugares(estado)["CP 05493-2"], ["Produção"])
        self.assertEqual([l.numero for l in estado.linhas_de(numeros["CP 05493-1"])], ["1", "2", "4"])
        self.assertEqual([l.numero for l in estado.linhas_de(numeros["CP 05493-2"])], ["3"])

    def test_proposed_destination_gets_a_child_for_what_arrived_ready_and_keeps_the_rest(self):
        estado = self.remanejar(m.PROPOSTO)
        numeros = ids(estado)
        self.assertFalse(estado.eh_mae_referencia(numeros["CP 05640"]))
        self.assertEqual(lugares(estado)["CP 05640"], ["Produção"])
        self.assertEqual(lugares(estado)["CP 05640-1"], ["Expedição"])
        self.assertEqual([l.numero for l in estado.linhas_de(numeros["CP 05640-1"])], ["3"])
        self.assertEqual([l.numero for l in estado.linhas_de(numeros["CP 05640"])], ["1", "2", "4"])

    def test_no_proposal_is_in_two_places_in_the_proposed_mode(self):
        estado = self.remanejar(m.PROPOSTO)
        for proposta in estado.ativas():
            self.assertLessEqual(len(estado.aparece_em(proposta.id)), 1, proposta.numero)

    def test_proposed_marker_follows_the_family_until_it_is_whole_again(self):
        estado = self.remanejar(m.PROPOSTO)
        numeros = ids(estado)
        for numero in ("CP 05493", "CP 05493-1", "CP 05493-2", "CP 05640", "CP 05640-1"):
            self.assertTrue(estado.tem_marca(numeros[numero]), numero)
        self.assertTrue(any("RM-001" in texto and "cedeu" in texto for texto in estado.detalhes_marca(numeros["CP 05493-1"])))

    def test_full_life_of_the_replacement_merges_the_parts_and_reborn_the_mothers(self):
        estado = self.remanejar(m.PROPOSTO)
        numeros = ids(estado)
        # A CP 05493-2 (item 3) e fabricada, vai para a galvanizacao, volta: junta com a -1 e a mae renasce.
        estado.concluir_producao(numeros["CP 05493-2"])
        self.assertEqual(lugares(estado)["CP 05493-2"], ["Galvanização"])
        carga = estado.enviar_carga([numeros["CP 05493-2"]])
        estado.retornar_carga(carga)
        self.assertEqual(estado.conferir(), [])
        self.assertEqual(sorted(p.numero for p in estado.ativas() if p.numero.startswith("CP 05493")), ["CP 05493"])
        self.assertEqual(estado.aparece_em(numeros["CP 05493"]), ["Expedição"])
        self.assertEqual([l.numero for l in estado.linhas_de(numeros["CP 05493"])], ["1", "2", "3", "4"])
        self.assertFalse(estado.tem_marca(numeros["CP 05493"]))
        # A CP 05640 conclui a producao dos 3 itens que restavam: tambem se junta e renasce.
        estado.concluir_producao(numeros["CP 05640"])
        carga = estado.enviar_carga([p.id for p in estado.ativas() if estado.soma(p.id, m.AGUARDANDO)])
        estado.retornar_carga(carga)
        self.assertEqual(estado.conferir(), [])
        self.assertEqual(sorted(p.numero for p in estado.ativas() if p.numero.startswith("CP 05640")), ["CP 05640"])
        self.assertEqual([l.numero for l in estado.linhas_de(numeros["CP 05640"])], ["1", "2", "3", "4"])
        self.assertEqual(estado.soma(numeros["CP 05640"], m.PRONTA), 5)

    def test_partial_delivery_of_one_part_keeps_the_family_until_everything_is_delivered(self):
        estado = self.remanejar(m.PROPOSTO)
        numeros = ids(estado)
        estado.entregar(numeros["CP 05493-1"])
        self.assertTrue(estado.eh_mae_referencia(numeros["CP 05493"]))
        self.assertEqual(estado.conferir(), [])


class VarianteDestinoTests(unittest.TestCase):
    def test_destination_can_also_be_split_one_part_per_place(self):
        estado = m.montar_cenario("2", m.PROPOSTO)
        estado.destino_por_lugar = True
        estado.remanejar(linha(estado, "CP 05710", "1").id, linha(estado, "CP 05700", "1").id, 5)
        self.assertEqual(estado.conferir(), [])
        numeros = ids(estado)
        self.assertTrue(estado.eh_mae_referencia(numeros["CP 05710"]))
        for filha in estado.filhas(numeros["CP 05710"]):
            self.assertLessEqual(len(estado.aparece_em(filha.id)), 1, filha.numero)

    def test_by_default_the_destination_keeps_the_rest_in_the_proposal(self):
        estado = m.montar_cenario("2", m.PROPOSTO)
        estado.remanejar(linha(estado, "CP 05710", "1").id, linha(estado, "CP 05700", "1").id, 5)
        numeros = ids(estado)
        self.assertFalse(estado.eh_mae_referencia(numeros["CP 05710"]))
        self.assertEqual(estado.aparece_em(numeros["CP 05710"]), ["Produção", "Galvanização"])


class CenarioDoisTests(unittest.TestCase):
    """Parte da quantidade e pecas em lugares diferentes."""

    def setUp(self):
        self.estado = m.montar_cenario("2", m.PROPOSTO)
        self.numeros = ids(self.estado)

    def test_taking_the_most_advanced_pieces_first(self):
        destino = linha(self.estado, "CP 05710", "1")
        self.assertEqual(self.estado.plano_tomada(destino, 5), [(m.EM_CARGA, 1, 4), (m.AGUARDANDO, 0, 1)])

    def test_part_of_the_quantity_splits_the_item_in_lots_and_the_source_in_one_part_per_place(self):
        self.estado.remanejar(linha(self.estado, "CP 05710", "1").id, linha(self.estado, "CP 05700", "1").id, 5)
        self.assertEqual(self.estado.conferir(), [])
        self.assertTrue(self.estado.eh_mae_referencia(self.numeros["CP 05700"]))
        partes = {p.numero: self.estado.aparece_em(p.id) for p in self.estado.filhas(self.numeros["CP 05700"])}
        self.assertEqual(partes, {"CP 05700-1": ["Expedição"], "CP 05700-2": ["Galvanização"], "CP 05700-3": ["Galvanização"]})
        pronta = self.estado.linhas_de(ids(self.estado)["CP 05700-1"])
        self.assertEqual([(l.numero, l.pecas[m.PRONTA]) for l in pronta], [("1", 5), ("2", 4)])
        self.assertEqual(sum(self.estado.pedido[(self.numeros["CP 05700"], numero)] for numero in ("1", "2")), 14)

    def test_the_part_in_the_load_joins_the_ready_part_when_the_load_comes_back(self):
        self.estado.remanejar(linha(self.estado, "CP 05710", "1").id, linha(self.estado, "CP 05700", "1").id, 5)
        self.estado.retornar_carga(1)
        self.assertEqual(self.estado.conferir(), [])
        self.assertEqual(sorted(p.numero for p in self.estado.ativas() if p.numero.startswith("CP 05700")), ["CP 05700", "CP 05700-1", "CP 05700-3"])
        pronta = self.estado.linhas_de(ids(self.estado)["CP 05700-1"])
        self.assertEqual([(l.numero, l.pecas[m.PRONTA]) for l in pronta], [("1", 9), ("2", 4)])

    def test_two_sources_for_the_same_destination_in_sequence_keep_the_count(self):
        self.estado.remanejar(linha(self.estado, "CP 05710", "1").id, linha(self.estado, "CP 05700", "1").id, 4)
        self.estado.remanejar(linha(self.estado, "CP 05710", "1").id, linha(self.estado, "CP 05720", "1").id, 3)
        self.assertEqual(self.estado.conferir(), [])
        destino = self.numeros["CP 05710"]
        recebidas = sum(l.pecas[m.PRONTA] for p in self.estado.familia(destino) if p.ativa for l in self.estado.linhas_de(p.id) if l.numero == "1")
        self.assertEqual(recebidas, 7)

    def test_today_the_mixed_item_keeps_ready_and_incoming_pieces_in_the_same_line(self):
        estado = m.montar_cenario("2", m.HOJE)
        estado.remanejar(linha(estado, "CP 05710", "1").id, linha(estado, "CP 05700", "1").id, 5)
        self.assertEqual(estado.conferir(), [])
        origem = linha(estado, "CP 05700", "1")
        self.assertEqual((origem.pecas[m.PRONTA], origem.pecas[m.EM_CARGA], origem.pecas[m.AGUARDANDO]), (5, 4, 1))
        self.assertEqual(estado.aparece_em(ids(estado)["CP 05700"]), ["Galvanização", "Expedição"])


class CenarioTresTests(unittest.TestCase):
    def test_giving_everything_in_one_batch_does_not_split_the_source(self):
        estado = m.montar_cenario("3", m.PROPOSTO)
        numeros = ids(estado)
        estado.remanejar_lote([
            (linha(estado, "CP 05810", "1").id, linha(estado, "CP 05800", "1").id, 3),
            (linha(estado, "CP 05810", "2").id, linha(estado, "CP 05800", "2").id, 2),
        ])
        self.assertEqual(estado.conferir(), [])
        self.assertEqual([p.numero for p in estado.ativas()], ["CP 05800", "CP 05810"])
        self.assertEqual(estado.aparece_em(numeros["CP 05800"]), ["Produção"])
        self.assertEqual(estado.aparece_em(numeros["CP 05810"]), ["Expedição"])
        # O destino foi atendido por completo: a proposta inteira vai para a Expedicao, sem filhas.
        self.assertFalse(estado.tem_filhas(numeros["CP 05810"]))

    def test_an_invalid_line_in_the_batch_changes_nothing(self):
        estado = m.montar_cenario("3", m.PROPOSTO)
        antes = {l.id: dict(l.pecas) for l in estado.linhas.values()}
        with self.assertRaises(m.ErroSimulacao):
            estado.remanejar_lote([
                (linha(estado, "CP 05810", "1").id, linha(estado, "CP 05800", "1").id, 3),
                (linha(estado, "CP 05810", "2").id, linha(estado, "CP 05800", "2").id, 9),
            ])
        self.assertEqual({l.id: dict(l.pecas) for l in estado.linhas.values()}, antes)
        self.assertEqual(estado.remanejamentos, [])
        self.assertEqual(estado.conferir(), [])


class RegrasTests(unittest.TestCase):
    def test_validations(self):
        estado = m.montar_cenario("1", m.PROPOSTO)
        origem, destino = linha(estado, "CP 05493", "3"), linha(estado, "CP 05640", "3")
        with self.assertRaises(m.ErroSimulacao):
            estado.remanejar(destino.id, origem.id, 2)  # origem so tem 1
        with self.assertRaises(m.ErroSimulacao):
            estado.remanejar(destino.id, linha(estado, "CP 05493", "1").id, 1)  # codigos diferentes
        with self.assertRaises(m.ErroSimulacao):
            estado.remanejar(origem.id, origem.id, 1)  # mesma proposta
        with self.assertRaises(m.ErroSimulacao):
            estado.remanejar(destino.id, origem.id, 0)

    def test_candidates_are_ready_lines_of_the_same_product_from_other_families(self):
        estado = m.montar_cenario("2", m.PROPOSTO)
        candidatas = estado.candidatas_origem(linha(estado, "CP 05710", "1").id)
        self.assertEqual(sorted((estado.propostas[l.proposta_id].numero, l.pecas[m.PRONTA]) for l in candidatas), [("CP 05700", 10), ("CP 05720", 6)])

    def test_the_free_scenario_survives_a_long_sequence_of_actions_in_both_modes(self):
        for modo in (m.HOJE, m.PROPOSTO):
            with self.subTest(modo=modo):
                estado = m.montar_cenario("4", modo)
                numeros = ids(estado)
                estado.remanejar(linha(estado, "CP 05920", "1").id, linha(estado, "CP 05900", "1").id, 6)
                estado.remanejar(linha(estado, "CP 05930", "1").id, linha(estado, "CP 05910", "1").id, 3)
                for proposta in list(estado.ativas()):
                    if estado.soma(proposta.id, m.A_FABRICAR):
                        estado.concluir_producao(proposta.id)
                for _ in range(3):
                    pendentes = [p.id for p in estado.ativas() if estado.soma(p.id, m.AGUARDANDO)]
                    if pendentes:
                        estado.enviar_carga(pendentes)
                    for carga in list(estado.cargas_em_transito()):
                        estado.retornar_carga(carga)
                self.assertEqual(estado.conferir(), [], modo)
                self.assertEqual(sum(estado.soma(p.id, m.A_FABRICAR) + estado.soma(p.id, m.AGUARDANDO) + estado.soma(p.id, m.EM_CARGA) for p in estado.ativas()), 0)
                del numeros


class JanelaTests(unittest.TestCase):
    """Fumaca da tela do simulador (sem abrir dialogos): so confere que as listas refletem o modelo."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])
        import simulador

        cls.simulador = simulador

    def janela(self, modo):
        janela = self.simulador.Janela("1", modo)
        estado = janela.estado
        numeros = {p.numero: p.id for p in estado.propostas.values()}
        destino = next(l for l in estado.linhas_de(numeros["CP 05640"]) if l.numero == "3").id
        origem = next(l for l in estado.linhas_de(numeros["CP 05493"]) if l.numero == "3").id
        janela._executar("Remanejar", lambda: janela.estado.remanejar_lote([(destino, origem, 1)]))
        return janela

    def propostas_da_tabela(self, tabela):
        return [tabela.item(i, 0).text() for i in range(tabela.rowCount())]

    def test_lists_follow_the_proposed_mode(self):
        janela = self.janela(m.PROPOSTO)
        self.assertEqual(self.propostas_da_tabela(janela.t_geral), ["CP 05493", "CP 05640"])
        self.assertEqual(self.propostas_da_tabela(janela.t_producao), ["CP 05493-2", "CP 05640"])
        self.assertEqual(self.propostas_da_tabela(janela.t_exp), ["CP 05493-1", "CP 05640-1"])
        self.assertIn("Conferência", janela.conferencia.text())
        self.assertEqual(janela.conferencia.objectName(), "Ok")
        marcada = janela.t_geral.item(0, 0)
        self.assertTrue(marcada.data(self.simulador.ROLE_MARCA))

    def test_today_a_proposal_shows_in_two_lists(self):
        janela = self.janela(m.HOJE)
        self.assertEqual(self.propostas_da_tabela(janela.t_producao), ["CP 05493", "CP 05640"])
        self.assertEqual(self.propostas_da_tabela(janela.t_exp), ["CP 05493", "CP 05640"])

    def test_undo_brings_the_scenario_back(self):
        janela = self.janela(m.PROPOSTO)
        janela.desfazer()
        self.assertEqual(self.propostas_da_tabela(janela.t_exp), ["CP 05493"])
        self.assertEqual(janela.estado.remanejamentos, [])

    def test_clicking_the_marker_asks_for_the_proposal_details(self):
        janela = self.janela(m.PROPOSTO)
        pedidos = []
        janela.t_geral.marca_clicada.connect(pedidos.append)
        indice = janela.t_geral.model().index(0, 0)
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        janela.resize(1440, 860)
        janela.show()
        self.app.processEvents()
        rect = janela.t_geral.visualRect(indice)
        icone, _codigo = self.simulador.geometria_marca(self.simulador.QRectF(rect), "CP 05493", self.simulador.fonte(13, 600))
        # O dialogo e trocado no modulo da tela: sem isso o clique abre o dialogo de verdade e trava o teste.
        with patch.object(self.simulador, "DialogoMarca") as dialogo:
            QTest.mouseClick(janela.t_geral.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(icone.center().x()), int(icone.center().y())))
        self.assertEqual(len(pedidos), 1)
        dialogo.assert_called_once()
        dialogo.return_value.exec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
