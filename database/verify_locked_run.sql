\pset pager off

SELECT
    run_id,
    research_spec_id,
    actual_windows,
    result_column_count,
    information_set_diagnostic_column_count,
    min_cross_section,
    min_available_weight_fraction,
    locked
FROM v312.research_runs
ORDER BY imported_at;

SELECT status, count(*) AS windows
FROM v312.walk_forward_windows
GROUP BY status
ORDER BY status;

SELECT
    count(*) AS windows,
    count(*) FILTER (WHERE oos_role = 'formal') AS formal_windows,
    count(*) FILTER (WHERE oos_role = 'shadow') AS shadow_windows,
    min("window") AS first_window,
    max("window") AS last_window,
    count(DISTINCT "window") AS unique_windows
FROM v312.window_weight_sets;

SELECT
    count(*) AS invalid_weight_sets
FROM v312.window_weight_sets
WHERE abs(weight_sum - 1.0) > 1e-5
   OR weight_count <= 0
   OR nonzero_weight_count <= 0
   OR max_weight < 0.0;

SELECT
    count(*) AS validation_rows,
    count(*) FILTER (WHERE validation_stage = 'selection') AS selection_rows,
    count(*) FILTER (WHERE validation_stage = 'calibration') AS calibration_rows
FROM v312.validation_candidates;

SELECT count(*) AS factor_screening_rows
FROM v312.factor_screening;

SELECT count(*) AS artifact_rows
FROM v312.artifacts;
