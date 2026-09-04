from __future__ import annotations

import unittest

from app.main import run_startup_bootstrap
from app.services.bootstrap_service import BootstrapErrorCode, BootstrapResult, BootstrapState


def _needs_configuration_runner():
    return BootstrapResult(BootstrapState.NEEDS_CONFIGURATION, None, BootstrapErrorCode.CONFIG_MISSING, "none")


class DummyBootstrapDialog:
    calls: list = []

    def __init__(self, parent=None, *, proceed: bool):
        self.parent = parent
        self.proceed = proceed
        DummyBootstrapDialog.calls.append(self)

    def exec(self):
        return 0


def _dialog_factory(*, proceed: bool):
    def factory(parent=None):
        return DummyBootstrapDialog(parent, proceed=proceed)

    return factory


class RunStartupBootstrapTests(unittest.TestCase):
    """Testa app.main.run_startup_bootstrap via injecao de dependencia, sem Qt
    real (mesmo idioma de tests/test_startup_compatibility_check.py)."""

    def setUp(self):
        DummyBootstrapDialog.calls.clear()

    def test_proceeds_when_dialog_reports_proceed_true(self):
        proceed = run_startup_bootstrap(
            dialog_factory=_dialog_factory(proceed=True), bootstrap_runner=_needs_configuration_runner,
        )
        self.assertTrue(proceed)
        self.assertEqual(len(DummyBootstrapDialog.calls), 1)

    def test_blocks_when_dialog_reports_proceed_false(self):
        proceed = run_startup_bootstrap(
            dialog_factory=_dialog_factory(proceed=False), bootstrap_runner=_needs_configuration_runner,
        )
        self.assertFalse(proceed)

    def test_defaults_to_false_when_dialog_lacks_proceed_attribute(self):
        class BareDialog:
            def __init__(self, parent=None):
                pass

            def exec(self):
                return 0

        proceed = run_startup_bootstrap(
            dialog_factory=lambda parent=None: BareDialog(parent), bootstrap_runner=_needs_configuration_runner,
        )
        self.assertFalse(proceed)

    def test_proceeds_silently_without_dialog_when_bootstrap_is_ready(self):
        def ready_runner():
            return BootstrapResult(BootstrapState.READY_FOR_LOGIN, "https://api.local", BootstrapErrorCode.READY, "persisted")

        proceed = run_startup_bootstrap(dialog_factory=_dialog_factory(proceed=False), bootstrap_runner=ready_runner)
        self.assertTrue(proceed)
        self.assertEqual(len(DummyBootstrapDialog.calls), 0)

    def test_falls_back_to_dialog_when_silent_bootstrap_raises(self):
        def raising_runner():
            raise RuntimeError("boom")

        proceed = run_startup_bootstrap(dialog_factory=_dialog_factory(proceed=True), bootstrap_runner=raising_runner)
        self.assertTrue(proceed)
        self.assertEqual(len(DummyBootstrapDialog.calls), 1)


if __name__ == "__main__":
    unittest.main()
