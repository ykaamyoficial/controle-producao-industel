from __future__ import annotations

import unittest

from api.app.core import config as api_config
from app.integrations.api.compatibility import REQUIRED_FEATURES
from app.version import APP_VERSION, MINIMUM_API_VERSION
from app.versioning.parser import compare_versions


class VersionPolicyConsistencyTests(unittest.TestCase):
    """Politica de compatibilidade Desktop <-> API: as duas pontas precisam concordar."""

    def test_minimum_api_version_is_not_above_api_version(self):
        self.assertLessEqual(compare_versions(MINIMUM_API_VERSION, api_config.API_VERSION), 0)

    def test_api_accepts_this_desktop(self):
        self.assertLessEqual(compare_versions(api_config.MINIMUM_DESKTOP_VERSION, APP_VERSION), 0)

    def test_recommended_desktop_is_not_below_minimum(self):
        self.assertGreaterEqual(
            compare_versions(api_config.RECOMMENDED_DESKTOP_VERSION, api_config.MINIMUM_DESKTOP_VERSION), 0,
        )

    def test_api_declares_every_feature_the_desktop_requires(self):
        self.assertEqual(REQUIRED_FEATURES - set(api_config.SUPPORTED_FEATURES), set())


if __name__ == "__main__":
    unittest.main()
