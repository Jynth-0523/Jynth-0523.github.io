import unittest
import os
from unittest.mock import patch

from research_platform.historical_contract import (
    canonical_artifact_path,
    locked_research_is_unchanged,
)


class HistoricalContractTests(unittest.TestCase):
    def test_configured_fields_accept_only_explicit_false(self):
        with patch.dict(os.environ, {"DISCOVERY_MODIFICATION_FIELD": "archived_code_modified"}):
            for key in ("archived_code_modified", "locked_research_code_modified"):
                self.assertTrue(locked_research_is_unchanged({key: False}))
                for value in (True, None, 0, "false"):
                    self.assertFalse(locked_research_is_unchanged({key: value}))
            self.assertFalse(locked_research_is_unchanged({}))

    def test_conflicting_aliases_fail_closed(self):
        with patch.dict(os.environ, {"DISCOVERY_MODIFICATION_FIELD": "archived_code_modified"}):
            self.assertFalse(locked_research_is_unchanged({
                "archived_code_modified": True, "locked_research_code_modified": False,
            }))

    def test_aliases_preserve_paths_without_broad_normalization(self):
        with patch.dict(os.environ, {"DISCOVERY_IMPLEMENTATION_DIRECTORY": "external_engine",
                                    "DISCOVERY_RESULT_DIRECTORY": "external_results"}):
            self.assertEqual(canonical_artifact_path("external_engine/run_discovery.py"),
                             "factor_discovery/run_discovery.py")
            self.assertEqual(canonical_artifact_path("external_results/candidate_ledger.json"),
                             "runtime/factor_discovery/candidate_ledger.json")
            self.assertEqual(canonical_artifact_path("external_results/../unsafe.json"), "external_results/../unsafe.json")
            self.assertEqual(canonical_artifact_path("../unsafe.json"), "../unsafe.json")


if __name__ == "__main__":
    unittest.main()
