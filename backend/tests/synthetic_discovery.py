"""Synthetic V8-shaped fixtures; these are not empirical research results."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq


def make_discovery_fixture(testcase):
    temporary = tempfile.TemporaryDirectory()
    testcase.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    implementation = root / 'factor_discovery_stage_v8'
    runtime = root / 'runtime/factor_discovery_v8'
    implementation.mkdir()
    runtime.mkdir(parents=True)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    runner = implementation / 'run_discovery.py'
    runner.write_text('raise SystemExit("Synthetic fixture must not execute research")\n')
    config = json.loads((Path(__file__).resolve().parents[1]/'config/discovery_config.json').read_text())
    config['command']['python_path'] = sys.executable
    config['command']['project_root'] = str(root)
    config['implementation_sha256'] = {'factor_discovery_stage_v8/run_discovery.py': digest(runner)}
    ledger, screening, selected = [], [], []
    for i in range(1000):
        factor = f'synthetic_{i:04d}'
        expression = f'identity(feature_{i})'
        ledger.append({'factor': factor, 'expression': expression,
                       'expression_sha256': hashlib.sha256(expression.encode()).hexdigest(),
                       'candidate_index': i, 'operation': 'identity', 'left': f'feature_{i}',
                       'generation_source': 'synthetic_fixture', 'batch': 0})
        screening.append({'factor': factor, 'valid_months': 60, 'mean_rankic': .01,
                          'abs_mean_rankic': .01, 'icir': .1, 'abs_icir': .1, 'direction': 1,
                          'directional_consistency': .6, 'subperiod_stability': .6,
                          'valid_subperiod_ratio': 1., 'median_coverage': 1.,
                          'passed_train_hygiene': True, 'top_stability_100': i < 100,
                          'factor_stability_score': .5})
        if i < 30:
            selected.append({'factor': factor, 'expression': expression,
                             'frozen_weight': .04 if i < 25 else 0., 'direction': 1})
    ledger_path = runtime/'candidate_ledger.json'
    ledger_path.write_text(json.dumps({'formal_sample_accessed': False, 'generation_used_outcomes': False,
                                      'candidates': ledger}))
    screening_path = runtime/'train_screening.parquet'
    pq.write_table(pa.Table.from_pylist(screening), screening_path)
    result = {'research_spec_id': config['identity']['research_spec_id'],
              'feature_snapshot_identity': config['identity']['feature_snapshot_identity'],
              'formal_sample_accessed': False, 'formal_sample_authorized': False,
              'v312_code_modified': False, 'state': 'SYNTHETIC_TEST_ONLY',
              'generated_at': '2000-01-01T00:00:00Z', 'calibration_passed': True,
              'calibration_threshold': .55, 'calibration': {'validation_confidence': .6},
              'quality_checks': {'status': 'PASS', 'duplicate_permno_pointdate_keys': 0,
                                 'cache_rows': 1000, 'score_coverage_by_role': {}},
              'candidate_count': 1000, 'train_hygiene_pass_count': 1000,
              'top_stability_count': 100, 'correlation_pruned_factor_count': 30,
              'selected_factors': selected, 'artifacts': {
                  'candidate_ledger': 'runtime/factor_discovery_v8/candidate_ledger.json',
                  'candidate_ledger_sha256': digest(ledger_path),
                  'train_screening': 'runtime/factor_discovery_v8/train_screening.parquet',
                  'train_screening_sha256': digest(screening_path)}}
    (runtime/'discovery_result.json').write_text(json.dumps(result))
    (root/'config').mkdir()
    path = root/'config/discovery_config.json'
    path.write_text(json.dumps(config))
    return path
