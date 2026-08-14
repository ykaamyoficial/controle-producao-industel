from __future__ import annotations

import unittest

from app.main import run_startup_bootstrap


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
        proceed = run_startup_bootstrap(dialog_factory=_dialog_factory(proceed=True))
        self.assertTrue(proceed)
        self.assertEqual(len(DummyBootstrapDialog.calls), 1)

    def test_blocks_when_dialog_reports_proceed_false(self):
        proceed = run_startup_bootstrap(dialog_factory=_dialog_factory(proceed=False))
        self.assertFalse(proceed)

    def test_defaults_to_false_when_dialog_lacks_proceed_attribute(self):
        class BareDialog:
            def __init__(self, parent=None):
                pass

            def exec(self):
                return 0

        proceed = run_startup_bootstrap(dialog_factory=lambda parent=None: BareDialog(parent))
        self.assertFalse(proceed)


if __name__ == "__main__":
    unittest.main()
