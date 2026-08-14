from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.build_release_image import (
    ReleaseVersionMismatchError,
    resolve_build_time,
    resolve_commit_sha,
    resolve_release_tag,
)


class ResolveReleaseTagTests(unittest.TestCase):
    def test_no_tag_requested_uses_source_version(self):
        self.assertEqual(resolve_release_tag(None, source_version="0.8.0"), "0.8.0")

    def test_matching_tag_is_accepted(self):
        self.assertEqual(resolve_release_tag("0.8.0", source_version="0.8.0"), "0.8.0")

    def test_divergent_tag_raises_explicitly(self):
        with self.assertRaises(ReleaseVersionMismatchError):
            resolve_release_tag("9.9.9", source_version="0.8.0")

    def test_error_message_names_both_versions(self):
        with self.assertRaises(ReleaseVersionMismatchError) as ctx:
            resolve_release_tag("1.0.0", source_version="0.8.0")
        self.assertIn("1.0.0", str(ctx.exception))
        self.assertIn("0.8.0", str(ctx.exception))


class ResolveCommitShaTests(unittest.TestCase):
    def test_returns_a_short_hex_string_in_this_git_repo(self):
        sha = resolve_commit_sha()
        self.assertNotEqual(sha, "")
        # ou e "unknown" (sem git disponivel) ou um short sha hexadecimal
        if sha != "unknown":
            int(sha, 16)

    def test_returns_unknown_outside_a_git_repository(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_commit_sha(cwd=Path(tmp)), "unknown")


class ResolveBuildTimeTests(unittest.TestCase):
    def test_formats_as_utc_z_suffixed_timestamp(self):
        moment = datetime(2026, 8, 11, 12, 30, 45, tzinfo=timezone.utc)
        self.assertEqual(resolve_build_time(now=moment), "2026-08-11T12:30:45Z")

    def test_converts_non_utc_input_to_utc(self):
        from datetime import timedelta

        moment = datetime(2026, 8, 11, 9, 30, 45, tzinfo=timezone(timedelta(hours=-3)))
        self.assertEqual(resolve_build_time(now=moment), "2026-08-11T12:30:45Z")


if __name__ == "__main__":
    unittest.main()
