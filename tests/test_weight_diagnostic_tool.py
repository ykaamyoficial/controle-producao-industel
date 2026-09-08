from __future__ import annotations

from tools.diagnose_operational_weights import COUNT_QUERIES


def test_weight_diagnostic_queries_are_read_only():
    assert COUNT_QUERIES
    for query in COUNT_QUERIES.values():
        normalized = " ".join(query.upper().split())
        assert normalized.startswith("SELECT")
        assert " UPDATE " not in f" {normalized} "
        assert " DELETE " not in f" {normalized} "
        assert " INSERT " not in f" {normalized} "
