import unittest

from research_platform.historical_contract import (
    LEGACY_MODIFICATION_FIELD,
    LEGACY_IMPLEMENTATION_DIRECTORY,
    LEGACY_RESULT_DIRECTORY,
    canonical_artifact_path,
    locked_research_is_unchanged,
)


class HistoricalContractTests(unittest.TestCase):
    def test_old_and_descriptive_fields_accept_only_explicit_false(self):
        for key in (LEGACY_MODIFICATION_FIELD, "locked_research_code_modified"):
            self.assertTrue(locked_research_is_unchanged({key: False}))
            for value in (True, None, 0, "false"):
                self.assertFalse(locked_research_is_unchanged({key: value}))
        self.assertFalse(locked_research_is_unchanged({}))

    def test_conflicting_aliases_fail_closed(self):
        self.assertFalse(locked_research_is_unchanged({
            LEGACY_MODIFICATION_FIELD: True, "locked_research_code_modified": False,
        }))

    def test_aliases_preserve_paths_without_broad_normalization(self):
        self.assertEqual(canonical_artifact_path(LEGACY_IMPLEMENTATION_DIRECTORY + "/run_discovery.py"),
                         "factor_discovery/run_discovery.py")
        self.assertEqual(canonical_artifact_path(LEGACY_RESULT_DIRECTORY + "/candidate_ledger.json"),
                         "runtime/factor_discovery/candidate_ledger.json")
        self.assertEqual(canonical_artifact_path("../unsafe.json"), "../unsafe.json")


if __name__ == "__main__":
    unittest.main()
