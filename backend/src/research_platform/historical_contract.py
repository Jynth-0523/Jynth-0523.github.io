"""Read-only compatibility with immutable historical result documents.

Historical identity strings are data contracts, not public module names. Never
rewrite a frozen artifact just to rename its fields or directories.
"""

LEGACY_MODIFICATION_FIELD = "v312_code_modified"
LEGACY_IMPLEMENTATION_DIRECTORY = "factor_discovery_stage_v8"
LEGACY_RESULT_DIRECTORY = "runtime/factor_discovery_v8"


def locked_research_is_unchanged(result: dict) -> bool:
    keys = ("locked_research_code_modified", LEGACY_MODIFICATION_FIELD)
    present = [result[key] for key in keys if key in result]
    return bool(present) and all(value is False for value in present)


def canonical_artifact_path(value: str) -> str:
    """Map known directory labels for comparison only; never change files."""
    if value.startswith(LEGACY_IMPLEMENTATION_DIRECTORY + "/"):
        return "factor_discovery/" + value.split("/", 1)[1]
    if value.startswith(LEGACY_RESULT_DIRECTORY + "/"):
        return "runtime/factor_discovery/" + value[len(LEGACY_RESULT_DIRECTORY) + 1:]
    return value
