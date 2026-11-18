from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .alerts import LocalAlertManager
from .config import PlatformConfig
from .constants import ONLY_COMMAND_ID, PLATFORM_SCHEMA_VERSION
from .health_schema import HealthValidation, status_counts, validate_health_bytes
from .lock import LockUnavailable, SingleInstanceLock
from .store import RuntimeStore
from .util import (
    canonical_json_bytes,
    rfc3339,
    sha256_bytes,
    sha256_file,
    source_tree_sha256,
    utc_now,
)


@dataclass(frozen=True)
class RunOutcome:
    state: str
    validated_status: str | None = None
    envelope_path: str | None = None
    envelope_sha256: str | None = None
    idempotency_key: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "validated_status": self.validated_status,
            "envelope_path": self.envelope_path,
            "envelope_sha256": self.envelope_sha256,
            "idempotency_key": self.idempotency_key,
            "message": self.message,
        }


@dataclass(frozen=True)
class ProcessObservation:
    started_at: datetime
    finished_at: datetime
    exit_code: int | None
    timed_out: bool
    stdout: bytes
    stderr: bytes
    health_content: bytes | None
    health_mtime_ns: int | None
    health_size_bytes: int | None
    validation: HealthValidation


def _bucket_start(value: datetime, bucket_seconds: int) -> int:
    return int(value.timestamp()) // bucket_seconds * bucket_seconds


def build_idempotency_key(config: PlatformConfig, scheduled_at: datetime) -> str:
    payload = {
        "bucket_start_epoch": _bucket_start(scheduled_at, config.idempotency_bucket_seconds),
        "command_id": config.command_id,
        "script_sha256": config.script_sha256,
        "config_sha256": sha256_file(config.path),
        "platform_code_sha256": source_tree_sha256(config.project_root),
    }
    return sha256_bytes(canonical_json_bytes(payload))


def _limited(content: bytes, limit: int) -> bytes:
    return content[:limit]


