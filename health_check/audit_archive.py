"""Audit archive: read-only historical verification."""

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


from audit_common import Recorder, add_locked_file_check, is_null_text, json_load, parse_sha256sums, relative_path_is_safe

def validate_canonical_csv(recorder: Recorder, config: dict[str, Any], archive_dir: Path) -> None:
    identity = {**config["identity"], **config["archive_identity"]}
    path = archive_dir / "results" / "walk_forward_all_results.csv"
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
    except FileNotFoundError:
        recorder.blocked("archive.canonical_csv_identity", "readable canonical CSV", "missing", {"path": str(path)}, "Cannot read canonical CSV.", "files")
        return
    except (PermissionError, OSError, csv.Error) as exc:
        recorder.blocked("archive.canonical_csv_identity", "readable canonical CSV", type(exc).__name__, {"path": str(path)}, f"Cannot parse canonical CSV: {exc}", "files")
        return

    windows: list[int] = []
    for row in rows:
        try:
            windows.append(int(row.get("window", "")))
        except (TypeError, ValueError):
            windows.append(-1)
    statuses = Counter(row.get("status") for row in rows)
    formal = [not is_null_text(row.get("oos_test_rankic")) for row in rows]
    shadow = [not is_null_text(row.get("shadow_oos_test_rankic")) for row in rows]
    specs = sorted({row.get("research_spec_id") for row in rows})
    branch_violations: list[int] = []
    for index, row in enumerate(rows):
        status = row.get("status")
        formal_present = formal[index]
        shadow_present = shadow[index]
        expected_formal = status in {"deploy_high_confidence", "deploy_moderate_confidence"}
        expected_shadow = status == "no_trade_calibration_gate"
        if formal_present != expected_formal or shadow_present != expected_shadow:
            try:
                branch_violations.append(int(row.get("window", "-1")))
            except ValueError:
                branch_violations.append(-1)
    actual = {
        "rows": len(rows),
        "columns": len(fieldnames),
        "windows": windows,
        "status_counts": dict(statuses),
        "formal_non_null": sum(formal),
        "shadow_non_null": sum(shadow),
        "overlap": sum(a and b for a, b in zip(formal, shadow)),
        "neither": sum(not a and not b for a, b in zip(formal, shadow)),
        "research_spec_ids": specs,
        "branch_semantic_violation_windows": branch_violations,
    }
    expected = {
        "rows": identity["canonical_rows"],
        "columns": identity["canonical_columns"],
        "windows": identity["windows"],
        "status_counts": identity["status_counts"],
        "formal_non_null": identity["formal_oos_non_null"],
        "shadow_non_null": identity["shadow_oos_non_null"],
        "overlap": identity["formal_shadow_overlap"],
        "neither": identity["neither_oos_non_null"],
        "research_spec_ids": [identity["research_spec_id"]],
        "branch_semantic_violation_windows": [],
    }
    recorder.equal(
        "archive.canonical_csv_identity",
        expected,
        actual,
        {"path": str(path), "nulls_preserved": True},
        "Canonical CSV preserves 23x72 shape, consecutive windows, statuses, and mutually exclusive Formal/Shadow roles.",
        "Canonical CSV identity changed.",
        "files",
    )



