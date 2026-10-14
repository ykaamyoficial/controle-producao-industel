from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QTableWidget

from app.services.remanagement_flow_state import (
    RemanagementFlowState, RemanagementItemSelection, RemanagementStageTransferView, availability_from_api, review_from_api,
)
from app.ui.components.wizard_stepper import WizardStepper
from app.ui.remanagement_wizard import RemanagementWizardDialog
from app.ui.remanagement_wizard import destination_page as destination_module
from app.ui.remanagement_wizard import dialog as dialog_module
from app.ui.remanagement_wizard import items_page as items_module
from app.ui.remanagement_wizard import review_page as review_module
from app.ui.remanagement_wizard import sources_page as sources_module
from app.ui.remanagement_wizard.destination_page import DestinationPage
from app.ui.remanagement_wizard.items_page import ItemsPage
from app.ui.remanagement_wizard.review_page import ReviewPage, what_happens
from app.ui.remanagement_wizard.sources_page import SourcesPage


def _candidate(source_id, number, item_id, available, client="CLIENTE", site="OBRA", unit="UN"):
    return {
        "source_proposal_id": source_id, "source_proposal_number": number, "source_item_id": item_id, "source_item_version": 1,
        "client": client, "site": site, "available_quantity": str(available), "unit": unit, "operational_status": "SEPARADO",
    }


class FakeWizardService:
    """Servico de mentira com a API inteira do Remanejamento: destinos,
    itens do destino, material pronto, simulacao e confirmacao."""

    def __init__(self):
        self.destinations = [
            {"id": 9, "proposta": "CP05385", "cliente": "MNS Engenharia", "obra_site": "MSNVL002_A",
             "localizacao_atual": "PRODUCAO", "prazo_entrega": "20/10/2026", "api_version": 4},
            {"id": 10, "proposta": "CP05401", "cliente": "Eletro Sul", "obra_site": "Canoas",
             "localizacao_atual": "GALVANIZACAO", "prazo_entrega": "30/10/2026", "api_version": 2},
        ]
        self.items = [
            {"item_id": 101, "product_code": "300.23", "description": "PECA W17", "unit": "UN", "total_quantity": "30",
             "already_attended": "10", "remanageable_need": "20", "selectable": True, "block_reason": None},
            {"item_id": 102, "product_code": "401.20", "description": "CANTONEIRA", "unit": "UN", "total_quantity": "5",
             "already_attended": "0", "remanageable_need": "5", "selectable": True, "block_reason": None},
            {"item_id": 103, "product_code": "500.01", "description": "CHAPA", "unit": "UN", "total_quantity": "8",
             "already_attended": "8", "remanageable_need": "0", "selectable": False, "block_reason": "Item sem necessidade pendente de remanejamento."},
            {"item_id": 104, "product_code": "", "description": "SEM CODIGO", "unit": "UN", "total_quantity": "2",
             "already_attended": "0", "remanageable_need": "2", "selectable": False, "block_reason": "Item sem codigo de produto para busca de remanejamento."},
        ]
        # codigo do produto -> candidatos
        self.candidates = {
            "300.23": [
                _candidate(20, "CP05236", 501, 12, "ENERGY SYSTEM", "SE CAMPESTRE"),
                _candidate(21, "CP05301", 502, 5, "MNS ENGENHARIA", "TAMTROI0013"),
                _candidate(22, "CP05401", 503, 20, "MNS ENGENHARIA", "MSRBS006_A"),
            ],
            "401.20": [
                _candidate(23, "CP05306", 700, 7, "GREGO", "OBRA"),
                _candidate(22, "CP05401", 504, 3, "MNS ENGENHARIA", "MSRBS006_A"),
            ],
        }
        self.destination_calls = 0
        self.items_calls: list[int] = []
        self.availability_calls: list[tuple[int, list[dict]]] = []
        self.review_calls: list[tuple] = []
        self.confirm_calls: list[tuple] = []
        self.destination_error: Exception | None = None
        self.items_error: Exception | None = None
        self.availability_error: Exception | None = None
        self.review_error: Exception | None = None
        self.review_errors: list[dict] = []
        self.confirm_error: Exception | None = None
        self.confirm_response = {"operation_id": "op-1", "status": "CONFIRMED"}
        # Pecas do destino que passam para a origem (resposta nova da API); None = resposta antiga, sem o campo.
        self.stage_transfers: list[dict] | None = None
        self.parts: list[dict] | None = None  # remanejamento por linhas: o que acontece com cada proposta

    def early_delivery_destination_candidates(self, search: str = ""):
        self.destination_calls += 1
        if self.destination_error is not None:
            raise self.destination_error
        return [dict(row) for row in self.destinations]

    def remanagement_destination_items(self, destination_id):
        self.items_calls.append(destination_id)
        if self.items_error is not None:
            raise self.items_error
        return [dict(row) for row in self.items]

    def remanagement_availability(self, destination_id, items):
        self.availability_calls.append((destination_id, items))
        if self.availability_error is not None:
            raise self.availability_error
        by_id = {row["item_id"]: row for row in self.items}
        groups = []
        for row in items:
            item = by_id[int(row["destination_item_id"])]
            candidates = [dict(c) for c in self.candidates.get(item["product_code"], [])]
            total = sum((Decimal(c["available_quantity"]) for c in candidates), Decimal("0"))
            requested = Decimal(str(row["requested_quantity"]))
            coverage = "SEM_DISPONIBILIDADE" if not candidates else ("SUFICIENTE" if total >= requested else "PARCIAL")
            groups.append({
                "destination_item_id": item["item_id"], "product_code": item["product_code"], "description": item["description"],
                "unit": item["unit"], "requested_quantity": str(requested), "total_available": str(total),
                "coverage_status": coverage, "candidates": candidates,
            })
        return {"destination_proposal_id": destination_id, "items": groups}

    def remanagement_review(self, destination_id, items, allocations, reason):
        self.review_calls.append((destination_id, items, allocations, reason))
        if self.review_error is not None:
            raise self.review_error
        available = {
            (c["source_proposal_id"], c["source_item_id"]): Decimal(c["available_quantity"])
            for candidates in self.candidates.values() for c in candidates
        }
        review_items = []
        origins = set()
        for row in items:
            item_id = int(row["destination_item_id"])
            code = next(i["product_code"] for i in self.items if i["item_id"] == item_id)
            requested = Decimal(str(row["requested_quantity"]))
            sources = []
            for allocation in allocations:
                if int(allocation["destination_item_id"]) != item_id:
                    continue
                key = (int(allocation["source_proposal_id"]), int(allocation["source_item_id"]))
                quantity = Decimal(str(allocation["allocated_quantity"]))
                origins.add(key[0])
                source_row = {
                    "source_proposal_id": key[0], "source_item_id": key[1], "ready_transfer": str(quantity),
                    "production_compensation": str(quantity), "source_before": str(available[key]),
                    "source_after_simulated": str(available[key] - quantity),
                }
                if self.stage_transfers is not None:
                    source_row["stage_transfers"] = list(self.stage_transfers)
                sources.append(source_row)
            allocated = sum((Decimal(s["ready_transfer"]) for s in sources), Decimal("0"))
            status = "NAO_ALOCADO" if allocated <= 0 else ("COMPLETO" if allocated >= requested else "PARCIAL")
            review_items.append({
                "destination_item_id": item_id, "product_code": code, "requested": str(requested), "allocated": str(allocated),
                "remaining": str(max(requested - allocated, Decimal("0"))), "status": status, "sources": sources,
            })
        errors = list(self.review_errors)
        if not (reason or "").strip():
            errors.append({"code": "REASON_REQUIRED", "message": "Informe o motivo.", "destination_item_id": None, "source_item_id": None})
        return {
            "destination_proposal_id": destination_id, "valid": not errors, "warnings": [], "errors": errors,
            "summary": {
                "product_count": len(review_items), "source_proposal_count": len(origins),
                "source_item_count": sum(len(i["sources"]) for i in review_items), "total_quantity": "25", "total_unit": "UN",
                "complete_items": sum(i["status"] == "COMPLETO" for i in review_items),
                "partial_items": sum(i["status"] == "PARCIAL" for i in review_items),
                "not_allocated_items": sum(i["status"] == "NAO_ALOCADO" for i in review_items), "invalid_items": 0,
            },
            "items": review_items,
            "engine": "ROWS" if self.parts is not None else "TRANSFER",
            "parts": list(self.parts or []),
        }

    def remanagement_confirm(self, operation_id, destination_id, items, allocations, reason):
        self.confirm_calls.append((operation_id, destination_id, items, allocations, reason))
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.confirm_response


