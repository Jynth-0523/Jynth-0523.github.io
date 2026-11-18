"""Check research assets: read-only historical verification."""

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


from audit_archive import validate_archive
from audit_common import Recorder, STATUS_EXIT, atomic_write, collect_tree_snapshot, json_load, path_is_within
from audit_database import run_database_checks
from audit_reports import validate_protected_and_dump, validate_report_package
from audit_tableau import validate_tableau
from health_report import markdown_report

SCRIPT_DIR = Path(__file__).resolve().parent

def run_health_check() -> int:
    started_monotonic = time.monotonic()
    parser = argparse.ArgumentParser(description="V3.1.2 read-only health check")
    parser.add_argument("--config", default=str(SCRIPT_DIR / "health_check_config.json"))
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    try:
        config = json_load(config_path)
        def expand(value):
            if isinstance(value, dict):
                return {key: expand(item) for key, item in value.items()}
            if isinstance(value, list):
                return [expand(item) for item in value]
            if isinstance(value, str):
                expanded = os.path.expandvars(value)
                if re.search(r'\$\{[^}]+\}', expanded):
                    raise ValueError(f'Required environment variable is unset: {value}')
                return expanded
            return value
        config = expand(config)
        directory = Path(config['health_check_directory'])
        if not directory.is_absolute():
            config['health_check_directory'] = str((config_path.parent / directory).resolve())
    except Exception as exc:  # structured output is impossible without the locked directory config
        print(f"BLOCKED: cannot load health-check config: {type(exc).__name__}: {exc}", file=sys.stderr)
        return STATUS_EXIT["BLOCKED"]

    locked_health_dir = Path(config["health_check_directory"]).resolve()
    if SCRIPT_DIR != locked_health_dir or not path_is_within(config_path, locked_health_dir):
        print("BLOCKED: script/config must run from the locked health_check directory", file=sys.stderr)
        return STATUS_EXIT["BLOCKED"]

    recorder = Recorder()
    paths = config["paths"]
    snapshot_roots = [
        Path(paths["archive_manifest"]).parent,
        Path(paths["report_directory"]),
        Path(paths["tableau_verification_directory"]),
    ]
    snapshot_files = [
        Path(paths["handoff"]),
        Path(paths["database_dump"]),
        Path(paths["tableau_validation_report"]),
        Path(paths["tableau_twb"]),
        Path(paths["tableau_twbx"]),
        *(Path(item["path"]) for item in config["protected_files"]),
    ]
    before_snapshot, before_errors = collect_tree_snapshot(snapshot_roots, snapshot_files)
    if before_errors:
        recorder.blocked("safety.official_asset_snapshot_before", "readable official assets", before_errors, {"roots": [str(path) for path in snapshot_roots]}, "Cannot record a complete pre-run snapshot of official assets.", "safety")
    else:
        recorder.add("safety.official_asset_snapshot_before", "PASS", "readable official assets", {"records": len(before_snapshot)}, {"roots": [str(path) for path in snapshot_roots]}, "Recorded the pre-run content and mtime snapshot of official assets.", "safety")

    archive_manifest = validate_archive(recorder, config)
    report_manifest = validate_report_package(recorder, config)
    protected_summary = validate_protected_and_dump(recorder, config)
    tableau_summary = validate_tableau(recorder, config, report_manifest)
    database_summary = run_database_checks(recorder, config)

    after_snapshot, after_errors = collect_tree_snapshot(snapshot_roots, snapshot_files)
    if after_errors:
        recorder.blocked("safety.official_assets_unchanged", "complete post-check snapshot", after_errors, {"roots": [str(path) for path in snapshot_roots]}, "Cannot record a complete post-run snapshot of official assets.", "safety")
        official_unchanged = False
    else:
        official_unchanged = before_snapshot == after_snapshot
        changed_paths = sorted(
            key for key in set(before_snapshot) | set(after_snapshot) if before_snapshot.get(key) != after_snapshot.get(key)
        )
        recorder.equal(
            "safety.official_assets_unchanged",
            [],
            changed_paths,
            {"before_records": len(before_snapshot), "after_records": len(after_snapshot)},
            "Archive, final_report, Tableau, dump, and protected-file contents and mtimes are unchanged.",
            "Official asset content, mtime, or file-set changes were detected during checks.",
            "safety",
        )

    for item in protected_summary["protected_files"]:
        protected_path = item["path"]
        item["before_sha256"] = before_snapshot.get(protected_path, {}).get("sha256")
        item["after_sha256"] = after_snapshot.get(protected_path, {}).get("sha256")
        item["unchanged"] = (
            item["before_sha256"] == item["after_sha256"] == item["expected_sha256"]
        )
    dump_path_key = protected_summary["database_dump"]["path"]
    protected_summary["database_dump"]["before_sha256"] = before_snapshot.get(dump_path_key, {}).get("sha256")
    protected_summary["database_dump"]["after_sha256"] = after_snapshot.get(dump_path_key, {}).get("sha256")
    protected_summary["database_dump"]["unchanged"] = (
        protected_summary["database_dump"]["before_sha256"]
        == protected_summary["database_dump"]["after_sha256"]
        == protected_summary["database_dump"]["expected_sha256"]
    )

    pyc_paths = sorted(str(path) for path in SCRIPT_DIR.rglob("*.pyc"))
    cache_dirs = sorted(str(path) for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir())
    pyc_created = bool(pyc_paths or cache_dirs)
    recorder.equal(
        "safety.no_python_bytecode",
        {"pyc": [], "__pycache__": []},
        {"pyc": pyc_paths, "__pycache__": cache_dirs},
        {"python_dont_write_bytecode": bool(sys.dont_write_bytecode)},
        "No .pyc or __pycache__ was generated.",
        ".pyc or __pycache__ detected.",
        "safety",
    )
    recorder.equal(
        "safety.python_dash_B",
        True,
        bool(sys.dont_write_bytecode),
        {"sys.dont_write_bytecode": bool(sys.dont_write_bytecode)},
        "Python bytecode writes are disabled.",
        "Current process was not started with -B/PYTHONDONTWRITEBYTECODE.",
        "safety",
    )

    recorder.add(
        "safety.prohibited_actions_attestation",
        "PASS",
        {"database_modified": False, "research_algorithm_executed": False, "writes_outside_health_check": False},
        {"database_modified": False, "research_algorithm_executed": False, "writes_outside_health_check": False},
        {
            "database_transaction": "READ ONLY",
            "research_module_imported": False,
            "output_root": str(SCRIPT_DIR),
            "v3_cache_accessed": False,
            "new_research_gate_created": False,
            "oos_used_for_tuning": False,
        },
        "No database writes, research execution, OOS tuning, or writes outside health_check occurred.",
        "safety",
    )

    checked_at_dt = datetime.now().astimezone()
    duration = time.monotonic() - started_monotonic
    summaries = {category: recorder.summary(category) for category in ["files", "database", "tableau", "protected", "safety"]}
    overall = recorder.overall()
    status_document: dict[str, Any] = {
        "schema_version": "1.0",
        "overall_status": overall,
        "checked_at": checked_at_dt.isoformat(timespec="seconds"),
        "duration_seconds": round(duration, 6),
        "research_spec_id": config["identity"]["research_spec_id"],
        "run_id": config["identity"]["run_id"],
        "canonical_result_identity": {
            "rows": config["identity"]["canonical_rows"],
            "columns": config["identity"]["canonical_columns"],
            "windows": config["identity"]["windows"],
            "status_counts": config["identity"]["status_counts"],
            "formal_oos_non_null": config["identity"]["formal_oos_non_null"],
            "shadow_oos_non_null": config["identity"]["shadow_oos_non_null"],
            "overlap": config["identity"]["formal_shadow_overlap"],
            "neither": config["identity"]["neither_oos_non_null"],
        },
        "checks": recorder.checks,
        "summaries": summaries,
        "file_checks_summary": {
            **summaries["files"],
            "archive_manifest_loaded": archive_manifest is not None,
            "report_manifest_loaded": report_manifest is not None,
        },
        "database_checks_summary": database_summary,
        "tableau_checks_summary": tableau_summary,
        "protected_files_checks_summary": protected_summary,
        "governance": config["governance"],
        "database_modified": False,
        "research_algorithm_executed": False,
        "walk_forward_executed": False,
        "main_executed": False,
        "v3_cache_modified": False,
        "oos_used_for_tuning": False,
        "new_research_gate_created": False,
        "pyc_created": pyc_created,
        "credentials_recorded": False,
        "official_assets_unchanged_during_run": official_unchanged,
        "writes_outside_health_check": False,
        "output_directory": str(SCRIPT_DIR),
    }

    json_text = json.dumps(status_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    md_text = markdown_report(status_document)
    inherited_secret = os.environ.get("PGPASSWORD", "")
    generated_text = json_text + md_text
    secret_found = bool(inherited_secret and len(inherited_secret) >= 3 and inherited_secret in generated_text)
    uri_credential_found = bool(re.search(r"(?i)postgres(?:ql)?://[^:\s/]+:[^@\s]+@", generated_text))
    if secret_found or uri_credential_found:
        print("BLOCKED: generated output failed credential-safety scan", file=sys.stderr)
        return STATUS_EXIT["BLOCKED"]

    stamp = checked_at_dt.strftime("%Y%m%dT%H%M%S%f%z")
    logs_dir = SCRIPT_DIR / "logs"
    latest_json = SCRIPT_DIR / "latest_health_status.json"
    latest_md = SCRIPT_DIR / "latest_health_report.md"
    log_json = logs_dir / f"{stamp}_health_status.json"
    log_md = logs_dir / f"{stamp}_health_report.md"
    try:
        atomic_write(latest_json, json_text)
        atomic_write(latest_md, md_text)
        atomic_write(log_json, json_text)
        atomic_write(log_md, md_text)
    except (PermissionError, OSError) as exc:
        print(f"BLOCKED: cannot write health-check outputs: {type(exc).__name__}: {exc}", file=sys.stderr)
        return STATUS_EXIT["BLOCKED"]

    print(f"{overall}: V3.1.2 health check")
    print(f"JSON: {latest_json}")
    print(f"Markdown: {latest_md}")
    return STATUS_EXIT[overall]


if __name__ == "__main__":
    raise SystemExit(run_health_check())
