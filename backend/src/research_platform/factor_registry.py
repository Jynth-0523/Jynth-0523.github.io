from __future__ import annotations

from .historical_contract import canonical_artifact_path, locked_research_is_unchanged

import hashlib
import json
import math
import os
import threading
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


REVIEW_DECISIONS = frozenset({"UNREVIEWED", "KEEP", "WATCH", "REJECT"})


class FactorRegistryError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FactorRegistryError(message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FactorRegistryError(f"cannot read {label}") from exc
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def build_registry_snapshot(*, project_root: Path, result_path: Path) -> dict[str, Any]:
    """Build the human-review registry from frozen development discovery artifacts."""
    result = _read_json(result_path, label="development discovery result")
    _require(result.get("formal_sample_accessed") is False, "development discovery result crossed the Formal boundary")
    _require(result.get("formal_sample_authorized") is False, "development discovery result authorized Formal access")
    _require(locked_research_is_unchanged(result), "development discovery result reports a locked research modification")
    quality = result.get("quality_checks")
    _require(isinstance(quality, dict) and quality.get("status") == "PASS", "development discovery quality checks did not pass")
    _require(int(quality.get("duplicate_permno_pointdate_keys", -1)) == 0, "development discovery cache contains duplicate stable keys")

    artifacts = result.get("artifacts")
    _require(isinstance(artifacts, dict), "development discovery artifact manifest is missing")
    expected_artifacts = {
        "candidate_ledger": Path("runtime/factor_discovery/candidate_ledger.json"),
        "train_screening": Path("runtime/factor_discovery/train_screening.parquet"),
    }
    resolved_artifacts: dict[str, Path] = {}
    artifact_hashes: dict[str, str] = {}
    for key, expected_relative in expected_artifacts.items():
        relative = Path(str(artifacts.get(key, "")))
        _require(canonical_artifact_path(relative.as_posix()) == expected_relative.as_posix(), f"unexpected development discovery {key} path")
        path = project_root / relative
        _require(path.is_file() and not path.is_symlink(), f"development discovery {key} is missing or symlinked")
        expected_hash = artifacts.get(f"{key}_sha256")
        _require(isinstance(expected_hash, str) and len(expected_hash) == 64, f"development discovery {key} hash is invalid")
        _require(_sha256_file(path) == expected_hash, f"development discovery {key} hash mismatch")
        resolved_artifacts[key] = path
        artifact_hashes[key] = expected_hash

    ledger = _read_json(resolved_artifacts["candidate_ledger"], label="candidate ledger")
    _require(ledger.get("formal_sample_accessed") is False, "candidate ledger crossed the Formal boundary")
    _require(ledger.get("generation_used_outcomes") is False, "candidate generation used outcomes")
    ledger_candidates = ledger.get("candidates")
    _require(isinstance(ledger_candidates, list) and len(ledger_candidates) == 1000, "candidate ledger is incomplete")
    ledger_by_factor = {
        str(item.get("factor")): item
        for item in ledger_candidates
        if isinstance(item, dict) and isinstance(item.get("factor"), str)
    }
    _require(len(ledger_by_factor) == len(ledger_candidates), "candidate factor ids are not unique")

    screening_columns = [
        "factor",
        "valid_months",
        "mean_rankic",
        "abs_mean_rankic",
        "icir",
        "abs_icir",
        "direction",
        "directional_consistency",
        "subperiod_stability",
        "valid_subperiod_ratio",
        "median_coverage",
        "passed_train_hygiene",
        "top_stability_100",
        "factor_stability_score",
    ]
    screening_table = pq.read_table(resolved_artifacts["train_screening"], columns=screening_columns)
    _require(screening_table.num_rows == 1000, "train screening is incomplete")
    screening_by_factor = {
        str(item["factor"]): item
        for item in screening_table.to_pylist()
    }
    _require(len(screening_by_factor) == screening_table.num_rows, "screening factor ids are not unique")

    selected = result.get("selected_factors")
    _require(isinstance(selected, list) and len(selected) == 30, "development discovery selected component set is incomplete")
    weight_order = sorted(
        range(len(selected)),
        key=lambda index: (-abs(float(selected[index]["frozen_weight"])), str(selected[index]["factor"])),
    )
    weight_rank = {index: rank + 1 for rank, index in enumerate(weight_order)}
    candidates: list[dict[str, Any]] = []
    for selected_index, selected_item in enumerate(selected):
        _require(isinstance(selected_item, dict), "selected component is invalid")
        factor_id = str(selected_item.get("factor", ""))
        ledger_item = ledger_by_factor.get(factor_id)
        screening_item = screening_by_factor.get(factor_id)
        _require(isinstance(ledger_item, dict), f"selected component missing from ledger: {factor_id}")
        _require(isinstance(screening_item, dict), f"selected component missing from screening: {factor_id}")
        expression = str(selected_item.get("expression", ""))
        _require(expression == ledger_item.get("expression"), f"selected expression mismatch: {factor_id}")
        weight = float(selected_item.get("frozen_weight", math.nan))
        _require(math.isfinite(weight) and weight >= 0, f"selected weight is invalid: {factor_id}")
        expression_hash = str(ledger_item.get("expression_sha256", ""))
        _require(len(expression_hash) == 64, f"expression hash is invalid: {factor_id}")
        candidates.append(
            {
                "factor_id": factor_id,
                "candidate_index": int(ledger_item.get("candidate_index", -1)),
                "candidate_sha256": str(ledger_item.get("candidate_sha256", "")),
                "expression": expression,
                "expression_sha256": expression_hash,
                "operation": str(ledger_item.get("operation", "")),
                "left": str(ledger_item.get("left", "")),
                "right": str(ledger_item.get("right") or ""),
                "generation_source": str(ledger_item.get("generation_source", "")),
                "batch": int(ledger_item.get("batch", -1)),
                "direction": int(selected_item.get("direction", 0)),
                "frozen_weight": weight,
                "weight_rank": weight_rank[selected_index],
                "active_in_frozen_score": weight > 1e-12,
                "train_metrics": {
                    "valid_months": int(screening_item["valid_months"]),
                    "mean_rankic": float(screening_item["mean_rankic"]),
                    "abs_mean_rankic": float(screening_item["abs_mean_rankic"]),
                    "icir": float(screening_item["icir"]),
                    "abs_icir": float(screening_item["abs_icir"]),
                    "directional_consistency": float(screening_item["directional_consistency"]),
                    "subperiod_stability": float(screening_item["subperiod_stability"]),
                    "valid_subperiod_ratio": float(screening_item["valid_subperiod_ratio"]),
                    "median_coverage": float(screening_item["median_coverage"]),
                    "factor_stability_score": float(screening_item["factor_stability_score"]),
                    "passed_train_hygiene": bool(screening_item["passed_train_hygiene"]),
                    "top_stability_100": bool(screening_item["top_stability_100"]),
                },
            }
        )

    factor_ids = [item["factor_id"] for item in candidates]
    expression_hashes = [item["expression_sha256"] for item in candidates]
    duplicate_expression_count = sum(count - 1 for count in Counter(expression_hashes).values() if count > 1)
    _require(len(set(factor_ids)) == len(factor_ids), "selected component ids are not unique")
    _require(duplicate_expression_count == 0, "selected expressions are duplicated")

    identity_payload = {
        "research_spec_id": result.get("research_spec_id"),
        "result_generated_at": result.get("generated_at"),
        "artifact_hashes": artifact_hashes,
        "components": [
            {
                "factor_id": item["factor_id"],
                "expression_sha256": item["expression_sha256"],
                "direction": item["direction"],
                "frozen_weight": item["frozen_weight"],
            }
            for item in candidates
        ],
    }
    registry_id = _canonical_sha256(identity_payload)
    active_count = sum(bool(item["active_in_frozen_score"]) for item in candidates)
    return {
        "schema_version": "research.factor-component-registry",
        "registry_id": registry_id,
        "source": {
            "research_spec_id": str(result.get("research_spec_id", "")),
            "result_generated_at": str(result.get("generated_at", "")),
            "result_state": str(result.get("state", "")),
            "candidate_ledger_sha256": artifact_hashes["candidate_ledger"],
            "train_screening_sha256": artifact_hashes["train_screening"],
            "formal_sample_accessed": False,
            "locked_research_code_modified": False,
        },
        "summary": {
            "component_count": len(candidates),
            "active_weight_count": active_count,
            "zero_weight_count": len(candidates) - active_count,
            "duplicate_factor_id_count": 0,
            "duplicate_expression_count": duplicate_expression_count,
            "frozen_weight_sum": float(sum(item["frozen_weight"] for item in candidates)),
            "selection_population_count": int(result.get("ga", {}).get("validation_candidate_count", 0)),
            "frozen_candidate_index": int(result.get("frozen_candidate_index", -1)),
            "calibration_passed": bool(result.get("calibration_passed")),
            "calibration_confidence": float(result.get("calibration", {}).get("validation_confidence", math.nan)),
        },
        "candidates": candidates,
    }


class FactorRegistryStore:
    def __init__(self, snapshot: dict[str, Any], state_path: Path) -> None:
        self.snapshot = deepcopy(snapshot)
        self.state_path = state_path.resolve()
        self._lock = threading.Lock()
        self._candidate_ids = frozenset(item["factor_id"] for item in self.snapshot["candidates"])
        self._document = self._load_or_create_document()

    def _empty_entry(self) -> dict[str, Any]:
        return {
            "registry_id": self.snapshot["registry_id"],
            "created_at": _utc_now(),
            "state": "OPEN",
            "reviews": {
                factor_id: {"decision": "UNREVIEWED", "updated_at": None}
                for factor_id in sorted(self._candidate_ids)
            },
            "events": [],
            "freeze": None,
        }

    def _load_or_create_document(self) -> dict[str, Any]:
        if self.state_path.exists():
            _require(self.state_path.is_file() and not self.state_path.is_symlink(), "registry state path is unsafe")
            document = _read_json(self.state_path, label="factor registry state")
            self._validate_document(document)
        else:
            document = {
                "schema_version": "research.factor-component-review-state",
                "current_registry_id": self.snapshot["registry_id"],
                "registries": {},
            }
        registry_id = self.snapshot["registry_id"]
        registries = document["registries"]
        if registry_id not in registries:
            registries[registry_id] = self._empty_entry()
            document["current_registry_id"] = registry_id
            self._persist(document)
        else:
            document["current_registry_id"] = registry_id
            self._validate_current_entry(registries[registry_id])
            self._persist(document)
        return document

    def _validate_document(self, document: dict[str, Any]) -> None:
        _require(document.get("schema_version") == "research.factor-component-review-state", "wrong registry state schema")
        _require(isinstance(document.get("registries"), dict), "registry state collection is invalid")

    def _validate_current_entry(self, entry: Any) -> None:
        _require(isinstance(entry, dict), "registry state entry is invalid")
        _require(entry.get("registry_id") == self.snapshot["registry_id"], "registry state identity mismatch")
        _require(entry.get("state") in {"OPEN", "FROZEN"}, "registry review state is invalid")
        reviews = entry.get("reviews")
        _require(isinstance(reviews, dict) and set(reviews) == set(self._candidate_ids), "registry review keys changed")
        for review in reviews.values():
            _require(isinstance(review, dict) and review.get("decision") in REVIEW_DECISIONS, "registry decision is invalid")
        _require(isinstance(entry.get("events"), list), "registry event log is invalid")
        if entry.get("state") == "FROZEN":
            freeze = entry.get("freeze")
            _require(isinstance(freeze, dict) and len(str(freeze.get("review_sha256", ""))) == 64, "registry freeze is invalid")

    def _persist(self, document: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.state_path)

    def _current_entry(self) -> dict[str, Any]:
        return self._document["registries"][self.snapshot["registry_id"]]

    def status(self) -> dict[str, Any]:
        with self._lock:
            entry = deepcopy(self._current_entry())
            payload = deepcopy(self.snapshot)
            reviews = entry["reviews"]
            for candidate in payload["candidates"]:
                candidate["review"] = deepcopy(reviews[candidate["factor_id"]])
            counts = Counter(review["decision"] for review in reviews.values())
            payload.update(
                review_state=entry["state"],
                review_counts={decision: int(counts.get(decision, 0)) for decision in sorted(REVIEW_DECISIONS)},
                reviewed_count=len(self._candidate_ids) - int(counts.get("UNREVIEWED", 0)),
                can_freeze=entry["state"] == "OPEN" and counts.get("UNREVIEWED", 0) == 0,
                freeze=deepcopy(entry["freeze"]),
                prior_registry_count=max(0, len(self._document["registries"]) - 1),
                decision_effect="review_only_does_not_modify_frozen_weights",
                formal_sample_allowed=False,
                ai_decision_authority=False,
            )
            return payload

    def update_review(self, factor_id: str, decision: str) -> dict[str, Any]:
        normalized_factor = factor_id.strip()
        normalized_decision = decision.strip().upper()
        with self._lock:
            entry = self._current_entry()
            _require(entry["state"] == "OPEN", "registry review is frozen")
            _require(normalized_factor in self._candidate_ids, "factor id is not in the current registry")
            _require(normalized_decision in REVIEW_DECISIONS, "review decision is not allowed")
            previous = entry["reviews"][normalized_factor]["decision"]
            now = _utc_now()
            entry["reviews"][normalized_factor] = {
                "decision": normalized_decision,
                "updated_at": now,
            }
            if previous != normalized_decision:
                entry["events"].append(
                    {
                        "event": "REVIEW_DECISION_CHANGED",
                        "factor_id": normalized_factor,
                        "previous": previous,
                        "decision": normalized_decision,
                        "at": now,
                    }
                )
                entry["events"] = entry["events"][-1000:]
            self._persist(self._document)
        return self.status()

    def freeze(self) -> dict[str, Any]:
        with self._lock:
            entry = self._current_entry()
            _require(entry["state"] == "OPEN", "registry review is already frozen")
            decisions = {
                factor_id: entry["reviews"][factor_id]["decision"]
                for factor_id in sorted(self._candidate_ids)
            }
            _require("UNREVIEWED" not in decisions.values(), "all components must be reviewed before freezing")
            freeze_payload = {
                "registry_id": self.snapshot["registry_id"],
                "decisions": decisions,
            }
            now = _utc_now()
            entry["state"] = "FROZEN"
            entry["freeze"] = {
                "frozen_at": now,
                "review_sha256": _canonical_sha256(freeze_payload),
                "decision_counts": dict(sorted(Counter(decisions.values()).items())),
            }
            entry["events"].append(
                {
                    "event": "REGISTRY_REVIEW_FROZEN",
                    "at": now,
                    "review_sha256": entry["freeze"]["review_sha256"],
                }
            )
            self._persist(self._document)
        return self.status()


class FactorRegistryController:
    """Keep the review registry aligned with the latest verified development discovery result."""

    def __init__(self, *, project_root: Path, result_path: Path, state_path: Path) -> None:
        self.project_root = project_root.resolve()
        self.result_path = result_path.resolve()
        self.state_path = state_path.resolve()
        self._lock = threading.Lock()
        self._result_sha256 = ""
        self._store: FactorRegistryStore | None = None
        with self._lock:
            self._refresh_locked()

    def _refresh_locked(self) -> None:
        signature_before = _sha256_file(self.result_path)
        if self._store is not None and signature_before == self._result_sha256:
            return
        snapshot = build_registry_snapshot(
            project_root=self.project_root,
            result_path=self.result_path,
        )
        signature_after = _sha256_file(self.result_path)
        _require(signature_after == signature_before, "development discovery result changed while registry was loading")
        self._store = FactorRegistryStore(snapshot, self.state_path)
        self._result_sha256 = signature_after

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            assert self._store is not None
            return self._store.status()

    def update_review(self, factor_id: str, decision: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            assert self._store is not None
            return self._store.update_review(factor_id, decision)

    def freeze(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            assert self._store is not None
            return self._store.freeze()