def _selections(*pairs) -> list[RemanagementItemSelection]:
    names = {101: ("300.23", "PECA W17"), 102: ("401.20", "CANTONEIRA")}
    return [
        RemanagementItemSelection(
            destination_item_id=item_id, product_code=names[item_id][0], description=names[item_id][1], unit="UN",
            remanage_quantity=Decimal(str(quantity)), current_need=Decimal(str(quantity)),
        )
        for item_id, quantity in pairs
    ]


def _state_with_items(*pairs) -> RemanagementFlowState:
    state = RemanagementFlowState()
    state.set_destination(9, 4)
    state.set_item_selections(_selections(*(pairs or ((101, 20), (102, 5)))))
    return state


def _row_of(table, column, key):
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if item is not None and item.data(Qt.UserRole) == key:
            return row
    raise AssertionError(f"linha {key!r} nao encontrada")


def _texts(table, column):
    return [table.item(row, column).text() for row in range(table.rowCount())]


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])


class WhatHappensTests(unittest.TestCase):
    def _t(self, *pairs):
        return [RemanagementStageTransferView(stage=stage, quantity=Decimal(str(quantity))) for stage, quantity in pairs]

    def test_one_stage(self):
        self.assertEqual(
            what_happens("CP 05600", "CP 05507", Decimal("4"), self._t(("IN_GALVANIZATION", 4)), "un"),
            "A CP 05507 entrega 4 un prontas à CP 05600. Em troca, passam a ser da CP 05507 (eram da CP 05600): 4 un na galvanização.",
        )

    def test_several_stages_in_order(self):
        text = what_happens("B", "A", Decimal("9"), self._t(("IN_GALVANIZATION", 4), ("AWAITING_GALVANIZATION", 3), ("TO_PRODUCE", 2)), "")
        self.assertTrue(text.endswith("4 na galvanização, 3 já fabricadas, aguardando galvanização e 2 ainda a fabricar."))

    def test_pieces_without_a_defined_flow_follow_the_flow_of_the_source(self):
        self.assertEqual(
            what_happens("B", "A", Decimal("4"), self._t(("UNDEFINED_FLOW", 4)), "un"),
            "A A entrega 4 un prontas à B. Em troca, passam a ser da A (eram da B): 4 un ainda sem fluxo definido (seguem o fluxo da origem).",
        )

    def test_zero_quantities_are_left_out_and_no_detail_gives_only_the_first_sentence(self):
        self.assertEqual(what_happens("B", "A", Decimal("2"), self._t(("TO_PRODUCE", 0)), "kg"), "A A entrega 2 kg prontas à B.")
        self.assertEqual(what_happens("B", "A", Decimal("2"), [], "kg"), "A A entrega 2 kg prontas à B.")

    def test_the_api_detail_is_parsed(self):
        result = review_from_api({
            "destination_proposal_id": 9, "valid": True, "warnings": [], "errors": [],
            "summary": {"product_count": 1, "source_proposal_count": 1, "source_item_count": 1},
            "items": [{
                "destination_item_id": 101, "product_code": "X", "requested": "5", "allocated": "5", "remaining": "0", "status": "COMPLETO",
                "sources": [{
                    "source_proposal_id": 20, "source_item_id": 501, "ready_transfer": "5", "production_compensation": "5",
                    "source_before": "8", "source_after_simulated": "3",
                    "stage_transfers": [{"stage": "AWAITING_GALVANIZATION", "quantity": "5.0000"}],
                }],
            }],
        })
        transfers = result.items[0].sources[0].stage_transfers
        self.assertEqual([(t.stage, t.quantity, t.label) for t in transfers], [("AWAITING_GALVANIZATION", Decimal("5"), "já fabricadas, aguardando galvanização")])

    def test_an_older_response_has_no_stage_transfers(self):
        result = review_from_api({
            "destination_proposal_id": 9, "valid": True, "summary": {},
            "items": [{"destination_item_id": 1, "sources": [{"source_proposal_id": 2, "source_item_id": 3}]}],
        })
        self.assertEqual(result.items[0].sources[0].stage_transfers, [])


