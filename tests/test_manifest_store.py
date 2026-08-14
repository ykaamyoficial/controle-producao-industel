from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.updater.manifest import ArtifactDescriptor, ReleaseManifest
from app.updater.manifest_store import LastKnownGoodManifestStore


def _manifest(**overrides) -> ReleaseManifest:
    base = dict(
        manifest_schema_version=1, release_version="2.6.0", channel="production",
        published_at=datetime.now(timezone.utc), minimum_server_version="0.8.0", api_contract_version="v1",
        artifact=ArtifactDescriptor(filename="pkg.exe", size_bytes=10, sha256="a" * 64),
    )
    base.update(overrides)
    return ReleaseManifest(**base)


class LastKnownGoodManifestStoreTests(unittest.TestCase):
    def test_returns_none_when_nothing_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LastKnownGoodManifestStore(Path(tmp))
            self.assertIsNone(store.load())

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LastKnownGoodManifestStore(Path(tmp))
            manifest = _manifest()
            store.save(manifest)
            loaded = store.load()
            self.assertEqual(loaded.release_version, manifest.release_version)
            self.assertEqual(loaded.artifact.sha256, manifest.artifact.sha256)

    def test_newer_save_overwrites_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LastKnownGoodManifestStore(Path(tmp))
            store.save(_manifest(release_version="2.6.0"))
            store.save(_manifest(release_version="2.7.0"))
            self.assertEqual(store.load().release_version, "2.7.0")

    def test_corrupted_file_returns_none_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_valid_manifest.json"
            path.write_text("{not valid json", encoding="utf-8")
            store = LastKnownGoodManifestStore(Path(tmp))
            self.assertIsNone(store.load())


if __name__ == "__main__":
    unittest.main()
