from __future__ import annotations

import unittest

from app.version import APP_VERSION
from app.versioning import (
    CompatibilityPolicy,
    CompatibilityStatus,
    SemVer,
    SystemVersionInfo,
    build_system_version_info,
    compare_versions,
    evaluate_desktop,
    get_desktop_version,
    is_version_at_least,
    is_version_newer,
    parse_version,
)


class ParseVersionTests(unittest.TestCase):
    def test_accepts_valid_semver(self):
        self.assertEqual(parse_version("3.2.0"), SemVer(3, 2, 0))
        self.assertEqual(parse_version("0.8.0"), SemVer(0, 8, 0))
        self.assertEqual(parse_version("v4.0.0"), SemVer(4, 0, 0))

    def test_rejects_invalid_versions(self):
        for invalid in ("", "   ", "3.2", "3.2.a", "3.2.0.1", "-1.0.0", "abc", None):
            with self.assertRaises(ValueError):
                parse_version(invalid)  # type: ignore[arg-type]

    def test_semver_rejects_negative_components(self):
        with self.assertRaises(ValueError):
            SemVer(-1, 0, 0)


class CompareVersionsTests(unittest.TestCase):
    def test_compares_numerically_not_lexicographically(self):
        # "3.10.0" > "3.9.0" numericamente, embora "3.10.0" < "3.9.0" como string.
        self.assertEqual(compare_versions("3.10.0", "3.9.0"), 1)
        self.assertEqual(compare_versions("3.9.0", "3.10.0"), -1)

    def test_compares_major_minor_patch_independently(self):
        self.assertEqual(compare_versions("4.0.0", "3.9.9"), 1)
        self.assertEqual(compare_versions("3.3.0", "3.2.9"), 1)
        self.assertEqual(compare_versions("3.2.1", "3.2.0"), 1)

    def test_recognizes_equality(self):
        self.assertEqual(compare_versions("3.2.0", "3.2.0"), 0)
        self.assertEqual(compare_versions("v3.2.0", "3.2.0"), 0)

    def test_is_version_at_least(self):
        self.assertTrue(is_version_at_least("3.2.0", "3.1.0"))
        self.assertTrue(is_version_at_least("3.1.0", "3.1.0"))
        self.assertFalse(is_version_at_least("3.0.9", "3.1.0"))

    def test_is_version_newer(self):
        self.assertTrue(is_version_newer("2.4.1", "2.4.0"))
        self.assertFalse(is_version_newer("2.4.0", "2.4.0"))
        self.assertFalse(is_version_newer("2.3.9", "2.4.0"))


class SystemVersionInfoTests(unittest.TestCase):
    def test_serializes_to_dict(self):
        info = SystemVersionInfo(
            desktop_version="2.5.2",
            server_version="0.8.0",
            api_contract_version="v1",
            database_schema_version="20260810_0015",
        )
        self.assertEqual(
            info.to_dict(),
            {
                "desktop_version": "2.5.2",
                "server_version": "0.8.0",
                "api_contract_version": "v1",
                "database_schema_version": "20260810_0015",
            },
        )

    def test_rejects_empty_fields(self):
        with self.assertRaises(ValueError):
            SystemVersionInfo(
                desktop_version="2.5.2",
                server_version="0.8.0",
                api_contract_version="",
                database_schema_version="20260810_0015",
            )

    def test_rejects_invalid_desktop_version_format(self):
        with self.assertRaises(ValueError):
            SystemVersionInfo(
                desktop_version="not-a-version",
                server_version="0.8.0",
                api_contract_version="v1",
                database_schema_version="20260810_0015",
            )

    def test_build_system_version_info_uses_central_desktop_version(self):
        info = build_system_version_info(
            server_version="0.8.0",
            api_contract_version="v1",
            database_schema_version="20260810_0015",
        )
        self.assertEqual(info.desktop_version, APP_VERSION)


class GetDesktopVersionTests(unittest.TestCase):
    def test_returns_app_version_and_validates_it(self):
        self.assertEqual(get_desktop_version(), APP_VERSION)
        parse_version(get_desktop_version())  # nao deve levantar


class CompatibilityPolicyEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.policy = CompatibilityPolicy(
            minimum_desktop_version="3.1.0",
            recommended_desktop_version="3.2.0",
            server_version="3.2.0",
            api_contract_version="v1",
            database_schema_version="27",
            maximum_desktop_version=None,
        )

    def test_returns_compatible_when_at_or_above_recommended(self):
        self.assertEqual(evaluate_desktop(self.policy, "3.2.0"), CompatibilityStatus.COMPATIBLE)
        self.assertEqual(evaluate_desktop(self.policy, "3.3.0"), CompatibilityStatus.COMPATIBLE)

    def test_returns_update_available_between_minimum_and_recommended(self):
        self.assertEqual(evaluate_desktop(self.policy, "3.1.5"), CompatibilityStatus.UPDATE_AVAILABLE)

    def test_returns_update_required_below_minimum(self):
        self.assertEqual(evaluate_desktop(self.policy, "3.0.9"), CompatibilityStatus.UPDATE_REQUIRED)

    def test_returns_incompatible_above_maximum(self):
        policy = CompatibilityPolicy(
            minimum_desktop_version="3.1.0",
            recommended_desktop_version="3.2.0",
            server_version="3.2.0",
            api_contract_version="v1",
            database_schema_version="27",
            maximum_desktop_version="3.2.5",
        )
        self.assertEqual(evaluate_desktop(policy, "4.0.0"), CompatibilityStatus.INCOMPATIBLE)

    def test_rejects_invalid_policy_fields(self):
        with self.assertRaises(ValueError):
            CompatibilityPolicy(
                minimum_desktop_version="3.1.0",
                recommended_desktop_version="3.2.0",
                server_version="3.2.0",
                api_contract_version="",
                database_schema_version="27",
            )


if __name__ == "__main__":
    unittest.main()