# ---------------------------------------------------------------------------
# Passo 1 - proposta destino
# ---------------------------------------------------------------------------
class DestinationPageTests(QtCase):
    def _page(self, service=None):
        service = service or FakeWizardService()
        page = DestinationPage(service, RemanagementFlowState())
        page.enter()
        return page, service

    def test_lists_candidates_with_their_stage(self):
        page, _ = self._page()
        self.assertEqual(page.table.rowCount(), 2)
        self.assertEqual(destination_module.stage_name(page.selected_row() or page._rows[0]), "Produção")
        self.assertEqual(destination_module.stage_name(page._rows[1]), "Galvanização")
        self.assertEqual(_texts(page.table, destination_module.COLUMN_PROPOSAL), ["CP05385", "CP05401"])
        self.assertEqual(_texts(page.table, destination_module.COLUMN_DEADLINE), ["20/10/2026", "30/10/2026"])

    def test_states_the_eligibility_rule_on_screen(self):
        page, _ = self._page()
        text = page.rule_notice.text_label.text()
        self.assertIn("Produção ou Galvanização", text)
        self.assertIn("Expedição", text)

    def test_search_filters_locally_without_calling_the_service_again(self):
        page, service = self._page()
        calls = service.destination_calls
        page.search.setText("canoas")
        self.assertEqual(page.table.rowCount(), 1)
        page.search.setText("05385")
        self.assertEqual(page.table.rowCount(), 1)
        page.search.setText("")
        self.assertEqual(page.table.rowCount(), 2)
        self.assertEqual(service.destination_calls, calls)

    def test_invalid_without_selection(self):
        page, _ = self._page()
        self.assertFalse(page.is_valid())
        self.assertEqual(page.summary(), "Nenhuma proposta selecionada.")

    def test_selecting_a_row_enables_advance_and_fills_the_summary_panel(self):
        page, _ = self._page()
        emitted = []
        page.validity_changed.connect(lambda: emitted.append(True))
        page.table.selectRow(1)
        self.assertTrue(page.is_valid())
        self.assertTrue(emitted)
        self.assertIn("CP05401", page.summary())
        texts = " ".join(label.text() for label in page.summary_panel.findChildren(QLabel))
        self.assertIn("Eletro Sul", texts)
        self.assertIn("Galvanização", texts)

    def test_selection_survives_a_filter_roundtrip(self):
        page, _ = self._page()
        page.table.selectRow(1)
        page.search.setText("MNS")
        self.assertEqual(page.table.rowCount(), 1)
        self.assertTrue(page.is_valid())
        page.search.setText("")
        self.assertEqual(page.selected_row()["id"], 10)

    def test_commit_writes_destination_and_version_to_state(self):
        page, _ = self._page()
        page.table.selectRow(0)
        self.assertTrue(page.commit())
        self.assertEqual(page.state.destination_proposal_id, 9)
        self.assertEqual(page.state.destination_version, 4)

    def test_commit_revalidates_and_blocks_a_destination_that_left_the_list(self):
        page, service = self._page()
        page.table.selectRow(0)
        service.destinations.pop(0)
        with patch.object(destination_module.QMessageBox, "warning", return_value=None) as warning:
            self.assertFalse(page.commit())
        warning.assert_called_once()
        self.assertIsNone(page.state.destination_proposal_id)
        self.assertEqual(page.table.rowCount(), 1)
        self.assertFalse(page.is_valid())

    def test_load_error_is_shown_inside_the_page(self):
        service = FakeWizardService()
        service.destination_error = RuntimeError("API fora do ar")
        page, _ = self._page(service)
        self.assertEqual(page.load_error, "API fora do ar")
        self.assertFalse(page.notice.isHidden())
        self.assertEqual(page.table.rowCount(), 0)

    def test_double_click_asks_the_wizard_to_advance_only_when_valid(self):
        page, _ = self._page()
        requested = []
        page.advance_requested.connect(lambda: requested.append(True))
        page.table.itemDoubleClicked.emit(page.table.item(0, 0))
        self.assertEqual(requested, [])
        page.table.selectRow(0)
        page.table.itemDoubleClicked.emit(page.table.item(0, 0))
        self.assertEqual(requested, [True])


# ---------------------------------------------------------------------------
# Passo 2 - itens
# ---------------------------------------------------------------------------
def _items_page(service=None, state=None):
    service = service or FakeWizardService()
    state = state or RemanagementFlowState()
    if state.destination_proposal_id is None:
        state.set_destination(9, 4)
    page = ItemsPage(service, state)
    page.set_destination(service.destinations[0])
    page.enter()
    return page, service


def _item_row(page, item_id):
    return _row_of(page.table, items_module.COLUMN_CHECK, item_id)


def _check(page, item_id, checked=True):
    page.table.item(_item_row(page, item_id), items_module.COLUMN_CHECK).setCheckState(Qt.Checked if checked else Qt.Unchecked)


def _quantity_cell(page, item_id):
    return page.table.item(_item_row(page, item_id), items_module.COLUMN_REMANAGE)


class ItemsPageTests(QtCase):
    def test_loads_destination_header_and_items(self):
        page, service = _items_page()
        self.assertEqual(service.items_calls, [9])
        self.assertEqual(page.table.rowCount(), 4)
        self.assertIn("CP05385", page.destination_label.text())
        self.assertIn("Produção", page.destination_caption.text())

    def test_blocked_items_cannot_be_checked_and_explain_why(self):
        page, _ = _items_page()
        for item_id in (103, 104):
            cell = page.table.item(_item_row(page, item_id), items_module.COLUMN_CHECK)
            self.assertFalse(cell.flags() & Qt.ItemIsEnabled)
            self.assertTrue(cell.toolTip())
            note = page.table.item(_item_row(page, item_id), items_module.COLUMN_NOTE).text()
            self.assertTrue(note)

    def test_checking_an_item_fills_the_need_and_unchecking_clears_it(self):
        page, _ = _items_page()
        _check(page, 101)
        self.assertEqual(_quantity_cell(page, 101).text(), "20")
        self.assertTrue(_quantity_cell(page, 101).flags() & Qt.ItemIsEditable)
        _check(page, 101, False)
        self.assertEqual(_quantity_cell(page, 101).text(), "")
        self.assertFalse(_quantity_cell(page, 101).flags() & Qt.ItemIsEditable)
        self.assertFalse(page.is_valid())

    def test_select_all_marks_only_the_items_that_can_receive_material(self):
        page, _ = _items_page()
        page.select_all_button.click()
        checked = {
            page.table.item(row, items_module.COLUMN_CHECK).data(Qt.UserRole)
            for row in range(page.table.rowCount())
            if page.table.item(row, items_module.COLUMN_CHECK).checkState() == Qt.Checked
        }
        self.assertEqual(checked, {101, 102})
        self.assertEqual(_quantity_cell(page, 101).text(), "20")
        self.assertEqual(_quantity_cell(page, 102).text(), "5")
        self.assertTrue(page.is_valid())
        self.assertEqual(page.items_number.text(), "2")
        self.assertEqual(page.quantity_number.text(), "25 UN")

    def test_select_all_only_touches_the_items_listed_by_the_search(self):
        page, _ = _items_page()
        page.search.setText("CANTONEIRA")
        page.select_all_button.click()
        page.search.setText("")
        self.assertEqual(page.table.item(_item_row(page, 102), items_module.COLUMN_CHECK).checkState(), Qt.Checked)
        self.assertEqual(page.table.item(_item_row(page, 101), items_module.COLUMN_CHECK).checkState(), Qt.Unchecked)

    def test_clear_selection_unchecks_everything(self):
        page, _ = _items_page()
        page.select_all_button.click()
        page.clear_button.click()
        self.assertFalse(page.is_valid())
        self.assertEqual(page.items_number.text(), "0")

    def test_search_keeps_the_selection(self):
        page, _ = _items_page()
        _check(page, 101)
        page.search.setText("CANTONEIRA")
        self.assertEqual(page.table.rowCount(), 1)
        page.search.setText("")
        self.assertEqual(page.table.item(_item_row(page, 101), items_module.COLUMN_CHECK).checkState(), Qt.Checked)
        self.assertEqual(_quantity_cell(page, 101).text(), "20")

    def test_quantity_above_the_need_is_clamped(self):
        page, _ = _items_page()
        _check(page, 101)
        _quantity_cell(page, 101).setText("999")
        self.assertEqual(_quantity_cell(page, 101).text(), "20")
        self.assertTrue(page.is_valid())

    def test_zero_or_negative_quantity_clamps_and_blocks_advance(self):
        page, _ = _items_page()
        _check(page, 101)
        _quantity_cell(page, 101).setText("0")
        self.assertFalse(page.is_valid())
        _quantity_cell(page, 101).setText("-4")
        self.assertEqual(_quantity_cell(page, 101).text(), "0")
        self.assertFalse(page.is_valid())

    def test_decimal_quantity_is_preserved(self):
        page, _ = _items_page()
        _check(page, 101)
        _quantity_cell(page, 101).setText("7.5")
        self.assertEqual(_quantity_cell(page, 101).text(), "7.5")
        self.assertTrue(page.commit())
        self.assertEqual(page.state.item_selections[0].remanage_quantity, Decimal("7.5"))

    def test_commit_writes_the_selections_to_state(self):
        page, _ = _items_page()
        page.select_all_button.click()
        self.assertTrue(page.commit())
        state = page.state
        self.assertEqual(sorted(state.selected_item_ids), [101, 102])
        selection = next(row for row in state.item_selections if row.destination_item_id == 101)
        self.assertEqual((selection.product_code, selection.remanage_quantity, selection.current_need), ("300.23", Decimal("20"), Decimal("20")))

    def test_commit_with_an_unchanged_selection_keeps_availability_and_allocations(self):
        page, _ = _items_page()
        page.select_all_button.click()
        page.commit()
        page.state.set_availability(availability_from_api([]))
        marker = object()
        page.state.allocations = [marker]
        self.assertTrue(page.commit())
        self.assertEqual(page.state.allocations, [marker])

    def test_commit_with_a_changed_selection_clears_what_depended_on_it(self):
        page, _ = _items_page()
        page.select_all_button.click()
        page.commit()
        page.state.allocations = [object()]
        _quantity_cell(page, 101).setText("10")
        self.assertTrue(page.commit())
        self.assertEqual(page.state.allocations, [])

    def test_reentering_restores_the_selection_from_state(self):
        state = _state_with_items((101, 12))
        page, _ = _items_page(state=state)
        self.assertEqual(page.table.item(_item_row(page, 101), items_module.COLUMN_CHECK).checkState(), Qt.Checked)
        self.assertEqual(_quantity_cell(page, 101).text(), "12")

    def test_reentering_drops_what_lost_eligibility_or_shrank(self):
        state = _state_with_items((101, 20), (102, 5))
        service = FakeWizardService()
        service.items[0]["remanageable_need"] = "8"
        service.items[1]["selectable"] = False
        page, _ = _items_page(service, state)
        self.assertEqual(_quantity_cell(page, 101).text(), "8")
        self.assertEqual(page.table.item(_item_row(page, 102), items_module.COLUMN_CHECK).checkState(), Qt.Unchecked)

    def test_changing_the_destination_discards_the_old_selection(self):
        state = _state_with_items((101, 20))
        page, service = _items_page(state=state)
        state.set_destination(10, 2)
        page.enter()
        self.assertFalse(page.is_valid())
        self.assertEqual(page.table.item(_item_row(page, 101), items_module.COLUMN_CHECK).checkState(), Qt.Unchecked)

    def test_failure_loading_items_is_shown_inside_the_page(self):
        service = FakeWizardService()
        service.items_error = RuntimeError("falhou")
        page, _ = _items_page(service)
        self.assertEqual(page.load_error, "falhou")
        self.assertEqual(page.table.rowCount(), 0)
        self.assertFalse(page.is_valid())


