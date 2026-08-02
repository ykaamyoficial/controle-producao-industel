from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.legacy_sqlite_migration.validate_proposals_replica import build_inventory, compare, summarize, write_reports


class ValidateProposalsReplicaTests(unittest.TestCase):
    def test_inventory_classifies_source_data_without_writing(self):
        snapshot = [
            {
                "legacy_id": 1,
                "proposal_number": "CP00000",
                "current_area": "AREA_NOVA",
                "current_status": "STATUS_NOVO",
                "is_cancelled": False,
                "is_completed": True,
                "is_partial": False,
                "items": [
                    {"legacy_id": 10, "description": "Linha 1\nLinha 2", "quantity": "0.0000", "total_weight": "-1.0000"}
                ],
            }
        ]

        inventory = build_inventory(snapshot)

        self.assertEqual(inventory["total_proposals"], 1)
        self.assertEqual(inventory["total_items"], 1)
        self.assertEqual(inventory["multiline_descriptions"], 1)
        self.assertEqual(inventory["unknown_areas"], ["AREA_NOVA"])
        self.assertEqual(inventory["cp00000"], 1)

    def test_compare_reports_missing_and_field_mismatches(self):
        sqlite_snapshot = [
            {
                "legacy_id": 1,
                "proposal_number": "CP00001",
                "customer_name": "Cliente",
                "project_name": "Site",
                "order_reference": None,
                "lot": None,
                "proposal_date": "2026-07-20",
                "deadline_date": None,
                "current_area": "PRODUCAO",
                "current_status": "EM PRODUCAO",
                "is_partial": False,
                "is_cancelled": False,
                "is_completed": False,
                "source_hash": "a" * 64,
                "items": [
                    {
                        "legacy_id": 10,
                        "item_number": "1",
                        "product_code": "COD",
                        "description": "Linha\r\nDois",
                        "quantity": "2.0000",
                        "unit": "un",
                        "unit_weight": "1.0000",
                        "total_weight": "2.0000",
                        "produce_internally": "SIM",
                        "requires_galvanization": "NAO",
                        "flow_defined": False,
                        "produced": False,
                        "galvanized": False,
                        "delivered": False,
                        "source_hash": "b" * 64,
                    }
                ],
            }
        ]
        api_snapshot = [{**sqlite_snapshot[0], "current_status": "OUTRO", "items": []}]

        differences = compare(sqlite_snapshot, api_snapshot, redact=True)
        summary = summarize(differences, build_inventory(sqlite_snapshot))

        self.assertGreaterEqual(summary["critical"], 1)
        self.assertIn("FIELD_MISMATCH", summary["categories"])
        self.assertIn("ITEM_COUNT_MISMATCH", summary["categories"])
        self.assertTrue(all(diff.proposal_number is None for diff in differences))

    def test_write_reports_creates_json_and_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            differences = compare([{"legacy_id": 1, "proposal_number": "CP1", "items": []}], [], redact=False)
            paths = write_reports(differences, {"total_proposals": 1, "total_items": 0}, reports_dir=Path(temp_dir))

            self.assertTrue(paths["json"].exists())
            self.assertTrue(paths["csv"].exists())


if __name__ == "__main__":
    unittest.main()
