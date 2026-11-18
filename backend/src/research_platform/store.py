from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
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
class ClaimResult:
    acquired: bool
    recovered_stale: bool
    state: str


class RuntimeStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.envelopes = root / "envelopes"
        self.claims = root / "claims"
        self.control = root / "control"
        self.audit = root / "audit"
        self.locks = root / "locks"

    def initialize(self) -> None:
        for path in (self.envelopes, self.claims, self.control, self.audit, self.locks):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)

    def disabled(self) -> bool:
        return (self.control / "DISABLED.json").is_file()

    def set_disabled(self, disabled: bool, reason: str) -> Path:
        self.initialize()
        normalized_reason = " ".join(reason.split())[:200] or "unspecified"
        now = utc_now()
        event = {
            "schema_version": "1.0",
            "event": "DISABLE" if disabled else "ENABLE",
            "reason": normalized_reason,
            "recorded_at": rfc3339(now),
            "pid": os.getpid(),
        }
        event_bytes = canonical_json_bytes(event) + b"\n"
        event_name = now.strftime("%Y%m%dT%H%M%S.%fZ") + f"_{os.getpid()}.json"
        event_path = self.audit / event_name
        exclusive_publish_bytes(event_path, event_bytes)
        marker = self.control / "DISABLED.json"
        if disabled:
            atomic_write_bytes(marker, event_bytes)
        else:
            marker.unlink(missing_ok=True)
        return event_path

    def claim(self, key: str, lease_seconds: int) -> ClaimResult:
        self.initialize()
        path = self.claims / f"{key}.json"
        now = utc_now()
        record = {
            "idempotency_key": key,
            "state": "IN_PROGRESS",
            "started_at": rfc3339(now),
            "pid": os.getpid(),
        }
        content = canonical_json_bytes(record) + b"\n"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                state = str(existing.get("state", "UNKNOWN"))
                if state == "COMPLETE":
                    return ClaimResult(False, False, state)
                started_text = str(existing.get("started_at", ""))
                started = datetime.fromisoformat(started_text.replace("Z", "+00:00"))
                age = (now - started.astimezone(timezone.utc)).total_seconds()
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                return ClaimResult(False, False, "CORRUPT")
            if state == "IN_PROGRESS" and age <= lease_seconds:
                return ClaimResult(False, False, state)
            atomic_write_bytes(path, content)
            return ClaimResult(True, True, "IN_PROGRESS")
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            return ClaimResult(True, False, "IN_PROGRESS")

    def complete_claim(self, key: str, envelope_sha256: str, status: str) -> None:
        path = self.claims / f"{key}.json"
        content = canonical_json_bytes(
            {
                "idempotency_key": key,
                "state": "COMPLETE",
                "completed_at": rfc3339(utc_now()),
                "envelope_sha256": envelope_sha256,
                "validated_status": status,
            }
        ) + b"\n"
        atomic_write_bytes(path, content)

    def head(self) -> str | None:
        path = self.root / "chain_head.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        digest = value.get("envelope_sha256")
        return digest if isinstance(digest, str) and len(digest) == 64 else None

    def publish_envelope(self, envelope: dict[str, Any]) -> tuple[Path, str]:
        self.initialize()
        payload = dict(envelope)
        payload.pop("envelope_sha256", None)
        digest = sha256_bytes(canonical_json_bytes(payload))
        payload["envelope_sha256"] = digest
        content = canonical_json_bytes(payload) + b"\n"
        timestamp = str(payload["finished_at"]).replace(":", "").replace("-", "").replace(".", "")
        path = self.envelopes / f"{timestamp}_{payload['automation_run_id']}.json"
        exclusive_publish_bytes(path, content)
        atomic_write_bytes(
            self.root / "chain_head.json",
            canonical_json_bytes(
                {
                    "envelope_sha256": digest,
                    "path": str(path.relative_to(self.root)),
                    "updated_at": rfc3339(utc_now()),
                }
            ) + b"\n",
        )
        return path, digest

    def read_envelope_by_digest(self, digest: str) -> dict[str, Any] | None:
        for path in self.envelopes.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("envelope_sha256") == digest:
                return value
        return None

    def verify_chain(self) -> tuple[bool, list[str]]:
        issues: list[str] = []
        envelopes: dict[str, dict[str, Any]] = {}
        for path in self.envelopes.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                claimed = value.pop("envelope_sha256")
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                issues.append(f"{path.name}: unreadable envelope: {type(exc).__name__}")
                continue
            actual = sha256_bytes(canonical_json_bytes(value))
            if claimed != actual:
                issues.append(f"{path.name}: envelope hash mismatch")
                continue
            value["envelope_sha256"] = claimed
            envelopes[claimed] = value
        head = self.head()
        if not envelopes:
            return (head is None, issues + ([] if head is None else ["head exists without envelopes"]))
        if head not in envelopes:
            issues.append("chain head does not reference an envelope")
            return False, issues
        visited: set[str] = set()
        cursor: str | None = head
        while cursor is not None:
            if cursor in visited:
                issues.append("envelope chain contains a cycle")
                break
            visited.add(cursor)
            envelope = envelopes.get(cursor)
            if envelope is None:
                issues.append("envelope chain references a missing parent")
                break
            parent = envelope.get("previous_envelope_sha256")
            if parent is not None and not (isinstance(parent, str) and len(parent) == 64):
                issues.append("invalid parent digest")
                break
            cursor = parent
        if visited != set(envelopes):
            issues.append("unreachable envelope exists outside the chain")
        return not issues, issues
