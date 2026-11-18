"""Exercise importer CLI path handling with all database operations mocked."""
import argparse
import ast
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]


def isolated_main():
    # Compile only the CLI function: optional database dependencies are unnecessary.
    source = ROOT / 'database/import_locked_run.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'main')
    names = ('load_csv', 'create_core_schema', 'insert_run', 'create_frame_table',
             'copy_frame', 'insert_weights', 'insert_artifacts', 'create_indexes_and_views',
             'install_append_only_guards', 'psycopg')
    namespace = {name: MagicMock() for name in names}
    namespace.update(argparse=argparse, Path=Path, json=json,
                     CSV_TABLES={'results/model_comparison.csv': 'model_comparison'})
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


class ImporterPathsTests(unittest.TestCase):
    def test_explicit_paths_preserve_existing_filenames(self):
        namespace = isolated_main()
        with tempfile.TemporaryDirectory(prefix='archive paths ') as directory:
            root = Path(directory)
            files = [root / name for name in ('original_source.py', 'original_tests.py',
                                              'original_backup.py', 'original_comparison.csv')]
            for path in files:
                path.touch()
            argv = ['import_locked_run.py', '--source-root', str(root), '--project-root', str(root),
                    '--run-id', 'synthetic', '--source-file', files[0].name,
                    '--test-file', str(files[1]), '--backup-file', files[2].name,
                    '--comparison-file', files[3].name]
            with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                namespace['psycopg'].connect.return_value.__enter__.return_value.info.dbname = 'synthetic'
                namespace['main']()
            call = namespace['insert_run'].call_args.kwargs
            self.assertEqual(call['source_path'], files[0].resolve())
            self.assertEqual(call['test_path'], files[1].resolve())
            self.assertEqual(call['backup_path'], files[2].resolve())
            namespace['load_csv'].assert_any_call(files[3].resolve())

    def test_missing_files_block_before_database_connection(self):
        namespace = isolated_main()
        with tempfile.TemporaryDirectory() as directory:
            argv = ['import_locked_run.py', '--source-root', directory,
                    '--project-root', directory, '--run-id', 'synthetic']
            with patch.object(sys, 'argv', argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                namespace['main']()
            self.assertEqual(error.exception.code, 2)
        namespace['psycopg'].connect.assert_not_called()
