from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.updater.manifest import ArtifactDescriptor, ReleaseManifest
from app.updater.manifest_policy import evaluate_manifest_against_policy


def _manifest(**overrides) -> ReleaseManifest:
    base = dict(
        manifest_schema_version=1, release_version="2.6.0", channel="production",
        published_at=datetime.now(timezone.utc), minimum_server_version="0.8.0", api_contract_version="v1",
        artifact=ArtifactDescriptor(filename="pkg.exe", size_bytes=10, sha256="a" * 64),
    )
    base.update(overrides)
    return ReleaseManifest(**base)


class EvaluateManifestAgainstPolicyTests(unittest.TestCase):
    def test_newer_release_with_compatible_server_is_authorized(self):
        decision = evaluate_manifest_against_policy(
            _manifest(), current_desktop_version="2.5.2", current_server_version="0.9.0", current_api_contract_version="v1",
        )
        self.assertTrue(decision.should_download)

    def test_server_below_minimum_blocks_download(self):
        decision = evaluate_manifest_against_policy(
            _manifest(minimum_server_version="1.0.0"), current_desktop_version="2.5.2", current_server_version="0.5.0",
        )
        self.assertFalse(decision.should_download)

    def test_unrecognized_api_contract_blocks_download(self):
        decision = evaluate_manifest_against_policy(
            _manifest(), current_desktop_version="2.5.2", current_api_contract_version="v99",
        )
        self.assertFalse(decision.should_download)

    def test_mismatched_but_known_api_contract_blocks_download(self):
        decision = evaluate_manifest_against_policy(
            _manifest(api_contract_version="v1"), current_desktop_version="2.5.2", current_api_contract_version="v1",
        )
        self.assertTrue(decision.should_download)

    def test_already_installed_version_is_not_reinstalled(self):
        decision = evaluate_manifest_against_policy(_manifest(release_version="2.5.2"), current_desktop_version="2.5.2")
        self.assertFalse(decision.should_download)

    def test_downgrade_without_flag_is_refused(self):
        decision = evaluate_manifest_against_policy(_manifest(release_version="2.0.0"), current_desktop_version="2.5.2")
        self.assertFalse(decision.should_download)

    def test_downgrade_with_explicit_flag_is_authorized(self):
        decision = evaluate_manifest_against_policy(
            _manifest(release_version="2.0.0"), current_desktop_version="2.5.2", allow_downgrade=True,
        )
        self.assertTrue(decision.should_download)

    def test_missing_server_info_does_not_block_by_itself(self):
        decision = evaluate_manifest_against_policy(_manifest(), current_desktop_version="2.5.2")
        self.assertTrue(decision.should_download)


if __name__ == "__main__":
    unittest.main()
