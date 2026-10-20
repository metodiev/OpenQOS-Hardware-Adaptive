"""Validation of hardware inventory documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openqos import HARDWARE_SCHEMA_VERSION
from openqos.errors import SchemaError
from openqos.schemas import hardware_schema_path

_REQUIRED_TOP_LEVEL = {
    "schema_version": str,
    "generated_at": str,
    "privacy_mode": bool,
    "tool": dict,
    "host": dict,
    "graphics": dict,
    "pci_devices": list,
    "usb_devices": list,
    "storage": list,
    "network": list,
    "audio": dict,
    "bluetooth": list,
    "cameras": list,
    "input_devices": list,
    "power": dict,
    "kernel_modules": list,
    "warnings": list,
    "unavailable": list,
}


def load_document(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SchemaError(f"cannot read {path}: {error}") from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SchemaError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise SchemaError(f"{path} must contain a JSON object")
    return document


def validate_document(document: dict[str, Any], *, version: str | None = None) -> list[str]:
    """Validate ``document``; return a list of human readable problems.

    The JSON Schema check is used when ``jsonschema`` is installed. A built-in
    structural check always runs so the command is useful in a minimal live
    environment that has no third-party Python packages.
    """
    problems = _structural_problems(document)
    schema_problems = _jsonschema_problems(document, version)
    seen = set(problems)
    for problem in schema_problems:
        if problem not in seen:
            problems.append(problem)
    return problems


def validate_or_raise(document: dict[str, Any], *, version: str | None = None) -> None:
    problems = validate_document(document, version=version)
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        raise SchemaError(f"hardware inventory is invalid:\n{joined}")


def _structural_problems(document: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key, expected in _REQUIRED_TOP_LEVEL.items():
        if key not in document:
            problems.append(f"missing required field {key!r}")
            continue
        value = document[key]
        if not isinstance(value, expected):
            problems.append(
                f"field {key!r} must be {expected.__name__}, got {type(value).__name__}"
            )
    if document.get("schema_version") != HARDWARE_SCHEMA_VERSION:
        problems.append(
            f"schema_version is {document.get('schema_version')!r}, "
            f"expected {HARDWARE_SCHEMA_VERSION!r}"
        )
    for key in ("cpu", "memory"):
        if key in document and document[key] is not None and not isinstance(document[key], dict):
            problems.append(f"field {key!r} must be an object or null")
    for key in ("warnings", "unavailable"):
        entries = document.get(key)
        if isinstance(entries, list):
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    problems.append(f"{key}[{index}] must be an object")
    return problems


def _jsonschema_problems(document: dict[str, Any], version: str | None) -> list[str]:
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:
        return []

    try:
        schema = json.loads(hardware_schema_path(version).read_text(encoding="utf-8"))
    except (OSError, SchemaError) as error:
        return [f"schema unavailable: {error}"]

    validator = jsonschema.Draft202012Validator(schema)
    problems = []
    for issue in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in issue.absolute_path) or "<root>"
        problems.append(f"{location}: {issue.message}")
    return problems
