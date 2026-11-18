from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from research_platform.ai_explainer import (
    AIExplanationError,
    build_ollama_request,
    build_responses_request,
    ollama_model_available,
    request_ollama_explanation,
    request_openai_explanation,
    validate_model_output,
)


VALID_OUTPUT = {
    "primary_evidence_key": "CALIBRATION_ABOVE_THRESHOLD",
    "primary_caveat_key": "AGGREGATES_ONLY",
    "next_action_key": "KEEP_SPEC_FROZEN",
}


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class AIExplainerTests(unittest.TestCase):
    def test_request_is_no_tool_non_stored_and_strictly_structured(self) -> None:
        request = build_responses_request({"development_result": {}}, model="gpt-5.6-luna")
        self.assertFalse(request["store"])
        self.assertNotIn("tools", request)
        self.assertEqual(request["reasoning"]["effort"], "low")
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertEqual(request["text"]["format"]["type"], "json_schema")

    def test_ollama_request_is_local_no_tool_and_strictly_structured(self) -> None:
        request = build_ollama_request({"development_result": {}}, model="qwen3:4b")
        self.assertFalse(request["stream"])
        self.assertFalse(request["think"])
        self.assertNotIn("tools", request)
        self.assertEqual(request["options"]["temperature"], 0)
        self.assertEqual(request["format"]["additionalProperties"], False)

    def test_model_output_can_only_select_deterministic_evidence_and_action(self) -> None:
        validated = validate_model_output(VALID_OUTPUT)
        self.assertEqual(validated["next_action_key"], "KEEP_SPEC_FROZEN")
        invented = dict(VALID_OUTPUT, primary_evidence_key="INVENTED_FACT")
        with self.assertRaises(AIExplanationError):
            validate_model_output(invented)

    def test_model_output_rejects_free_text_and_unknown_selections(self) -> None:
        with self.assertRaises(AIExplanationError):
            validate_model_output(dict(VALID_OUTPUT, conclusion="unsupported prose"))
        with self.assertRaises(AIExplanationError):
            validate_model_output(dict(VALID_OUTPUT, primary_caveat_key="INVENTED_CAVEAT"))

    def test_http_response_is_reduced_to_public_explanation(self) -> None:
        response_payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(VALID_OUTPUT, ensure_ascii=False)}],
                }
            ],
        }
        captured: dict[str, object] = {}

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(response_payload)

        with patch("research_platform.ai_explainer.utc_now", return_value="2026-08-11T00:00:00Z"):
            result = request_openai_explanation(
                api_key="sk-test-not-a-real-secret",
                model="gpt-5.6-luna",
                payload={"development_result": {"calibration_passed": True}},
                opener=opener,
            )
        self.assertFalse(result["decision_authority"])
        self.assertEqual(result["generated_at"], "2026-08-11T00:00:00Z")
        self.assertEqual(len(result["evidence"]), 2)
        request = captured["request"]
        body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        self.assertNotIn("tools", body)
        self.assertNotIn("sk-test", json.dumps(body))

    def test_local_model_detection_and_ollama_response(self) -> None:
        tags = {"models": [{"name": "qwen3:4b"}]}

        def tags_opener(request: object, *, timeout: float) -> _FakeResponse:
            self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/tags")  # type: ignore[attr-defined]
            self.assertLessEqual(timeout, 1.0)
            return _FakeResponse(tags)

        self.assertTrue(ollama_model_available("qwen3:4b", opener=tags_opener))

        chat = {
            "done": True,
            "message": {"role": "assistant", "content": json.dumps(VALID_OUTPUT, ensure_ascii=False)},
        }

        def chat_opener(request: object, *, timeout: float) -> _FakeResponse:
            self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")  # type: ignore[attr-defined]
            self.assertGreaterEqual(timeout, 1.0)
            body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            self.assertNotIn("tools", body)
            return _FakeResponse(chat)

        result = request_ollama_explanation(
            model="qwen3:4b",
            payload={"development_result": {"calibration_passed": True}},
            opener=chat_opener,
        )
        self.assertEqual(result["model"], "qwen3:4b")
        self.assertFalse(result["decision_authority"])


if __name__ == "__main__":
    unittest.main()
