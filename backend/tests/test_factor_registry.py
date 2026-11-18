from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from synthetic_discovery import make_discovery_fixture
from pathlib import Path

from research_platform.discovery_api import default_config_path, load_discovery_config
from research_platform.factor_registry import (
    FactorRegistryController,
    FactorRegistryError,
    FactorRegistryStore,
    build_registry_snapshot,
)


def current_snapshot() -> dict[str, object]:
    config = load_discovery_config(default_config_path())
    return build_registry_snapshot(project_root=config.project_root, result_path=config.result_path)


class FactorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.fixture_path = make_discovery_fixture(self)
        patcher = patch(__name__ + '.default_config_path', return_value=self.fixture_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_snapshot_matches_the_locked_component_structure(self) -> None:
        snapshot = current_snapshot()
        self.assertEqual(snapshot["summary"]["component_count"], 30)  # type: ignore[index]
        self.assertEqual(snapshot["summary"]["active_weight_count"], 25)  # type: ignore[index]
        self.assertEqual(snapshot["summary"]["zero_weight_count"], 5)  # type: ignore[index]
        self.assertEqual(snapshot["summary"]["duplicate_expression_count"], 0)  # type: ignore[index]
        self.assertAlmostEqual(snapshot["summary"]["frozen_weight_sum"], 1.0, places=6)  # type: ignore[index]
        self.assertFalse(snapshot["source"]["formal_sample_accessed"])  # type: ignore[index]
        candidates = snapshot["candidates"]  # type: ignore[index]
        self.assertEqual(len({item["factor_id"] for item in candidates}), 30)
        self.assertEqual(len({item["expression_sha256"] for item in candidates}), 30)
        self.assertTrue(all(item["train_metrics"]["passed_train_hygiene"] for item in candidates))
        self.assertTrue(all(item["train_metrics"]["top_stability_100"] for item in candidates))

    def test_review_state_is_allowlisted_and_persistent(self) -> None:
        snapshot = current_snapshot()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            store = FactorRegistryStore(snapshot, path)
            first_id = store.status()["candidates"][0]["factor_id"]
            status = store.update_review(first_id, "KEEP")
            self.assertEqual(status["review_counts"]["KEEP"], 1)
            self.assertEqual(status["reviewed_count"], 1)
            reopened = FactorRegistryStore(snapshot, path).status()
            self.assertEqual(reopened["review_counts"]["KEEP"], 1)
            with self.assertRaises(FactorRegistryError):
                store.update_review("factor_not_registered", "KEEP")
            with self.assertRaises(FactorRegistryError):
                store.update_review(first_id, "DEPLOY")

    def test_freeze_requires_complete_review_and_is_irreversible(self) -> None:
        snapshot = current_snapshot()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            store = FactorRegistryStore(snapshot, path)
            with self.assertRaises(FactorRegistryError):
                store.freeze()
            for candidate in store.status()["candidates"]:
                decision = "KEEP" if candidate["active_in_frozen_score"] else "WATCH"
                store.update_review(candidate["factor_id"], decision)
            status = store.freeze()
            self.assertEqual(status["review_state"], "FROZEN")
            self.assertEqual(len(status["freeze"]["review_sha256"]), 64)
            self.assertFalse(status["can_freeze"])
            with self.assertRaises(FactorRegistryError):
                store.update_review(status["candidates"][0]["factor_id"], "REJECT")
            reopened = FactorRegistryStore(snapshot, path).status()
            self.assertEqual(reopened["freeze"]["review_sha256"], status["freeze"]["review_sha256"])

    def test_controller_tracks_new_verified_result_in_the_same_state_file(self) -> None:
        config = load_discovery_config(default_config_path())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_copy = root / "discovery_result.json"
            result = json.loads(config.result_path.read_text(encoding="utf-8"))
            result_copy.write_text(json.dumps(result), encoding="utf-8")
            state_path = root / "factor_registry" / "state.json"
            controller = FactorRegistryController(
                project_root=config.project_root,
                result_path=result_copy,
                state_path=state_path,
            )
            first = controller.status()
            result["generated_at"] = "2099-01-01T00:00:00Z"
            result_copy.write_text(json.dumps(result), encoding="utf-8")
            second = controller.status()
            self.assertNotEqual(first["registry_id"], second["registry_id"])
            self.assertEqual(second["prior_registry_count"], 1)
            self.assertEqual(list((root / "factor_registry").iterdir()), [state_path])


if __name__ == "__main__":
    unittest.main()
