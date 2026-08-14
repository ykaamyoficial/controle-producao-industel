from __future__ import annotations

import sqlite3

import pytest

from app.services.official_proposal_storage import ProposalStorageNotOfficialError, official_proposals_enabled, require_sqlite_proposal_write_allowed
from tools.legacy_sqlite_runtime.production_repository import Repository


def test_official_proposals_flag_defaults_to_disabled():
    assert official_proposals_enabled({}) is False
    require_sqlite_proposal_write_allowed({})


def test_official_proposals_flag_blocks_sqlite_writes():
    with pytest.raises(ProposalStorageNotOfficialError):
        require_sqlite_proposal_write_allowed({"postgresql_official_proposals_enabled": True})


def test_repository_blocks_proposal_save_when_api_is_official():
    repo = Repository(sqlite3.connect(":memory:"))
    repo.postgresql_official_proposals_enabled = True

    with pytest.raises(ProposalStorageNotOfficialError):
        repo.save_process({}, {"id": 1})

