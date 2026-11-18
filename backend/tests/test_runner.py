from __future__ import annotations

import json
import multiprocessing
import os
import shlex
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_platform.config import load_config
from research_platform.runner import AutomationRunner
from research_platform.store import RuntimeStore
from research_platform.util import sha256_file


PROJECT = Path(__file__).resolve().parents[1]
PASS_FIXTURE = PROJECT / "tests" / "fixtures" / "pass.json"


def _concurrent_worker(arguments: tuple[str, str]) -> str:
    config_path, scheduled_at = arguments
    config = load_config(Path(config_path))
    outcome = AutomationRunner(config).run(
        scheduled_at=datetime.fromisoformat(scheduled_at)
    )
    return outcome.state


class RunnerTests(unittest.TestCase):
    def _project(
        self,
        directory: Path,
        *,
        fixture: Path = PASS_FIXTURE,
        exit_code: int = 0,
        sleep_seconds: float = 0,
        timeout_seconds: float = 2,
        blocked_retries: int = 0,
        counter: Path | None = None,
    ) -> Path:
        config_dir = directory / "config"
        health_dir = directory / "health"
        config_dir.mkdir(parents=True)
        health_dir.mkdir(parents=True)
        script = health_dir / "run_health.sh"
        health_output = health_dir / "latest_health_status.json"
        lines = ["#!/bin/sh", "set -eu"]
        if counter is not None:
            lines.append(f"printf 'run\\n' >> {shlex.quote(str(counter))}")
        if sleep_seconds:
            lines.append(f"sleep {sleep_seconds}")
        lines.append(f"cp {shlex.quote(str(fixture))} {shlex.quote(str(health_output))}")
        lines.append(f"exit {exit_code}")
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o700)

        raw = json.loads((PROJECT / "config" / "platform_config.json").read_text(encoding="utf-8"))
        raw["command"]["script_path"] = str(script)
        raw["command"]["script_sha256"] = sha256_file(script)
        raw["command"]["health_status_path"] = str(health_output)
        raw["runtime"]["timeout_seconds"] = timeout_seconds
        raw["runtime"]["blocked_retries"] = blocked_retries
        raw["runtime"]["retry_backoff_seconds"] = 0
        raw["runtime"]["claim_lease_seconds"] = 5
        config_path = config_dir / "platform_config.json"
        config_path.write_text(json.dumps(raw), encoding="utf-8")
        return config_path

    def test_runner_executes_only_fixed_command_and_writes_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = load_config(self._project(root))
            runner = AutomationRunner(config)
            outcome = runner.run(scheduled_at=datetime(2026, 8, 11, tzinfo=timezone.utc))
            self.assertEqual(outcome.state, "COMPLETED")
            self.assertEqual(outcome.validated_status, "PASS")
            self.assertTrue(Path(outcome.envelope_path).is_file())
            envelope = json.loads(Path(outcome.envelope_path).read_text(encoding="utf-8"))
            self.assertEqual(envelope["tool_trace"]["policy_decision"], "ALLOW_FIXED_HASH_VERIFIED_COMMAND")
            self.assertFalse(envelope["safety"]["database_write_requested"])
            self.assertFalse(envelope["safety"]["research_execution_requested"])
            self.assertFalse(envelope["safety"]["user_shell_arguments_accepted"])
            self.assertEqual(envelope["notification_state"], "silent_archive")
            self.assertEqual(envelope["health_findings"], [])
            self.assertNotIn("stdout", envelope["tool_trace"])
            self.assertNotIn("stderr", envelope["tool_trace"])

    def test_arbitrary_command_id_is_denied_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "counter.txt"
            config = load_config(self._project(root, counter=counter))
            outcome = AutomationRunner(config).run(command_id="anything_else")
            self.assertEqual(outcome.state, "DENIED")
            self.assertFalse(counter.exists())

    def test_kill_switch_prevents_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "counter.txt"
            config = load_config(self._project(root, counter=counter))
            RuntimeStore(config.runtime_root).set_disabled(True, "test")
            outcome = AutomationRunner(config).run()
            self.assertEqual(outcome.state, "DISABLED")
            self.assertFalse(counter.exists())

    def test_same_bucket_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "counter.txt"
            config = load_config(self._project(root, counter=counter))
            scheduled = datetime(2026, 8, 11, 2, 5, tzinfo=timezone.utc)
            first = AutomationRunner(config).run(scheduled_at=scheduled)
            second = AutomationRunner(config).run(scheduled_at=scheduled + timedelta(minutes=20))
            self.assertEqual(first.state, "COMPLETED")
            self.assertEqual(second.state, "DUPLICATE")
            self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["run"])

    def test_timeout_becomes_blocked_with_bounded_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "counter.txt"
            config = load_config(
                self._project(
                    root,
                    sleep_seconds=0.15,
                    timeout_seconds=0.03,
                    blocked_retries=1,
                    counter=counter,
                )
            )
            outcome = AutomationRunner(config).run()
            self.assertEqual(outcome.state, "COMPLETED")
            self.assertEqual(outcome.validated_status, "BLOCKED")
            envelope = json.loads(Path(outcome.envelope_path).read_text(encoding="utf-8"))
            self.assertEqual(len(envelope["attempts"]), 2)
            self.assertTrue(all(attempt["timed_out"] for attempt in envelope["attempts"]))
            self.assertEqual(
                [attempt["attempt"] for attempt in envelope["attempts"]],
                [1, 2],
            )

    def test_fail_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "counter.txt"
            config = load_config(
                self._project(
                    root,
                    fixture=PROJECT / "tests" / "fixtures" / "fail.json",
                    exit_code=1,
                    blocked_retries=2,
                    counter=counter,
                )
            )
            outcome = AutomationRunner(config).run()
            self.assertEqual(outcome.validated_status, "FAIL")
            envelope = json.loads(Path(outcome.envelope_path).read_text(encoding="utf-8"))
            self.assertEqual(len(envelope["attempts"]), 1)
            self.assertEqual(envelope["notification_state"], "local_outbox_pending")
            self.assertTrue(envelope["health_findings"])
            self.assertEqual(len(list((config.runtime_root / "alerts" / "outbox").glob("*.json"))), 1)
            self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["run"])

    def test_deterministic_fail_with_rejected_payload_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "counter.txt"
            config = load_config(
                self._project(
                    root,
                    fixture=PROJECT / "tests" / "fixtures" / "overlap_invalid.json",
                    exit_code=1,
                    blocked_retries=2,
                    counter=counter,
                )
            )
            outcome = AutomationRunner(config).run()
            self.assertEqual(outcome.validated_status, "FAIL")
            envelope = json.loads(Path(outcome.envelope_path).read_text(encoding="utf-8"))
            self.assertEqual(len(envelope["attempts"]), 1)
            self.assertTrue(envelope["attempts"][0]["validation_issues"])
            self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["run"])

    def test_two_time_buckets_form_a_valid_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = load_config(self._project(root))
            runner = AutomationRunner(config)
            first = runner.run(scheduled_at=datetime(2026, 8, 11, 1, tzinfo=timezone.utc))
            second = runner.run(scheduled_at=datetime(2026, 8, 11, 2, tzinfo=timezone.utc))
            self.assertEqual(first.state, "COMPLETED")
            self.assertEqual(second.state, "COMPLETED")
            store = RuntimeStore(config.runtime_root)
            valid, issues = store.verify_chain()
            self.assertTrue(valid, issues)
            second_envelope = json.loads(Path(second.envelope_path).read_text(encoding="utf-8"))
            self.assertEqual(second_envelope["previous_envelope_sha256"], first.envelope_sha256)

    def test_one_hundred_concurrent_triggers_execute_subprocess_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "counter.txt"
            config_path = self._project(root, sleep_seconds=0.12, counter=counter)
            scheduled = datetime(2026, 8, 11, 3, tzinfo=timezone.utc).isoformat()
            arguments = [(str(config_path), scheduled)] * 100
            context = multiprocessing.get_context("fork")
            with context.Pool(processes=16) as pool:
                states = pool.map(_concurrent_worker, arguments)
            self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["run"])
            self.assertEqual(states.count("COMPLETED"), 1)
            self.assertEqual(states.count("COMPLETED") + states.count("DUPLICATE") + states.count("ALREADY_RUNNING"), 100)

    def test_runner_environment_has_no_database_secret_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(self._project(Path(temporary)))
            environment, keys = AutomationRunner(config)._safe_environment()
            forbidden = {"PGPASSWORD", "DATABASE_URL", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}
            self.assertTrue(forbidden.isdisjoint(environment))
            self.assertTrue(forbidden.isdisjoint(keys))


if __name__ == "__main__":
    unittest.main()