# ---------------------------------------------------------------------------
# Passo 3 - origem do material
# ---------------------------------------------------------------------------
def _sources_page(service=None, state=None):
    service = service or FakeWizardService()
    state = state or _state_with_items()
    page = SourcesPage(service, state)
    page.enter()
    return page, service


def _select_source(page, proposal_id):
    page.sources_table.selectRow(_row_of(page.sources_table, sources_module.SOURCE_COLUMN_NUMBER, proposal_id))


def _take_cell(page, item_id, key):
    return page.detail_table.item(_row_of(page.detail_table, sources_module.ITEM_COLUMN_TAKE, (item_id, key)), sources_module.ITEM_COLUMN_TAKE)


def _take(page, proposal_id, item_id, key, text):
    _select_source(page, proposal_id)
    _take_cell(page, item_id, key).setText(text)


class SourcesPageTests(QtCase):
    def test_searches_the_expedition_with_the_selected_items(self):
        page, service = _sources_page()
        destination_id, payload = service.availability_calls[0]
        self.assertEqual(destination_id, 9)
        self.assertEqual(
            [(row["destination_item_id"], row["requested_quantity"]) for row in payload],
            [(101, Decimal("20")), (102, Decimal("5"))],
        )
        self.assertEqual(len(page.state.availability), 2)

    def test_lists_source_proposals_ordered_by_how_much_they_cover(self):
        page, _ = _sources_page()
        self.assertEqual(
            _texts(page.sources_table, sources_module.SOURCE_COLUMN_NUMBER),
            ["CP05401", "CP05236", "CP05306", "CP05301"],
        )
        self.assertEqual(_texts(page.sources_table, sources_module.SOURCE_COLUMN_COVERS), ["2 de 2", "1 de 2", "1 de 2", "1 de 2"])

    def test_first_source_is_selected_and_shows_only_the_items_it_can_supply(self):
        page, _ = _sources_page()
        self.assertEqual(page.detail_table.rowCount(), 2)  # CP05401 cobre os dois itens
        self.assertIn("CP05401", page.detail_title.text())
        _select_source(page, 21)
        self.assertEqual(page.detail_table.rowCount(), 1)
        self.assertEqual(page.detail_table.item(0, sources_module.ITEM_COLUMN_CODE).text(), "300.23")
        self.assertIn("não tem 1 dos 2 itens", page.detail_caption.text())

    def test_search_filters_the_source_list(self):
        page, _ = _sources_page()
        page.sources_search.setText("grego")
        self.assertEqual(_texts(page.sources_table, sources_module.SOURCE_COLUMN_NUMBER), ["CP05306"])
        self.assertIn("CP05306", page.detail_title.text())

    def test_nothing_is_chosen_automatically(self):
        page, _ = _sources_page()
        self.assertFalse(page.is_valid())
        self.assertEqual(_texts(page.sources_table, sources_module.SOURCE_COLUMN_TAKING), ["—"] * 4)

    def test_typed_quantity_is_clamped_to_what_the_source_has_ready(self):
        page, _ = _sources_page()
        _take(page, 21, 101, (21, 502), "99")
        self.assertEqual(_take_cell(page, 101, (21, 502)).text(), "5")
        self.assertEqual(page.allocation(101, (21, 502)), Decimal("5"))
        self.assertTrue(page.is_valid())

    def test_typed_quantity_is_clamped_to_what_is_still_missing_across_sources(self):
        page, _ = _sources_page()
        _take(page, 22, 101, (22, 503), "15")
        _take(page, 20, 101, (20, 501), "12")
        self.assertEqual(page.allocation(101, (20, 501)), Decimal("5"))  # faltavam 5 dos 20 pedidos

    def test_negative_quantity_becomes_zero_and_zero_removes_the_allocation(self):
        page, _ = _sources_page()
        _take(page, 21, 101, (21, 502), "-3")
        self.assertEqual(_take_cell(page, 101, (21, 502)).text(), "0")
        self.assertEqual(page.allocation(101, (21, 502)), Decimal("0"))
        _take_cell(page, 101, (21, 502)).setText("3")
        _take_cell(page, 101, (21, 502)).setText("0")
        self.assertFalse(page.is_valid())

    def test_decimal_quantity_is_preserved(self):
        page, _ = _sources_page()
        _take(page, 21, 101, (21, 502), "2.5")
        self.assertEqual(page.allocation(101, (21, 502)), Decimal("2.5"))

    def test_the_sources_list_shows_how_much_is_being_taken_from_each(self):
        page, _ = _sources_page()
        _take(page, 22, 101, (22, 503), "15")
        _take_cell(page, 102, (22, 504)).setText("3")
        row = _row_of(page.sources_table, sources_module.SOURCE_COLUMN_NUMBER, 22)
        self.assertEqual(page.sources_table.item(row, sources_module.SOURCE_COLUMN_TAKING).text(), "2 itens · 18 UN")

    def test_take_max_from_the_selected_source(self):
        page, _ = _sources_page()
        _select_source(page, 22)
        page.take_max_button.click()
        self.assertEqual(page.allocation(101, (22, 503)), Decimal("20"))
        self.assertEqual(page.allocation(102, (22, 504)), Decimal("3"))

    def test_take_max_never_exceeds_what_the_order_still_needs(self):
        page, _ = _sources_page()
        _take(page, 20, 101, (20, 501), "12")
        _select_source(page, 22)
        page.take_max_button.click()
        self.assertEqual(page.allocation(101, (22, 503)), Decimal("8"))  # 20 pedidos - 12 ja retirados

    def test_clear_only_the_selected_source(self):
        page, _ = _sources_page()
        _take(page, 20, 101, (20, 501), "6")
        _take(page, 23, 102, (23, 700), "2")
        _select_source(page, 20)
        page.clear_source_button.click()
        self.assertEqual(page.allocation(101, (20, 501)), Decimal("0"))
        self.assertEqual(page.allocation(102, (23, 700)), Decimal("2"))

    def test_suggest_fills_every_item_using_the_largest_balance_first(self):
        page, _ = _sources_page()
        page.suggest_button.click()
        self.assertEqual(page.allocation(101, (22, 503)), Decimal("20"))
        self.assertEqual(page.allocation(101, (20, 501)), Decimal("0"))
        self.assertEqual(page.allocation(102, (23, 700)), Decimal("5"))  # 7 e o maior saldo do item 102
        self.assertTrue(page.is_valid())

    def test_suggest_replaces_instead_of_accumulating(self):
        page, _ = _sources_page()
        page.suggest_button.click()
        page.suggest_button.click()
        self.assertEqual(page.allocation(101, (22, 503)), Decimal("20"))
        self.assertEqual(page.allocation(102, (23, 700)), Decimal("5"))

    def test_clear_all_empties_the_plan(self):
        page, _ = _sources_page()
        page.suggest_button.click()
        page.clear_all_button.click()
        self.assertFalse(page.is_valid())

    def test_coverage_panel_tells_complete_partial_and_missing(self):
        service = FakeWizardService()
        service.candidates["401.20"] = []
        page, _ = _sources_page(service)

        def badge(item_id):
            return page._coverage[item_id]["badge"].text()

        self.assertEqual(badge(101), "Sem origem escolhida")
        self.assertEqual(badge(102), "Sem material pronto")
        _take(page, 21, 101, (21, 502), "5")
        self.assertEqual(badge(101), "Parcial")
        self.assertIn("falta 15 UN", page._coverage[101]["amount"].text())
        _take(page, 22, 101, (22, 503), "15")
        self.assertEqual(badge(101), "Completo")
        self.assertIn("1 de 2 item(ns) com o pedido completo", page.coverage_summary.text())

    def test_commit_writes_the_plan_with_availability_snapshots(self):
        page, _ = _sources_page()
        _take(page, 22, 101, (22, 503), "15")
        _take(page, 21, 101, (21, 502), "5")
        self.assertTrue(page.commit())
        plan = {row.destination_item_id: row for row in page.state.allocations}
        self.assertEqual(list(plan), [101])
        self.assertEqual(plan[101].allocated_quantity, Decimal("20"))
        by_source = {row.source_proposal_id: row for row in plan[101].allocations}
        self.assertEqual(by_source[22].available_snapshot, Decimal("20"))
        self.assertEqual(by_source[22].allocated_quantity, Decimal("15"))

    def test_commit_without_a_source_chosen_is_refused(self):
        page, _ = _sources_page()
        with patch.object(sources_module.QMessageBox, "warning", return_value=None) as warning:
            self.assertFalse(page.commit())
        warning.assert_called_once()

    def test_reentering_keeps_the_choices_already_made(self):
        state = _state_with_items()
        page, service = _sources_page(state=state)
        _take(page, 22, 101, (22, 503), "15")
        page.commit()
        again = SourcesPage(service, state)
        again.enter()
        self.assertEqual(again.allocation(101, (22, 503)), Decimal("15"))
        self.assertTrue(again.notice.isHidden())

    def test_reentering_with_less_material_adjusts_the_quantity_and_warns(self):
        state = _state_with_items()
        page, service = _sources_page(state=state)
        _take(page, 22, 101, (22, 503), "15")
        page.commit()
        service.candidates["300.23"][2]["available_quantity"] = "9"
        page.enter()
        self.assertEqual(page.allocation(101, (22, 503)), Decimal("9"))
        self.assertFalse(page.notice.isHidden())
        self.assertIn("ajustadas", page.notice.text())

    def test_reentering_without_the_source_drops_the_choice(self):
        state = _state_with_items()
        page, service = _sources_page(state=state)
        _take(page, 21, 101, (21, 502), "5")
        service.candidates["300.23"] = [c for c in service.candidates["300.23"] if c["source_proposal_id"] != 21]
        page.enter()
        self.assertEqual(page.allocation(101, (21, 502)), Decimal("0"))
        self.assertIn("ajustadas", page.notice.text())

    def test_refresh_button_searches_again(self):
        page, service = _sources_page()
        page.refresh_button.click()
        self.assertEqual(len(service.availability_calls), 2)

    def test_no_material_ready_anywhere_explains_and_blocks(self):
        service = FakeWizardService()
        service.candidates = {}
        page, _ = _sources_page(service)
        self.assertEqual(page.sources_table.rowCount(), 0)
        self.assertIn("Nenhuma proposta da Expedição", page.notice.text())
        self.assertFalse(page.is_valid())

    def test_service_error_is_shown_inside_the_page(self):
        service = FakeWizardService()
        service.availability_error = RuntimeError("sem conexao")
        page, _ = _sources_page(service)
        self.assertEqual(page.load_error, "sem conexao")
        self.assertFalse(page.is_valid())

    def test_missing_item_selection_is_an_error(self):
        state = RemanagementFlowState()
        state.set_destination(9, 4)
        page, _ = _sources_page(state=state)
        self.assertIn("Nenhum item foi selecionado", page.load_error)

    def test_changing_the_destination_drops_the_old_plan(self):
        state = _state_with_items()
        page, service = _sources_page(state=state)
        _take(page, 21, 101, (21, 502), "5")
        state.set_destination(10, 2)
        state.set_item_selections(_selections((101, 20), (102, 5)))
        page.enter()
        self.assertFalse(page.is_valid())


