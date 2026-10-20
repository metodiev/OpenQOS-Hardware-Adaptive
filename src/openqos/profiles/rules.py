"""Data-driven hardware profile rules.

Rules live in ``openqos/config/hardware-profiles.json`` and are validated before
use, so a malformed or hostile rule file can never select an unintended
configuration silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from openqos.errors import ProfileError

RULES_SCHEMA_VERSION = "1.0.0"

_OPERATORS = {"eq", "ne", "in", "not_in", "ge", "le", "exists"}
_PACKAGE_SOURCES = {"fedora", "third-party", "manual"}
_MISSING = object()


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    priority: int
    conditions: tuple[dict[str, Any], ...]
    package_sets: tuple[str, ...]
    default_policy: str
    notes: tuple[str, ...]
    fallback: bool


@dataclass(frozen=True)
class RuleSet:
    schema_version: str
    revision: str
    rules: tuple[Rule, ...]
    package_sets: dict[str, dict[str, Any]]


def default_ruleset_path() -> Path:
    resource = resources.files("openqos.config").joinpath("hardware-profiles.json")
    return Path(str(resource))


def load_ruleset(path: Path | None = None) -> RuleSet:
    """Load and validate the profile rules."""
    source = Path(path) if path is not None else default_ruleset_path()
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as error:
        raise ProfileError(f"cannot read profile rules at {source}: {error}") from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProfileError(f"{source} is not valid JSON: {error}") from error
    problems = validate_ruleset(document)
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        raise ProfileError(f"{source} is not a valid rule set:\n{joined}")
    return _to_ruleset(document)


def validate_ruleset(document: Any) -> list[str]:
    """Return structural problems with a rule document (empty list if valid)."""
    problems: list[str] = []
    if not isinstance(document, dict):
        return ["rule document must be a JSON object"]
    if document.get("schema_version") != RULES_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {RULES_SCHEMA_VERSION!r}, "
            f"got {document.get('schema_version')!r}"
        )
    if not isinstance(document.get("revision"), str) or not document.get("revision"):
        problems.append("revision must be a non-empty string")

    package_sets = document.get("package_sets")
    if not isinstance(package_sets, dict):
        problems.append("package_sets must be an object")
        package_sets = {}
    else:
        for name, entry in package_sets.items():
            if not isinstance(entry, dict):
                problems.append(f"package_sets.{name} must be an object")
                continue
            source = entry.get("source")
            if source not in _PACKAGE_SOURCES:
                problems.append(
                    f"package_sets.{name}.source must be one of {sorted(_PACKAGE_SOURCES)}"
                )
            packages = entry.get("packages")
            if not isinstance(packages, list) or not all(
                isinstance(package, str) and package for package in packages
            ):
                problems.append(f"package_sets.{name}.packages must be a list of strings")
            if not isinstance(entry.get("reason"), str) or not entry["reason"]:
                problems.append(f"package_sets.{name}.reason must be a non-empty string")

    profiles = document.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        problems.append("profiles must be a non-empty list")
        return problems

    seen: set[str] = set()
    fallbacks = 0
    for index, profile in enumerate(profiles):
        location = f"profiles[{index}]"
        if not isinstance(profile, dict):
            problems.append(f"{location} must be an object")
            continue
        rule_id = profile.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            problems.append(f"{location}.id must be a non-empty string")
        elif rule_id in seen:
            problems.append(f"duplicate profile id {rule_id!r}")
        else:
            seen.add(rule_id)
        if not isinstance(profile.get("description"), str) or not profile.get("description"):
            problems.append(f"{location}.description must be a non-empty string")
        priority = profile.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool):
            problems.append(f"{location}.priority must be an integer")
        match = profile.get("match")
        if not isinstance(match, dict) or not isinstance(match.get("all"), list):
            problems.append(f"{location}.match.all must be a list")
            continue
        if profile.get("fallback"):
            fallbacks += 1
            if match["all"]:
                problems.append(f"{location} is a fallback and must not have conditions")
        for condition_index, condition in enumerate(match["all"]):
            problems.extend(
                _condition_problems(condition, f"{location}.match.all[{condition_index}]")
            )
        for name in profile.get("package_sets", []):
            if name not in package_sets:
                problems.append(f"{location} references unknown package set {name!r}")
        if not isinstance(profile.get("default_policy", "balanced"), str):
            problems.append(f"{location}.default_policy must be a string")
    if fallbacks > 1:
        problems.append("at most one fallback profile is allowed")
    return problems


def _condition_problems(condition: Any, location: str) -> list[str]:
    if not isinstance(condition, dict):
        return [f"{location} must be an object"]
    problems = []
    field = condition.get("field")
    if not isinstance(field, str) or not field or field.startswith("."):
        problems.append(f"{location}.field must be a dotted field name")
    operator = condition.get("op")
    if operator not in _OPERATORS:
        problems.append(f"{location}.op must be one of {sorted(_OPERATORS)}")
    if operator in {"in", "not_in"} and not isinstance(condition.get("value"), list):
        problems.append(f"{location}.value must be a list for {operator!r}")
    if operator in {"ge", "le"} and not isinstance(condition.get("value"), (int, float)):
        problems.append(f"{location}.value must be a number for {operator!r}")
    if operator not in {"exists"} and "value" not in condition:
        problems.append(f"{location}.value is required for {operator!r}")
    return problems


def _to_ruleset(document: dict[str, Any]) -> RuleSet:
    rules = []
    for profile in document["profiles"]:
        rules.append(
            Rule(
                id=profile["id"],
                description=profile["description"],
                priority=int(profile["priority"]),
                conditions=tuple(profile["match"]["all"]),
                package_sets=tuple(profile.get("package_sets") or ()),
                default_policy=profile.get("default_policy", "balanced"),
                notes=tuple(profile.get("notes") or ()),
                fallback=bool(profile.get("fallback")),
            )
        )
    return RuleSet(
        schema_version=document["schema_version"],
        revision=document["revision"],
        rules=tuple(rules),
        package_sets=dict(document["package_sets"]),
    )


def match_profile(profile: dict[str, Any], ruleset: RuleSet) -> dict[str, Any]:
    """Select the highest-priority matching profile deterministically."""
    evaluated: list[dict[str, Any]] = []
    matches: list[tuple[Rule, list[str]]] = []
    fallback: Rule | None = None

    for rule in ruleset.rules:
        if rule.fallback:
            fallback = rule
            continue
        matched, explanations = _evaluate_rule(profile, rule)
        evaluated.append(
            {
                "rule": rule.id,
                "matched": matched,
                "conditions": explanations,
            }
        )
        if matched:
            matches.append((rule, explanations))

    matches.sort(key=lambda entry: (-entry[0].priority, entry[0].id))
    if matches:
        selected, explanations = matches[0]
        used_fallback = False
    elif fallback is not None:
        selected, explanations, used_fallback = fallback, [], True
    else:
        raise ProfileError("no profile matched and the rule set has no fallback")

    return {
        "profile_id": selected.id,
        "description": selected.description,
        "priority": selected.priority,
        "fallback": used_fallback,
        "matched_conditions": explanations,
        "evaluated_rules": evaluated,
        "package_sets": list(selected.package_sets),
        "notes": list(selected.notes),
        "default_policy": selected.default_policy,
        "rules_revision": ruleset.revision,
    }


def _evaluate_rule(profile: dict[str, Any], rule: Rule) -> tuple[bool, list[str]]:
    explanations: list[str] = []
    for condition in rule.conditions:
        outcome, explanation = evaluate_condition(profile, condition)
        explanations.append(explanation)
        if not outcome:
            return False, explanations
    return True, explanations


def evaluate_condition(profile: dict[str, Any], condition: dict[str, Any]) -> tuple[bool, str]:
    field = condition["field"]
    operator = condition["op"]
    expected = condition.get("value")
    actual = _resolve(profile, field)
    label = f"{field} {operator}"

    if operator == "exists":
        outcome = actual is not _MISSING and actual is not None
        return outcome, f"{field} exists={outcome}"

    if actual is _MISSING:
        return False, f"{field} is not present"

    if operator == "eq":
        outcome = actual == expected
    elif operator == "ne":
        outcome = actual != expected
    elif operator in {"in", "not_in"}:
        if not isinstance(expected, list):
            return False, f"{label} has a non-list comparison value"
        outcome = actual in expected if operator == "in" else actual not in expected
    elif operator == "ge":
        outcome = _comparable(actual) and actual >= expected
    elif operator == "le":
        outcome = _comparable(actual) and actual <= expected
    else:  # pragma: no cover - validation rejects unknown operators
        return False, f"{label} is not a supported operator"
    return bool(outcome), f"{label} {expected!r} (actual {actual!r})"


def _comparable(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _resolve(profile: dict[str, Any], field: str) -> Any:
    current: Any = profile
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current
