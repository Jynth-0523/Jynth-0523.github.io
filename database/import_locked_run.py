#!/usr/bin/env python3
"""Import one immutable V3.1.2 walk-forward run into PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


FINAL_RESEARCH_SPEC_ID = (
    "v312_two_stage_validation_hac_holm_full_grid_missing_aware_v3"
)
EXPECTED_WINDOWS = 23
EXPECTED_RESULT_COLUMNS = 72
MIN_CROSS_SECTION = 50
MIN_AVAILABLE_WEIGHT_FRACTION = 0.50

CSV_TABLES = {
    "results/walk_forward_all_results.csv": "walk_forward_windows",
    "results/oos_summary.csv": "oos_summary",
    "results/v3_v31_v311_v312_comparison.csv": "model_comparison",
    "diagnostics/validation_confidence_diagnostics.csv": "validation_candidates",
    "diagnostics/factor_screening_diagnostics.csv": "factor_screening",
    "diagnostics/confidence_calibration_summary.csv": "confidence_calibration_summary",
    "diagnostics/confidence_oos_relationship_summary.csv": "confidence_oos_relationship_summary",
    "diagnostics/confidence_oos_window_diagnostics.csv": "confidence_oos_windows",
    "diagnostics/low_confidence_component_summary.csv": "low_confidence_component_summary",
    "diagnostics/low_confidence_failure_diagnostics.csv": "low_confidence_failures",
    "diagnostics/window_stability_diagnostics.csv": "window_stability",
}

DATE_COLUMNS = {
    "train_start",
    "train_end",
    "validation_start",
    "validation_end",
    "selection_validation_start",
    "selection_validation_end",
    "calibration_validation_start",
    "calibration_validation_end",
    "selection_actual_start",
    "selection_actual_end",
    "calibration_actual_start",
    "calibration_actual_end",
    "test_start",
    "test_end",
    "planned_test_end",
    "validation_stage_start",
    "validation_stage_end",
    "validation_actual_start",
    "validation_actual_end",
}


def normalize_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        raise ValueError(f"Cannot normalize empty identifier from {value!r}")
    return normalized


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def postgres_type(series: pd.Series, column: str) -> str:
    if column in DATE_COLUMNS:
        return "date"
    if pd.api.types.is_bool_dtype(series.dtype):
        return "boolean"
    if pd.api.types.is_integer_dtype(series.dtype):
        return "bigint"
    if pd.api.types.is_float_dtype(series.dtype):
        return "double precision"
    return "text"


def load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.columns = [normalize_identifier(column) for column in frame.columns]
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError(f"Normalized duplicate columns in {path}")
    return frame


def create_frame_table(
    cursor: psycopg.Cursor,
    table_name: str,
    frame: pd.DataFrame,
) -> None:
    definitions = [sql.SQL("run_id text NOT NULL REFERENCES v312.research_runs(run_id)")]
    for column in frame.columns:
        definitions.append(
            sql.SQL("{} {}").format(
                sql.Identifier(column),
                sql.SQL(postgres_type(frame[column], column)),
            )
        )
    cursor.execute(
        sql.SQL("CREATE TABLE IF NOT EXISTS v312.{} ({})").format(
            sql.Identifier(table_name),
            sql.SQL(", ").join(definitions),
        )
    )


def copy_frame(
    cursor: psycopg.Cursor,
    run_id: str,
    table_name: str,
    frame: pd.DataFrame,
) -> None:
    payload = frame.copy()
    payload.insert(0, "run_id", run_id)
    buffer = io.StringIO()
    payload.to_csv(buffer, index=False, na_rep="\\N")
    columns = [sql.Identifier(column) for column in payload.columns]
    copy_statement = sql.SQL(
        "COPY v312.{} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '\\N')"
    ).format(sql.Identifier(table_name), sql.SQL(", ").join(columns))
    with cursor.copy(copy_statement) as copy:
        copy.write(buffer.getvalue())


def parse_json_cell(value: object, default: object) -> object:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return json.loads(str(value))


def canonical_weight_hash(weights: list[float]) -> str:
    values = np.asarray(weights, dtype=np.float64)
    return hashlib.sha256(values.tobytes(order="C")).hexdigest()


def create_core_schema(cursor: psycopg.Cursor) -> None:
    cursor.execute("CREATE SCHEMA IF NOT EXISTS v312")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS v312.research_runs (
            run_id text PRIMARY KEY,
            research_spec_id text NOT NULL,
            source_root text NOT NULL,
            imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expected_windows integer NOT NULL,
            actual_windows integer NOT NULL,
            result_column_count integer NOT NULL,
            information_set_diagnostic_column_count integer NOT NULL,
            min_cross_section integer NOT NULL,
            min_available_weight_fraction double precision NOT NULL,
            research_source_sha256 text NOT NULL,
            test_source_sha256 text NOT NULL,
            protected_backup_sha256 text NOT NULL,
            locked boolean NOT NULL DEFAULT true,
            CHECK (actual_windows = expected_windows),
            CHECK (result_column_count = 72),
            CHECK (information_set_diagnostic_column_count = 33),
            CHECK (min_cross_section = 50),
            CHECK (min_available_weight_fraction = 0.50)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS v312.artifacts (
            run_id text NOT NULL REFERENCES v312.research_runs(run_id),
            relative_path text NOT NULL,
            sha256 text NOT NULL,
            size_bytes bigint NOT NULL,
            modified_at timestamptz NOT NULL,
            row_count bigint,
            column_count integer,
            PRIMARY KEY (run_id, relative_path)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS v312.audit_manifests (
            run_id text NOT NULL REFERENCES v312.research_runs(run_id),
            relative_path text NOT NULL,
            payload jsonb NOT NULL,
            PRIMARY KEY (run_id, relative_path)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS v312.window_weight_sets (
            run_id text NOT NULL REFERENCES v312.research_runs(run_id),
            "window" bigint NOT NULL,
            oos_role text NOT NULL CHECK (oos_role IN ('formal', 'shadow')),
            weight_count integer NOT NULL,
            nonzero_weight_count integer NOT NULL,
            weight_sum double precision NOT NULL,
            max_weight double precision NOT NULL,
            weight_sha256 text NOT NULL,
            PRIMARY KEY (run_id, "window")
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS v312.window_factor_weights (
            run_id text NOT NULL REFERENCES v312.research_runs(run_id),
            "window" bigint NOT NULL,
            factor_position integer NOT NULL,
            factor_name text NOT NULL,
            direction smallint NOT NULL CHECK (direction IN (-1, 1)),
            weight double precision NOT NULL CHECK (weight >= 0.0),
            oos_role text NOT NULL CHECK (oos_role IN ('formal', 'shadow')),
            weight_sha256 text NOT NULL,
            PRIMARY KEY (run_id, "window", factor_position),
            FOREIGN KEY (run_id, "window")
                REFERENCES v312.window_weight_sets(run_id, "window")
        )
        """
    )


