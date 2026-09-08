from __future__ import annotations

import unittest

from api.app.core.config import (
    API_CONTRACT_VERSION,
    API_VERSION,
    EXPECTED_DATABASE_REVISION,
    MAXIMUM_DESKTOP_VERSION,
    MINIMUM_DESKTOP_VERSION,
    RECOMMENDED_DESKTOP_VERSION,
)
from api.app.core.versioning import (
    CompatibilityPolicy,
    CompatibilityStatus,
    SemVer,
    compare_versions,
    evaluate_desktop,
    get_api_contract_version,
    get_compatibility_policy,
    get_database_schema_version,
    get_server_version,
    is_version_at_least,
    is_version_newer,
    parse_version,
)


class ParseVersionTests(unittest.TestCase):
    def test_accepts_valid_semver(self):
        self.assertEqual(parse_version("3.2.0"), SemVer(3, 2, 0))
        self.assertEqual(parse_version(API_VERSION), parse_version(API_VERSION))

    def test_rejects_invalid_versions(self):
        for invalid in ("", "   ", "3.2", "3.2.x", "-1.0.0"):
            with self.assertRaises(ValueError):
                parse_version(invalid)

    def test_semver_rejects_negative_components(self):
        with self.assertRaises(ValueError):
            SemVer(1, -2, 0)


class CompareVersionsTests(unittest.TestCase):
    def test_compares_numerically_not_lexicographically(self):
        self.assertEqual(compare_versions("3.10.0", "3.9.0"), 1)
        self.assertEqual(compare_versions("3.9.0", "3.10.0"), -1)

    def test_compares_major_minor_patch(self):
        self.assertEqual(compare_versions("1.0.0", "0.9.9"), 1)
        self.assertEqual(compare_versions("1.1.0", "1.0.9"), 1)
        self.assertEqual(compare_versions("1.0.1", "1.0.0"), 1)

    def test_recognizes_equality(self):
        self.assertEqual(compare_versions("0.8.0", "0.8.0"), 0)

    def test_is_version_at_least_and_newer(self):
        self.assertTrue(is_version_at_least("2.0.0", "1.9.0"))
        self.assertFalse(is_version_at_least("1.8.0", "1.9.0"))
        self.assertTrue(is_version_newer("2.0.0", "1.9.0"))
        self.assertFalse(is_version_newer("1.9.0", "1.9.0"))


class AccessorTests(unittest.TestCase):
    def test_get_server_version_matches_config_and_is_valid_semver(self):
        self.assertEqual(get_server_version(), API_VERSION)
        parse_version(get_server_version())

    def test_get_api_contract_version_matches_config(self):
        self.assertEqual(get_api_contract_version(), API_CONTRACT_VERSION)
        self.assertTrue(get_api_contract_version().strip())

    def test_get_database_schema_version_resolves_without_touching_database(self):
        # Deve refletir a revisao Alembic esperada (fonte de verdade estatica),
        # sem executar nenhuma query ou migration.
        self.assertEqual(get_database_schema_version(), EXPECTED_DATABASE_REVISION)


class CompatibilityPolicyTests(unittest.TestCase):
    def test_get_compatibility_policy_reflects_config(self):
        policy = get_compatibility_policy()
        self.assertEqual(policy.minimum_desktop_version, MINIMUM_DESKTOP_VERSION)
        self.assertEqual(policy.recommended_desktop_version, RECOMMENDED_DESKTOP_VERSION)
        self.assertEqual(policy.server_version, API_VERSION)
        self.assertEqual(policy.api_contract_version, API_CONTRACT_VERSION)
        self.assertEqual(policy.database_schema_version, EXPECTED_DATABASE_REVISION)
        self.assertEqual(policy.maximum_desktop_version, MAXIMUM_DESKTOP_VERSION)

    def test_rejects_invalid_policy_fields(self):
        with self.assertRaises(ValueError):
            CompatibilityPolicy(
                minimum_desktop_version="not-a-version",
                recommended_desktop_version="3.2.0",
                server_version="0.8.0",
                api_contract_version="v1",
                database_schema_version="27",
            )
        with self.assertRaises(ValueError):
            CompatibilityPolicy(
                minimum_desktop_version="3.1.0",
                recommended_desktop_version="3.2.0",
                server_version="0.8.0",
                api_contract_version="",
                database_schema_version="27",
            )


class EvaluateDesktopTests(unittest.TestCase):
    def setUp(self):
        self.policy = CompatibilityPolicy(
            minimum_desktop_version="3.1.0",
            recommended_desktop_version="3.2.0",
            server_version="3.2.0",
            api_contract_version="v1",
            database_schema_version="27",
        )

    def test_compatible_at_recommended(self):
        self.assertEqual(evaluate_desktop(self.policy, "3.2.0"), CompatibilityStatus.COMPATIBLE)

    def test_update_available_between_minimum_and_recommended(self):
        self.assertEqual(evaluate_desktop(self.policy, "3.1.5"), CompatibilityStatus.UPDATE_AVAILABLE)

    def test_update_required_below_minimum(self):
        self.assertEqual(evaluate_desktop(self.policy, "3.0.9"), CompatibilityStatus.UPDATE_REQUIRED)

    def test_incompatible_above_maximum(self):
        policy = CompatibilityPolicy(
            minimum_desktop_version="3.1.0",
            recommended_desktop_version="3.2.0",
            server_version="3.2.0",
            api_contract_version="v1",
            database_schema_version="27",
            maximum_desktop_version="3.5.0",
        )
        self.assertEqual(evaluate_desktop(policy, "4.0.0"), CompatibilityStatus.INCOMPATIBLE)


if __name__ == "__main__":
    unittest.main()
