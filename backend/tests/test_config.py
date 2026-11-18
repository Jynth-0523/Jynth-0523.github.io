from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from research_platform.config import ConfigurationError, load_config
from research_platform.util import sha256_file


PROJECT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def test_real_config_loads_and_runtime_is_project_scoped(self) -> None:
        config = load_config(PROJECT / "config" / "platform_config.json")
        config.runtime_root.relative_to(PROJECT)
        self.assertEqual(config.blocked_retries, 2)

    def _temporary_config(self) -> tuple[tempfile.TemporaryDirectory, Path, dict]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        config_dir = root / "config"
        health_dir = root / "health"
        config_dir.mkdir()
        health_dir.mkdir()
        script = health_dir / "health.sh"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o700)
        status = health_dir / "latest.json"
        raw = json.loads((PROJECT / "config" / "platform_config.json").read_text(encoding="utf-8"))
        raw["command"]["script_path"] = str(script)
        raw["command"]["script_sha256"] = sha256_file(script)
        raw["command"]["health_status_path"] = str(status)
        path = config_dir / "platform_config.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return temporary, path, raw

    def test_non_allowlisted_command_is_rejected(self) -> None:
        temporary, path, raw = self._temporary_config()
        self.addCleanup(temporary.cleanup)
        raw["command"]["command_id"] = "run_arbitrary_shell"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "non-allowlisted"):
            load_config(path)

    def test_runtime_path_escape_is_rejected(self) -> None:
        temporary, path, raw = self._temporary_config()
        self.addCleanup(temporary.cleanup)
        raw["runtime"]["root"] = "../outside"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "escape"):
            load_config(path)

    def test_script_hash_mismatch_is_rejected(self) -> None:
        temporary, path, raw = self._temporary_config()
        self.addCleanup(temporary.cleanup)
        raw["command"]["script_sha256"] = "0" * 64
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "hash mismatch"):
            load_config(path)

    def test_any_write_or_ai_permission_is_rejected(self) -> None:
        for flag in (
            "database_writes_allowed",
            "research_execution_allowed",
            "ai_tools_allowed",
        ):
            temporary, path, raw = self._temporary_config()
            try:
                raw["governance"][flag] = True
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaisesRegex(ConfigurationError, "unsafe governance"):
                    load_config(path)
            finally:
                temporary.cleanup()


if __name__ == "__main__":
    unittest.main()