# ---------------------------------------------------------------------------
# Passo 4 - revisao e confirmacao
# ---------------------------------------------------------------------------
def _state_with_plan(reason="") -> RemanagementFlowState:
    service = FakeWizardService()
    state = _state_with_items()
    page = SourcesPage(service, state)
    page.enter()
    _take(page, 22, 101, (22, 503), "15")
    _take(page, 21, 101, (21, 502), "5")
    _take(page, 23, 102, (23, 700), "5")
    assert page.commit()
    state.set_reason(reason)
    return state


def _review_page(service=None, state=None, reason="Antecipar a entrega."):
    service = service or FakeWizardService()
    state = state or _state_with_plan(reason)
    page = ReviewPage(service, state)
    page.set_destination(service.destinations[0])
    page.enter()
    return page, service


def _card_text(page) -> str:
    texts = []
    for index in range(page.groups_layout.count()):
        widget = page.groups_layout.itemAt(index).widget()
        if widget is None:
            continue
        texts.extend(label.text() for label in widget.findChildren(QLabel))
    return "\n".join(texts)


class ReviewPageTests(QtCase):
    def test_review_runs_automatically_when_the_page_opens(self):
        page, service = _review_page()
        self.assertEqual(len(service.review_calls), 1)
        destination_id, items, allocations, reason = service.review_calls[0]
        self.assertEqual(destination_id, 9)
        self.assertEqual({row["destination_item_id"] for row in items}, {101, 102})
        self.assertEqual(len(allocations), 3)
        self.assertEqual(reason, "Antecipar a entrega.")
        self.assertIsNotNone(page.state.simulation)

    def test_shows_destination_summary_and_one_card_per_item(self):
        page, _ = _review_page()
        self.assertIn("CP05385", page.destination_label.text())
        text = _card_text(page)
        self.assertIn("300.23", text)
        self.assertIn("401.20", text)
        self.assertIn("Solicitado 20 UN", text)

    def test_shows_before_and_after_balance_and_the_production_obligation(self):
        page, _ = _review_page()
        found = []
        for index in range(page.groups_layout.count()):
            widget = page.groups_layout.itemAt(index).widget()
            if widget is not None:
                found.extend(widget.findChildren(QTableWidget))
        self.assertEqual(len(found), 2)
        first = found[0]
        self.assertIn("CP05385", first.horizontalHeaderItem(1).text())
        self.assertIn("CP05385", first.horizontalHeaderItem(3).text())
        rows = {first.item(row, 0).text(): [first.item(row, c).text() for c in (1, 2, 3)] for row in range(first.rowCount())}
        self.assertEqual(rows["CP05401"], ["15 UN", "20 → 5", "15 UN"])
        self.assertEqual(rows["CP05301"], ["5 UN", "5 → 0", "5 UN"])

    def test_review_shows_what_happens_with_each_proposal_when_the_engine_splits_them(self):
        service = FakeWizardService()
        service.parts = [
            {"proposal_number": "CP05401", "role": "ORIGEM", "place": "REFERENCIA", "item_numbers": [], "quantity": "0", "is_part": False},
            {"proposal_number": "CP05401-1", "role": "ORIGEM", "place": "EXPEDICAO", "item_numbers": ["1", "2", "4"], "quantity": "7", "is_part": True},
            {"proposal_number": "CP05401-2", "role": "ORIGEM", "place": "PRODUCAO", "item_numbers": ["3"], "quantity": "1", "is_part": True},
            {"proposal_number": "CP05385", "role": "DESTINO", "place": "PRODUCAO", "item_numbers": ["1", "2"], "quantity": "5", "is_part": False},
        ]
        page, _ = _review_page(service)
        self.assertFalse(page.parts_panel.isHidden())
        texts = [page.parts_holder.itemAt(i).widget().text() for i in range(page.parts_holder.count())]
        self.assertEqual(texts, [
            "CP05401: vira só referência no Controle Geral; as partes abaixo seguem sozinhas.",
            "CP05401-1 (parte): Expedição — os itens 1, 2 e 4 (total 7).",
            "CP05401-2 (parte): Produção — o item 3 (total 1).",
            "CP05385 (destino): Produção — os itens 1 e 2 (total 5).",
        ])

    def test_review_without_the_rows_engine_has_no_parts_panel(self):
        page, _ = _review_page(FakeWizardService())
        self.assertTrue(page.parts_panel.isHidden())

    def test_review_explains_in_plain_words_which_pieces_change_owner(self):
        service = FakeWizardService()
        service.stage_transfers = [{"stage": "IN_GALVANIZATION", "quantity": "3.0000"}, {"stage": "TO_PRODUCE", "quantity": "2.0000"}]
        page, _ = _review_page(service)
        text = _card_text(page)
        self.assertIn("A CP05401 entrega 15 UN prontas à CP05385. Em troca, passam a ser da CP05401 (eram da CP05385): 3 UN na galvanização e 2 UN ainda a fabricar.", text)
        found = []
        for index in range(page.groups_layout.count()):
            widget = page.groups_layout.itemAt(index).widget()
            if widget is not None:
                found.extend(widget.findChildren(QTableWidget))
        self.assertIn("3 UN na galvanização; 2 UN ainda a fabricar", [found[0].item(row, 3).text() for row in range(found[0].rowCount())])
        self.assertIn("CP05385", found[0].horizontalHeaderItem(3).text())

    def test_review_still_works_with_an_older_api_without_the_stage_detail(self):
        page, _ = _review_page(FakeWizardService())
        self.assertIn("A CP05401 entrega 15 UN prontas à CP05385.", _card_text(page))
        self.assertNotIn("Em troca", _card_text(page))

    def test_partial_coverage_shows_the_attention_notice(self):
        state = _state_with_items()
        service = FakeWizardService()
        page = SourcesPage(service, state)
        page.enter()
        _take(page, 21, 101, (21, 502), "5")
        page.commit()
        review, _ = _review_page(service, state)
        self.assertIn("continuarão sem atendimento", _card_text(review))
        self.assertIn("Parcial", _card_text(review))

    def test_confirm_needs_a_reason(self):
        page, _ = _review_page(reason="")
        self.assertFalse(page.is_valid())
        page.reason_edit.setPlainText("   ")
        self.assertFalse(page.is_valid())
        page.reason_edit.setPlainText("Urgente")
        self.assertTrue(page.is_valid())

    def test_reason_typed_goes_to_state_as_typed(self):
        page, _ = _review_page()
        page.reason_edit.setPlainText("  Cliente pediu  ")
        self.assertEqual(page.state.reason, "  Cliente pediu  ")

    def test_blocking_error_shows_the_message_and_blocks_confirm(self):
        service = FakeWizardService()
        service.review_errors = [{"code": "SOURCE_BALANCE_CHANGED", "message": "Saldo da origem mudou.", "destination_item_id": 101, "source_item_id": 503}]
        page, _ = _review_page(service)
        self.assertFalse(page.is_valid())
        self.assertIn("Saldo da origem mudou.", page.warnings_label.text())
        self.assertFalse(page.warnings_label.isHidden())
        self.assertIn("Bloqueio: Saldo da origem mudou.", _card_text(page))

    def test_revalidate_runs_the_review_again(self):
        page, service = _review_page()
        page.revalidate_button.click()
        self.assertEqual(len(service.review_calls), 2)

    def test_missing_plan_is_an_error_inside_the_page(self):
        state = _state_with_items()
        page, _ = _review_page(state=state)
        self.assertIn("Nenhuma origem foi escolhida", page.load_error)
        self.assertFalse(page.is_valid())

    def test_review_service_error_is_shown_inside_the_page(self):
        service = FakeWizardService()
        service.review_error = RuntimeError("fora do ar")
        page, _ = _review_page(service)
        self.assertEqual(page.load_error, "fora do ar")
        self.assertFalse(page.is_valid())

    def test_commit_confirms_with_the_operation_id_and_the_plan(self):
        page, service = _review_page()
        with patch.object(review_module.QMessageBox, "question", return_value=review_module.QMessageBox.Yes):
            self.assertTrue(page.commit())
        operation_id, destination_id, items, allocations, reason = service.confirm_calls[0]
        self.assertEqual(operation_id, page.state.operation_id)
        self.assertEqual(destination_id, 9)
        self.assertEqual(len(allocations), 3)
        self.assertEqual(reason, "Antecipar a entrega.")
        self.assertEqual(page.confirm_result, service.confirm_response)

    def test_commit_saves_the_trimmed_reason(self):
        page, service = _review_page()
        page.reason_edit.setPlainText("  Motivo real  ")
        with patch.object(review_module.QMessageBox, "question", return_value=review_module.QMessageBox.Yes):
            page.commit()
        self.assertEqual(service.confirm_calls[0][4], "Motivo real")
        self.assertEqual(page.state.reason, "Motivo real")

    def test_declining_the_question_writes_nothing(self):
        page, service = _review_page()
        with patch.object(review_module.QMessageBox, "question", return_value=review_module.QMessageBox.No):
            self.assertFalse(page.commit())
        self.assertEqual(service.confirm_calls, [])

    def test_commit_without_reason_never_asks_or_writes(self):
        page, service = _review_page(reason="")
        with patch.object(review_module.QMessageBox, "question") as question:
            self.assertFalse(page.commit())
        question.assert_not_called()
        self.assertEqual(service.confirm_calls, [])

    def test_confirm_failure_warns_revalidates_and_stays(self):
        page, service = _review_page()
        service.confirm_error = RuntimeError("Saldo mudou")
        with patch.object(review_module.QMessageBox, "question", return_value=review_module.QMessageBox.Yes), \
                patch.object(review_module.QMessageBox, "warning", return_value=None) as warning:
            self.assertFalse(page.commit())
        warning.assert_called_once()
        self.assertIn("Saldo mudou", warning.call_args.args[2])
        self.assertEqual(len(service.review_calls), 2)
        self.assertIsNone(page.load_error)

    def test_confirm_failure_when_revalidation_also_fails_shows_the_error(self):
        page, service = _review_page()
        service.confirm_error = RuntimeError("Saldo mudou")
        service.review_error = RuntimeError("API caiu")
        with patch.object(review_module.QMessageBox, "question", return_value=review_module.QMessageBox.Yes), \
                patch.object(review_module.QMessageBox, "warning", return_value=None):
            self.assertFalse(page.commit())
        self.assertEqual(page.load_error, "API caiu")
        self.assertFalse(page.is_valid())

    def test_operation_id_is_stable_and_changes_with_the_destination(self):
        state = _state_with_plan()
        first = state.operation_id
        state.set_reason("outro motivo")
        self.assertEqual(state.operation_id, first)
        state.set_destination(10, 2)
        self.assertNotEqual(state.operation_id, first)


