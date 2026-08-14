from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from api.app.core.versioning import CompatibilityPolicy, CompatibilityStatus, EnforcementMode, evaluate_desktop_with_enforcement


def _policy(**overrides) -> CompatibilityPolicy:
    base = dict(
        minimum_desktop_version="3.1.0", recommended_desktop_version="3.2.0",
        server_version="3.2.0", api_contract_version="v1", database_schema_version="rev1",
    )
    base.update(overrides)
    return CompatibilityPolicy(**base)


def _evaluate(current_version: str, *, enforcement=EnforcementMode.NONE, authorized_update_version=None, grace_until=None, now=None, policy=None) -> CompatibilityStatus:
    return evaluate_desktop_with_enforcement(
        policy or _policy(), current_version, enforcement=enforcement,
        authorized_update_version=authorized_update_version, grace_until=grace_until,
        now=now or datetime.now(UTC),
    )


class BasicMatrixTests(unittest.TestCase):
    """Fase 13, Secao 8: os tres exemplos exatos do prompt."""

    def test_at_recommended_is_compatible(self):
        self.assertEqual(_evaluate("3.2.0"), CompatibilityStatus.COMPATIBLE)

    def test_between_minimum_and_recommended_is_available_by_default(self):
        self.assertEqual(_evaluate("3.1.5"), CompatibilityStatus.UPDATE_AVAILABLE)

    def test_between_minimum_and_recommended_is_recommended_with_recommended_enforcement(self):
        self.assertEqual(_evaluate("3.1.5", enforcement=EnforcementMode.RECOMMENDED), CompatibilityStatus.UPDATE_RECOMMENDED)

    def test_below_minimum_is_required(self):
        self.assertEqual(_evaluate("3.0.9"), CompatibilityStatus.UPDATE_REQUIRED)

    def test_below_minimum_with_blocked_enforcement_is_incompatible(self):
        self.assertEqual(_evaluate("3.0.9", enforcement=EnforcementMode.BLOCKED), CompatibilityStatus.INCOMPATIBLE)

    def test_above_maximum_is_incompatible_regardless_of_enforcement(self):
        policy = _policy(maximum_desktop_version="3.3.0")
        self.assertEqual(_evaluate("3.4.0", policy=policy, enforcement=EnforcementMode.NONE), CompatibilityStatus.INCOMPATIBLE)


class EnforcementModeTests(unittest.TestCase):
    def test_none_never_escalates(self):
        self.assertEqual(_evaluate("3.1.5", enforcement=EnforcementMode.NONE), CompatibilityStatus.UPDATE_AVAILABLE)

    def test_optional_never_escalates(self):
        self.assertEqual(_evaluate("3.1.5", enforcement=EnforcementMode.OPTIONAL), CompatibilityStatus.UPDATE_AVAILABLE)

    def test_required_escalates_when_outdated_vs_recommended_without_authorized_target(self):
        self.assertEqual(_evaluate("3.1.5", enforcement=EnforcementMode.REQUIRED), CompatibilityStatus.UPDATE_REQUIRED)

    def test_required_uses_authorized_target_instead_of_recommended_when_present(self):
        # authorized_update_version mais baixo que a versao atual: a escalada para
        # REQUIRED nao se aplica mais (ja nao esta desatualizado em relacao ao alvo
        # obrigatorio), mas o aviso mais brando de UPDATE_AVAILABLE ainda vale
        # porque a versao recomendada (3.2.0) continua mais nova.
        result = _evaluate("3.1.5", enforcement=EnforcementMode.REQUIRED, authorized_update_version="3.1.2")
        self.assertEqual(result, CompatibilityStatus.UPDATE_AVAILABLE)

    def test_required_does_not_escalate_when_already_on_authorized_version(self):
        result = _evaluate("3.2.0", enforcement=EnforcementMode.REQUIRED, authorized_update_version="3.2.0")
        self.assertEqual(result, CompatibilityStatus.COMPATIBLE)

    def test_blocked_wins_even_when_version_is_fully_compatible(self):
        self.assertEqual(_evaluate("3.2.0", enforcement=EnforcementMode.BLOCKED), CompatibilityStatus.INCOMPATIBLE)


class GracePeriodTests(unittest.TestCase):
    def test_before_grace_deadline_warns_but_allows_operation(self):
        future = datetime.now(UTC) + timedelta(hours=1)
        result = _evaluate("3.1.5", enforcement=EnforcementMode.REQUIRED, authorized_update_version="3.2.0", grace_until=future)
        self.assertEqual(result, CompatibilityStatus.UPDATE_RECOMMENDED)

    def test_after_grace_deadline_blocks(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        result = _evaluate("3.1.5", enforcement=EnforcementMode.REQUIRED, authorized_update_version="3.2.0", grace_until=past)
        self.assertEqual(result, CompatibilityStatus.UPDATE_REQUIRED)

    def test_no_grace_until_blocks_immediately(self):
        result = _evaluate("3.1.5", enforcement=EnforcementMode.REQUIRED, authorized_update_version="3.2.0", grace_until=None)
        self.assertEqual(result, CompatibilityStatus.UPDATE_REQUIRED)

    def test_decision_uses_injected_now_not_local_clock(self):
        # o "agora" usado na decisao vem do parametro `now` (o servidor), nunca de
        # datetime.now() lido implicitamente dentro da funcao.
        future = datetime.now(UTC) + timedelta(days=365)
        far_future_now = future + timedelta(days=1)
        result = _evaluate("3.1.5", enforcement=EnforcementMode.REQUIRED, authorized_update_version="3.2.0", grace_until=future, now=far_future_now)
        self.assertEqual(result, CompatibilityStatus.UPDATE_REQUIRED)


if __name__ == "__main__":
    unittest.main()
