from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import selectors
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping

from .ai_boundary import build_minimized_discovery_ai_input
from .historical_contract import canonical_artifact_path, locked_research_is_unchanged
from .ai_candidate_proposer import request_ollama_proposals
from .ai_explainer import (
    AIExplanationError,
    normalize_model,
    normalize_ollama_model,
    ollama_model_available,
    request_ai_explanation,
)
from .factor_registry import (
    FactorRegistryController,
    FactorRegistryError,
)


class DiscoveryConfigurationError(ValueError):
    pass


class DiscoveryResultError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DiscoveryConfigurationError(message)


@dataclass(frozen=True)
class DiscoveryConfig:
    path: Path
    platform_root: Path
    python_path: Path
    project_root: Path
    runner_path: Path
    result_path: Path
    timeout_seconds: float
    bind_host: str
    port: int
    allowed_origins: tuple[str, ...]
    run_header: str
    research_spec_id: str
    feature_snapshot_identity: str
    implementation_sha256: dict[str, str]


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "discovery_config.json"


def load_discovery_config(path: Path, *, verify_hashes: bool = True) -> DiscoveryConfig:
    resolved = path.resolve()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryConfigurationError(f"cannot read discovery config: {exc}") from exc
    _require(isinstance(raw, dict), "discovery config must be an object")
    _require(raw.get("schema_version") == "1.0", "wrong discovery config schema")
    api = raw.get("api")
    command = raw.get("command")
    identity = raw.get("identity")
    hashes = raw.get("implementation_sha256")
    _require(isinstance(api, dict), "api config missing")
    _require(isinstance(command, dict), "command config missing")
    _require(isinstance(identity, dict), "identity config missing")
    _require(isinstance(hashes, dict) and hashes, "implementation hashes missing")
    _require(api.get("bind_host") == "127.0.0.1", "discovery API must bind to IPv4 loopback")
    port = int(api.get("port", 0))
    _require(1024 <= port <= 65535, "discovery API port out of range")
    origins = api.get("allowed_origins")
    _require(
        isinstance(origins, list)
        and origins
        and set(origins) <= {"http://localhost:3000", "http://127.0.0.1:3000"},
        "unsafe discovery API origin",
    )
    run_header = api.get("run_header")
    _require(run_header == "run-development-discovery-only", "wrong fixed run header")

    python_setting = os.environ.get("PLATFORM_PYTHON", str(command.get("python_path", "")))
    python_path = Path(sys.executable if python_setting == "CURRENT_INTERPRETER" else python_setting)
    project_root = Path(os.environ.get("DISCOVERY_ENGINE_ROOT", str(command.get("project_root", ""))))
    if not project_root.is_absolute():
        project_root = (resolved.parent.parent / project_root).resolve()
    runner_relative = Path(str(command.get("runner_path", "")))
    result_relative = Path(str(command.get("result_path", "")))
    _require(python_path.is_absolute() and python_path.is_file(), "fixed Python interpreter is missing")
    _require(project_root.is_absolute() and project_root.is_dir(), "fixed development discovery project root is missing")
    # A Python virtual environment normally exposes its interpreter as a
    # symlink. The allowlist locks the exact venv path; research source files
    # remain independently content-hash locked below.
    for relative, label in ((runner_relative, "runner"), (result_relative, "result")):
        _require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe {label} path")
    _require(
        canonical_artifact_path(runner_relative.as_posix()) == "factor_discovery/run_discovery.py",
        "only the reviewed development discovery runner is allowlisted",
    )
    _require(
        canonical_artifact_path(result_relative.as_posix()) == "runtime/factor_discovery/discovery_result.json",
        "wrong development discovery result path",
    )
    runner_path = project_root / runner_relative
    result_path = project_root / result_relative
    _require(runner_path.is_file() and not runner_path.is_symlink(), "development discovery runner is missing or symlinked")
    timeout_seconds = float(command.get("timeout_seconds", 0))
    _require(30 <= timeout_seconds <= 900, "development discovery timeout out of range")

    _require(
        identity.get("research_spec_id") == "v4_automatic_factor_discovery_v8_development_only_v1",
        "wrong development discovery research spec",
    )
    _require(
        identity.get("allowed_roles") == ["train_discovery", "selection", "calibration"],
        "development discovery role allowlist changed",
    )
    _require(identity.get("formal_sample_allowed") is False, "Formal sample must remain forbidden")
    snapshot_identity = identity.get("feature_snapshot_identity")
    _require(isinstance(snapshot_identity, str) and len(snapshot_identity) == 64, "bad snapshot identity")

    normalized_hashes: dict[str, str] = {}
    for relative_text, expected in hashes.items():
        relative = Path(str(relative_text))
        _require(not relative.is_absolute() and ".." not in relative.parts, "unsafe implementation path")
        _require(isinstance(expected, str) and len(expected) == 64, "bad implementation hash")
        implementation_path = project_root / relative
        _require(implementation_path.is_file() and not implementation_path.is_symlink(), "implementation file missing")
        if verify_hashes:
            _require(_sha256_file(implementation_path) == expected, f"implementation hash mismatch: {relative}")
        normalized_hashes[str(relative)] = expected
    _require(str(runner_relative) in normalized_hashes, "runner hash is not locked")

    return DiscoveryConfig(
        path=resolved,
        platform_root=resolved.parent.parent,
        python_path=python_path,
        project_root=project_root,
        runner_path=runner_path,
        result_path=result_path,
        timeout_seconds=timeout_seconds,
        bind_host="127.0.0.1",
        port=port,
        allowed_origins=tuple(origins),
        run_header=run_header,
        research_spec_id=str(identity["research_spec_id"]),
        feature_snapshot_identity=str(snapshot_identity),
        implementation_sha256=normalized_hashes,
    )


