from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.updater.contract import (
    InvalidUpdateRequestError,
    UpdateJournal,
    UpdateRequest,
    UpdateState,
    validate_update_request,
)


def _request(**overrides) -> UpdateRequest:
    base = dict(
        request_id="req-1",
        current_version="1.0.0",
        target_version="1.1.0",
        package_url_or_source="http://127.0.0.1:8000/package.zip",
        install_dir=r"C:\Program Files\Industel\Controle de Producao",
        executable_path=r"C:\Program Files\Industel\Controle de Producao\ControleProducao.exe",
        parent_pid=1234,
    )
    base.update(overrides)
    return UpdateRequest(**base)


class UpdateRequestValidationTests(unittest.TestCase):
    def test_valid_request_passes(self):
        validate_update_request(_request())  # nao deve levantar

    def test_empty_request_id_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(request_id=""))

    def test_invalid_current_version_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(current_version="not-a-version"))

    def test_invalid_target_version_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(target_version="not-a-version"))

    def test_target_version_equal_to_current_is_rejected_without_allow_downgrade(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(target_version="1.0.0"))

    def test_target_version_lower_than_current_is_rejected_without_allow_downgrade(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(target_version="0.9.0"))

    def test_downgrade_accepted_when_explicitly_allowed(self):
        validate_update_request(_request(target_version="0.9.0", allow_downgrade=True))  # nao deve levantar

    def test_empty_package_source_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(package_url_or_source=""))

    def test_relative_install_dir_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(install_dir="relative/path"))

    def test_relative_executable_path_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(executable_path="relative/exe.exe"))

    def test_executable_outside_install_dir_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(executable_path=r"C:\Somewhere\Else\App.exe"))

    def test_non_positive_parent_pid_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(parent_pid=0))
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(parent_pid=-5))

    def test_negative_expected_size_rejected(self):
        with self.assertRaises(InvalidUpdateRequestError):
            validate_update_request(_request(package_expected_size=-1))


class UpdateRequestSerializationTests(unittest.TestCase):
    def test_save_then_load_round_trips(self):
        request = _request(package_expected_size=1024, package_expected_hash="a" * 64, restart_args=("--flag",))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.json"
            request.save(path)
            loaded = UpdateRequest.load(path)
        self.assertEqual(loaded, request)


class UpdateJournalTests(unittest.TestCase):
    def test_round_trip_to_dict_from_dict(self):
        journal = UpdateJournal(
            request_id="req-1", current_version="1.0.0", target_version="1.1.0", state=UpdateState.DOWNLOADING,
            staging_path="/staging/req-1", backup_path="/backup/req-1", started_at=datetime.now(timezone.utc),
            last_step="DOWNLOADING",
        )
        restored = UpdateJournal.from_dict(journal.to_dict())
        self.assertEqual(restored, journal)

    def test_is_terminal(self):
        base = dict(
            request_id="r", current_version="1.0.0", target_version="1.1.0", staging_path="s", backup_path="b",
            started_at=datetime.now(timezone.utc), last_step="x",
        )
        for state in (UpdateState.SUCCESS, UpdateState.ROLLED_BACK, UpdateState.MANUAL_INTERVENTION_REQUIRED):
            self.assertTrue(UpdateJournal(state=state, **base).is_terminal)
        for state in (UpdateState.REQUESTED, UpdateState.DOWNLOADING, UpdateState.APPLYING, UpdateState.FAILED):
            self.assertFalse(UpdateJournal(state=state, **base).is_terminal)


if __name__ == "__main__":
    unittest.main()
