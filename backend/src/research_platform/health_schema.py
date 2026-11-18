from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import ALLOWED_HEALTH_STATUSES


class DuplicateKeyError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class HealthValidation:
    valid: bool
    data: dict[str, Any] | None
    issues: tuple[ValidationIssue, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.as_dict() for issue in self.issues],
            "validated_status": self.data.get("overall_status") if self.valid and self.data else None,
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _issue(issues: list[ValidationIssue], code: str, path: str, message: str) -> None:
    issues.append(ValidationIssue(code=code, path=path, message=message))


def _strict_bool(
    data: dict[str, Any],
    key: str,
    expected: bool,
    issues: list[ValidationIssue],
) -> None:
    value = data.get(key)
    if type(value) is not bool:
        _issue(issues, "TYPE", f"$.{key}", "must be a JSON boolean")
    elif value is not expected:
        _issue(issues, "UNSAFE_FLAG", f"$.{key}", f"must equal {str(expected).lower()}")


def parse_health_bytes(content: bytes, maximum_bytes: int) -> tuple[dict[str, Any] | None, tuple[ValidationIssue, ...]]:
    issues: list[ValidationIssue] = []
    if len(content) > maximum_bytes:
        _issue(issues, "SIZE_LIMIT", "$", "health JSON exceeds configured limit")
        return None, tuple(issues)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        _issue(issues, "UTF8", "$", "health JSON is not valid UTF-8")
        return None, tuple(issues)
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        _issue(issues, "JSON_PARSE", "$", str(exc))
        return None, tuple(issues)
    if not isinstance(value, dict):
        _issue(issues, "TYPE", "$", "health JSON must be an object")
        return None, tuple(issues)
    return value, tuple(issues)


