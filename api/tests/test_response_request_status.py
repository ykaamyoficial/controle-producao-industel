from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from api.app.modules.chat.service import _effective_question_status


NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


class EffectiveQuestionStatusTests(unittest.TestCase):
    def test_awaiting_without_due_date_never_overdue(self):
        self.assertEqual(_effective_question_status("AGUARDANDO_RESPOSTA", None, now=NOW), "AGUARDANDO_RESPOSTA")

    def test_awaiting_with_future_due_date_stays_awaiting(self):
        due = NOW + timedelta(hours=1)
        self.assertEqual(_effective_question_status("AGUARDANDO_RESPOSTA", due, now=NOW), "AGUARDANDO_RESPOSTA")

    def test_awaiting_with_past_due_date_becomes_overdue(self):
        due = NOW - timedelta(minutes=1)
        self.assertEqual(_effective_question_status("AGUARDANDO_RESPOSTA", due, now=NOW), "ATRASADA")

    def test_answered_never_becomes_overdue_even_with_past_due_date(self):
        due = NOW - timedelta(days=5)
        self.assertEqual(_effective_question_status("RESPONDIDA", due, now=NOW), "RESPONDIDA")

    def test_cancelled_never_becomes_overdue_even_with_past_due_date(self):
        due = NOW - timedelta(days=5)
        self.assertEqual(_effective_question_status("CANCELADA", due, now=NOW), "CANCELADA")

    def test_none_status_passthrough(self):
        self.assertIsNone(_effective_question_status(None, NOW - timedelta(days=1), now=NOW))

    def test_due_exactly_now_is_not_yet_overdue(self):
        self.assertEqual(_effective_question_status("AGUARDANDO_RESPOSTA", NOW, now=NOW), "AGUARDANDO_RESPOSTA")


if __name__ == "__main__":
    unittest.main()
