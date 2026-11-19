"""Audit reports: read-only historical verification."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


from audit_common import Recorder, add_locked_file_check, json_load, relative_path_is_safe

def validate_report_package(recorder: Recorder, config: dict[str, Any]) -> dict[str, Any] | None:
    paths = config["paths"]
    manifest_path = Path(paths["report_manifest"])
    report_dir = Path(paths["report_directory"])
    root_record = add_locked_file_check(
        recorder,
        "report.root_manifest_sha256",
        manifest_path,
        config["root_sha256"]["report_manifest"],
        "files",
        root_dependency=True,
    )
    if root_record.get("exists") is not True or root_record.get("is_file") is not True:
        recorder.blocked("report.outputs", "readable report manifest", root_record, {"path": str(manifest_path)}, "Report manifest unavailable; registered outputs cannot be checked.", "files")
        return None
    try:
        manifest = json_load(manifest_path)
    except (json.JSONDecodeError, UnicodeError, PermissionError, OSError) as exc:
        recorder.blocked("report.outputs", "valid report manifest JSON", type(exc).__name__, {"path": str(manifest_path)}, f"Cannot parse report manifest: {exc}", "files")
        return None

    identity = {**config["identity"], **config["archive_identity"]}
    research = manifest.get("research_identity", {})
    actual_identity = {
        "research_spec_id": research.get("research_spec_id"),
        "run_id": research.get("run_id"),
        "canonical_result_rows": research.get("canonical_result_rows"),
        "canonical_result_columns": research.get("canonical_result_columns"),
        "status_counts": research.get("status_counts"),
        "oos_counts": research.get("oos_counts"),
        "package_status": manifest.get("package_status"),
        "report_directory": manifest.get("report_directory"),
    }
    expected_identity = {
        "research_spec_id": identity["research_spec_id"],
        "run_id": identity["run_id"],
        "canonical_result_rows": identity["canonical_rows"],
        "canonical_result_columns": identity["canonical_columns"],
        "status_counts": identity["status_counts"],
        "oos_counts": {
            "formal": identity["formal_oos_non_null"],
            "overlap": identity["formal_shadow_overlap"],
            "shadow": identity["shadow_oos_non_null"],
        },
        "package_status": "PASS",
        "report_directory": str(report_dir),
    }
    recorder.equal(
        "report.manifest_identity",
        expected_identity,
        actual_identity,
        {"path": str(manifest_path)},
        "Report manifest run/spec/23x72 identity matches.",
        "Report manifest research identity mismatch.",
        "files",
    )

    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        recorder.blocked("report.outputs", "outputs list", type(outputs).__name__, {"path": str(manifest_path)}, "Report outputs is not a valid list.", "files")
        return manifest
    allowed_names = {manifest_path.name}
    malformed: list[Any] = []
    for entry in outputs:
        if not isinstance(entry, dict):
            malformed.append(entry)
            continue
        filename = str(entry.get("filename", ""))
        if not relative_path_is_safe(filename) or Path(filename).name != filename:
            malformed.append(entry)
            continue
        path = report_dir / filename
        allowed_names.add(filename)
        recorded_path = Path(str(entry.get("path", "")))
        if recorded_path != path:
            recorder.add(
                f"report.path::{filename}",
                "FAIL",
                str(path),
                str(recorded_path),
                {"manifest": str(manifest_path)},
                "Absolute report path is outside the locked report directory.",
                "files",
            )
        add_locked_file_check(
            recorder,
            f"report.file::{filename}",
            path,
            str(entry.get("sha256", "")),
            "files",
            expected_size=entry.get("size_bytes"),
        )
    recorder.equal(
        "report.output_entries_well_formed",
        [],
        malformed,
        {"output_count": len(outputs)},
        "Report output entries are valid.",
        "Report output entries contain invalid paths or structures.",
        "files",
    )
    try:
        actual_names = {path.name for path in report_dir.iterdir()}
        recorder.equal(
            "report.no_unregistered_entries",
            sorted(allowed_names),
            sorted(actual_names),
            {"report_directory": str(report_dir)},
            "Final report directory has no missing or unregistered entries.",
            "Final report directory has missing or unregistered entries.",
            "files",
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        recorder.blocked("report.no_unregistered_entries", sorted(allowed_names), type(exc).__name__, {"report_directory": str(report_dir)}, f"Cannot read report directory: {exc}", "files")
    return manifest



def validate_protected_and_dump(recorder: Recorder, config: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"protected_files": []}
    for entry in config["protected_files"]:
        path = Path(entry["path"])
        actual = add_locked_file_check(
            recorder,
            f"protected.file::{path.name}",
            path,
            entry["sha256"],
            "protected",
            root_dependency=True,
        )
        summary["protected_files"].append(
            {"path": str(path), "expected_sha256": entry["sha256"], "actual_sha256": actual.get("sha256")}
        )
    dump_path = Path(config["paths"]["database_dump"])
    dump_actual = add_locked_file_check(
        recorder,
        "files.database_dump_sha256",
        dump_path,
        config["root_sha256"]["database_dump"],
        "files",
        root_dependency=True,
    )
    summary["database_dump"] = {
        "path": str(dump_path),
        "expected_sha256": config["root_sha256"]["database_dump"],
        "actual_sha256": dump_actual.get("sha256"),
    }
    return summary



def report_source_entries(manifest: dict[str, Any] | None, role: str) -> list[dict[str, Any]]:
    if not manifest:
        return []
    entries = manifest.get("source_files", [])
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("role") == role]

