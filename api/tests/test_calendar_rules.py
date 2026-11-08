"""Regras de data (calendar_rules): funcoes puras, sem banco."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from api.app.core.exceptions import ApiError
from api.app.modules.logistics import calendar_rules as cr


class CalendarRulesTests(unittest.TestCase):
    def test_local_date_uses_sao_paulo_not_utc(self):
        # 01:00 UTC do dia 8 ainda e 22:00 do dia 7 em Sao Paulo (o "dia na etapa" virava as 21h por usar UTC).
        self.assertEqual(cr.local_date(datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)), date(2026, 11, 7))
        self.assertEqual(cr.local_date(datetime(2026, 11, 8, 3, 30, tzinfo=timezone.utc)), date(2026, 11, 8))

    def test_holidays_public_only_factory_and_state(self):
        self.assertEqual(cr.holiday_name(date(2026, 2, 17)), None)  # Carnaval nao para
        self.assertEqual(cr.holiday_name(date(2026, 6, 4)), None)  # Corpus Christi nao para
        self.assertIsNotNone(cr.factory_holiday_name(date(2026, 11, 2)))  # Finados (nacional)
        self.assertEqual(cr.factory_holiday_name(date(2030, 5, 24)), "Nossa Senhora Auxiliadora")  # constante de Goiania
        self.assertIsNone(cr.holiday_name(date(2030, 5, 24), subdiv="MA"))
        self.assertEqual(cr.state_subdiv("EQT-MA"), "MA")
        self.assertIsNone(cr.state_subdiv("XYZ"))

    def test_business_days(self):
        self.assertTrue(cr.is_business_day(date(2030, 3, 12)))
        self.assertFalse(cr.is_business_day(date(2030, 3, 16)))
        # sex 30/10 -> ter 03/11/2026: sab, dom, seg (Finados) fora; so a terca conta.
        self.assertEqual(cr.business_days_between(date(2026, 10, 30), date(2026, 11, 3)), 1)
        self.assertEqual(cr.business_days_between(date(2026, 11, 3), date(2026, 11, 3)), 0)
        self.assertEqual(cr.business_days_between(date(2026, 11, 5), date(2026, 11, 3)), 0)

    def test_warnings(self):
        today = date(2030, 3, 12)
        self.assertEqual(cr.warn_past("visit_date", date(2030, 3, 11), today)[0]["code"], "DATE_IN_PAST")
        self.assertEqual(cr.warn_past("visit_date", today, today), [])
        self.assertEqual(cr.warn_non_business("loading_date", date(2030, 3, 16))[0]["code"], "NON_BUSINESS_DAY")
        self.assertEqual(cr.warn_non_business("loading_date", date(2030, 3, 15)), [])
        self.assertEqual(cr.warn_delivery_before_loading(date(2030, 3, 1), date(2030, 3, 2))[0]["code"], "DELIVERY_BEFORE_LOADING")
        self.assertEqual(cr.warn_delivery_before_loading(date(2030, 3, 2), date(2030, 3, 2)), [])
        self.assertEqual(cr.warn_departure_vs_loading(date(2030, 3, 2), [("LOG1", date(2030, 3, 2)), ("LOG2", date(2030, 3, 3))])[0]["code"], "DEPARTURE_DIFFERS_FROM_LOADING")
        self.assertEqual(cr.warn_departure_vs_loading(date(2030, 3, 2), [("LOG1", date(2030, 3, 2))]), [])
        self.assertEqual(cr.warn_delivery_before_inspection(date(2030, 3, 1), [("CP 1", date(2030, 3, 2))])[0]["code"], "DELIVERY_BEFORE_INSPECTION_DONE")
        self.assertEqual(cr.warn_delivery_before_inspection(date(2030, 3, 2), [("CP 1", date(2030, 3, 2))]), [])

    def test_confirmation_is_409_only_with_warnings_and_without_confirm(self):
        cr.ensure_dates_confirmed([], False)
        warns = [cr.warning("X", "visit_date", "m")]
        cr.ensure_dates_confirmed(warns, True)
        with self.assertRaises(ApiError) as ctx:
            cr.ensure_dates_confirmed(warns, False)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code, ctx.exception.details), (409, "DATE_CONFIRMATION_REQUIRED", {"warnings": warns}))


if __name__ == "__main__":
    unittest.main()