def validate_health_data(data: dict[str, Any], identity: dict[str, Any]) -> HealthValidation:
    issues: list[ValidationIssue] = []
    required = {
        "schema_version",
        "checked_at",
        "overall_status",
        "research_spec_id",
        "run_id",
        "checks",
        "canonical_result_identity",
        "governance",
        "database_modified",
        "research_algorithm_executed",
        "walk_forward_executed",
        "main_executed",
        "pyc_created",
        "credentials_recorded",
        "oos_used_for_tuning",
        "new_research_gate_created",
        "research_cache_modified",
        "writes_outside_health_check",
        "official_assets_unchanged_during_run",
    }
    missing = sorted(required - set(data))
    for key in missing:
        _issue(issues, "REQUIRED", f"$.{key}", "required field is missing")

    if data.get("research_spec_id") != identity.get("research_spec_id"):
        _issue(issues, "IDENTITY", "$.research_spec_id", "research specification does not match locked identity")
    if data.get("run_id") != identity.get("run_id"):
        _issue(issues, "IDENTITY", "$.run_id", "run id does not match locked identity")

    status = data.get("overall_status")
    if status not in ALLOWED_HEALTH_STATUSES:
        _issue(issues, "ENUM", "$.overall_status", "unknown health status")

    checked_at = data.get("checked_at")
    if not isinstance(checked_at, str):
        _issue(issues, "TYPE", "$.checked_at", "must be a timestamp string")
    else:
        try:
            datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        except ValueError:
            _issue(issues, "FORMAT", "$.checked_at", "must be an RFC3339-compatible timestamp")

    checks = data.get("checks")
    check_statuses: list[str] = []
    if not isinstance(checks, list) or not checks:
        _issue(issues, "TYPE", "$.checks", "must be a non-empty list")
    elif len(checks) > 2000:
        _issue(issues, "SIZE_LIMIT", "$.checks", "too many checks")
    else:
        seen: set[str] = set()
        for index, check in enumerate(checks):
            base = f"$.checks[{index}]"
            if not isinstance(check, dict):
                _issue(issues, "TYPE", base, "check must be an object")
                continue
            missing_check = {
                "check_id",
                "status",
                "category",
                "message",
                "expected",
                "actual",
                "evidence",
            } - set(check)
            for key in sorted(missing_check):
                _issue(issues, "REQUIRED", f"{base}.{key}", "required check field is missing")
            check_id = check.get("check_id")
            if not isinstance(check_id, str) or not check_id or len(check_id) > 200:
                _issue(issues, "TYPE", f"{base}.check_id", "invalid check id")
            elif check_id in seen:
                _issue(issues, "DUPLICATE", f"{base}.check_id", "check id must be unique")
            else:
                seen.add(check_id)
            check_status = check.get("status")
            if check_status not in ALLOWED_HEALTH_STATUSES:
                _issue(issues, "ENUM", f"{base}.status", "unknown check status")
            else:
                check_statuses.append(check_status)
            if not isinstance(check.get("category"), str):
                _issue(issues, "TYPE", f"{base}.category", "category must be a string")
            if not isinstance(check.get("message"), str):
                _issue(issues, "TYPE", f"{base}.message", "message must be a string")

    if check_statuses:
        derived = "BLOCKED" if "BLOCKED" in check_statuses else "FAIL" if "FAIL" in check_statuses else "PASS"
        if status != derived:
            _issue(issues, "STATUS_MISMATCH", "$.overall_status", f"must equal status derived from checks: {derived}")

    canonical = data.get("canonical_result_identity")
    if not isinstance(canonical, dict):
        _issue(issues, "TYPE", "$.canonical_result_identity", "must be an object")
    else:
        expected_canonical = {
            "rows": identity.get("canonical_rows"),
            "columns": identity.get("canonical_columns"),
            "windows": identity.get("windows"),
            "status_counts": identity.get("status_counts"),
            "formal_oos_non_null": identity.get("formal_oos_non_null"),
            "shadow_oos_non_null": identity.get("shadow_oos_non_null"),
            "overlap": identity.get("formal_shadow_overlap"),
            "neither": identity.get("neither_oos_non_null"),
        }
        for key, expected in expected_canonical.items():
            if canonical.get(key) != expected:
                _issue(issues, "SEMANTIC_IDENTITY", f"$.canonical_result_identity.{key}", "does not match locked canonical identity")
        counts = canonical.get("status_counts")
        if isinstance(counts, dict):
            total = sum(value for value in counts.values() if type(value) is int)
            if total != identity.get("canonical_rows"):
                _issue(issues, "SEMANTIC_COUNT", "$.canonical_result_identity.status_counts", "status count total is inconsistent")

    governance = data.get("governance")
    if not isinstance(governance, dict):
        _issue(issues, "TYPE", "$.governance", "must be an object")
    else:
        required_governance = {
            "formal_shadow_must_be_mutually_exclusive": True,
            "null_must_not_be_coerced_to_zero": True,
            "health_results_must_not_be_used_for_tuning": True,
            "information_set_33_columns_are_diagnostic_only": True,
            "new_gate_created": False,
        }
        for key, expected in required_governance.items():
            if governance.get(key) is not expected:
                _issue(issues, "GOVERNANCE", f"$.governance.{key}", f"must equal {expected!r}")

    for key in (
        "database_modified",
        "research_algorithm_executed",
        "walk_forward_executed",
        "main_executed",
        "pyc_created",
        "credentials_recorded",
        "oos_used_for_tuning",
        "new_research_gate_created",
        "research_cache_modified",
        "writes_outside_health_check",
    ):
        _strict_bool(data, key, False, issues)
    _strict_bool(data, "official_assets_unchanged_during_run", True, issues)

    return HealthValidation(valid=not issues, data=data if not issues else None, issues=tuple(issues))


def validate_health_bytes(content: bytes, identity: dict[str, Any], maximum_bytes: int) -> HealthValidation:
    data, parse_issues = parse_health_bytes(content, maximum_bytes)
    if parse_issues or data is None:
        return HealthValidation(valid=False, data=None, issues=parse_issues)
    return validate_health_data(data, identity)


def validate_health_file(path: Path, identity: dict[str, Any], maximum_bytes: int) -> HealthValidation:
    try:
        content = path.read_bytes()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return HealthValidation(
            valid=False,
            data=None,
            issues=(ValidationIssue("READ", "$", f"cannot read health output: {type(exc).__name__}"),),
        )
    return validate_health_bytes(content, identity, maximum_bytes)


def status_counts(data: dict[str, Any]) -> dict[str, int]:
    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    counts = Counter(check.get("status") for check in checks if isinstance(check, dict))
    return {status: counts.get(status, 0) for status in ("PASS", "FAIL", "BLOCKED")}

