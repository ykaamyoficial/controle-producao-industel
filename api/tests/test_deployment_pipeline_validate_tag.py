from __future__ import annotations

import unittest

from api.app.core.config import API_VERSION
from scripts.build_release_image import ReleaseVersionMismatchError
from scripts.deployment.validate_tag import (
    InvalidReleaseTagError,
    validate_release_trigger,
    version_from_tag,
)


class VersionFromTagTests(unittest.TestCase):
    def test_valid_tag_extracts_semver(self):
        self.assertEqual(version_from_tag("api-v0.8.0"), "0.8.0")

    def test_rejects_tag_without_prefix(self):
        with self.assertRaises(InvalidReleaseTagError):
            version_from_tag("0.8.0")

    def test_rejects_legacy_product_tag_convention(self):
        # tags historicas do repositorio (Desktop/produto) nunca devem ser
        # aceitas como gatilho de release do servidor.
        with self.assertRaises(InvalidReleaseTagError):
            version_from_tag("v2.3.0-relatorios-operacionais")

    def test_rejects_non_semver_suffix(self):
        with self.assertRaises(InvalidReleaseTagError):
            version_from_tag("api-v0.8")

    def test_rejects_v_without_api_prefix(self):
        with self.assertRaises(InvalidReleaseTagError):
            version_from_tag("v0.8.0")


class ValidateReleaseTriggerTests(unittest.TestCase):
    def test_tag_matching_central_version_is_accepted(self):
        self.assertEqual(validate_release_trigger(tag=f"api-v{API_VERSION}", version=None), API_VERSION)

    def test_workflow_dispatch_version_matching_central_version_is_accepted(self):
        self.assertEqual(validate_release_trigger(tag=None, version=API_VERSION), API_VERSION)

    def test_tag_diverging_from_central_version_is_rejected(self):
        with self.assertRaises(ReleaseVersionMismatchError):
            validate_release_trigger(tag="api-v9.9.9", version=None)

    def test_workflow_dispatch_version_diverging_from_central_version_is_rejected(self):
        with self.assertRaises(ReleaseVersionMismatchError):
            validate_release_trigger(tag=None, version="9.9.9")

    def test_invalid_tag_format_is_rejected_before_version_comparison(self):
        with self.assertRaises(InvalidReleaseTagError):
            validate_release_trigger(tag="release-9.9.9", version=None)

    def test_requires_exactly_one_of_tag_or_version(self):
        with self.assertRaises(ValueError):
            validate_release_trigger(tag=None, version=None)
        with self.assertRaises(ValueError):
            validate_release_trigger(tag=f"api-v{API_VERSION}", version=API_VERSION)


if __name__ == "__main__":
    unittest.main()
