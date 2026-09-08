from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.icons import AppIcons, icon_provider
from app.ui.icons.icon_registry import ICON_REGISTRY, LUCIDE_DIR
from app.ui.status_dialog import ManualStatusDialog, ProductionPauseDialog, StatusDialog


def _production_actions(status: str) -> list[dict]:
    """Mirrors BackendAdapter.process_actions()'s PRODUCAO branch
    (app/services/backend_adapter.py:1122-1139) exactly, so the dialog is
    exercised with realistic action-list shapes without needing a real DB."""
    actions: list[dict] = []

    def add(action_id, label, icon, status_value=""):
        actions.append({"id": action_id, "label": label, "icon": icon, "status": status_value, "area": "PRODUCAO"})

    if status != "FINALIZADO":
        add("DEFINE_ITEM_FLOW", "Definir fluxo dos itens", "settings")
    if status in ("NAO_INICIADO", "LIBERADO_PRODUCAO", "ITEM_PENDENTE_FABRICACAO", "PARADO"):
        add("STATUS", "Retomar producao" if status == "PARADO" else "Iniciar producao", "production", "INICIADO")
    if status == "INICIADO":
        add("STATUS", "Pausar producao", "pause", "PARADO")
    if status in ("INICIADO", "FINALIZADO_PARCIAL"):
        add("REGISTER_PRODUCTION", "Registrar producao", "status")
    if status != "FINALIZADO":
        add("EDIT_ITEM_WEIGHTS", "Informar pesos dos itens", "edit")
    return actions


class FakeService:
    def __init__(self, status: str, palette_name: str = "claro", admin: bool = False):
        self.status = status
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self._admin = admin
        self.admin_calls = []

    def get_process_dict(self, process_id):
        return {"id": process_id, "proposta": "CP05385", "cliente": "MNS ENGENHARIA"}

    def get_process_area_dict(self, process_id, area):
        return self.get_process_dict(process_id)

    def current_location(self, process):
        return ("PRODUCAO", "Producao", self.status)

    def status_for_area(self, process, area):
        return self.status

    def area_status_label(self, area, status):
        return status.replace("_", " ").title()

    def process_actions(self, process_id, area):
        return _production_actions(self.status)

    def can_admin(self):
        return self._admin

    def administrative_correction_options(self, process_id):
        self.admin_calls.append(("options", process_id))
        return {
            "version": 8,
            "current_state": {
                "current_area": "PRODUCAO",
                "current_status": "FINALIZADO",
                "production_status": "FINALIZADO",
                "galvanization_status": None,
                "shipping_status": None,
                "fiscal_status": None,
            },
            "options": [
                {
                    "target_area": "EXPEDICAO",
                    "target_status": "EM_SEPARACAO",
                    "label": "Expedicao / Em Separacao",
                }
            ],
        }

    def preview_administrative_correction(self, process_id, expected_version, area, status):
        self.admin_calls.append(("preview", process_id, expected_version, area, status))
        return {
            "allowed": True,
            "changes": [{"field": "current_area", "before": "PRODUCAO", "after": "EXPEDICAO"}],
            "unchanged_fields": ["quantidades produzidas", "cargas", "entregas", "Fiscal"],
            "effects": ["A fila da proposta sera atualizada."],
            "blockers": [],
        }

    def administrative_correction(self, process_id, expected_version, area, status, reason, idempotency_key):
        self.admin_calls.append(("apply", process_id, expected_version, area, status, reason, idempotency_key))


class StatusDialogPrimaryActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build(self, status: str, **kwargs) -> StatusDialog:
        service = FakeService(status, **kwargs)
        return StatusDialog(service, 1, "PRODUCAO")

    def _action_types(self, dialog: StatusDialog) -> dict[str, str]:
        actions = dialog.service.process_actions(dialog.process_id, dialog.area)
        primary_index = dialog._primary_action_index(actions)
        return {
            action["label"]: dialog._action_type(action, index, primary_index)
            for index, action in enumerate(actions)
        }

    def test_awaiting_start_makes_start_production_primary(self):
        for status in ("NAO_INICIADO", "LIBERADO_PRODUCAO"):
            with self.subTest(status=status):
                dialog = self._build(status)
                types = self._action_types(dialog)
                self.assertEqual(types["Iniciar producao"], "primary")
                self.assertEqual(types["Definir fluxo dos itens"], "secondary")
                self.assertEqual(types["Informar pesos dos itens"], "secondary")

    def test_in_progress_makes_register_production_primary(self):
        dialog = self._build("INICIADO")
        types = self._action_types(dialog)
        self.assertEqual(types["Registrar producao"], "primary")
        self.assertEqual(types["Pausar producao"], "warning")
        self.assertEqual(types["Definir fluxo dos itens"], "secondary")

    def test_paused_makes_resume_production_primary(self):
        dialog = self._build("PARADO")
        types = self._action_types(dialog)
        self.assertEqual(types["Retomar producao"], "primary")
        self.assertEqual(types["Definir fluxo dos itens"], "secondary")

    def test_productive_transition_actions_match_each_state(self):
        transition_labels = {"Iniciar producao", "Pausar producao", "Retomar producao", "Registrar producao"}
        expected = {
            "NAO_INICIADO": {"Iniciar producao"},
            "INICIADO": {"Pausar producao", "Registrar producao"},
            "PARADO": {"Retomar producao"},
            "FINALIZADO": set(),
        }
        for status, labels in expected.items():
            with self.subTest(status=status):
                actual = {action["label"] for action in _production_actions(status)} & transition_labels
                self.assertEqual(actual, labels)

    def test_undefined_flow_status_still_renders_without_crash(self):
        dialog = self._build("ITEM_PENDENTE_FABRICACAO")
        self.assertTrue(any(b.isEnabled() for b in dialog._action_buttons))


class StatusDialogIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_action_icon_resolves_via_lucide_never_procedural_fallback(self):
        for status in ("NAO_INICIADO", "LIBERADO_PRODUCAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL"):
            for action in _production_actions(status):
                with self.subTest(status=status, action=action["id"], target=action.get("status")):
                    resolved = StatusDialog._action_icon(action)
                    # _action_icon so devolve um AppIcons (override) ou a
                    # string crua do backend; se for AppIcons, tem que
                    # existir de verdade no registro Lucide.
                    if resolved in ICON_REGISTRY:
                        slug = ICON_REGISTRY[resolved]
                        self.assertTrue((LUCIDE_DIR / f"{slug}.svg").exists())

    def test_icon_pixmap_has_no_clipping_devicepixelratio(self):
        pixmap = icon_provider.render_pixmap(AppIcons.WORKFLOW, 20, "#123456")
        self.assertIsNotNone(pixmap)
        self.assertEqual(pixmap.devicePixelRatio(), 1.0)


class StatusDialogAdminCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_admin_button_hidden_without_permission(self):
        service = FakeService("INICIADO", admin=False)
        dialog = StatusDialog(service, 1, "PRODUCAO")
        from PySide6.QtWidgets import QPushButton

        labels = [btn.text() for btn in dialog.findChildren(QPushButton)]
        self.assertNotIn("Correcao administrativa", labels)

    def test_admin_button_visible_with_permission(self):
        service = FakeService("INICIADO", admin=True)
        dialog = StatusDialog(service, 1, "PRODUCAO")
        from PySide6.QtWidgets import QPushButton

        labels = [btn.text() for btn in dialog.findChildren(QPushButton)]
        self.assertIn("Correcao administrativa", labels)

    def test_manual_correction_uses_only_api_options_preview_version_and_idempotency(self):
        service = FakeService("FINALIZADO", admin=True)
        dialog = ManualStatusDialog(service, 1, "PRODUCAO")

        self.assertFalse(hasattr(dialog, "area_combo"))
        self.assertEqual(dialog.option_combo.count(), 1)
        self.assertIn("current_area", dialog.impact.toPlainText())
        self.assertIn(("options", 1), service.admin_calls)
        self.assertIn(("preview", 1, 8, "EXPEDICAO", "EM_SEPARACAO"), service.admin_calls)

        dialog.reason.setPlainText("  Falha de sincronizacao  ")
        with patch("app.ui.status_dialog.QMessageBox.question", return_value=QMessageBox.Yes):
            dialog.save()
        apply = next(call for call in service.admin_calls if call[0] == "apply")
        self.assertEqual(apply[1:6], (1, 8, "EXPEDICAO", "EM_SEPARACAO", "Falha de sincronizacao"))
        self.assertGreaterEqual(len(apply[6]), 8)
        self.assertEqual(dialog.result(), QDialog.Accepted)


class StatusDialogThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_light_and_dark_theme_apply_correct_palette(self):
        light = StatusDialog(FakeService("INICIADO", palette_name="claro"), 1, "PRODUCAO")
        dark = StatusDialog(FakeService("INICIADO", palette_name="escuro"), 1, "PRODUCAO")
        self.assertEqual(light.service.palette["accent"], OFFICIAL_COLOR_PALETTES["claro"]["accent"])
        self.assertEqual(dark.service.palette["accent"], OFFICIAL_COLOR_PALETTES["escuro"]["accent"])
        self.assertNotEqual(light.service.palette["accent"], dark.service.palette["accent"])


class StatusDialogKeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_primary_card_receives_initial_focus(self):
        dialog = StatusDialog(FakeService("NAO_INICIADO"), 1, "PRODUCAO")
        # setFocus() numa janela ainda nao mostrada define o "foco logico"
        # (focusWidget()); hasFocus() so fica True apos show()+ativacao da
        # janela, entao verificamos o proxy logico aqui.
        self.assertIn(dialog.focusWidget(), dialog._action_buttons)

    def test_escape_closes_without_running_any_action(self):
        dialog = StatusDialog(FakeService("NAO_INICIADO"), 1, "PRODUCAO")
        calls = []
        original = dialog.run_action
        dialog.run_action = lambda action: calls.append(action) or original(action)
        dialog.show()
        from PySide6.QtTest import QTest

        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertEqual(calls, [])
        self.assertFalse(dialog.isVisible())


class ProductionPauseDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reason_is_mandatory_and_trimmed(self):
        dialog = ProductionPauseDialog()
        dialog.reason.setPlainText("   ")
        with patch("app.ui.status_dialog.QMessageBox.warning") as warning:
            dialog._accept_pause()
        warning.assert_called_once()
        self.assertEqual(dialog.result(), QDialog.Rejected)

        dialog.reason.setPlainText("  Aguardando materia-prima  ")
        dialog._accept_pause()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.pause_reason, "Aguardando materia-prima")


if __name__ == "__main__":
    unittest.main()