def validate_archive(recorder: Recorder, config: dict[str, Any]) -> dict[str, Any] | None:
    paths = config["paths"]
    roots = config["root_sha256"]
    manifest_path = Path(paths["archive_manifest"])
    sums_path = Path(paths["archive_sha256sums"])
    archive_dir = Path(paths["archive_directory"])

    manifest_record = add_locked_file_check(
        recorder,
        "archive.root_manifest_sha256",
        manifest_path,
        roots["archive_manifest"],
        "files",
        root_dependency=True,
    )
    sums_record = add_locked_file_check(
        recorder,
        "archive.root_sha256sums_sha256",
        sums_path,
        roots["archive_sha256sums"],
        "files",
        root_dependency=True,
    )
    if manifest_record.get("exists") is not True or manifest_record.get("is_file") is not True:
        recorder.blocked("archive.inventory", "readable archive manifest", manifest_record, {"path": str(manifest_path)}, "Archive manifest is unavailable; per-file verification is blocked.", "files")
        return None
    try:
        manifest = json_load(manifest_path)
    except (json.JSONDecodeError, UnicodeError, PermissionError, OSError) as exc:
        recorder.blocked("archive.inventory", "valid JSON archive manifest", type(exc).__name__, {"path": str(manifest_path)}, f"Cannot parse archive manifest: {exc}", "files")
        return None

    identity = {**config["identity"], **config["archive_identity"]}
    manifest_identity_actual = {
        "research_spec_id": manifest.get("research_spec_id"),
        "run_id": manifest.get("run_id"),
        "file_count": manifest.get("file_count"),
        "file_set_sha256": manifest.get("file_set_sha256"),
        "archive_directory": manifest.get("archive_directory"),
        "status": manifest.get("status"),
    }
    manifest_identity_expected = {
        "research_spec_id": identity["research_spec_id"],
        "run_id": identity["run_id"],
        "file_count": 30,
        "file_set_sha256": roots["archive_file_set"],
        "archive_directory": str(archive_dir),
        "status": "PASS",
    }
    recorder.equal(
        "archive.manifest_identity",
        manifest_identity_expected,
        manifest_identity_actual,
        {"path": str(manifest_path)},
        "Archive manifest identity matches the locked facts.",
        "Archive manifest identity mismatch.",
        "files",
    )

    result_identity = manifest.get("result_identity", {})
    expected_result_identity = {
        "shape": [identity["canonical_rows"], identity["canonical_columns"]],
        "windows": identity["windows"],
        "status_counts": identity["status_counts"],
        "formal_oos_non_null": identity["formal_oos_non_null"],
        "shadow_oos_non_null": identity["shadow_oos_non_null"],
        "formal_shadow_overlap": identity["formal_shadow_overlap"],
    }
    actual_result_identity = {key: result_identity.get(key) for key in expected_result_identity}
    recorder.equal(
        "archive.manifest_result_identity",
        expected_result_identity,
        actual_result_identity,
        {"path": str(manifest_path)},
        "Archived 23x72 identity matches.",
        "Archived result identity mismatch.",
        "files",
    )

    raw_entries = manifest.get("archive_files")
    if not isinstance(raw_entries, list):
        recorder.blocked("archive.inventory", "archive_files list", type(raw_entries).__name__, {"path": str(manifest_path)}, "archive_files is not a valid list.", "files")
        return manifest

    manifest_entries: dict[str, dict[str, Any]] = {}
    malformed: list[Any] = []
    duplicates: list[str] = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or not relative_path_is_safe(str(entry.get("relative_path", ""))):
            malformed.append(entry)
            continue
        relative = str(entry["relative_path"])
        if relative in manifest_entries:
            duplicates.append(relative)
        manifest_entries[relative] = entry
    recorder.equal(
        "archive.manifest_paths_well_formed",
        {"malformed": [], "duplicates": []},
        {"malformed": malformed, "duplicates": duplicates},
        {"entry_count": len(raw_entries)},
        "Archive relative paths are safe and unique.",
        "Archive manifest contains unsafe or duplicate paths.",
        "files",
    )

    try:
        actual_files = {
            str(path.relative_to(archive_dir)): path
            for path in archive_dir.rglob("*")
            if path.is_file()
        }
        actual_symlinks = [str(path.relative_to(archive_dir)) for path in archive_dir.rglob("*") if path.is_symlink()]
    except (FileNotFoundError, PermissionError, OSError) as exc:
        recorder.blocked("archive.actual_file_set", sorted(manifest_entries), type(exc).__name__, {"path": str(archive_dir)}, f"Cannot read archive directory: {exc}", "files")
        return manifest

    recorder.equal(
        "archive.actual_file_set",
        {"files": sorted(manifest_entries), "symlinks": []},
        {"files": sorted(actual_files), "symlinks": sorted(actual_symlinks)},
        {"archive_directory": str(archive_dir)},
        "Archive has no missing files, extra files, or symlinks.",
        "Archive file set differs from the manifest.",
        "files",
    )

    for relative in sorted(manifest_entries):
        entry = manifest_entries[relative]
        add_locked_file_check(
            recorder,
            f"archive.file::{relative}",
            archive_dir / relative,
            str(entry.get("sha256", "")),
            "files",
            expected_size=entry.get("size_bytes"),
            expected_mtime_ns=entry.get("mtime_ns"),
        )

    if sums_record.get("exists") is True and sums_record.get("is_file") is True:
        try:
            sums_entries, sums_errors = parse_sha256sums(sums_path, archive_dir.name)
            manifest_hashes = {relative: str(entry.get("sha256")) for relative, entry in manifest_entries.items()}
            recorder.equal(
                "archive.manifest_vs_sha256sums",
                {"entries": manifest_hashes, "parse_errors": []},
                {"entries": sums_entries, "parse_errors": sums_errors},
                {"manifest_count": len(manifest_hashes), "sha256sums_count": len(sums_entries)},
                "archive_manifest matches SHA256SUMS exactly.",
                "archive_manifest and SHA256SUMS have missing, extra, or mismatched entries.",
                "files",
            )
        except (PermissionError, OSError, UnicodeError) as exc:
            recorder.blocked("archive.manifest_vs_sha256sums", "readable SHA256SUMS", type(exc).__name__, {"path": str(sums_path)}, f"Cannot parse SHA256SUMS: {exc}", "files")
    else:
        recorder.blocked("archive.manifest_vs_sha256sums", "readable SHA256SUMS", sums_record, {"path": str(sums_path)}, "SHA256SUMS is unavailable.", "files")

    total_bytes = sum(int(entry.get("size_bytes", -1)) for entry in manifest_entries.values())
    actual_count_bytes = {"file_count": len(manifest_entries), "total_bytes": total_bytes}
    expected_count_bytes = {"file_count": manifest.get("file_count"), "total_bytes": manifest.get("total_bytes")}
    recorder.equal(
        "archive.count_and_total_bytes",
        expected_count_bytes,
        actual_count_bytes,
        {"archive_directory": str(archive_dir)},
        "Archive file count and total bytes match.",
        "Archive file count or total bytes mismatch.",
        "files",
    )

    source_entries = manifest.get("source_files")
    recorder.equal(
        "archive.source_archive_record_identity",
        raw_entries,
        source_entries,
        {"source_directory": manifest.get("source_directory")},
        "Source and archive file records match in the manifest.",
        "Source and archive file records differ in the manifest.",
        "files",
    )
    validate_canonical_csv(recorder, config, archive_dir)
    return manifest

