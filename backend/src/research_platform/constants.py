from __future__ import annotations

PLATFORM_SCHEMA_VERSION = "1.0"
ONLY_COMMAND_ID = "locked_research_health_check"
ALLOWED_HEALTH_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED"})

LOCKED_RESEARCH_SPEC_ID = (
    "two_stage_validation_hac_holm_missing_aware"
)
LOCKED_RUN_ID = "locked_walk_forward_archive"

FORBIDDEN_AI_FIELD_TOKENS = frozenset(
    {
        "oos",
        "formal",
        "shadow",
        "rankic",
        "factor",
        "weight",
        "candidate",
        "selected",
    }
)

