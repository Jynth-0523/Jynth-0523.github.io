from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable


DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_OLLAMA_MODEL = "qwen3:4b"
ALLOWED_MODELS = frozenset({"gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"})
EVIDENCE_TEXT = {
    "CALIBRATION_ABOVE_THRESHOLD": "Development calibration confidence exceeds the preset threshold.",
    "TRAIN_HYGIENE_COMPLETED": "Candidates passed training-period hygiene screening.",
    "STABILITY_AND_CORRELATION_COMPLETED": "Candidates completed stability screening and correlation pruning.",
    "QUALITY_CHECKS_CLEAN": "Cache integrity passed with zero duplicate stable keys.",
}
CONCLUSION_TEXT = {
    "DEVELOPMENT_GATE_PASSED_WITH_LIMITS": "Development calibration passed the preset gate and is eligible for human review; conclusions remain limited to this evidence.",
    "DEVELOPMENT_GATE_NOT_PASSED": "Development calibration failed the preset gate; the summary does not support further approval review.",
}
CAVEAT_TEXT = {
    "AGGREGATES_ONLY": "Input contains aggregate summaries only, without raw research data, expressions, or weights.",
    "DEVELOPMENT_ONLY": "The explanation covers only the current development summary.",
    "HUMAN_REVIEW_REQUIRED": "An explanation cannot replace deterministic checks and human review.",
    "NO_PERFORMANCE_INFERENCE": "This explanation does not establish returns, significance, or tradability.",
}
NEXT_ACTION_TEXT = {
    "REVIEW_DEVELOPMENT_OUTPUT": "Review development candidates and quality reports manually while keeping the specification frozen.",
    "KEEP_SPEC_FROZEN": "Keep the specification frozen; do not tune parameters using this explanation.",
    "NO_ACTION": "Take no research action; retain the read-only explanation.",
}

EXPLANATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "primary_evidence_key": {"type": "string", "enum": sorted(EVIDENCE_TEXT)},
        "primary_caveat_key": {"type": "string", "enum": sorted(CAVEAT_TEXT)},
        "next_action_key": {"type": "string", "enum": sorted(NEXT_ACTION_TEXT)},
    },
    "required": [
        "primary_evidence_key",
        "primary_caveat_key",
        "next_action_key",
    ],
    "additionalProperties": False,
}

SYSTEM_INSTRUCTIONS = """You are a read-only interpreter in a quantitative research platform. Input contains development aggregates only.
Explain these facts only. Do not infer returns, significance, out-of-sample performance, tradability, or production readiness.
Do not suggest parameter changes, rescreening, backtests, deployment, trading, or tool calls.
Do not claim access to raw data, candidate expressions, companies, securities, holdings, or weights.
Return only the three schema-enumerated keys, without free text. Select one primary evidence item, one primary limitation, and one safe action.
This is an explanation, not approval, and cannot change research state."""

class AIExplanationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_model(value: str | None) -> str:
    model = (value or DEFAULT_MODEL).strip()
    if model not in ALLOWED_MODELS:
        raise AIExplanationError("AI model is not allowlisted")
    return model


def normalize_ollama_model(value: str | None) -> str:
    model = (value or DEFAULT_OLLAMA_MODEL).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", model):
        raise AIExplanationError("Ollama model name is invalid")
    return model


def build_responses_request(payload: dict[str, Any], *, model: str) -> dict[str, Any]:
    normalized_model = normalize_model(model)
    return {
        "model": normalized_model,
        "store": False,
        "reasoning": {"effort": "low", "context": "current_turn"},
        "max_output_tokens": 700,
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "v8_development_read_only_explanation",
                "strict": True,
                "schema": EXPLANATION_SCHEMA,
            },
        },
        "input": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {
                "role": "user",
                "content": "Explain only the following JSON summary:\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            },
        ],
    }


def build_ollama_request(payload: dict[str, Any], *, model: str) -> dict[str, Any]:
    normalized_model = normalize_ollama_model(model)
    return {
        "model": normalized_model,
        "stream": False,
        "think": False,
        "format": EXPLANATION_SCHEMA,
        "options": {"temperature": 0, "num_predict": 700},
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {
                "role": "user",
                "content": "Explain only the following JSON summary and match the supplied JSON Schema exactly:\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            },
        ],
    }


def _extract_output_text(response: dict[str, Any]) -> str:
    if response.get("status") != "completed":
        raise AIExplanationError("AI response did not complete")
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text:
                    return text
            if isinstance(content, dict) and content.get("type") == "refusal":
                raise AIExplanationError("AI request was refused")
    raise AIExplanationError("AI response contained no text")


