from __future__ import annotations

import json
import unittest

from research_platform.ai_candidate_proposer import (
    build_ollama_proposal_request,
    build_proposal_payload,
    request_ollama_proposals,
    validate_proposals,
)
from research_platform.ai_explainer import AIExplanationError


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class AICandidateProposerTests(unittest.TestCase):
    def test_payload_excludes_values_targets_results_and_authority(self) -> None:
        payload = build_proposal_payload(["book_to_market", "momentum_12_1"])
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("return", serialized.lower())
        self.assertFalse(payload["policy"]["raw_values_available"])
        self.assertFalse(payload["policy"]["targets_available"])
        self.assertFalse(payload["policy"]["validation_results_available"])
        self.assertFalse(payload["policy"]["decision_authority"])

    def test_ollama_request_has_no_tools_and_a_strict_bounded_schema(self) -> None:
        payload = build_proposal_payload(["value", "quality"])
        request = build_ollama_proposal_request(payload, model="qwen3:4b")
        self.assertNotIn("tools", request)
        self.assertFalse(request["think"])
        self.assertEqual(request["options"]["temperature"], 0)
        self.assertEqual(request["format"]["additionalProperties"], False)
        self.assertEqual(request["format"]["properties"]["proposals"]["maxItems"], 12)

    def test_validator_maps_only_allowlisted_ids_and_operations(self) -> None:
        payload = build_proposal_payload(["value", "quality"])
        proposals = validate_proposals(
            {
                "proposals": [
                    {
                        "operation": "product",
                        "left_feature_id": "F001",
                        "right_feature_id": "F002",
                        "rationale_key": "COMPLEMENTARITY",
                    }
                ]
            },
            payload,
        )
        self.assertEqual(proposals[0]["left_feature"], "value")
        self.assertEqual(proposals[0]["right_feature"], "quality")
        self.assertFalse(proposals[0]["decision_authority"])

    def test_validator_rejects_code_unknown_features_and_unary_second_input(self) -> None:
        payload = build_proposal_payload(["value", "quality"])
        for invalid in [
            {"operation": "python", "left_feature_id": "F001", "right_feature_id": None, "rationale_key": "LEVEL_EFFECT"},
            {"operation": "identity", "left_feature_id": "F999", "right_feature_id": None, "rationale_key": "LEVEL_EFFECT"},
            {"operation": "lag1", "left_feature_id": "F001", "right_feature_id": "F002", "rationale_key": "PERSISTENCE"},
        ]:
            with self.assertRaises(AIExplanationError):
                validate_proposals({"proposals": [invalid]}, payload)

    def test_local_response_is_revalidated_before_becoming_a_proposal(self) -> None:
        chat = {
            "done": True,
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "proposals": [
                            {
                                "operation": "lag1",
                                "left_feature_id": "F001",
                                "right_feature_id": None,
                                "rationale_key": "PERSISTENCE",
                            }
                        ]
                    }
                ),
            },
        }

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")  # type: ignore[attr-defined]
            body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            self.assertNotIn("tools", body)
            self.assertGreaterEqual(timeout, 1.0)
            return _FakeResponse(chat)

        result = request_ollama_proposals(
            model="qwen3:4b",
            feature_columns=["momentum", "quality"],
            opener=opener,
        )
        self.assertEqual(result["proposals"][0]["left_feature"], "momentum")
        self.assertFalse(result["raw_data_shared"])
        self.assertFalse(result["decision_authority"])


if __name__ == "__main__":
    unittest.main()
