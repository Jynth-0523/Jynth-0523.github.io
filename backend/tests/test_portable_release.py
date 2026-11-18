"""Release integration checks; never execute research or contact PostgreSQL."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


class PortableReleaseTests(unittest.TestCase):
    def test_configuration_is_independent_of_working_directory(self):
        code = (
            'from research_platform.config import load_config; '
            'from pathlib import Path; '
            f'c=load_config(Path({str(ROOT / "backend/config/platform_config.json")!r})); '
            f'assert c.script_path.resolve() == Path({str(ROOT / "health_check/run_health_check.sh")!r}).resolve()'
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=directory,
                env={**os.environ, 'PYTHONPATH': str(ROOT / 'backend/src')},
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_archive_configuration_blocks_before_access(self):
        environment = {key: value for key, value in os.environ.items()
                       if key != 'RESEARCH_ASSETS_ROOT'}
        environment['PLATFORM_PYTHON'] = sys.executable
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['/bin/sh', str(ROOT / 'health_check/run_health_check.sh')],
                cwd=directory, env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('Required environment variable is unset', result.stderr)

    def test_tableau_template_has_no_embedded_credentials(self):
        tree = ET.parse(ROOT / 'tableau/research_dashboard_template.twb')
        connections = tree.findall('.//connection')
        self.assertTrue(connections)
        for connection in connections:
            self.assertFalse(connection.get('username'))
            self.assertFalse(connection.get('password'))


if __name__ == '__main__':
    unittest.main()