# ---------------------------------------------------------------------------
# O assistente inteiro
# ---------------------------------------------------------------------------
class WizardDialogTests(QtCase):
    def _wizard(self, service=None):
        service = service or FakeWizardService()
        return RemanagementWizardDialog(service), service

    def _advance_to_sources(self, wizard):
        wizard.destination_page.table.selectRow(0)
        wizard._next()
        wizard.items_page.select_all_button.click()
        wizard._next()

    def test_one_window_with_four_steps_that_opens_large(self):
        wizard, _ = self._wizard()
        self.assertEqual(wizard.stepper.steps(), ["Proposta destino", "Itens", "Origem do material", "Revisão"])
        self.assertEqual(wizard.stack.count(), 4)
        self.assertGreaterEqual(wizard.width(), 1180)
        self.assertGreaterEqual(wizard.height(), 690)

    def test_opens_at_the_size_of_the_chat_window_relative_to_the_parent(self):
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        parent.resize(1600, 960)
        parent.show()
        wizard = RemanagementWizardDialog(FakeWizardService(), parent)
        # Mesma proporcao da central de chats: 94% x 94% da janela dona.
        self.assertEqual(wizard.width(), int(parent.width() * 0.94))
        self.assertEqual(wizard.height(), max(690, int(parent.height() * 0.94)))

    def test_first_step_hides_back_and_disables_next_until_a_proposal_is_chosen(self):
        wizard, _ = self._wizard()
        self.assertTrue(wizard.back_button.isHidden())
        self.assertFalse(wizard.next_button.isEnabled())
        self.assertEqual(wizard.next_button.text(), "Escolher itens")
        wizard.destination_page.table.selectRow(0)
        self.assertTrue(wizard.next_button.isEnabled())

    def test_header_tells_the_step_and_its_instruction(self):
        wizard, _ = self._wizard()
        self.assertEqual(wizard.header.subtitle_label.text(), "Passo 1 de 4 — Escolha a proposta que vai receber o material pronto.")
        wizard.destination_page.table.selectRow(0)
        wizard._next()
        self.assertTrue(wizard.header.subtitle_label.text().startswith("Passo 2 de 4"))

    def test_advancing_moves_through_the_pages_and_the_stepper(self):
        wizard, service = self._wizard()
        self._advance_to_sources(wizard)
        self.assertIs(wizard.current_page(), wizard.sources_page)
        self.assertEqual(wizard.stepper.current(), 2)
        self.assertEqual([wizard.stepper.state_of(i) for i in range(4)], ["done", "done", "current", "pending"])
        self.assertEqual(service.items_calls, [9])
        self.assertEqual(len(service.availability_calls), 1)
        self.assertFalse(wizard.back_button.isHidden())
        self.assertFalse(wizard.next_button.isEnabled())

    def test_the_footer_summarizes_the_current_step(self):
        wizard, _ = self._wizard()
        wizard.destination_page.table.selectRow(1)
        self.assertIn("CP05401", wizard.summary_label.text())
        wizard._next()
        self.assertEqual(wizard.summary_label.text(), "Nenhum item selecionado.")
        wizard.items_page.select_all_button.click()
        self.assertEqual(wizard.summary_label.text(), "2 de 2 item(ns) selecionado(s)")

    def test_back_keeps_what_was_chosen(self):
        wizard, service = self._wizard()
        self._advance_to_sources(wizard)
        wizard.sources_page.suggest_button.click()
        wizard._back()
        self.assertIs(wizard.current_page(), wizard.items_page)
        wizard._back()
        self.assertIs(wizard.current_page(), wizard.destination_page)
        self.assertEqual(wizard.destination_page.selected_row()["id"], 9)
        self.assertEqual(sorted(wizard.state.selected_item_ids), [101, 102])
        self.assertEqual(len(service.items_calls), 1)  # voltar nao recarrega

    def test_clicking_a_finished_step_in_the_stepper_goes_back_to_it(self):
        wizard, _ = self._wizard()
        self._advance_to_sources(wizard)
        wizard.stepper.step_clicked.emit(1)
        self.assertIs(wizard.current_page(), wizard.items_page)
        wizard.stepper.step_clicked.emit(3)  # passo que ainda nao foi feito: ignora
        self.assertIs(wizard.current_page(), wizard.items_page)

    def test_going_forward_again_reloads_with_what_was_kept(self):
        wizard, service = self._wizard()
        self._advance_to_sources(wizard)
        wizard.sources_page.suggest_button.click()
        wizard._back()
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.sources_page)
        self.assertEqual(len(service.availability_calls), 2)
        self.assertTrue(wizard.sources_page.is_valid())

    def test_choosing_another_destination_discards_items_and_origins(self):
        wizard, service = self._wizard()
        self._advance_to_sources(wizard)
        wizard.sources_page.suggest_button.click()
        wizard.stepper.step_clicked.emit(0)
        wizard.destination_page.table.selectRow(1)
        wizard._next()
        self.assertEqual(wizard.state.destination_proposal_id, 10)
        self.assertEqual(wizard.state.item_selections, [])
        self.assertFalse(wizard.items_page.is_valid())
        wizard.items_page.select_all_button.click()
        wizard._next()
        self.assertFalse(wizard.sources_page.is_valid())

    def test_complete_flow_confirms_once_and_accepts(self):
        wizard, service = self._wizard()
        self._advance_to_sources(wizard)
        wizard.sources_page.suggest_button.click()
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertEqual(wizard.next_button.text(), "Confirmar remanejamento")
        self.assertFalse(wizard.next_button.isEnabled())  # falta o motivo
        wizard.review_page.reason_edit.setPlainText("Antecipar entrega")
        self.assertTrue(wizard.next_button.isEnabled())
        with patch.object(review_module.QMessageBox, "question", return_value=review_module.QMessageBox.Yes):
            wizard._next()
        self.assertEqual(wizard.result(), QDialog.Accepted)
        self.assertEqual(len(service.confirm_calls), 1)
        self.assertEqual(wizard.confirm_result, service.confirm_response)

    def test_a_failed_confirmation_keeps_the_window_open_on_the_review(self):
        wizard, service = self._wizard()
        self._advance_to_sources(wizard)
        wizard.sources_page.suggest_button.click()
        wizard._next()
        wizard.review_page.reason_edit.setPlainText("Antecipar entrega")
        service.confirm_error = RuntimeError("Saldo mudou")
        with patch.object(review_module.QMessageBox, "question", return_value=review_module.QMessageBox.Yes), \
                patch.object(review_module.QMessageBox, "warning", return_value=None):
            wizard._next()
        self.assertNotEqual(wizard.result(), QDialog.Accepted)
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertTrue(wizard.next_button.isEnabled())

    def test_closing_without_choices_does_not_ask_anything(self):
        wizard, _ = self._wizard()
        closed = []
        wizard.rejected.connect(lambda: closed.append(True))
        with patch.object(dialog_module.QMessageBox, "question") as question:
            wizard.reject()
        question.assert_not_called()
        self.assertEqual(closed, [True])

    def test_closing_with_choices_asks_and_can_be_cancelled(self):
        wizard, service = self._wizard()
        closed = []
        wizard.rejected.connect(lambda: closed.append(True))
        self._advance_to_sources(wizard)
        with patch.object(dialog_module.QMessageBox, "question", return_value=dialog_module.QMessageBox.No) as question:
            wizard.reject()
        question.assert_called_once()
        self.assertEqual(closed, [])
        with patch.object(dialog_module.QMessageBox, "question", return_value=dialog_module.QMessageBox.Yes):
            wizard.reject()
        self.assertEqual(closed, [True])
        self.assertEqual(service.confirm_calls, [])

    def test_the_close_button_uses_the_same_confirmation(self):
        wizard, _ = self._wizard()
        self._advance_to_sources(wizard)
        with patch.object(dialog_module.QMessageBox, "question", return_value=dialog_module.QMessageBox.No) as question:
            wizard.close_button.click()
        question.assert_called_once()

    def test_double_click_on_a_proposal_advances_to_the_items(self):
        wizard, _ = self._wizard()
        wizard.destination_page.table.selectRow(0)
        wizard.destination_page.table.itemDoubleClicked.emit(wizard.destination_page.table.item(0, 0))
        self.assertIs(wizard.current_page(), wizard.items_page)

    def test_next_is_not_enabled_twice_while_committing(self):
        wizard, _ = self._wizard()
        wizard.destination_page.table.selectRow(0)
        seen = []
        original = wizard.destination_page.commit

        def watching_commit():
            seen.append(wizard.next_button.isEnabled())
            return original()

        wizard.destination_page.commit = watching_commit
        wizard._next()
        self.assertEqual(seen, [False])

    def test_a_page_that_fails_to_load_shows_the_error_and_allows_going_back(self):
        service = FakeWizardService()
        service.items_error = RuntimeError("falhou")
        wizard, _ = self._wizard(service)
        wizard.destination_page.table.selectRow(0)
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.items_page)
        self.assertEqual(wizard.items_page.load_error, "falhou")
        self.assertFalse(wizard.next_button.isEnabled())
        wizard._back()
        self.assertIs(wizard.current_page(), wizard.destination_page)


