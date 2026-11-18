from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import (
    atomic_write_bytes,
    canonical_json_bytes,
    exclusive_publish_bytes,
    rfc3339,
    sha256_bytes,
    utc_now,
)


@dataclass(frozen=True)
class AlertDecision:
    action: str
    severity: str | None
    fingerprint: str | None
    state_path: str | None = None
    outbox_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "severity": self.severity,
            "fingerprint": self.fingerprint,
            "state_path": self.state_path,
            "outbox_path": self.outbox_path,
        }


def _root_cause(envelope: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    attempts = envelope.get("attempts")
    last_attempt = attempts[-1] if isinstance(attempts, list) and attempts else {}
    findings = envelope.get("health_findings")
    failing_checks = sorted(
        str(finding.get("check_id"))
        for finding in findings or []
        if isinstance(finding, dict) and finding.get("check_id")
    )
    validation_codes = sorted(
        str(issue.get("code"))
        for issue in last_attempt.get("validation_issues", [])
        if isinstance(issue, dict) and issue.get("code")
    )
    root = {
        "command_id": envelope.get("command_id"),
        "validated_status": envelope.get("validated_status"),
        "failing_check_ids": failing_checks,
        "validation_issue_codes": validation_codes,
        "timed_out": bool(last_attempt.get("timed_out")),
        "exit_code": last_attempt.get("exit_code"),
    }
    return root, failing_checks


class LocalAlertManager:
    """Local-only alert simulation with deduplication and auditable ACKs.

    The manager never sends network messages and never reads or writes research
    assets. Its outbox contains only status, check IDs, and envelope hashes.
    """

    def __init__(self, runtime_root: Path) -> None:
        self.root = runtime_root / "alerts"
        self.states = self.root / "states"
        self.outbox = self.root / "outbox"
        self.audit = self.root / "audit"

    def initialize(self) -> None:
        for path in (self.states, self.outbox, self.audit):
            path.mkdir(parents=True, exist_ok=True)

    def _publish_audit(self, event: dict[str, Any]) -> Path:
        now = utc_now()
        name = now.strftime("%Y%m%dT%H%M%S.%fZ") + "_" + sha256_bytes(
            canonical_json_bytes(event)
        )[:12] + ".json"
        path = self.audit / name
        exclusive_publish_bytes(path, canonical_json_bytes(event) + b"\n")
        return path

    def process(
        self,
        envelope: dict[str, Any],
        envelope_sha256: str,
    ) -> AlertDecision:
        status = envelope.get("validated_status")
        if status == "PASS":
            return AlertDecision("SILENT_ARCHIVE", None, None)
        if status not in {"FAIL", "BLOCKED"}:
            raise ValueError("alert manager accepts only validated terminal statuses")

        self.initialize()
        now = rfc3339(utc_now())
        root_cause, failing_checks = _root_cause(envelope)
        fingerprint = sha256_bytes(canonical_json_bytes(root_cause))
        severity = "CRITICAL" if status == "FAIL" else "WARNING"
        state_path = self.states / f"{fingerprint}.json"

        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["occurrences"] = int(state.get("occurrences", 1)) + 1
            state["last_seen_at"] = now
            state["latest_envelope_sha256"] = envelope_sha256
            atomic_write_bytes(state_path, canonical_json_bytes(state) + b"\n")
            self._publish_audit(
                {
                    "schema_version": "1.0",
                    "event": "DEDUPED",
                    "fingerprint": fingerprint,
                    "envelope_sha256": envelope_sha256,
                    "recorded_at": now,
                }
            )
            return AlertDecision(
                "DEDUPED",
                severity,
                fingerprint,
                state_path=str(state_path),
            )

        state = {
            "schema_version": "1.0",
            "fingerprint": fingerprint,
            "state": "NOTIFIED",
            "severity": severity,
            "validated_status": status,
            "root_cause": root_cause,
            "occurrences": 1,
            "first_seen_at": now,
            "last_seen_at": now,
            "latest_envelope_sha256": envelope_sha256,
        }
        atomic_write_bytes(state_path, canonical_json_bytes(state) + b"\n")
        outbox_item = {
            "schema_version": "1.0",
            "delivery_mode": "LOCAL_SIMULATION_ONLY",
            "severity": severity,
            "validated_status": status,
            "fingerprint": fingerprint,
            "failing_check_ids": failing_checks,
            "envelope_sha256": envelope_sha256,
            "created_at": now,
        }
        outbox_path = self.outbox / f"{fingerprint}_{envelope_sha256[:12]}.json"
        exclusive_publish_bytes(outbox_path, canonical_json_bytes(outbox_item) + b"\n")
        self._publish_audit(
            {
                "schema_version": "1.0",
                "event": "NOTIFIED_LOCAL",
                "fingerprint": fingerprint,
                "envelope_sha256": envelope_sha256,
                "recorded_at": now,
            }
        )
        return AlertDecision(
            "NOTIFIED_LOCAL",
            severity,
            fingerprint,
            state_path=str(state_path),
            outbox_path=str(outbox_path),
        )

    def acknowledge(self, fingerprint: str, reason: str) -> AlertDecision:
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError("fingerprint must be a lowercase SHA-256 digest")
        self.initialize()
        path = self.states / f"{fingerprint}.json"
        if not path.is_file():
            raise FileNotFoundError("alert fingerprint does not exist")
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("state") == "ACKNOWLEDGED":
            return AlertDecision("ALREADY_ACKNOWLEDGED", state.get("severity"), fingerprint, str(path))
        now = rfc3339(utc_now())
        normalized_reason = " ".join(reason.split())[:200] or "acknowledged"
        state["state"] = "ACKNOWLEDGED"
        state["acknowledged_at"] = now
        state["acknowledgement_reason"] = normalized_reason
        atomic_write_bytes(path, canonical_json_bytes(state) + b"\n")
        self._publish_audit(
            {
                "schema_version": "1.0",
                "event": "ACKNOWLEDGED",
                "fingerprint": fingerprint,
                "reason": normalized_reason,
                "recorded_at": now,
            }
        )
        return AlertDecision("ACKNOWLEDGED", state.get("severity"), fingerprint, str(path))

