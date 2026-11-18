from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_platform.alerts import LocalAlertManager


def _envelope(status: str, check_id: str = "files.example") -> dict:
    return {
        "command_id": "locked_research_health_check",
        "validated_status": status,
        "attempts": [
            {
                "exit_code": {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status],
                "timed_out": False,
                "validation_issues": [],
            }
        ],
        "health_findings": (
            []
            if status == "PASS"
            else [{"check_id": check_id, "category": "files", "status": status}]
        ),
    }


class AlertTests(unittest.TestCase):
    def test_pass_is_silent_and_creates_no_alert_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = LocalAlertManager(Path(temporary))
            decision = manager.process(_envelope("PASS"), "a" * 64)
            self.assertEqual(decision.action, "SILENT_ARCHIVE")
            self.assertFalse(manager.root.exists())

    def test_fail_and_blocked_have_distinct_severity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = LocalAlertManager(Path(temporary))
            failed = manager.process(_envelope("FAIL"), "a" * 64)
            blocked = manager.process(_envelope("BLOCKED"), "b" * 64)
            self.assertEqual(failed.severity, "CRITICAL")
            self.assertEqual(blocked.severity, "WARNING")
            self.assertTrue(Path(failed.outbox_path).is_file())
            self.assertTrue(Path(blocked.outbox_path).is_file())

    def test_same_root_cause_is_deduplicated_and_ack_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = LocalAlertManager(Path(temporary))
            first = manager.process(_envelope("FAIL"), "a" * 64)
            second = manager.process(_envelope("FAIL"), "b" * 64)
            self.assertEqual(second.action, "DEDUPED")
            self.assertEqual(first.fingerprint, second.fingerprint)
            self.assertEqual(len(list(manager.outbox.glob("*.json"))), 1)
            state = json.loads(Path(first.state_path).read_text(encoding="utf-8"))
            self.assertEqual(state["occurrences"], 2)
            acknowledged = manager.acknowledge(first.fingerprint, "reviewed by human")
            self.assertEqual(acknowledged.action, "ACKNOWLEDGED")
            state = json.loads(Path(first.state_path).read_text(encoding="utf-8"))
            self.assertEqual(state["state"], "ACKNOWLEDGED")
            events = [json.loads(path.read_text(encoding="utf-8")) for path in manager.audit.glob("*.json")]
            self.assertIn("ACKNOWLEDGED", {event["event"] for event in events})


if __name__ == "__main__":
    unittest.main()

