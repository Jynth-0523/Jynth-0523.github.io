from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_platform.lock import LockUnavailable, SingleInstanceLock
from research_platform.store import RuntimeStore
from research_platform.util import atomic_write_bytes, canonical_json_bytes, rfc3339


class StoreAndLockTests(unittest.TestCase):
    def test_single_instance_lock_rejects_second_holder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "platform.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)
            first.acquire()
            try:
                with self.assertRaises(LockUnavailable):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()

    def test_complete_claim_is_idempotent_and_stale_claim_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory))
            first = store.claim("a" * 64, lease_seconds=30)
            self.assertTrue(first.acquired)
            store.complete_claim("a" * 64, "b" * 64, "PASS")
            duplicate = store.claim("a" * 64, lease_seconds=30)
            self.assertFalse(duplicate.acquired)
            self.assertEqual(duplicate.state, "COMPLETE")

            store.initialize()
            stale_key = "c" * 64
            stale_path = store.claims / f"{stale_key}.json"
            stale = {
                "idempotency_key": stale_key,
                "state": "IN_PROGRESS",
                "started_at": rfc3339(datetime.now(timezone.utc) - timedelta(hours=2)),
                "pid": 999999,
            }
            atomic_write_bytes(stale_path, canonical_json_bytes(stale) + b"\n")
            recovered = store.claim(stale_key, lease_seconds=30)
            self.assertTrue(recovered.acquired)
            self.assertTrue(recovered.recovered_stale)

    def test_envelope_chain_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory))
            first = {
                "automation_run_id": "one",
                "finished_at": "2026-08-11T00:00:00Z",
                "previous_envelope_sha256": None,
            }
            first_path, first_hash = store.publish_envelope(first)
            second = {
                "automation_run_id": "two",
                "finished_at": "2026-08-11T01:00:00Z",
                "previous_envelope_sha256": first_hash,
            }
            second_path, _ = store.publish_envelope(second)
            valid, issues = store.verify_chain()
            self.assertTrue(valid, issues)

            value = json.loads(first_path.read_text(encoding="utf-8"))
            value["automation_run_id"] = "tampered"
            first_path.write_text(json.dumps(value), encoding="utf-8")
            valid, issues = store.verify_chain()
            self.assertFalse(valid)
            self.assertTrue(any("hash mismatch" in issue for issue in issues))

    def test_kill_switch_has_separate_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory))
            disable_event = store.set_disabled(True, "maintenance")
            self.assertTrue(store.disabled())
            enable_event = store.set_disabled(False, "complete")
            self.assertFalse(store.disabled())
            self.assertNotEqual(disable_event, enable_event)
            self.assertTrue(disable_event.is_file())
            self.assertTrue(enable_event.is_file())


if __name__ == "__main__":
    unittest.main()

