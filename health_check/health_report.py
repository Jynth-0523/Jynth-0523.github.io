"""Health report: read-only historical verification."""

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



def format_value(value: Any, max_length: int = 500) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(rendered) > max_length:
        return rendered[: max_length - 1] + "…"
    return rendered



def markdown_report(status: dict[str, Any]) -> str:
    lines = [
        "# locked research Read-only Health Check Report",
        "",
        f"- **Overall status: {status['overall_status']}**",
        f"- Checked at: {status['checked_at']}",
        f"- Duration: {status['duration_seconds']:.3f} seconds",
        f"- research_spec_id：`{status['research_spec_id']}`",
        f"- run_id：`{status['run_id']}`",
        "- Canonical results: 23 rows x 72 columns; consecutive windows 1-23",
        "- Statuses: 13 high, 1 moderate, 9 calibration no-trade",
        "- OOS：Formal 14、Shadow 9、overlap 0, neither role populated 0",
        "",
        "## Check summary",
        "",
        "| Category | PASS | FAIL | BLOCKED |",
        "|---|---:|---:|---:|",
    ]
    for key, label in [("files", "Files and archives"), ("database", "PostgreSQL"), ("tableau", "Tableau"), ("protected", "Protected files"), ("safety", "Safety and idempotency")]:
        summary = status["summaries"].get(key, {})
        lines.append(f"| {label} | {summary.get('pass', 0)} | {summary.get('fail', 0)} | {summary.get('blocked', 0)} |")

    lines.extend(
        [
            "",
            "## Formal / Shadow Governance semantics",
            "",
            "- Formal OOS covers deployment windows; Shadow OOS covers calibration no-trade windows.",
            "- Shadow is ex-post diagnostic only; Formal and Shadow must remain mutually exclusive and separate.",
            "- NULL remains NULL and must not be converted to zero.",
            "- Health checks must not be used for tuning or creating new research gates.",
            "- The 33 information-set columns remain diagnostic and are not a new gate.",
            "",
            "## Individual results",
            "",
            "| Status | check_id | Description | actual |",
            "|---|---|---|---|",
        ]
    )
    for check in status["checks"]:
        message = str(check["message"]).replace("|", "\\|").replace("\n", " ")
        actual = format_value(check["actual"]).replace("|", "\\|").replace("\n", " ")
        check_id = str(check["check_id"]).replace("|", "\\|")
        lines.append(f"| {check['status']} | `{check_id}` | {message} | {actual} |")

    lines.extend(
        [
            "",
            "## Safety statement",
            "",
            f"- Database modified: **{'Yes' if status['database_modified'] else 'No'}**",
            f"- Research algorithm executed: **{'Yes' if status['research_algorithm_executed'] else 'No'}**",
            f"- Created `.pyc` / `__pycache__`：**{'Yes' if status['pyc_created'] else 'No'}**",
            f"- Official assets changed during checks: **{'Yes' if not status['official_assets_unchanged_during_run'] else 'No'}**",
            f"- Wrote outside health_check: **{'Yes' if status['writes_outside_health_check'] else 'No'}**",
            "",
            "This report describes locked-asset health only and provides no basis or authorization for OOS-driven tuning.",
            "",
        ]
    )
    return "\n".join(lines)

