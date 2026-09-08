from __future__ import annotations

import os
import unittest
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from app.services.nomus_api_importer import NomusApiOrderNotFoundError
from app.services.proposal_import.schemas import (
    FieldConfidence,
    ImportedProposalData,
    ImportedProposalItem,
    ProposalImportMetadata,
    StandardProposalImportResult,
)
from app.ui.nomus_api_import_dialog import NomusApiImportDialog


class FakeStore:
    def __init__(self, *, enabled=True, configured=True):
        self.enabled = enabled
        self.configured = configured

    def load_settings(self):
        return type(
            "Settings",
            (),
            {
                "enabled": self.enabled,
                "base_url": "https://nomus.example/rest",
                "api_key_configured": self.configured,
            },
        )()


class FakeImporter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def fetch_proposal(self, identifier):
        self.calls.append(identifier)
        if self.error:
            raise self.error
        return self.result


def standard_result() -> StandardProposalImportResult:
    confidence = FieldConfidence("proposal_number", Decimal("0.96"), "teste", "nomus_api")
    return StandardProposalImportResult(
        proposal=ImportedProposalData(
            proposal_number="CP05252",
            raw_budget_number="CP05252",
            proposal_date=date(2026, 6, 19),
            client="MNS ENGENHARIA",
            site="OBRA TESTE",
            deadline_raw="10 DIAS",
        ),
        items=[
            ImportedProposalItem(
                item_number=1,
                product_code="450.983",
                description="ITEM OPERACIONAL",
                quantity=Decimal("1"),
                unit="UNIDADE",
                total_weight=Decimal("63"),
            )
        ],
        field_confidences={"proposal_number": confidence},
        overall_confidence=Decimal("0.92"),
        metadata=ProposalImportMetadata(source="nomus_api", extraction_method="nomus_api_get"),
    )


class NomusApiImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_success_returns_conference_payload_without_internet(self):
        importer = FakeImporter(result=standard_result())
        dialog = NomusApiImportDialog(
            config_store=FakeStore(),
            importer_factory=lambda: importer,
            synchronous=True,
        )
        try:
            dialog.identifier.setText("CP05252")
            dialog.start_lookup()

            self.assertEqual(importer.calls, ["CP05252"])
            self.assertEqual(dialog.result(), QDialog.Accepted)
            self.assertIsNotNone(dialog.preview_payload)
            self.assertEqual(dialog.preview_payload["source"], "nomus_api")
            self.assertEqual(dialog.preview_payload["items"][0]["product_code"], "450.983")
            self.assertNotIn("api", dialog.preview_payload.get("warnings", []))
        finally:
            dialog.close()

    def test_configuration_disabled_blocks_lookup(self):
        importer = FakeImporter(result=standard_result())
        dialog = NomusApiImportDialog(
            config_store=FakeStore(enabled=False),
            importer_factory=lambda: importer,
            synchronous=True,
        )
        try:
            dialog.identifier.setText("CP05252")
            dialog.start_lookup()

            self.assertEqual(importer.calls, [])
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
            self.assertIn("desativada", dialog.status.text().lower())
        finally:
            dialog.close()

    def test_not_found_error_is_friendly(self):
        importer = FakeImporter(error=NomusApiOrderNotFoundError("detalhe tecnico"))
        dialog = NomusApiImportDialog(
            config_store=FakeStore(),
            importer_factory=lambda: importer,
            synchronous=True,
        )
        try:
            dialog.identifier.setText("CP00000")
            dialog.start_lookup()

            self.assertIn("nenhuma proposta", dialog.status.text().lower())
            self.assertNotIn("detalhe tecnico", dialog.status.text().lower())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
