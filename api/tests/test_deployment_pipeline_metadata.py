from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.deployment.metadata import DeploymentMetadata


def _metadata(**overrides) -> DeploymentMetadata:
    base = dict(
        deployment_id="deploy_20260811T120000Z_v1.0.0_aaaaaaaa",
        release_version="1.0.0",
        git_commit_sha="abc1234",
        image_repository="ghcr.io/owner/controle-producao-api",
        image_tag="1.0.0",
        api_contract_version="v1",
        expected_database_schema="20260811_0016",
    )
    base.update(overrides)
    return DeploymentMetadata(**base)


class DeploymentMetadataTests(unittest.TestCase):
    def test_image_ref_by_tag(self):
        metadata = _metadata()
        self.assertEqual(metadata.image_ref_by_tag, "ghcr.io/owner/controle-producao-api:1.0.0")

    def test_image_ref_by_digest_none_when_digest_missing(self):
        metadata = _metadata(image_digest=None)
        self.assertIsNone(metadata.image_ref_by_digest)

    def test_image_ref_by_digest_present(self):
        metadata = _metadata(image_digest="sha256:" + "a" * 64)
        self.assertEqual(metadata.image_ref_by_digest, f"ghcr.io/owner/controle-producao-api@sha256:{'a' * 64}")

    def test_save_then_load_round_trips(self):
        metadata = _metadata(image_digest="sha256:" + "b" * 64, workflow_run_id="12345")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            metadata.save(path)
            loaded = DeploymentMetadata.load(path)
        self.assertEqual(loaded, metadata)

    def test_load_ignores_unknown_extra_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            path.write_text(
                '{"deployment_id": "d1", "release_version": "1.0.0", "git_commit_sha": "abc", '
                '"image_repository": "ghcr.io/owner/app", "image_tag": "1.0.0", '
                '"api_contract_version": "v1", "expected_database_schema": "rev1", "unexpected_field": "x"}',
                encoding="utf-8",
            )
            loaded = DeploymentMetadata.load(path)
        self.assertEqual(loaded.deployment_id, "d1")


if __name__ == "__main__":
    unittest.main()