def validate_model_output(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "primary_evidence_key",
        "primary_caveat_key",
        "next_action_key",
    }:
        raise AIExplanationError("AI explanation shape is invalid")
    evidence_key = value["primary_evidence_key"]
    caveat_key = value["primary_caveat_key"]
    if evidence_key not in EVIDENCE_TEXT:
        raise AIExplanationError("AI evidence selection is invalid")
    if caveat_key not in CAVEAT_TEXT:
        raise AIExplanationError("AI caveats are invalid")
    next_action_key = value["next_action_key"]
    if next_action_key not in NEXT_ACTION_TEXT:
        raise AIExplanationError("AI next action is invalid")
    return {
        "evidence_key": evidence_key,
        "caveat_key": caveat_key,
        "next_action_key": next_action_key,
    }


def public_explanation(value: dict[str, Any], *, model: str, calibration_passed: bool) -> dict[str, Any]:
    validated = validate_model_output(value)
    conclusion_key = (
        "DEVELOPMENT_GATE_PASSED_WITH_LIMITS"
        if calibration_passed
        else "DEVELOPMENT_GATE_NOT_PASSED"
    )
    fallback_evidence = "QUALITY_CHECKS_CLEAN"
    if validated["evidence_key"] == fallback_evidence:
        fallback_evidence = "CALIBRATION_ABOVE_THRESHOLD" if calibration_passed else "TRAIN_HYGIENE_COMPLETED"
    fallback_caveat = "HUMAN_REVIEW_REQUIRED"
    if validated["caveat_key"] == fallback_caveat:
        fallback_caveat = "AGGREGATES_ONLY"
    normalized_model = normalize_model(model) if model in ALLOWED_MODELS else normalize_ollama_model(model)
    return {
        "conclusion": CONCLUSION_TEXT[conclusion_key],
        "evidence": [EVIDENCE_TEXT[validated["evidence_key"]], EVIDENCE_TEXT[fallback_evidence]],
        "caveats": [CAVEAT_TEXT[validated["caveat_key"]], CAVEAT_TEXT[fallback_caveat]],
        "next_action": NEXT_ACTION_TEXT[validated["next_action_key"]],
        "model": normalized_model,
        "generated_at": utc_now(),
        "decision_authority": False,
    }


def request_openai_explanation(
    *,
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout_seconds: float = 45.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    if not api_key or any(character.isspace() for character in api_key):
        raise AIExplanationError("OpenAI API key is unavailable")
    request_body = build_responses_request(payload, model=model)
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise AIExplanationError("OpenAI request failed") from exc
    if len(raw) > 1_000_000:
        raise AIExplanationError("AI response exceeded the size limit")
    try:
        response_payload = json.loads(raw.decode("utf-8"))
        structured = json.loads(_extract_output_text(response_payload))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AIExplanationError("AI response was not valid structured output") from exc
    calibration_passed = bool(payload.get("development_result", {}).get("calibration_passed"))
    return public_explanation(structured, model=model, calibration_passed=calibration_passed)


def ollama_model_available(
    model: str,
    *,
    timeout_seconds: float = 0.6,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> bool:
    normalized_model = normalize_ollama_model(model)
    request = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return False
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    names = {
        str(item.get("name", ""))
        for item in payload.get("models", [])
        if isinstance(item, dict)
    }
    return normalized_model in names


def request_ollama_explanation(
    *,
    model: str,
    payload: dict[str, Any],
    timeout_seconds: float = 90.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    request_body = build_ollama_request(payload, model=model)
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(request_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise AIExplanationError("Ollama request failed") from exc
    if len(raw) > 1_000_000:
        raise AIExplanationError("AI response exceeded the size limit")
    try:
        response_payload = json.loads(raw.decode("utf-8"))
        if response_payload.get("done") is not True:
            raise AIExplanationError("Ollama response did not complete")
        message = response_payload.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise AIExplanationError("Ollama response contained no text")
        structured = json.loads(message["content"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AIExplanationError("AI response was not valid structured output") from exc
    calibration_passed = bool(payload.get("development_result", {}).get("calibration_passed"))
    return public_explanation(
        structured,
        model=normalize_ollama_model(model),
        calibration_passed=calibration_passed,
    )


def request_ai_explanation(
    *,
    provider: str,
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    if provider == "ollama":
        return request_ollama_explanation(
            model=model,
            payload=payload,
            timeout_seconds=max(timeout_seconds, 90.0),
        )
    if provider == "openai":
        return request_openai_explanation(
            api_key=api_key,
            model=model,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
    raise AIExplanationError("AI provider is not allowlisted")