def insert_run(
    cursor: psycopg.Cursor,
    *,
    run_id: str,
    source_root: Path,
    windows: pd.DataFrame,
    project_root: Path,
) -> None:
    cursor.execute(
        "SELECT 1 FROM v312.research_runs WHERE run_id = %s",
        (run_id,),
    )
    if cursor.fetchone() is not None:
        raise ValueError(f"Immutable run_id already exists: {run_id}")
    spec_ids = set(windows["research_spec_id"].dropna().astype(str))
    if spec_ids != {FINAL_RESEARCH_SPEC_ID}:
        raise ValueError(f"Unexpected research_spec_id values: {sorted(spec_ids)}")
    if windows.shape != (EXPECTED_WINDOWS, EXPECTED_RESULT_COLUMNS):
        raise ValueError(
            f"Expected {(EXPECTED_WINDOWS, EXPECTED_RESULT_COLUMNS)}, got {windows.shape}"
        )
    if windows["window"].tolist() != list(range(1, EXPECTED_WINDOWS + 1)):
        raise ValueError("Window numbers must be exactly 1..23")
    source_path = project_root / "v312_research.py"
    test_path = project_root / "test_v312.py"
    backup_path = project_root / "v312_research_before_fix.py"
    cursor.execute(
        """
        INSERT INTO v312.research_runs (
            run_id, research_spec_id, source_root, expected_windows,
            actual_windows, result_column_count,
            information_set_diagnostic_column_count, min_cross_section,
            min_available_weight_fraction, research_source_sha256,
            test_source_sha256, protected_backup_sha256, locked
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
        """,
        (
            run_id,
            FINAL_RESEARCH_SPEC_ID,
            str(source_root),
            EXPECTED_WINDOWS,
            len(windows),
            len(windows.columns),
            33,
            MIN_CROSS_SECTION,
            MIN_AVAILABLE_WEIGHT_FRACTION,
            sha256_file(source_path),
            sha256_file(test_path),
            sha256_file(backup_path),
        ),
    )


def insert_artifacts(
    cursor: psycopg.Cursor,
    run_id: str,
    source_root: Path,
) -> None:
    for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
        relative_path = str(path.relative_to(source_root))
        row_count = None
        column_count = None
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
            row_count, column_count = frame.shape
        stat = path.stat()
        cursor.execute(
            """
            INSERT INTO v312.artifacts (
                run_id, relative_path, sha256, size_bytes, modified_at,
                row_count, column_count
            ) VALUES (%s, %s, %s, %s, to_timestamp(%s), %s, %s)
            """,
            (
                run_id,
                relative_path,
                sha256_file(path),
                stat.st_size,
                stat.st_mtime,
                row_count,
                column_count,
            ),
        )
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            cursor.execute(
                """
                INSERT INTO v312.audit_manifests (run_id, relative_path, payload)
                VALUES (%s, %s, %s)
                """,
                (run_id, relative_path, Jsonb(payload)),
            )


