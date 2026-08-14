from __future__ import annotations

import unittest

from app.integrations.api.models import SystemCompatibilityDto
from app.services.compatibility_check import CompatibilityCheckResult
from app.services.session_policy_monitor import classify_session_policy_action
from app.versioning.models import CompatibilityStatus


def _dto(**overrides) -> SystemCompatibilityDto:
    base = dict(
        server_version="3.2.0", api_contract_version="v1", database_revision="rev1",
        minimum_desktop_version="3.1.0", recommended_desktop_version="3.2.0", maintenance_mode=False,
    )
    base.update(overrides)
    return SystemCompatibilityDto(**base)


class ClassifySessionPolicyActionTests(unittest.TestCase):
    def test_compatible_never_shows_a_banner(self):
        result = CompatibilityCheckResult(CompatibilityStatus.COMPATIBLE, "3.2.0")
        action = classify_session_policy_action(result)
        self.assertFalse(action.show_banner)

    def test_update_available_shows_info_banner(self):
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_AVAILABLE, "3.1.5")
        action = classify_session_policy_action(result)
        self.assertTrue(action.show_banner)
        self.assertEqual(action.severity, "info")

    def test_update_recommended_shows_warning_banner(self):
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_RECOMMENDED, "3.1.5")
        action = classify_session_policy_action(result)
        self.assertTrue(action.show_banner)
        self.assertEqual(action.severity, "warning")

    def test_update_required_shows_blocking_banner_with_save_and_restart_guidance(self):
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0")
        action = classify_session_policy_action(result)
        self.assertTrue(action.show_banner)
        self.assertEqual(action.severity, "blocking")
        self.assertIn("salve", action.banner_text.lower())

    def test_incompatible_shows_blocking_banner(self):
        result = CompatibilityCheckResult(CompatibilityStatus.INCOMPATIBLE, "3.0.0")
        action = classify_session_policy_action(result)
        self.assertTrue(action.show_banner)
        self.assertEqual(action.severity, "blocking")

    def test_maintenance_is_silent_never_alarms_on_every_poll(self):
        result = CompatibilityCheckResult(CompatibilityStatus.MAINTENANCE, "3.0.0")
        action = classify_session_policy_action(result)
        self.assertFalse(action.show_banner)

    def test_check_failed_is_silent_transient_network_noise(self):
        result = CompatibilityCheckResult(CompatibilityStatus.CHECK_FAILED, "3.0.0")
        action = classify_session_policy_action(result)
        self.assertFalse(action.show_banner)

    def test_server_message_is_appended_when_present(self):
        dto = _dto(message="Corrija uma vulnerabilidade critica.")
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0", dto=dto)
        action = classify_session_policy_action(result)
        self.assertIn("Corrija uma vulnerabilidade critica.", action.banner_text)

    def test_no_server_message_does_not_append_empty_suffix(self):
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_RECOMMENDED, "3.1.5", dto=_dto(message=""))
        action = classify_session_policy_action(result)
        self.assertFalse(action.banner_text.endswith(" "))


if __name__ == "__main__":
    unittest.main()
