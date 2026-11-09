from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from app.ui.components import date_quick_field as date_quick_field_module


class FakeDatetime(datetime):
    """Relogio do PC em UTC 02:00 do dia 10: em Sao Paulo ainda e dia 09."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc).astimezone(tz)


class LocalTodayTests(unittest.TestCase):
    def test_local_today_uses_sao_paulo_day_not_pc_day(self):
        with patch.object(date_quick_field_module, "datetime", FakeDatetime):
            self.assertEqual(date_quick_field_module.local_today(), date(2026, 11, 9))


if __name__ == "__main__":
    unittest.main()
