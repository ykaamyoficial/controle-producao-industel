from __future__ import annotations


class ProposalStorageNotOfficialError(RuntimeError):
    pass


def official_proposals_enabled(config: dict) -> bool:
    return bool(config.get("postgresql_official_proposals_enabled"))


def require_sqlite_proposal_write_allowed(config: dict) -> None:
    if official_proposals_enabled(config):
        raise ProposalStorageNotOfficialError(
            "Propostas novas sao oficiais no PostgreSQL. Escrita SQLite bloqueada para propostas e itens."
        )