class WizardStepperTests(QtCase):
    def test_states_follow_the_current_step(self):
        stepper = WizardStepper(["A", "B", "C"])
        self.assertEqual([stepper.state_of(i) for i in range(3)], ["current", "pending", "pending"])
        stepper.set_current(2)
        self.assertEqual([stepper.state_of(i) for i in range(3)], ["done", "done", "current"])
        self.assertEqual(stepper.accessible_text(), "Passo 3 de 3: C")

    def test_current_is_kept_inside_the_range(self):
        stepper = WizardStepper(["A", "B"])
        stepper.set_current(9)
        self.assertEqual(stepper.current(), 1)
        stepper.set_current(-3)
        self.assertEqual(stepper.current(), 0)

    def _click(self, stepper, x):
        event = QMouseEvent(QEvent.MouseButtonRelease, QPointF(x, 10), QPointF(x, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        stepper.mouseReleaseEvent(event)

    def test_only_finished_steps_are_clickable(self):
        stepper = WizardStepper(["A", "B", "C"])
        stepper.resize(300, 48)
        stepper.set_current(2)
        clicked = []
        stepper.step_clicked.connect(clicked.append)
        self._click(stepper, 10)    # A (feito)
        self._click(stepper, 110)   # B (feito)
        self._click(stepper, 250)   # C (atual)
        self.assertEqual(clicked, [0, 1])


if __name__ == "__main__":
    unittest.main()
