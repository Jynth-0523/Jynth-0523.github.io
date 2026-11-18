from __future__ import annotations

import json
import time
import unittest
from synthetic_discovery import make_discovery_fixture
from pathlib import Path
from unittest.mock import patch

from research_platform.discovery_api import (
    AICandidateProposalController,
    AIExplanationController,
    DiscoveryConfigurationError,
    DiscoveryController,
    DiscoveryResultError,
    build_command,
    default_config_path,
    load_discovery_config,
    parse_progress,
    summarize_result,
)


class DiscoveryApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture_path = make_discovery_fixture(self)
        patcher = patch(__name__ + '.default_config_path', return_value=self.fixture_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_local_ai_candidate_proposer_has_no_data_or_decision_authority(self) -> None:
        captured: dict[str, object] = {}

        def requester(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {
                "schema_version": "1.0",
                "model": "qwen3:4b",
                "proposals": [],
                "raw_data_shared": False,
                "targets_shared": False,
                "validation_results_shared": False,
                "decision_authority": False,
            }

        controller = AICandidateProposalController(
            environment={"OLLAMA_MODEL": "qwen3:4b"},
            requester=requester,
            local_model_checker=lambda _: True,
        )
        status = controller.status()
        self.assertTrue(status["configured"])
        self.assertFalse(status["raw_data_allowed"])
        self.assertFalse(status["decision_authority"])
        result = controller.propose(["value", "quality"])
        self.assertEqual(captured["feature_columns"], ["value", "quality"])
        self.assertFalse(result["targets_shared"])

    def test_locked_config_allows_only_v8_development_runner(self) -> None:
        config = load_discovery_config(default_config_path())
        self.assertEqual(config.bind_host, "127.0.0.1")
        self.assertEqual(config.runner_path.name, "run_discovery.py")
        self.assertNotIn("formal", " ".join(build_command(config)).lower())
        self.assertEqual(build_command(config)[1], "-B")

    def test_any_reviewed_implementation_hash_change_blocks_start(self) -> None:
        with patch("research_platform.discovery_api._sha256_file", return_value="0" * 64):
            with self.assertRaises(DiscoveryConfigurationError):
                load_discovery_config(default_config_path())

    def test_progress_parser_is_bounded_and_stage_specific(self) -> None:
        self.assertEqual(parse_progress("    Train screening 400/1000"), (27, "Train screening 400/1000"))
        self.assertEqual(parse_progress("    Correlation months 227/227"), (75, "Correlation pruning 227/227"))
        self.assertEqual(parse_progress("    GA 8/8")[0], 92)
        self.assertIsNone(parse_progress("untrusted arbitrary output"))

    def test_current_result_is_development_only_and_quality_checked(self) -> None:
        config = load_discovery_config(default_config_path())
        result = summarize_result(config)
        self.assertTrue(result["calibration_passed"])
        self.assertFalse(result["formal_sample_accessed"])
        self.assertEqual(result["duplicate_keys"], 0)

    def test_result_reader_rejects_formal_access(self) -> None:
        config = load_discovery_config(default_config_path())
        payload = json.loads(config.result_path.read_text(encoding="utf-8"))
        payload["formal_sample_accessed"] = True
        with patch.object(Path, "read_text", return_value=json.dumps(payload)):
            with self.assertRaises(DiscoveryResultError):
                summarize_result(config)

    def test_running_state_rejects_a_duplicate_trigger(self) -> None:
        controller = DiscoveryController(default_config_path())
        with controller._lock:
            controller._status["state"] = "RUNNING"
        accepted, status = controller.start()
        self.assertFalse(accepted)
        self.assertEqual(status["state"], "RUNNING")

    def test_ai_explainer_is_disabled_cleanly_without_a_key(self) -> None:
        discovery = DiscoveryController(default_config_path())
        controller = AIExplanationController(
            discovery,
            default_config_path(),
            environment={"PLATFORM_AI_PROVIDER": "openai"},
        )
        status = controller.status()
        self.assertFalse(status["configured"])
        self.assertEqual(status["state"], "UNCONFIGURED")
        self.assertNotIn("key", json.dumps(status).lower())
        accepted, _ = controller.start()
        self.assertFalse(accepted)

    def test_local_ai_receives_only_minimized_summary_and_cannot_act(self) -> None:
        discovery = DiscoveryController(default_config_path())
        captured: dict[str, object] = {}

        def requester(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {
                "conclusion": "The development summary meets the preset workflow requirements.",
                "evidence": ["Cache integrity passed with zero duplicate stable keys."],
                "caveats": ["The aggregate summary has limited scope and requires human review."],
                "next_action": "Keep the current specification frozen.",
                "model": "qwen3:4b",
                "generated_at": "2026-08-11T00:00:00Z",
                "decision_authority": False,
            }

        controller = AIExplanationController(
            discovery,
            default_config_path(),
            environment={"PLATFORM_AI_PROVIDER": "ollama", "OLLAMA_MODEL": "qwen3:4b"},
            requester=requester,
            local_model_checker=lambda _: True,
        )
        accepted, status = controller.start()
        self.assertTrue(accepted)
        self.assertEqual(status["state"], "RUNNING")
        for _ in range(100):
            status = controller.status()
            if status["state"] != "RUNNING":
                break
            time.sleep(0.01)
        self.assertEqual(status["state"], "COMPLETED")
        self.assertEqual(captured["provider"], "ollama")
        serialized = json.dumps(captured["payload"], sort_keys=True).lower()
        self.assertNotIn("formal", serialized)
        self.assertNotIn("factor", serialized)
        self.assertNotIn("candidate", serialized)
        self.assertNotIn("tools", serialized.replace('"tools_available": false', ""))
        self.assertFalse(status["decision_authority"])


if __name__ == "__main__":
    unittest.main()