class AutomationRunner:
    def __init__(self, config: PlatformConfig) -> None:
        self.config = config
        self.store = RuntimeStore(config.runtime_root)
        self.alerts = LocalAlertManager(config.runtime_root)

    def _safe_environment(self) -> tuple[dict[str, str], tuple[str, ...]]:
        keys = tuple(sorted(set(self.config.environment_allowlist)))
        environment = {key: os.environ[key] for key in keys if key in os.environ}
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["V312_AUTOMATION_COMMAND_ID"] = ONLY_COMMAND_ID
        return environment, tuple(sorted(environment))

    def _observe_once(self) -> ProcessObservation:
        started = utc_now()
        before_mtime: int | None
        try:
            before_mtime = self.config.health_status_path.stat().st_mtime_ns
        except (FileNotFoundError, PermissionError, OSError):
            before_mtime = None

        environment, _ = self._safe_environment()
        process = subprocess.Popen(
            [str(self.config.script_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            cwd=str(self.config.script_path.parent),
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=self.config.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
        finished = utc_now()
        stdout = _limited(stdout, self.config.maximum_subprocess_output_bytes)
        stderr = _limited(stderr, self.config.maximum_subprocess_output_bytes)

        health_content: bytes | None = None
        health_mtime_ns: int | None = None
        health_size_bytes: int | None = None
        if not timed_out:
            try:
                stat = self.config.health_status_path.stat()
                health_mtime_ns = stat.st_mtime_ns
                health_size_bytes = stat.st_size
                if before_mtime is None or health_mtime_ns != before_mtime:
                    health_content = self.config.health_status_path.read_bytes()
            except (FileNotFoundError, PermissionError, OSError):
                pass

        if timed_out:
            validation = HealthValidation(valid=False, data=None, issues=())
        elif health_content is None:
            from .health_schema import ValidationIssue

            validation = HealthValidation(
                valid=False,
                data=None,
                issues=(ValidationIssue("STALE_OUTPUT", "$", "health output was not freshly produced"),),
            )
        else:
            validation = validate_health_bytes(
                health_content,
                self.config.identity,
                self.config.maximum_health_json_bytes,
            )

        return ProcessObservation(
            started_at=started,
            finished_at=finished,
            exit_code=process.returncode,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            health_content=health_content,
            health_mtime_ns=health_mtime_ns,
            health_size_bytes=health_size_bytes,
            validation=validation,
        )

    @staticmethod
    def _status_from_observation(observation: ProcessObservation) -> str:
        if observation.timed_out:
            return "BLOCKED"
        # The locked health checker owns the PASS/FAIL/BLOCKED exit contract.
        # A deterministic exit 1 must never be softened into a retryable state,
        # even if the semantic validator rejects the accompanying payload.
        if observation.exit_code == 1:
            return "FAIL"
        if observation.exit_code == 2:
            return "BLOCKED"
        if not observation.validation.valid or not observation.validation.data:
            return "FAIL" if observation.health_content is not None else "BLOCKED"
        status = str(observation.validation.data["overall_status"])
        expected_exit = {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status]
        if observation.exit_code != expected_exit:
            return "FAIL"
        return status

    def run(
        self,
        *,
        command_id: str = ONLY_COMMAND_ID,
        scheduled_at: datetime | None = None,
    ) -> RunOutcome:
        if command_id != ONLY_COMMAND_ID:
            return RunOutcome(state="DENIED", message="command id is not allowlisted")
        if self.config.command_id != ONLY_COMMAND_ID:
            return RunOutcome(state="DENIED", message="configuration command id is not allowlisted")
        if sha256_file(self.config.script_path) != self.config.script_sha256:
            return RunOutcome(state="DENIED", message="locked script hash mismatch")

        self.store.initialize()
        scheduled = scheduled_at or utc_now()
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        idempotency_key = build_idempotency_key(self.config, scheduled)

        if self.store.disabled():
            return RunOutcome(
                state="DISABLED",
                validated_status="DISABLED",
                idempotency_key=idempotency_key,
                message="kill switch is active; subprocess was not started",
            )

        lock = SingleInstanceLock(self.store.locks / "platform.lock")
        try:
            lock.acquire()
        except LockUnavailable:
            return RunOutcome(
                state="ALREADY_RUNNING",
                idempotency_key=idempotency_key,
                message="single-instance lock is held",
            )

        try:
            claim = self.store.claim(idempotency_key, self.config.claim_lease_seconds)
            if not claim.acquired:
                return RunOutcome(
                    state="DUPLICATE",
                    idempotency_key=idempotency_key,
                    message=f"idempotency claim state: {claim.state}",
                )

            automation_run_id = str(uuid.uuid4())
            attempts: list[dict[str, Any]] = []
            observation: ProcessObservation | None = None
            validated_status = "BLOCKED"
            for attempt_number in range(1, self.config.blocked_retries + 2):
                observation = self._observe_once()
                validated_status = self._status_from_observation(observation)
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "started_at": rfc3339(observation.started_at),
                        "finished_at": rfc3339(observation.finished_at),
                        "exit_code": observation.exit_code,
                        "timed_out": observation.timed_out,
                        "derived_status": validated_status,
                        "validation_issues": [issue.as_dict() for issue in observation.validation.issues],
                    }
                )
                if validated_status != "BLOCKED" or attempt_number > self.config.blocked_retries:
                    break
                if self.config.retry_backoff_seconds:
                    time.sleep(self.config.retry_backoff_seconds * (2 ** (attempt_number - 1)))

            assert observation is not None
            previous = self.store.head()
            config_hash = sha256_file(self.config.path)
            platform_code_hash = source_tree_sha256(self.config.project_root)
            health_hash = sha256_bytes(observation.health_content) if observation.health_content is not None else None
            environment, environment_keys = self._safe_environment()
            del environment
            argument_hash = sha256_bytes(
                canonical_json_bytes(
                    {
                        "command_id": ONLY_COMMAND_ID,
                        "script_path": str(self.config.script_path),
                        "script_sha256": self.config.script_sha256,
                    }
                )
            )
            health_findings = []
            if observation.validation.valid and observation.validation.data:
                health_findings = [
                    {
                        "check_id": check.get("check_id"),
                        "category": check.get("category"),
                        "status": check.get("status"),
                    }
                    for check in observation.validation.data.get("checks", [])
                    if isinstance(check, dict) and check.get("status") != "PASS"
                ]
            envelope = {
                "schema_version": PLATFORM_SCHEMA_VERSION,
                "automation_run_id": automation_run_id,
                "scheduled_at": rfc3339(scheduled),
                "started_at": attempts[0]["started_at"],
                "finished_at": attempts[-1]["finished_at"],
                "idempotency_key": idempotency_key,
                "command_id": ONLY_COMMAND_ID,
                "script_sha256": self.config.script_sha256,
                "config_sha256": config_hash,
                "platform_code_sha256": platform_code_hash,
                "validated_status": validated_status,
                "health_json_sha256": health_hash,
                "previous_envelope_sha256": previous,
                "attempts": attempts,
                "health_check_counts": (
                    status_counts(observation.validation.data)
                    if observation.validation.valid and observation.validation.data
                    else None
                ),
                "health_findings": health_findings,
                "tool_trace": {
                    "tool_name": ONLY_COMMAND_ID,
                    "normalized_argument_sha256": argument_hash,
                    "policy_decision": "ALLOW_FIXED_HASH_VERIFIED_COMMAND",
                    "environment_keys": list(environment_keys),
                    "exit_code": observation.exit_code,
                    "stdout_sha256": sha256_bytes(observation.stdout),
                    "stderr_sha256": sha256_bytes(observation.stderr),
                    "stdout_bytes_retained": len(observation.stdout),
                    "stderr_bytes_retained": len(observation.stderr),
                    "parent_envelope_sha256": previous,
                },
                "observation_provenance": {
                    "source_type": "locked_health_json",
                    "source_path": str(self.config.health_status_path),
                    "observed_at": attempts[-1]["finished_at"],
                    "content_sha256": health_hash,
                    "size_bytes": observation.health_size_bytes,
                    "mtime_ns": observation.health_mtime_ns,
                    "producer_script_sha256": self.config.script_sha256,
                },
                "safety": {
                    "database_write_requested": False,
                    "research_execution_requested": False,
                    "user_shell_arguments_accepted": False,
                    "ai_tools_available": False,
                    "ai_input_created": False,
                },
                "notification_state": (
                    "silent_archive" if validated_status == "PASS" else "local_outbox_pending"
                ),
                "ai_explanation_sha256": None,
            }
            envelope_path, envelope_sha = self.store.publish_envelope(envelope)
            try:
                self.alerts.process(envelope, envelope_sha)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                # Notification failures never block or change the health result.
                pass
            self.store.complete_claim(idempotency_key, envelope_sha, validated_status)
            return RunOutcome(
                state="COMPLETED",
                validated_status=validated_status,
                envelope_path=str(envelope_path),
                envelope_sha256=envelope_sha,
                idempotency_key=idempotency_key,
            )
        finally:
            lock.release()