def build_command(config: DiscoveryConfig) -> tuple[str, ...]:
    return (str(config.python_path), "-B", str(config.runner_path))


def parse_progress(line: str) -> tuple[int, str] | None:
    screening = re.search(r"Train screening (\d+)/1000", line)
    if screening:
        completed = min(1000, int(screening.group(1)))
        return 5 + int(55 * completed / 1000), f"Train screening {completed}/1000"
    correlation = re.search(r"Correlation months (\d+)/227", line)
    if correlation:
        completed = min(227, int(correlation.group(1)))
        return 60 + int(15 * completed / 227), f"Correlation pruning {completed}/227"
    generation = re.search(r"GA (\d+)/8", line)
    if generation:
        completed = min(8, int(generation.group(1)))
        return 75 + int(17 * completed / 8), f"Genetic search {completed}/8"
    if "Loading Train Discovery frame" in line:
        return 3, "Loading training panel"
    if "Loading Selection frame" in line:
        return 94, "Freezing Selection candidate"
    if "Loading Calibration frame" in line:
        return 97, "Single Calibration evaluation"
    return None


def summarize_result(config: DiscoveryConfig) -> dict[str, Any]:
    try:
        result = json.loads(config.result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryResultError(f"cannot read development discovery result: {exc}") from exc
    if result.get("research_spec_id") != config.research_spec_id:
        raise DiscoveryResultError("development discovery result research spec mismatch")
    if result.get("feature_snapshot_identity") != config.feature_snapshot_identity:
        raise DiscoveryResultError("development discovery result snapshot mismatch")
    if result.get("formal_sample_accessed") is not False:
        raise DiscoveryResultError("development discovery result does not preserve Formal isolation")
    if not locked_research_is_unchanged(result):
        raise DiscoveryResultError("development discovery result reports a locked research modification")
    quality = result.get("quality_checks")
    calibration = result.get("calibration")
    if not isinstance(quality, dict) or quality.get("status") != "PASS":
        raise DiscoveryResultError("development discovery quality checks did not pass")
    if not isinstance(calibration, dict):
        raise DiscoveryResultError("development discovery calibration result missing")
    confidence = float(calibration.get("validation_confidence", math.nan))
    threshold = float(result.get("calibration_threshold", math.nan))
    if not np_isfinite(confidence) or not np_isfinite(threshold):
        raise DiscoveryResultError("development discovery calibration values are invalid")
    return {
        "result_state": str(result.get("state")),
        "calibration_passed": bool(result.get("calibration_passed")),
        "calibration_confidence": confidence,
        "calibration_threshold": threshold,
        "candidate_count": int(result.get("candidate_count", 0)),
        "train_hygiene_pass_count": int(result.get("train_hygiene_pass_count", 0)),
        "top_stability_count": int(result.get("top_stability_count", 0)),
        "selected_factor_count": int(result.get("correlation_pruned_factor_count", 0)),
        "cache_rows": int(quality.get("cache_rows", 0)),
        "duplicate_keys": int(quality.get("duplicate_permno_pointdate_keys", -1)),
        "score_coverage_by_role": dict(quality.get("score_coverage_by_role", {})),
        "generated_at": str(result.get("generated_at", "")),
        "formal_sample_accessed": False,
    }


def np_isfinite(value: float) -> bool:
    return math.isfinite(value)


class DiscoveryController:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path.resolve()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._status: dict[str, Any] = {
            "state": "READY",
            "progress": 100,
            "stage": "Latest result loaded",
            "message": "The same frozen development discovery workflow is available",
            "started_at": None,
            "finished_at": None,
            "result": None,
            "formal_sample_allowed": False,
        }
        try:
            config = load_discovery_config(self.config_path)
            self._status["result"] = summarize_result(config)
        except (DiscoveryConfigurationError, DiscoveryResultError) as exc:
            self._status.update(state="BLOCKED", progress=0, stage="Configuration validation failed", message=str(exc))
        self._persist()

    def _persist(self) -> None:
        try:
            platform_root = self.config_path.parent.parent
            target = platform_root / "runtime" / "discovery" / "status.json"
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self._status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        except OSError:
            pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._status))

    def start(self) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if self._status.get("state") == "RUNNING":
                return False, json.loads(json.dumps(self._status))
            try:
                config = load_discovery_config(self.config_path)
            except DiscoveryConfigurationError as exc:
                self._status.update(state="BLOCKED", progress=0, stage="Start rejected", message=str(exc))
                self._persist()
                return False, json.loads(json.dumps(self._status))
            self._status = {
                "state": "RUNNING",
                "progress": 1,
                "stage": "Verifying frozen implementation",
                "message": "Development discovery only; Formal access is unavailable",
                "started_at": _utc_now(),
                "finished_at": None,
                "result": self._status.get("result"),
                "formal_sample_allowed": False,
            }
            self._persist()
            thread = threading.Thread(target=self._run, args=(config,), daemon=True)
            thread.start()
            return True, json.loads(json.dumps(self._status))

    def _set_progress(self, progress: int, stage: str, message: str | None = None) -> None:
        with self._lock:
            self._status["progress"] = max(int(self._status.get("progress", 0)), progress)
            self._status["stage"] = stage
            if message:
                self._status["message"] = message[:500]
            self._persist()

    def _finish(self, *, state: str, stage: str, message: str, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._status.update(
                state=state,
                progress=100 if state in {"PASSED", "COMPLETED_NO_PASS"} else int(self._status.get("progress", 0)),
                stage=stage,
                message=message[:500],
                finished_at=_utc_now(),
            )
            if result is not None:
                self._status["result"] = result
            self._process = None
            self._persist()

    def _run(self, config: DiscoveryConfig) -> None:
        environment = {
            key: os.environ[key]
            for key in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
            if key in os.environ
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            process = subprocess.Popen(
                list(build_command(config)),
                cwd=str(config.project_root),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            self._finish(state="FAILED", stage="Process did not start", message=str(exc))
            return
        with self._lock:
            self._process = process
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + config.timeout_seconds
        last_line = ""
        timed_out = False
        while process.poll() is None:
            if time.monotonic() > deadline:
                timed_out = True
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
            for key, _ in selector.select(timeout=0.25):
                line = key.fileobj.readline()
                if not line:
                    continue
                last_line = line.strip()
                progress = parse_progress(last_line)
                if progress:
                    self._set_progress(progress[0], progress[1], last_line)
        for line in process.stdout:
            if line.strip():
                last_line = line.strip()
        selector.close()
        exit_code = process.wait()
        if timed_out:
            self._finish(state="BLOCKED", stage="Execution timed out", message="development discovery exceeded the fixed 300-second limit and was stopped")
            return
        if exit_code != 0:
            self._finish(state="FAILED", stage="Execution failed", message=last_line or f"development discovery exit code {exit_code}")
            return
        try:
            result = summarize_result(load_discovery_config(self.config_path))
        except (DiscoveryConfigurationError, DiscoveryResultError) as exc:
            self._finish(state="FAILED", stage="Result validation failed", message=str(exc))
            return
        if result["calibration_passed"]:
            self._finish(state="PASSED", stage="Development Calibration passed", message="Result updated; Formal remains locked", result=result)
        else:
            self._finish(state="COMPLETED_NO_PASS", stage="Development workflow completed", message="No candidate passed the preset Calibration gate; no fallback was used", result=result)


class AIExplanationController:
    """Run one no-tool explanation against a minimized development discovery summary."""

    def __init__(
        self,
        discovery_controller: DiscoveryController,
        config_path: Path,
        *,
        environment: Mapping[str, str] | None = None,
        requester: Callable[..., dict[str, Any]] = request_ai_explanation,
        local_model_checker: Callable[[str], bool] | None = None,
    ) -> None:
        source = os.environ if environment is None else environment
        self.discovery_controller = discovery_controller
        self.config_path = config_path.resolve()
        self._requester = requester
        self._api_key = source.get("OPENAI_API_KEY", "").strip()
        self._lock = threading.Lock()
        self._model = ""
        self._provider = source.get("PLATFORM_AI_PROVIDER", "ollama").strip().lower()
        self._status: dict[str, Any] = {
            "state": "UNCONFIGURED",
            "configured": False,
            "message": "AI is unconfigured; discovery and deterministic checks remain available",
            "model": None,
            "provider": self._provider,
            "started_at": None,
            "finished_at": None,
            "explanation": None,
            "decision_authority": False,
            "tools_allowed": False,
            "raw_research_data_allowed": False,
        }
        if self._provider not in {"ollama", "openai"}:
            self._status.update(
                state="BLOCKED",
                message="AI provider is not allowlisted",
            )
            return
        try:
            if self._provider == "ollama":
                self._model = normalize_ollama_model(source.get("OLLAMA_MODEL"))
            else:
                self._model = normalize_model(source.get("OPENAI_MODEL"))
        except Exception:
            self._status.update(state="BLOCKED", message="Local AI model is not allowlisted")
            return
        if self._provider == "openai" and not self._api_key:
            self._status["message"] = "OpenAI is unconfigured; discovery and deterministic checks remain available"
            return
        if self._provider == "ollama":
            checker = local_model_checker or (lambda model: ollama_model_available(model))
            if not checker(self._model):
                self._status.update(
                    message=f"Local open-source model not detected: {self._model}; other platform features remain available",
                    model=self._model,
                )
                return
        self._status.update(
            state="READY",
            configured=True,
            message="A read-only explanation is available for the latest development discovery summary",
            model=self._model,
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = json.loads(json.dumps(self._status))
        explanation = status.get("explanation")
        discovery_result = self.discovery_controller.status().get("result")
        if (
            isinstance(explanation, dict)
            and isinstance(discovery_result, dict)
            and explanation.get("source_generated_at") != discovery_result.get("generated_at")
        ):
            status.update(
                state="STALE",
                message="Discovery result changed; regenerate the read-only explanation",
            )
        return status

    def start(self) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if not self._status["configured"] or self._status["state"] == "RUNNING":
                return False, json.loads(json.dumps(self._status))
        discovery_status = self.discovery_controller.status()
        if discovery_status.get("state") == "RUNNING":
            with self._lock:
                self._status.update(state="BLOCKED", message="Wait for discovery to finish before requesting an explanation")
                return False, json.loads(json.dumps(self._status))
        try:
            result = summarize_result(load_discovery_config(self.config_path))
            payload = build_minimized_discovery_ai_input(result)
            source_generated_at = result["generated_at"]
        except (DiscoveryConfigurationError, DiscoveryResultError, TypeError, ValueError):
            with self._lock:
                self._status.update(state="BLOCKED", message="development discovery result validation failed; AI explanation was not started")
                return False, json.loads(json.dumps(self._status))
        with self._lock:
            if self._status["state"] == "RUNNING":
                return False, json.loads(json.dumps(self._status))
            self._status.update(
                state="RUNNING",
                message="Explaining the minimized development summary",
                started_at=_utc_now(),
                finished_at=None,
                explanation=None,
            )
            thread = threading.Thread(target=self._run, args=(payload, source_generated_at), daemon=True)
            thread.start()
            return True, json.loads(json.dumps(self._status))

    def _run(self, payload: dict[str, Any], source_generated_at: str) -> None:
        try:
            explanation = self._requester(
                provider=self._provider,
                api_key=self._api_key,
                model=self._model,
                payload=payload,
                timeout_seconds=45.0,
            )
        except AIExplanationError:
            with self._lock:
                self._status.update(
                    state="FAILED",
                    message="AI explanation failed; research results and platform state are unchanged",
                    finished_at=_utc_now(),
                )
            return
        explanation["source_generated_at"] = source_generated_at
        with self._lock:
            self._status.update(
                state="COMPLETED",
                message="Read-only explanation generated; no research action was triggered",
                finished_at=_utc_now(),
                explanation=explanation,
            )


class AICandidateProposalController:
    """Use a local open model to propose bounded structures from feature labels only."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        requester: Callable[..., dict[str, Any]] = request_ollama_proposals,
        local_model_checker: Callable[[str], bool] | None = None,
    ) -> None:
        source = os.environ if environment is None else environment
        self._requester = requester
        self.model = normalize_ollama_model(source.get("OLLAMA_MODEL"))
        checker = local_model_checker or (lambda model: ollama_model_available(model))
        self.configured = checker(self.model)

    def status(self) -> dict[str, Any]:
        return {
            "state": "READY" if self.configured else "UNCONFIGURED",
            "configured": self.configured,
            "model": self.model,
            "message": (
                "Local open-model candidate proposals are ready"
                if self.configured
                else "Local open model is unavailable; deterministic discovery remains available"
            ),
            "raw_data_allowed": False,
            "targets_allowed": False,
            "validation_results_allowed": False,
            "decision_authority": False,
        }

    def propose(self, feature_columns: list[str]) -> dict[str, Any]:
        if not self.configured:
            raise AIExplanationError("Local open model is unavailable")
        return self._requester(
            model=self.model,
            feature_columns=feature_columns,
            timeout_seconds=90.0,
        )


class DiscoveryRequestHandler(BaseHTTPRequestHandler):
    controller: DiscoveryController
    ai_controller: AIExplanationController
    ai_proposal_controller: AICandidateProposalController
    registry: FactorRegistryController
    config: DiscoveryConfig
    server_version = "ResearchDiscovery/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in self.config.allowed_origins

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin in self.config.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:
        if not self._origin_allowed():
            self._send(403, {"state": "DENIED", "message": "origin is not allowed"})
            return
        self.send_response(204)
        origin = self.headers.get("Origin")
        if origin in self.config.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Research-Discovery, X-Research-AI, X-Research-Review",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._origin_allowed():
            self._send(403, {"state": "DENIED"})
            return
        if self.path == "/api/discovery/status":
            self._send(200, self.controller.status())
            return
        if self.path == "/api/ai/status":
            self._send(200, self.ai_controller.status())
            return
        if self.path == "/api/ai/proposals/status":
            self._send(200, self.ai_proposal_controller.status())
            return
        if self.path == "/api/candidates/status":
            try:
                status = self.registry.status()
            except (FactorRegistryError, OSError) as exc:
                self._send(409, {"state": "BLOCKED", "message": str(exc)})
                return
            self._send(200, status)
            return
        if self.path not in {"/api/discovery/status", "/api/ai/status", "/api/ai/proposals/status", "/api/candidates/status"}:
            self._send(404 if self._origin_allowed() else 403, {"state": "DENIED"})
            return

    def do_POST(self) -> None:
        if not self._origin_allowed():
            self._send(403, {"state": "DENIED"})
            return
        if self.path not in {
            "/api/discovery/run",
            "/api/ai/explain",
            "/api/ai/propose",
            "/api/candidates/review",
            "/api/candidates/freeze",
        }:
            self._send(404 if self._origin_allowed() else 403, {"state": "DENIED"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"state": "DENIED", "message": "invalid content length"})
            return
        maximum_body = 16_384 if self.path == "/api/ai/propose" else 2_048
        if not 0 <= content_length <= maximum_body:
            self._send(400, {"state": "DENIED", "message": "request body is too large"})
            return
        if self.path == "/api/discovery/run":
            if self.headers.get("X-Research-Discovery") != self.config.run_header:
                self._send(403, {"state": "DENIED", "message": "fixed discovery header missing"})
                return
            if content_length > 0:
                self._send(400, {"state": "DENIED", "message": "endpoint accepts no input"})
                return
            accepted, status = self.controller.start()
            self._send(202 if accepted else 409, status)
            return
        if self.path == "/api/ai/explain":
            if self.headers.get("X-Research-AI") != "explain-discovery-summary-only":
                self._send(403, {"state": "DENIED", "message": "fixed AI header missing"})
                return
            if content_length > 0:
                self._send(400, {"state": "DENIED", "message": "endpoint accepts no input"})
                return
            accepted, status = self.ai_controller.start()
            self._send(202 if accepted else 409, status)
            return
        if self.path == "/api/ai/propose":
            if self.headers.get("X-Research-AI") != "propose-feature-labels-only":
                self._send(403, {"state": "DENIED", "message": "fixed AI proposal header missing"})
                return
            if content_length == 0 or self.headers.get_content_type() != "application/json":
                self._send(400, {"state": "DENIED", "message": "AI proposal endpoint requires JSON"})
                return
            try:
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, {"state": "DENIED", "message": "AI proposal body is invalid"})
                return
            if not isinstance(body, dict) or set(body) != {"feature_columns"}:
                self._send(400, {"state": "DENIED", "message": "AI proposal body shape is invalid"})
                return
            feature_columns = body["feature_columns"]
            if not isinstance(feature_columns, list) or not all(isinstance(item, str) for item in feature_columns):
                self._send(400, {"state": "DENIED", "message": "feature columns must be text"})
                return
            try:
                proposals = self.ai_proposal_controller.propose(feature_columns)
            except AIExplanationError as exc:
                self._send(409, {"state": "BLOCKED", "message": str(exc)})
                return
            self._send(200, {"state": "COMPLETED", **proposals})
            return
        if self.headers.get("X-Research-Review") != "review-components-only":
            self._send(403, {"state": "DENIED", "message": "fixed review header missing"})
            return
        if self.path == "/api/candidates/freeze":
            if content_length > 0:
                self._send(400, {"state": "DENIED", "message": "freeze endpoint accepts no input"})
                return
            try:
                status = self.registry.freeze()
            except FactorRegistryError as exc:
                self._send(409, {"state": "BLOCKED", "message": str(exc)})
                return
            self._send(200, status)
            return
        if content_length == 0 or self.headers.get_content_type() != "application/json":
            self._send(400, {"state": "DENIED", "message": "review endpoint requires JSON"})
            return
        try:
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"state": "DENIED", "message": "review body is invalid"})
            return
        if not isinstance(body, dict) or set(body) != {"factor_id", "decision"}:
            self._send(400, {"state": "DENIED", "message": "review body shape is invalid"})
            return
        if not isinstance(body["factor_id"], str) or not isinstance(body["decision"], str):
            self._send(400, {"state": "DENIED", "message": "review values must be text"})
            return
        try:
            status = self.registry.update_review(body["factor_id"], body["decision"])
        except FactorRegistryError as exc:
            self._send(409, {"state": "BLOCKED", "message": str(exc)})
            return
        self._send(200, status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research-discovery-api")
    parser.add_argument("--config", type=Path, default=default_config_path())
    args = parser.parse_args(argv)
    config = load_discovery_config(args.config)
    controller = DiscoveryController(args.config)
    ai_controller = AIExplanationController(controller, args.config)
    ai_proposal_controller = AICandidateProposalController()
    registry = FactorRegistryController(
        project_root=config.project_root,
        result_path=config.result_path,
        state_path=config.platform_root / "runtime" / "factor_registry" / "state.json",
    )
    handler = type(
        "BoundDiscoveryRequestHandler",
        (DiscoveryRequestHandler,),
        {
            "controller": controller,
            "ai_controller": ai_controller,
            "ai_proposal_controller": ai_proposal_controller,
            "registry": registry,
            "config": config,
        },
    )
    server = ThreadingHTTPServer((config.bind_host, config.port), handler)
    print(json.dumps({"state": "LISTENING", "host": config.bind_host, "port": config.port}), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
