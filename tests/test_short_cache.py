from __future__ import annotations

import unittest

from app.services.short_cache import ShortLivedCache


class ShortCacheTests(unittest.TestCase):
    def test_reuses_value_inside_ttl_and_isolates_mutations(self):
        cache = ShortLivedCache(default_ttl=5)
        calls = []

        def loader():
            calls.append(1)
            return [{"id": 1, "status": "A"}]

        first = cache.get_or_load("rows", loader)
        first[0]["status"] = "alterado pela UI"
        second = cache.get_or_load("rows", loader)

        self.assertEqual(len(calls), 1)
        self.assertEqual(second[0]["status"], "A")

    def test_invalidation_forces_new_read(self):
        cache = ShortLivedCache(default_ttl=5)
        calls = []

        def loader():
            calls.append(1)
            return {"value": len(calls)}

        self.assertEqual(cache.get_or_load("fiscal:rows", loader)["value"], 1)
        cache.invalidate("fiscal:")
        self.assertEqual(cache.get_or_load("fiscal:rows", loader)["value"], 2)


if __name__ == "__main__":
    unittest.main()
