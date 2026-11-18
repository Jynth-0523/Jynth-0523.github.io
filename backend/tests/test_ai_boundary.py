from __future__ import annotations

import json
import unittest
from pathlib import Path

from research_platform.ai_boundary import (
    build_minimized_ai_input,
    build_minimized_discovery_ai_input,
    recursively_contains_sensitive_key,
)


PROJECT = Path(__file__).resolve().parents[1]


class AIBoundaryTests(unittest.TestCase):
    def test_untrusted_instruction_cannot_change_policy(self) -> None:
        health = json.loads(
            (PROJECT / "tests" / "fixtures" / "injection_fail.json").read_text(encoding="utf-8")
        )
        payload = build_minimized_ai_input(health, automation_run_id="fixture-run")
        self.assertFalse(payload["policy"]["tools_available"])
        self.assertFalse(payload["policy"]["automatic_actions_allowed"])
        self.assertFalse(payload["policy"]["research_tuning_allowed"])
        self.assertIn("untrusted", payload["failed_or_blocked_checks"][0]["untrusted_message"].lower())
        self.assertNotIn("evidence", payload["failed_or_blocked_checks"][0])
        self.assertNotIn("actual", payload["failed_or_blocked_checks"][0])

    def test_sensitive_result_message_is_redacted(self) -> None:
        health = {
            "overall_status": "FAIL",
            "checks": [
                {
                    "check_id": "semantic.formal_shadow_overlap",
                    "status": "FAIL",
                    "category": "semantic",
                    "message": "Formal OOS and Shadow OOS values overlap.",
                }
            ],
        }
        payload = build_minimized_ai_input(health, automation_run_id="fixture-run")
        message = payload["failed_or_blocked_checks"][0]["untrusted_message"]
        self.assertIn("withheld", message)
        self.assertFalse(recursively_contains_sensitive_key(payload))

    def test_discovery_payload_is_a_fixed_aggregate_allowlist(self) -> None:
        payload = build_minimized_discovery_ai_input(
            {
                "calibration_passed": True,
                "calibration_confidence": 0.6765,
                "calibration_threshold": 0.55,
                "candidate_count": 1000,
                "train_hygiene_pass_count": 899,
                "top_stability_count": 100,
                "selected_factor_count": 30,
                "cache_rows": 527211,
                "duplicate_keys": 0,
                "formal_sample_accessed": False,
                "factor_names": ["must-not-cross"],
            }
        )
        serialized = json.dumps(payload, sort_keys=True).lower()
        self.assertFalse(recursively_contains_sensitive_key(payload))
        self.assertNotIn("must-not-cross", serialized)
        self.assertNotIn("formal", serialized)
        self.assertNotIn("factor", serialized)
        self.assertFalse(payload["policy"]["tools_available"])
        self.assertFalse(payload["policy"]["automatic_actions_allowed"])


if __name__ == "__main__":
    unittest.main()
