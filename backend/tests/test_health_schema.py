from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from research_platform.config import load_config
from research_platform.health_schema import validate_health_bytes, validate_health_file


PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "tests" / "fixtures"
CONFIG = load_config(PROJECT / "config" / "platform_config.json")


class HealthSchemaTests(unittest.TestCase):
    def validate_fixture(self, name: str):
        return validate_health_file(
            FIXTURES / name,
            CONFIG.identity,
            CONFIG.maximum_health_json_bytes,
        )

    def test_pass_fail_and_blocked_are_valid_health_documents(self) -> None:
        for name, status in (
            ("pass.json", "PASS"),
            ("fail.json", "FAIL"),
            ("blocked.json", "BLOCKED"),
        ):
            with self.subTest(name=name):
                result = self.validate_fixture(name)
                self.assertTrue(result.valid, [issue.as_dict() for issue in result.issues])
                self.assertEqual(result.data["overall_status"], status)

    def test_corrupt_and_duplicate_key_documents_are_rejected(self) -> None:
        for name in ("corrupt.json", "duplicate_key_invalid.json"):
            with self.subTest(name=name):
                result = self.validate_fixture(name)
                self.assertFalse(result.valid)
                self.assertTrue(any(issue.code == "JSON_PARSE" for issue in result.issues))

    def test_formal_shadow_overlap_is_rejected(self) -> None:
        result = self.validate_fixture("overlap_invalid.json")
        self.assertFalse(result.valid)
        self.assertTrue(
            any(issue.path == "$.canonical_result_identity.overlap" for issue in result.issues)
        )

    def test_null_coercion_permission_is_rejected(self) -> None:
        result = self.validate_fixture("null_semantics_invalid.json")
        self.assertFalse(result.valid)
        self.assertTrue(
            any(issue.path == "$.governance.null_must_not_be_coerced_to_zero" for issue in result.issues)
        )

    def test_status_must_match_worst_check_status(self) -> None:
        value = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))
        value["checks"][0]["status"] = "FAIL"
        content = json.dumps(value).encode("utf-8")
        result = validate_health_bytes(content, CONFIG.identity, CONFIG.maximum_health_json_bytes)
        self.assertFalse(result.valid)
        self.assertTrue(any(issue.code == "STATUS_MISMATCH" for issue in result.issues))

    def test_python_truthy_values_do_not_replace_json_booleans(self) -> None:
        value = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))
        value["database_modified"] = 0
        result = validate_health_bytes(
            json.dumps(value).encode("utf-8"),
            CONFIG.identity,
            CONFIG.maximum_health_json_bytes,
        )
        self.assertFalse(result.valid)
        self.assertTrue(any(issue.path == "$.database_modified" for issue in result.issues))

    def test_saved_synthetic_health_output_is_schema_compatible(self) -> None:
        result = validate_health_file(
            FIXTURES / "pass.json",
            CONFIG.identity,
            CONFIG.maximum_health_json_bytes,
        )
        self.assertTrue(result.valid, [issue.as_dict() for issue in result.issues])


if __name__ == "__main__":
    unittest.main()

