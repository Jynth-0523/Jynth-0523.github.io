"""Audit tableau: read-only historical verification."""

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


from audit_common import Recorder, add_locked_file_check, json_load, path_is_within
from audit_reports import report_source_entries

def validate_tableau(recorder: Recorder, config: dict[str, Any], report_manifest: dict[str, Any] | None) -> dict[str, Any]:
    paths = config["paths"]
    tableau_dir = Path(paths["tableau_directory"])
    validation_path = Path(paths["tableau_validation_report"])
    validation_entries = report_source_entries(report_manifest, "Tableau validation facts")
    screenshot_entries = report_source_entries(report_manifest, "verified Tableau screenshot")
    summary: dict[str, Any] = {"validation_report": str(validation_path), "screenshots_expected": len(screenshot_entries)}

    if len(validation_entries) != 1:
        recorder.add(
            "tableau.validation_report_manifest_entry",
            "FAIL" if report_manifest is not None else "BLOCKED",
            1,
            len(validation_entries),
            {"report_manifest": paths["report_manifest"]},
            "Tableau validation_report registration count is incorrect.",
            "tableau",
        )
    else:
        entry = validation_entries[0]
        add_locked_file_check(
            recorder,
            "tableau.validation_report_file",
            validation_path,
            str(entry.get("sha256", "")),
            "tableau",
            expected_size=entry.get("size_bytes"),
            root_dependency=True,
        )
        recorder.equal(
            "tableau.validation_report_path",
            str(validation_path),
            str(entry.get("path")),
            {"report_manifest": paths["report_manifest"]},
            "Tableau validation_report path matches.",
            "Tableau validation_report path mismatch.",
            "tableau",
        )

    screenshot_actual_count = 0
    unsafe_screenshots: list[str] = []
    for entry in screenshot_entries:
        path = Path(str(entry.get("path", "")))
        if not path_is_within(path, Path(paths["tableau_verification_directory"])):
            unsafe_screenshots.append(str(path))
            continue
        actual = add_locked_file_check(
            recorder,
            f"tableau.screenshot::{path.name}",
            path,
            str(entry.get("sha256", "")),
            "tableau",
            expected_size=entry.get("size_bytes"),
        )
        if actual.get("exists") is True and actual.get("is_file") is True:
            screenshot_actual_count += 1
    recorder.equal(
        "tableau.screenshot_manifest_scope",
        [],
        unsafe_screenshots,
        {"verification_directory": paths["tableau_verification_directory"]},
        "All registered screenshots are inside the verification directory.",
        "A screenshot path escapes the verification directory.",
        "tableau",
    )
    summary["screenshots_readable"] = screenshot_actual_count

    try:
        validation = json_load(validation_path)
    except FileNotFoundError:
        recorder.blocked("tableau.validation_semantics", "readable validation_report.json", "missing", {"path": str(validation_path)}, "validation_report is missing; Tableau semantics cannot be checked.", "tableau")
        return summary
    except (json.JSONDecodeError, UnicodeError, PermissionError, OSError) as exc:
        recorder.blocked("tableau.validation_semantics", "valid validation_report JSON", type(exc).__name__, {"path": str(validation_path)}, f"Cannot parse validation_report: {exc}", "tableau")
        return summary

    identity = config["identity"]
    expected_tables = [view.split(".", 1)[1] for view in config["database"]["views"]]
    expected_counts = {
        "walk_forward_rows": 23,
        "high_confidence_windows": 13,
        "moderate_confidence_windows": 1,
        "no_trade_windows": 9,
        "formal_oos_nonnull": 14,
        "shadow_oos_nonnull": 9,
        "formal_shadow_overlap": 0,
        "wrong_spec_rows": 0,
        "validation_rows": 253,
        "screening_rows": 2300,
        "weight_windows": 23,
    }
    expected_semantics = {
        "xml_valid": True,
        "source_tables": sorted(expected_tables),
        "dashboard_names": identity["dashboard_names"],
        "password_embedded": False,
        "live_connection": True,
        "formal_shadow_separate": True,
        "twbx_contains_extract": False,
        "database_modified": False,
        "database_counts": expected_counts,
        "twb_path": paths["tableau_twb"],
        "twb_sha256": config["root_sha256"]["tableau_twb"],
        "twbx_path": paths["tableau_twbx"],
        "twbx_sha256": config["root_sha256"]["tableau_twbx"],
    }
    actual_semantics = {
        "xml_valid": validation.get("xml_valid"),
        "source_tables": sorted(validation.get("source_tables", [])),
        "dashboard_names": validation.get("dashboard_names"),
        "password_embedded": validation.get("password_embedded"),
        "live_connection": validation.get("live_connection"),
        "formal_shadow_separate": validation.get("formal_shadow_separate"),
        "twbx_contains_extract": validation.get("twbx_contains_extract"),
        "database_modified": validation.get("database_modified"),
        "database_counts": validation.get("database_counts"),
        "twb_path": validation.get("twb_path"),
        "twb_sha256": validation.get("twb_sha256"),
        "twbx_path": validation.get("twbx_path"),
        "twbx_sha256": validation.get("twbx_sha256"),
    }
    recorder.equal(
        "tableau.validation_semantics",
        expected_semantics,
        actual_semantics,
        {"path": str(validation_path), "research_spec_id": identity["research_spec_id"]},
        "Tableau Live Connection, no extract/embedded credentials, and Formal/Shadow isolation are preserved.",
        "Tableau validation_report semantics or core counts differ.",
        "tableau",
    )

    twb_actual = add_locked_file_check(
        recorder,
        "tableau.formal_twb_sha256",
        Path(paths["tableau_twb"]),
        config["root_sha256"]["tableau_twb"],
        "tableau",
        root_dependency=True,
    )
    twbx_actual = add_locked_file_check(
        recorder,
        "tableau.formal_twbx_sha256",
        Path(paths["tableau_twbx"]),
        config["root_sha256"]["tableau_twbx"],
        "tableau",
        root_dependency=True,
    )
    summary.update(
        {
            "twb_sha256": twb_actual.get("sha256"),
            "twbx_sha256": twbx_actual.get("sha256"),
            "live_connection": validation.get("live_connection"),
            "formal_shadow_separate": validation.get("formal_shadow_separate"),
            "extract_present": validation.get("twbx_contains_extract"),
        }
    )
    return summary

