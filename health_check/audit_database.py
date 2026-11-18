"""Audit database: read-only historical verification."""

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


from audit_common import NULL_TOKEN, Recorder

def resolve_psql(candidates: list[str]) -> str | None:
    for candidate in candidates:
        if "/" in candidate:
            path = Path(candidate)
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        else:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return None



def sanitize(text: str, secrets: Iterable[str]) -> str:
    clean = text
    for secret in secrets:
        if secret and len(secret) >= 3:
            clean = clean.replace(secret, "<REDACTED>")
    clean = re.sub(r"(?i)(postgres(?:ql)?://[^:\s/]+:)[^@\s]+(@)", r"\1<REDACTED>\2", clean)
    return clean



def decimal_or_none(value: str) -> Decimal | None:
    if value == NULL_TOKEN:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None



def run_database_checks(recorder: Recorder, config: dict[str, Any]) -> dict[str, Any]:
    database = config["database"]
    identity = config["identity"]
    psql = resolve_psql(database["psql_candidates"])
    summary: dict[str, Any] = {
        "host": database["host"],
        "port": database["port"],
        "database": database["database"],
        "schema": database["schema"],
        "user": database["user"],
        "allowed_views": database["views"],
        "explicit_read_only_transaction": False,
        "committed": False,
        "database_modified": False,
        "credential_recorded": False,
    }
    if psql is None:
        recorder.blocked("database.execution", "available psql", None, {"candidates": database["psql_candidates"]}, "psql not found; database checks were not executed.", "database")
        return summary

    sql = f"""BEGIN TRANSACTION READ ONLY;
SELECT 'TX_MODE', current_setting('transaction_read_only');
SELECT 'WF', run_id, research_spec_id, \"window\"::text, status,
       CASE WHEN formal_oos_rankic IS NULL THEN '{NULL_TOKEN}' ELSE formal_oos_rankic::text END,
       CASE WHEN shadow_diagnostic_rankic IS NULL THEN '{NULL_TOKEN}' ELSE shadow_diagnostic_rankic::text END
FROM v312.tableau_walk_forward AS wf
ORDER BY wf.run_id, wf.\"window\";
SELECT 'WT', run_id, \"window\"::text,
       CASE WHEN weight IS NULL THEN '{NULL_TOKEN}' ELSE weight::text END,
       CASE WHEN weight_sum IS NULL THEN '{NULL_TOKEN}' ELSE weight_sum::text END
FROM v312.tableau_window_weights AS wt
ORDER BY wt.run_id, wt.\"window\", wt.factor_position;
SELECT 'VC', run_id, COUNT(*)::text
FROM v312.tableau_validation_candidates
GROUP BY run_id
ORDER BY run_id;
SELECT 'FS', run_id, COUNT(*)::text
FROM v312.tableau_factor_screening
GROUP BY run_id
ORDER BY run_id;
SELECT 'END_MARKER', 'ok';
COMMIT;
"""
    command = [
        psql,
        "-X",
        "-w",
        "--set=ON_ERROR_STOP=1",
        "--no-align",
        "--tuples-only",
        "--field-separator=\t",
        "--host",
        str(database["host"]),
        "--port",
        str(database["port"]),
        "--dbname",
        str(database["database"]),
        "--username",
        str(database["user"]),
        "--file=-",
    ]
    environment = os.environ.copy()
    inherited_secret = environment.pop("PGPASSWORD", "")
    environment.pop("PGOPTIONS", None)
    environment["LC_ALL"] = "C"
    secrets = [inherited_secret]
    try:
        completed = subprocess.run(
            command,
            input=sql,
            text=True,
            capture_output=True,
            env=environment,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        recorder.blocked("database.execution", "successful read-only psql execution", type(exc).__name__, {"psql": psql}, f"Cannot execute database checks: {sanitize(str(exc), secrets)}", "database")
        return summary

    stdout = sanitize(completed.stdout, secrets)
    stderr = sanitize(completed.stderr, secrets)
    if completed.returncode != 0:
        recorder.blocked(
            "database.execution",
            {"returncode": 0, "transaction": "BEGIN TRANSACTION READ ONLY ... COMMIT"},
            {"returncode": completed.returncode},
            {"psql": psql, "stderr": stderr[-2000:]},
            "PostgreSQL connection or read-only query failed; database checks are incomplete.",
            "database",
        )
        return summary

    lines = [line for line in stdout.splitlines() if line.strip()]
    began = bool(lines) and lines[0] == "BEGIN"
    committed = bool(lines) and lines[-1] == "COMMIT"
    end_marker = "END_MARKER\tok" in lines
    summary["explicit_read_only_transaction"] = began
    summary["committed"] = committed
    recorder.equal(
        "database.transaction_envelope",
        {"begin": True, "end_marker": True, "commit": True, "psql_returncode": 0},
        {"begin": began, "end_marker": end_marker, "commit": committed, "psql_returncode": completed.returncode},
        {"transaction": "BEGIN TRANSACTION READ ONLY; ... COMMIT;", "stderr": stderr[-1000:]},
        "PostgreSQL queries committed within an explicit read-only transaction.",
        "Read-only transaction envelope or COMMIT is incomplete.",
        "database",
    )

    tagged = [line.split("\t") for line in lines if "\t" in line]
    tx_values = [parts[1] for parts in tagged if parts[0] == "TX_MODE" and len(parts) == 2]
    recorder.equal(
        "database.transaction_read_only",
        ["on"],
        tx_values,
        {"query": "SELECT current_setting('transaction_read_only')"},
        "transaction_read_only = on。",
        "Transaction read-only state is not on.",
        "database",
    )

    wf: list[dict[str, Any]] = []
    wt: list[dict[str, Any]] = []
    vc: list[tuple[str, int]] = []
    fs: list[tuple[str, int]] = []
    parse_errors: list[str] = []
    for parts in tagged:
        try:
            if parts[0] == "WF" and len(parts) == 7:
                wf.append(
                    {
                        "run_id": parts[1],
                        "research_spec_id": parts[2],
                        "window": int(parts[3]),
                        "status": parts[4],
                        "formal": parts[5],
                        "shadow": parts[6],
                    }
                )
            elif parts[0] == "WT" and len(parts) == 5:
                wt.append(
                    {
                        "run_id": parts[1],
                        "window": int(parts[2]),
                        "weight": parts[3],
                        "weight_sum": parts[4],
                    }
                )
            elif parts[0] == "VC" and len(parts) == 3:
                vc.append((parts[1], int(parts[2])))
            elif parts[0] == "FS" and len(parts) == 3:
                fs.append((parts[1], int(parts[2])))
        except (ValueError, IndexError) as exc:
            parse_errors.append(f"{parts[0]}: {type(exc).__name__}")
    recorder.equal(
        "database.output_parse",
        [],
        parse_errors,
        {"wf_rows": len(wf), "weight_rows": len(wt), "candidate_groups": len(vc), "screening_groups": len(fs)},
        "Read-only database output was fully parsed.",
        "Database output contains unparseable records.",
        "database",
    )

    run_ids = {
        "v312.tableau_walk_forward": sorted({row["run_id"] for row in wf}),
        "v312.tableau_window_weights": sorted({row["run_id"] for row in wt}),
        "v312.tableau_validation_candidates": sorted({run_id for run_id, _ in vc}),
        "v312.tableau_factor_screening": sorted({run_id for run_id, _ in fs}),
    }
    expected_run_ids = {view: [identity["run_id"]] for view in database["views"]}
    recorder.equal(
        "database.run_id_isolation",
        expected_run_ids,
        run_ids,
        {"views": database["views"]},
        "All four read-only views contain only the locked run_id.",
        "The four read-only views have missing or additional run_ids.",
        "database",
    )
    specs = sorted({row["research_spec_id"] for row in wf})
    recorder.equal(
        "database.research_spec_id",
        [identity["research_spec_id"]],
        specs,
        {"view": "v312.tableau_walk_forward"},
        "research_spec_id matches the locked specification.",
        "research_spec_id mismatch.",
        "database",
    )

    view_counts = {
        "v312.tableau_walk_forward": len(wf),
        "v312.tableau_window_weights": len(wt),
        "v312.tableau_validation_candidates": sum(count for _, count in vc),
        "v312.tableau_factor_screening": sum(count for _, count in fs),
    }
    recorder.equal(
        "database.view_row_counts",
        database["expected_view_rows"],
        view_counts,
        {"transaction_read_only": tx_values},
        "The four Tableau view row counts are 23/415/253/2300.",
        "Tableau view row counts differ.",
        "database",
    )

    locked_wf = [row for row in wf if row["run_id"] == identity["run_id"]]
    windows = [row["window"] for row in locked_wf]
    recorder.equal(
        "database.window_sequence",
        identity["windows"],
        windows,
        {"view": "v312.tableau_walk_forward"},
        "Windows are consecutive from 1 to 23.",
        "Window sequence is nonconsecutive or out of bounds.",
        "database",
    )
    statuses = dict(Counter(row["status"] for row in locked_wf))
    recorder.equal(
        "database.status_counts",
        identity["status_counts"],
        statuses,
        {"run_id": identity["run_id"]},
        "Deployment counts are 13 high, 1 moderate, and 9 no-trade.",
        "Deployment status counts differ.",
        "database",
    )
    formal = [row["formal"] != NULL_TOKEN for row in locked_wf]
    shadow = [row["shadow"] != NULL_TOKEN for row in locked_wf]
    semantic_violations: list[int] = []
    for row, formal_present, shadow_present in zip(locked_wf, formal, shadow):
        expected_formal = row["status"] in {"deploy_high_confidence", "deploy_moderate_confidence"}
        expected_shadow = row["status"] == "no_trade_calibration_gate"
        if formal_present != expected_formal or shadow_present != expected_shadow:
            semantic_violations.append(row["window"])
    oos_actual = {
        "formal_non_null": sum(formal),
        "shadow_non_null": sum(shadow),
        "overlap": sum(a and b for a, b in zip(formal, shadow)),
        "neither": sum(not a and not b for a, b in zip(formal, shadow)),
        "semantic_violation_windows": semantic_violations,
    }
    oos_expected = {
        "formal_non_null": identity["formal_oos_non_null"],
        "shadow_non_null": identity["shadow_oos_non_null"],
        "overlap": identity["formal_shadow_overlap"],
        "neither": identity["neither_oos_non_null"],
        "semantic_violation_windows": [],
    }
    recorder.equal(
        "database.formal_shadow_integrity",
        oos_expected,
        oos_actual,
        {"nulls_preserved": True, "formal_shadow_pooled": False},
        "Formal covers deployments and Shadow covers no-trade windows, with mutually exclusive counts of 14/9.",
        "Formal/Shadow counts, exclusivity, or branch semantics differ.",
        "database",
    )

    locked_wt = [row for row in wt if row["run_id"] == identity["run_id"]]
    weight_windows = sorted({row["window"] for row in locked_wt})
    recorder.equal(
        "database.weight_window_coverage",
        identity["windows"],
        weight_windows,
        {"weight_rows": len(locked_wt)},
        "Frozen weights cover all 23 windows.",
        "Frozen-weight window coverage differs.",
        "database",
    )
    invalid_weight_rows: list[dict[str, Any]] = []
    invalid_sum_windows: set[int] = set()
    out_of_range_windows: set[int] = {value for value in windows + weight_windows if value < 1 or value > 23}
    tolerance = Decimal(str(database["weight_sum_tolerance"]))
    for row in locked_wt:
        weight = decimal_or_none(row["weight"])
        weight_sum = decimal_or_none(row["weight_sum"])
        if weight is None or not weight.is_finite() or weight < 0:
            invalid_weight_rows.append({"window": row["window"], "weight": row["weight"]})
        if weight_sum is None or not weight_sum.is_finite() or abs(weight_sum - Decimal("1")) > tolerance:
            invalid_sum_windows.add(row["window"])
    recorder.equal(
        "database.invalid_weight_rows",
        0,
        len(invalid_weight_rows),
        {"examples": invalid_weight_rows[:10], "nulls_not_coerced": True},
        "There are zero negative, NULL, or nonfinite weights.",
        "Negative, NULL, or nonfinite weights detected.",
        "database",
    )
    recorder.equal(
        "database.invalid_weight_sum_windows",
        0,
        len(invalid_sum_windows),
        {"windows": sorted(invalid_sum_windows), "tolerance": str(tolerance)},
        "Zero windows have invalid weight sums.",
        "Invalid window weight sums detected.",
        "database",
    )
    recorder.equal(
        "database.out_of_range_windows",
        0,
        len(out_of_range_windows),
        {"windows": sorted(out_of_range_windows)},
        "Zero out-of-range windows.",
        "Out-of-range windows detected.",
        "database",
    )
    summary.update(
        {
            "transaction_read_only": tx_values[0] if len(tx_values) == 1 else tx_values,
            "view_row_counts": view_counts,
            "status_counts": statuses,
            "formal_shadow_integrity": oos_actual,
            "weight_windows": len(weight_windows),
            "invalid_weight_rows": len(invalid_weight_rows),
            "invalid_weight_sum_windows": len(invalid_sum_windows),
            "out_of_range_windows": len(out_of_range_windows),
        }
    )
    return summary