def insert_weights(
    cursor: psycopg.Cursor,
    run_id: str,
    windows: pd.DataFrame,
) -> None:
    for row in windows.itertuples(index=False):
        factors = parse_json_cell(row.selected_factors, [])
        directions = parse_json_cell(row.directions, {})
        if bool(row.calibration_passed):
            weights = parse_json_cell(row.selected_weights, [])
            oos_role = "formal"
        else:
            weights = parse_json_cell(row.shadow_selected_weights, [])
            oos_role = "shadow"
        if not (len(factors) == len(weights) == len(directions)):
            raise ValueError(f"Window {row.window}: factor/weight/direction length mismatch")
        values = np.asarray(weights, dtype=np.float64)
        if not np.all(np.isfinite(values)) or np.any(values < 0.0):
            raise ValueError(f"Window {row.window}: invalid frozen weights")
        weight_hash = canonical_weight_hash(weights)
        cursor.execute(
            """
            INSERT INTO v312.window_weight_sets (
                run_id, "window", oos_role, weight_count, nonzero_weight_count,
                weight_sum, max_weight, weight_sha256
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                int(row.window),
                oos_role,
                len(weights),
                int(np.count_nonzero(values)),
                float(values.sum()),
                float(values.max()),
                weight_hash,
            ),
        )
        for position, (factor, weight) in enumerate(zip(factors, weights)):
            cursor.execute(
                """
                INSERT INTO v312.window_factor_weights (
                    run_id, "window", factor_position, factor_name, direction,
                    weight, oos_role, weight_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    int(row.window),
                    position,
                    factor,
                    int(directions[factor]),
                    float(weight),
                    oos_role,
                    weight_hash,
                ),
            )


def create_indexes_and_views(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_walk_forward_run_window "
        "ON v312.walk_forward_windows (run_id, \"window\")"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_validation_run_window_stage "
        "ON v312.validation_candidates (run_id, \"window\", validation_stage)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_factor_screening_run_window_factor "
        "ON v312.factor_screening (run_id, \"window\", factor)"
    )
    cursor.execute(
        """
        CREATE OR REPLACE VIEW v312.tableau_walk_forward AS
        SELECT
            w.*,
            CASE
                WHEN w.status IN ('deploy_high_confidence', 'deploy_moderate_confidence')
                    THEN 'formal'
                WHEN w.status = 'no_trade_calibration_gate' THEN 'shadow'
                ELSE 'none'
            END AS oos_branch,
            w.oos_test_rankic AS formal_oos_rankic,
            w.shadow_oos_test_rankic AS shadow_diagnostic_rankic
        FROM v312.walk_forward_windows AS w
        """
    )
    cursor.execute(
        """
        CREATE OR REPLACE VIEW v312.tableau_window_weights AS
        SELECT
            f.run_id, f."window", f.factor_position, f.factor_name,
            f.direction, f.weight, f.oos_role, f.weight_sha256,
            s.weight_count, s.nonzero_weight_count, s.weight_sum, s.max_weight
        FROM v312.window_factor_weights AS f
        JOIN v312.window_weight_sets AS s
          ON s.run_id = f.run_id AND s."window" = f."window"
        """
    )
    cursor.execute(
        "CREATE OR REPLACE VIEW v312.tableau_validation_candidates AS "
        "SELECT * FROM v312.validation_candidates"
    )
    cursor.execute(
        "CREATE OR REPLACE VIEW v312.tableau_factor_screening AS "
        "SELECT * FROM v312.factor_screening"
    )


def install_append_only_guards(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION v312.reject_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'V3.1.2 research archive is append-only';
        END;
        $$
        """
    )
    cursor.execute(
        """
        DO $$
        DECLARE item record;
        BEGIN
            FOR item IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'v312'
            LOOP
                EXECUTE format(
                    'DROP TRIGGER IF EXISTS reject_mutation ON v312.%I',
                    item.tablename
                );
                EXECUTE format(
                    'CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON v312.%I '
                    'FOR EACH ROW EXECUTE FUNCTION v312.reject_mutation()',
                    item.tablename
                );
            END LOOP;
        END
        $$
        """
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--dsn",
        default="",
        help="Optional libpq connection parameters; defaults to PGHOST/PGPORT/PGDATABASE/PGUSER and local authentication. Do not put passwords on the command line.",
    )
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    project_root = args.project_root.resolve()
    windows = load_csv(source_root / "results/walk_forward_all_results.csv")

    with psycopg.connect(args.dsn) as connection:
        with connection.cursor() as cursor:
            create_core_schema(cursor)
            insert_run(
                cursor,
                run_id=args.run_id,
                source_root=source_root,
                windows=windows,
                project_root=project_root,
            )
            for relative_path, table_name in CSV_TABLES.items():
                frame = load_csv(source_root / relative_path)
                create_frame_table(cursor, table_name, frame)
                copy_frame(cursor, args.run_id, table_name, frame)
            insert_weights(cursor, args.run_id, windows)
            insert_artifacts(cursor, args.run_id, source_root)
            create_indexes_and_views(cursor)
            install_append_only_guards(cursor)
        connection.commit()
    print(json.dumps({"database": "v312_research", "schema": "v312", "run_id": args.run_id}))


if __name__ == "__main__":
    main()
