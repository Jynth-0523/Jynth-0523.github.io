"""Configured-archive tests; all database subprocesses are stubbed."""
import copy
import csv
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'health_check'))
from audit_common import Recorder
from audit_database import run_database_checks
from audit_archive import validate_canonical_csv
from check_research_assets import expand_environment
from research_platform.config import load_config
from research_platform.runner import AutomationRunner


class ArchivePathTests(unittest.TestCase):
    def test_source_identity_is_checked_without_relabeling_the_archive(self):
        config = json.loads((ROOT/'health_check/health_check_config.json').read_text())
        config['archive_identity'] = {'research_spec_id': 'synthetic_source_spec',
                                      'run_id': 'synthetic_source_run'}
        columns = ['window', 'status', 'research_spec_id', 'oos_test_rankic', 'shadow_oos_test_rankic']
        columns += [f'diagnostic_{index}' for index in range(67)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'results').mkdir()
            with (root/'results/walk_forward_all_results.csv').open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for window in range(1,24):
                    writer.writerow({'window': window, 'research_spec_id': 'synthetic_source_spec',
                        'status': 'deploy_high_confidence' if window <= 13 else 'deploy_moderate_confidence' if window == 14 else 'no_trade_calibration_gate',
                        'oos_test_rankic': '.01' if window <= 14 else '',
                        'shadow_oos_test_rankic': '' if window <= 14 else '.01'})
            recorder = Recorder()
            validate_canonical_csv(recorder, config, root)
            self.assertEqual(recorder.overall(), 'PASS')
            config['archive_identity']['research_spec_id'] = config['identity']['research_spec_id']
            recorder = Recorder()
            validate_canonical_csv(recorder, config, root)
            self.assertEqual(recorder.overall(), 'FAIL')

    def test_runner_forwards_all_configured_archive_locations(self):
        config = load_config(ROOT/'backend/config/platform_config.json')
        required = set(re.findall(r'\$\{([A-Z_]+)\}', (ROOT/'health_check/health_check_config.json').read_text()))
        expected = {key: 'synthetic-location' for key in required}
        with patch.dict(os.environ, {**expected, 'UNRELATED_SECRET': 'not-forwarded'}, clear=True):
            environment, _ = AutomationRunner._safe_environment(SimpleNamespace(config=config))
        self.assertEqual({key: environment.get(key) for key in required}, expected)
        self.assertNotIn('UNRELATED_SECRET', environment)

    def test_schema_environment_expands_values_and_map_keys(self):
        with patch.dict(os.environ, {"PGSCHEMA": "authorized_archive"}):
            self.assertEqual(expand_environment({"${PGSCHEMA}.tableau_walk_forward": "${PGSCHEMA}"}),
                             {"authorized_archive.tableau_walk_forward": "authorized_archive"})

    def test_database_query_uses_configured_schema_and_read_only_transaction(self):
        config = json.loads((ROOT/'health_check/health_check_config.json').read_text())
        config['database']['schema'] = 'authorized_archive'
        fake = SimpleNamespace(returncode=1, stdout='', stderr='Synthetic blocked connection')
        with patch('audit_database.resolve_psql', return_value='psql'), patch('audit_database.subprocess.run', return_value=fake) as run:
            run_database_checks(Recorder(), config)
        sql = run.call_args.kwargs['input']
        self.assertTrue(sql.startswith('BEGIN TRANSACTION READ ONLY;'))
        self.assertIn('FROM authorized_archive.tableau_walk_forward', sql)
        self.assertNotIn('FROM research.', sql)

    def test_unsafe_schema_never_launches_a_database_command(self):
        config = {'database': {'schema': 'unsafe;DROP'}, 'identity': {}, 'archive_identity': {}}
        with patch('audit_database.subprocess.run') as run:
            result = run_database_checks(Recorder(), config)
        run.assert_not_called()
        self.assertFalse(result['database_modified'])
