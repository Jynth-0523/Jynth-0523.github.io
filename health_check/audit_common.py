"""Audit common: read-only historical verification."""

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



NULL_TOKEN = "<V312_NULL>"
STATUS_EXIT = {"PASS": 0, "FAIL": 1, "BLOCKED": 2}

class Recorder:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(
        self,
        check_id: str,
        status: str,
        expected: Any,
        actual: Any,
        evidence: Any,
        message: str,
        category: str,
    ) -> None:
        if status not in STATUS_EXIT:
            raise ValueError(f"unknown check status: {status}")
        self.checks.append(
            {
                "check_id": check_id,
                "status": status,
                "expected": expected,
                "actual": actual,
                "evidence": evidence,
                "message": message,
                "category": category,
            }
        )

    def equal(
        self,
        check_id: str,
        expected: Any,
        actual: Any,
        evidence: Any,
        pass_message: str,
        fail_message: str,
        category: str,
    ) -> bool:
        ok = actual == expected
        self.add(
            check_id,
            "PASS" if ok else "FAIL",
            expected,
            actual,
            evidence,
            pass_message if ok else fail_message,
            category,
        )
        return ok

    def blocked(self, check_id: str, expected: Any, actual: Any, evidence: Any, message: str, category: str) -> None:
        self.add(check_id, "BLOCKED", expected, actual, evidence, message, category)

    def overall(self) -> str:
        statuses = {item["status"] for item in self.checks}
        if "BLOCKED" in statuses:
            return "BLOCKED"
        if "FAIL" in statuses:
            return "FAIL"
        return "PASS"

    def summary(self, category: str) -> dict[str, Any]:
        selected = [item for item in self.checks if item["category"] == category]
        counts = Counter(item["status"] for item in selected)
        return {
            "check_count": len(selected),
            "pass": counts.get("PASS", 0),
            "fail": counts.get("FAIL", 0),
            "blocked": counts.get("BLOCKED", 0),
        }



def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def safe_stat_hash(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        if not path.is_file():
            return {"exists": True, "is_file": False, "mtime_ns": stat.st_mtime_ns}
        return {
            "exists": True,
            "is_file": True,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path),
        }
    except FileNotFoundError:
        return {"exists": False}
    except (PermissionError, OSError) as exc:
        return {"exists": None, "error": f"{type(exc).__name__}: {exc}"}



def json_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)



def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".v312_health_", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass



def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False



def relative_path_is_safe(value: str) -> bool:
    candidate = Path(value)
    return bool(value) and not candidate.is_absolute() and ".." not in candidate.parts



def status_for_file_error(record: dict[str, Any], root_dependency: bool = False) -> str:
    if record.get("exists") is None:
        return "BLOCKED"
    if root_dependency and not record.get("exists"):
        return "BLOCKED"
    return "FAIL"



def add_locked_file_check(
    recorder: Recorder,
    check_id: str,
    path: Path,
    expected_sha256: str,
    category: str,
    expected_size: int | None = None,
    expected_mtime_ns: int | None = None,
    root_dependency: bool = False,
) -> dict[str, Any]:
    actual = safe_stat_hash(path)
    expected: dict[str, Any] = {"sha256": expected_sha256}
    if expected_size is not None:
        expected["size_bytes"] = expected_size
    if expected_mtime_ns is not None:
        expected["mtime_ns"] = expected_mtime_ns
    comparable = actual.get("exists") is True and actual.get("is_file") is True
    if comparable:
        ok = actual.get("sha256") == expected_sha256
        if expected_size is not None:
            ok = ok and actual.get("size_bytes") == expected_size
        if expected_mtime_ns is not None:
            ok = ok and actual.get("mtime_ns") == expected_mtime_ns
        status = "PASS" if ok else "FAIL"
        message = "Path, size, mtime, and SHA-256 match." if ok else "File identity differs from the locked record."
    else:
        status = status_for_file_error(actual, root_dependency=root_dependency)
        message = "Required path is missing or unreadable."
    recorder.add(check_id, status, expected, actual, {"path": str(path)}, message, category)
    return actual



def collect_tree_snapshot(roots: Iterable[Path], single_files: Iterable[Path]) -> tuple[dict[str, Any], list[str]]:
    records: dict[str, Any] = {}
    errors: list[str] = []

    def capture(path: Path) -> None:
        key = str(path)
        if key in records:
            return
        try:
            stat = path.lstat()
            if path.is_symlink():
                records[key] = {"type": "symlink", "mtime_ns": stat.st_mtime_ns, "target": os.readlink(path)}
            elif path.is_dir():
                records[key] = {"type": "directory", "mtime_ns": stat.st_mtime_ns}
            elif path.is_file():
                records[key] = {
                    "type": "file",
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": sha256_file(path),
                }
            else:
                records[key] = {"type": "other", "mtime_ns": stat.st_mtime_ns}
        except FileNotFoundError:
            records[key] = {"type": "missing"}
        except (PermissionError, OSError) as exc:
            records[key] = {"type": "unreadable"}
            errors.append(f"{path}: {type(exc).__name__}: {exc}")

    for root in roots:
        capture(root)
        if root.is_dir():
            try:
                for path in sorted(root.rglob("*"), key=lambda item: str(item)):
                    capture(path)
            except (PermissionError, OSError) as exc:
                errors.append(f"{root}: {type(exc).__name__}: {exc}")
    for path in single_files:
        capture(path)
    return records, errors



def parse_sha256sums(path: Path, archive_name: str) -> tuple[dict[str, str], list[str]]:
    entries: dict[str, str] = {}
    errors: list[str] = []
    prefix = f"{archive_name}/"
    with path.open("r", encoding="utf-8") as handle:
        for number, raw_line in enumerate(handle, 1):
            line = raw_line.rstrip("\n")
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                errors.append(f"line {number}: invalid format")
                continue
            digest, listed_path = match.groups()
            if not listed_path.startswith(prefix):
                errors.append(f"line {number}: wrong archive prefix")
                continue
            relative = listed_path[len(prefix) :]
            if not relative_path_is_safe(relative):
                errors.append(f"line {number}: unsafe relative path")
                continue
            if relative in entries:
                errors.append(f"line {number}: duplicate path {relative}")
                continue
            entries[relative] = digest
    return entries, errors



def is_null_text(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in {"", "nan", "null", "none", NULL_TOKEN.lower()}

