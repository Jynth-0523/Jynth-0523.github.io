"""Explicit local mappings for optional external research documents.

The public package contains no project-release labels. An operator may configure
external field and directory names without rewriting source documents.
"""
import os
from pathlib import PurePosixPath


def locked_research_is_unchanged(result: dict) -> bool:
    keys = {"locked_research_code_modified", os.environ.get("DISCOVERY_MODIFICATION_FIELD", "locked_research_code_modified")}
    present = [result[key] for key in keys if key in result]
    return bool(present) and all(value is False for value in present)


def canonical_artifact_path(value: str) -> str:
    """Map explicitly configured safe directory names for comparison only."""
    if PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
        return value
    mappings = (
        ("DISCOVERY_IMPLEMENTATION_DIRECTORY", "factor_discovery"),
        ("DISCOVERY_RESULT_DIRECTORY", "runtime/factor_discovery"),
    )
    for setting, target in mappings:
        prefix = os.environ.get(setting, target).rstrip("/")
        parts = PurePosixPath(prefix)
        if not prefix or parts.is_absolute() or ".." in parts.parts:
            continue
        if value.startswith(prefix + "/"):
            return target + value[len(prefix):]
    return value
