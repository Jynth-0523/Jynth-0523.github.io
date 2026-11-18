from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    LOCKED_RESEARCH_SPEC_ID,
    LOCKED_RUN_ID,
    ONLY_COMMAND_ID,
    PLATFORM_SCHEMA_VERSION,
)
from .util import path_within, sha256_file


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PlatformConfig:
    path: Path
    project_root: Path
    raw: dict[str, Any]
    runtime_root: Path
    script_path: Path
    health_status_path: Path
    timeout_seconds: float
    blocked_retries: int
    retry_backoff_seconds: float
    idempotency_bucket_seconds: int
    claim_lease_seconds: int
    maximum_health_json_bytes: int
    maximum_subprocess_output_bytes: int

    @property
    def command_id(self) -> str:
        return str(self.raw["command"]["command_id"])

    @property
    def script_sha256(self) -> str:
        return str(self.raw["command"]["script_sha256"])

    @property
    def identity(self) -> dict[str, Any]:
        return dict(self.raw["identity"])

    @property
    def environment_allowlist(self) -> tuple[str, ...]:
        return tuple(self.raw["environment_allowlist"])


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigurationError(message)


def load_config(path: Path, *, verify_script: bool = True) -> PlatformConfig:
    resolved_path = path.resolve()
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read platform config: {exc}") from exc

    _require(isinstance(raw, dict), "platform config must be an object")
    _require(raw.get("schema_version") == PLATFORM_SCHEMA_VERSION, "wrong config schema version")

    command = raw.get("command")
    identity = raw.get("identity")
    runtime = raw.get("runtime")
    governance = raw.get("governance")
    _require(isinstance(command, dict), "command config missing")
    _require(isinstance(identity, dict), "identity config missing")
    _require(isinstance(runtime, dict), "runtime config missing")
    _require(isinstance(governance, dict), "governance config missing")

    _require(command.get("command_id") == ONLY_COMMAND_ID, "non-allowlisted command id")
    _require(identity.get("research_spec_id") == LOCKED_RESEARCH_SPEC_ID, "wrong research spec id")
    _require(identity.get("run_id") == LOCKED_RUN_ID, "wrong locked run id")

    for flag in (
        "database_writes_allowed",
        "research_execution_allowed",
        "formal_shadow_pooling_allowed",
        "null_to_zero_allowed",
        "ai_tools_allowed",
        "ai_cross_run_memory_allowed",
    ):
        _require(governance.get(flag) is False, f"unsafe governance flag: {flag}")

    project_root = resolved_path.parent.parent
    runtime_value = runtime.get("root")
    _require(isinstance(runtime_value, str) and runtime_value, "runtime root missing")
    runtime_path_value = Path(runtime_value)
    _require(not runtime_path_value.is_absolute(), "runtime root must be project-relative")
    _require(".." not in runtime_path_value.parts, "runtime root cannot escape project")
    runtime_root = (project_root / runtime_path_value).resolve()
    _require(path_within(runtime_root, project_root), "runtime root escapes project")

    script_path = Path(str(command.get("script_path", "")))
    health_status_path = Path(str(command.get("health_status_path", "")))
    # Repository-relative defaults work independently of the shell working directory.
    if not script_path.is_absolute():
        script_path = project_root / script_path
    if not health_status_path.is_absolute():
        health_status_path = project_root / health_status_path
    _require(script_path.is_absolute(), "health script path must be absolute")
    _require(health_status_path.is_absolute(), "health status path must be absolute")
    _require(not script_path.is_symlink(), "health script may not be a symlink")
    _require(not health_status_path.is_symlink(), "health status may not be a symlink")
    _require(health_status_path.parent == script_path.parent, "health output must share locked health directory")

    expected_script_hash = command.get("script_sha256")
    _require(
        isinstance(expected_script_hash, str) and len(expected_script_hash) == 64,
        "invalid script hash",
    )
    if verify_script:
        _require(script_path.is_file(), "locked health script is missing")
        _require(sha256_file(script_path) == expected_script_hash, "locked health script hash mismatch")

    timeout_seconds = float(runtime.get("timeout_seconds", 0))
    blocked_retries = int(runtime.get("blocked_retries", -1))
    retry_backoff_seconds = float(runtime.get("retry_backoff_seconds", -1))
    idempotency_bucket_seconds = int(runtime.get("idempotency_bucket_seconds", 0))
    claim_lease_seconds = int(runtime.get("claim_lease_seconds", 0))
    maximum_health_json_bytes = int(runtime.get("maximum_health_json_bytes", 0))
    maximum_subprocess_output_bytes = int(runtime.get("maximum_subprocess_output_bytes", 0))

    _require(0.01 <= timeout_seconds <= 3600, "timeout out of range")
    _require(0 <= blocked_retries <= 2, "blocked retries out of range")
    _require(0 <= retry_backoff_seconds <= 60, "retry backoff out of range")
    _require(1 <= idempotency_bucket_seconds <= 86400, "idempotency bucket out of range")
    _require(1 <= claim_lease_seconds <= 86400, "claim lease out of range")
    _require(1024 <= maximum_health_json_bytes <= 100 * 1024 * 1024, "health size limit out of range")
    _require(1024 <= maximum_subprocess_output_bytes <= 10 * 1024 * 1024, "output limit out of range")

    environment_allowlist = raw.get("environment_allowlist")
    _require(isinstance(environment_allowlist, list), "environment allowlist missing")
    _require(all(isinstance(item, str) and item for item in environment_allowlist), "bad environment key")
    _require(len(environment_allowlist) == len(set(environment_allowlist)), "duplicate environment key")

    return PlatformConfig(
        path=resolved_path,
        project_root=project_root,
        raw=raw,
        runtime_root=runtime_root,
        script_path=script_path,
        health_status_path=health_status_path,
        timeout_seconds=timeout_seconds,
        blocked_retries=blocked_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        idempotency_bucket_seconds=idempotency_bucket_seconds,
        claim_lease_seconds=claim_lease_seconds,
        maximum_health_json_bytes=maximum_health_json_bytes,
        maximum_subprocess_output_bytes=maximum_subprocess_output_bytes,
    )

