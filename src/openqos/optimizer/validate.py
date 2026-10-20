"""Validation of optimisation plans and normalised hardware profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openqos.errors import OptimizationError, ProfileError, SchemaError
from openqos.optimizer.engine import PLAN_SCHEMA_VERSION
from openqos.profiles.model import PROFILE_SCHEMA_VERSION
from openqos.schemas import schema_path

_DECISION_REQUIRED = {
    "id": str,
    "category": str,
    "title": str,
    "status": str,
    "target": str,
    "rationale": str,
    "evidence": list,
    "reversible": bool,
    "apply_stage": str,
    "packages": list,
    "source": str,
}
_DECISION_STATUSES = {"plan", "keep", "skip", "manual"}


def load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SchemaError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise SchemaError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise SchemaError(f"{path} must contain a JSON object")
    return document


def validate_profile_document(profile: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(profile, dict):
        return ["hardware profile must be a JSON object"]
    if profile.get("schema_version") != PROFILE_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {PROFILE_SCHEMA_VERSION!r}, "
            f"got {profile.get('schema_version')!r}"
        )
    for key in ("machine", "cpu", "memory", "graphics", "storage", "network", "power"):
        if not isinstance(profile.get(key), dict):
            problems.append(f"{key} must be an object")
    problems.extend(_jsonschema_problems(profile, "hardware-profile", PROFILE_SCHEMA_VERSION))
    return problems


def validate_profile_or_raise(profile: dict[str, Any]) -> None:
    problems = validate_profile_document(profile)
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        raise ProfileError(f"hardware profile is invalid:\n{joined}")


def validate_plan(plan: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(plan, dict):
        return ["optimisation plan must be a JSON object"]
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {PLAN_SCHEMA_VERSION!r}, "
            f"got {plan.get('schema_version')!r}"
        )
    for key in ("policy", "selected_profile", "decisions", "notices", "fallback", "summary"):
        if key not in plan:
            problems.append(f"missing required field {key!r}")
    decisions = plan.get("decisions")
    if not isinstance(decisions, list):
        return problems
    seen: set[str] = set()
    for index, decision in enumerate(decisions):
        location = f"decisions[{index}]"
        if not isinstance(decision, dict):
            problems.append(f"{location} must be an object")
            continue
        for key, expected in _DECISION_REQUIRED.items():
            if key not in decision:
                problems.append(f"{location} is missing {key!r}")
            elif not isinstance(decision[key], expected):
                problems.append(f"{location}.{key} must be {expected.__name__}")
        status = decision.get("status")
        if status not in _DECISION_STATUSES:
            problems.append(f"{location}.status must be one of {sorted(_DECISION_STATUSES)}")
        decision_id = decision.get("id")
        if isinstance(decision_id, str):
            if decision_id in seen:
                problems.append(f"{location}.id is duplicated")
            seen.add(decision_id)
        if not decision.get("rationale"):
            problems.append(f"{location}.rationale must not be empty")
        if status == "plan" and not decision.get("rollback"):
            problems.append(f"{location} is a planned change without a rollback")
    if any(
        isinstance(decision, dict) and decision.get("status") == "plan"
        for decision in decisions
    ) and not (plan.get("summary") or {}).get("all_reversible"):
        problems.append("summary.all_reversible must be true when planned changes exist")
    problems.extend(_jsonschema_problems(plan, "optimization-plan", PLAN_SCHEMA_VERSION))
    return problems


def validate_plan_or_raise(plan: dict[str, Any]) -> None:
    problems = validate_plan(plan)
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        raise OptimizationError(f"optimisation plan is invalid:\n{joined}")


def _jsonschema_problems(document: dict[str, Any], stem: str, version: str) -> list[str]:
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:
        return []
    try:
        schema = json.loads(schema_path(f"{stem}-{version}.json").read_text(encoding="utf-8"))
    except (OSError, SchemaError):
        return []
    validator = jsonschema.Draft202012Validator(schema)
    problems = []
    for issue in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in issue.absolute_path) or "<root>"
        problems.append(f"{location}: {issue.message}")
    return problems
