"""Guard descriptive publication filenames and author-independent source paths."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
IGNORED = {'.git', 'node_modules', 'dist', '.next', '.vinext', '.wrangler', '__pycache__', 'runtime'}


class PublicationNamesTests(unittest.TestCase):
    def test_names_paths_and_english_source(self):
        checked = 0
        for path in ROOT.rglob('*'):
            if not path.is_file() or set(path.relative_to(ROOT).parts) & IGNORED:
                continue
            self.assertNotRegex(path.name, r'(?i)(?:^|[_.-])v\d')
            if path.suffix not in {'.py', '.ts', '.tsx', '.mjs', '.md', '.json', '.sh', '.sql', '.twb'}:
                continue
            if path.name in {'package-lock.json', 'release_manifest.json', 'source_manifest.json'}:
                continue
            text = path.read_text(encoding='utf-8')
            self.assertNotRegex(text, r'/(?:Users|home)/[^/\s]+/', str(path.relative_to(ROOT)))
            self.assertNotRegex(text, r'[\u3400-\u9fff]', str(path.relative_to(ROOT)))
            checked += 1
        self.assertGreater(checked, 80)
