"""Deterministic optimisation plans.

The optimizer never applies anything. It produces a validated plan in which
every decision states what would change, why, on what evidence, and how to undo
it. Applying the plan is the installer's (Phase 3) responsibility.
"""

from __future__ import annotations

import datetime as _dt
import json
from importlib import resources
from pathlib import Path
from typing import Any

from openqos.errors import OptimizationError
from openqos.profiles.rules import RuleSet, load_ruleset, match_profile

PLAN_SCHEMA_VERSION = "1.0.0"
POLICIES_SCHEMA_VERSION = "1.0.0"
DEFAULT_POLICY = "balanced"

_STATUSES = {"plan", "keep", "skip", "manual"}

_DRIVER_PACKAGE_SETS = {
    "i915": "intel-graphics",
    "xe": "intel-graphics",
    "amdgpu": "amd-graphics",
    "radeon": "amd-graphics",
    "nouveau": "nvidia-firmware",
}


def default_policies_path() -> Path:
    resource = resources.files("openqos.config").joinpath("optimization-policies.json")
    return Path(str(resource))


def load_policies(path: Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else default_policies_path()
    try:
        document: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise OptimizationError(f"cannot read policies at {source}: {error}") from error
    except json.JSONDecodeError as error:
        raise OptimizationError(f"{source} is not valid JSON: {error}") from error
    problems = validate_policies(document)
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        raise OptimizationError(f"{source} is not a valid policy file:\n{joined}")
    return document


def validate_policies(document: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(document, dict):
        return ["policy document must be a JSON object"]
    if document.get("schema_version") != POLICIES_SCHEMA_VERSION:
        problems.append(f"schema_version must be {POLICIES_SCHEMA_VERSION!r}")
    policies = document.get("policies")
    if not isinstance(policies, dict) or not policies:
        problems.append("policies must be a non-empty object")
        return problems
    for name, policy in policies.items():
        location = f"policies.{name}"
        if not isinstance(policy, dict):
            problems.append(f"{location} must be an object")
            continue
        cpu = policy.get("cpu")
        if not isinstance(cpu, dict):
            problems.append(f"{location}.cpu must be an object")
        else:
            for key in ("governor", "energy_performance_preference", "platform_profile"):
                if key in cpu and not isinstance(cpu[key], str):
                    problems.append(f"{location}.cpu.{key} must be a string")
        memory = policy.get("memory")
        if not isinstance(memory, dict) or not isinstance(memory.get("swap"), str):
            problems.append(f"{location}.memory.swap must be a string")
        else:
            percent = memory.get("zram_percent_of_ram")
            if not isinstance(percent, int) or not 0 < percent <= 200:
                problems.append(f"{location}.memory.zram_percent_of_ram must be 1..200")
        storage = policy.get("storage")
        if not isinstance(storage, dict) or not isinstance(storage.get("trim"), bool):
            problems.append(f"{location}.storage.trim must be a boolean")
        if not isinstance(policy.get("rationale", []), list):
            problems.append(f"{location}.rationale must be a list")
    return problems


def build_plan(
    profile: dict[str, Any],
    *,
    policy: str = DEFAULT_POLICY,
    ruleset: RuleSet | None = None,
    policies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a validated optimisation plan for ``profile`` under ``policy``."""
    if not isinstance(profile, dict) or "machine" not in profile:
        raise OptimizationError("a normalised hardware profile is required")
    ruleset = ruleset or load_ruleset()
    policies = policies or load_policies()
    if policy not in policies["policies"]:
        known = ", ".join(sorted(policies["policies"]))
        raise OptimizationError(f"unknown policy {policy!r}; known policies: {known}")

    selected = match_profile(profile, ruleset)
    policy_document = policies["policies"][policy]

    decisions: list[dict[str, Any]] = []
    decisions.extend(_cpu_decisions(profile, policy_document, policy))
    decisions.extend(_graphics_decisions(profile))
    decisions.extend(_package_decisions(profile, selected, ruleset))
    decisions.extend(_memory_decisions(profile, policy_document))
    decisions.extend(_storage_decisions(profile, policy_document))

    _ensure_unique_ids(decisions)
    notices = _notices(profile, selected)
    summary = _summary(decisions)
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at": _dt.datetime.now(tz=_dt.UTC).replace(microsecond=0).isoformat(),
        "policy": policy,
        "policy_description": policy_document.get("description"),
        "policy_revision": policies.get("revision"),
        "selected_profile": selected,
        "decisions": sorted(decisions, key=lambda decision: (decision["category"], decision["id"])),
        "notices": notices,
        "fallback": {
            "baseline_profile": "generic-x86-64",
            "baseline_policy": DEFAULT_POLICY,
            "applies_when": [
                "no profile rule matches the machine",
                "the plan fails validation",
                "the kernel or firmware rejects a runtime change",
            ],
            "description": (
                "Re-run the planner with the generic profile and balanced policy. "
                "Every decision records its inverse so the previous values can be restored."
            ),
        },
        "summary": summary,
    }


def _cpu_decisions(
    profile: dict[str, Any], policy_document: dict[str, Any], policy: str
) -> list[dict[str, Any]]:
    power = profile.get("power") or {}
    cpu_policy = policy_document.get("cpu") or {}
    decisions: list[dict[str, Any]] = []

    decisions.append(
        _setting_decision(
            decision_id="cpu-governor",
            category="cpu",
            title="CPU frequency governor",
            target="cpufreq.scaling_governor",
            desired=cpu_policy.get("governor"),
            current=power.get("governor"),
            available=power.get("governors") or [],
            rationale=(
                f"The {policy} policy selects the "
                f"{cpu_policy.get('governor')!r} governor."
            ),
            evidence=[
                f"power.governors={power.get('governors')}",
                f"power.governor={power.get('governor')!r}",
            ],
            rollback_action="write",
        )
    )
    decisions.append(
        _setting_decision(
            decision_id="cpu-energy-performance",
            category="power",
            title="Energy performance preference",
            target="cpufreq.energy_performance_preference",
            desired=cpu_policy.get("energy_performance_preference"),
            current=power.get("energy_performance_preference"),
            available=power.get("energy_performance_preferences") or [],
            rationale=(
                "EPP is the supported interface for trading energy against "
                f"performance; the {policy} policy uses "
                f"{cpu_policy.get('energy_performance_preference')!r}."
            ),
            evidence=[
                "power.energy_performance_preferences="
                f"{power.get('energy_performance_preferences')}",
            ],
            rollback_action="write",
            skip_reason="the CPU driver does not expose energy performance preferences",
        )
    )
    choices = power.get("platform_profile_choices") or []
    decisions.append(
        _setting_decision(
            decision_id="platform-profile",
            category="power",
            title="ACPI platform profile",
            target="platform_profile",
            desired=cpu_policy.get("platform_profile"),
            current=power.get("platform_profile"),
            available=choices,
            rationale=(
                "The firmware platform profile lets the vendor's embedded "
                f"controller implement the {policy} policy."
            ),
            evidence=["power.platform_profile_choices=" f"{choices}"],
            rollback_action="write",
            skip_reason="the firmware does not expose an ACPI platform profile",
        )
    )
    return decisions


def _setting_decision(
    *,
    decision_id: str,
    category: str,
    title: str,
    target: str,
    desired: Any,
    current: Any,
    available: list[Any] | None,
    rationale: str,
    evidence: list[str],
    rollback_action: str,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    if desired is None:
        return _decision(
            decision_id=decision_id,
            category=category,
            title=title,
            status="skip",
            target=target,
            value=None,
            current_value=current,
            rationale=skip_reason or "the policy does not define a value for this setting",
            evidence=evidence,
        )
    if available is not None:
        if not available:
            return _decision(
                decision_id=decision_id,
                category=category,
                title=title,
                status="skip",
                target=target,
                value=desired,
                current_value=current,
                rationale=skip_reason
                or f"{title} is not exposed by this hardware, so it cannot be set safely",
                evidence=evidence,
            )
        if desired not in available:
            return _decision(
                decision_id=decision_id,
                category=category,
                title=title,
                status="skip",
                target=target,
                value=desired,
                current_value=current,
                rationale=(
                    f"{desired!r} is not offered by this hardware; "
                    f"available values are {available}"
                ),
                evidence=evidence,
            )
    if current == desired:
        return _decision(
            decision_id=decision_id,
            category=category,
            title=title,
            status="keep",
            target=target,
            value=desired,
            current_value=current,
            rationale=f"{rationale} The system is already using this value.",
            evidence=evidence,
            rollback={"action": rollback_action, "target": target, "value": current},
        )
    return _decision(
        decision_id=decision_id,
        category=category,
        title=title,
        status="plan",
        target=target,
        value=desired,
        current_value=current,
        rationale=rationale,
        evidence=evidence,
        rollback={"action": rollback_action, "target": target, "value": current},
    )


def _graphics_decisions(profile: dict[str, Any]) -> list[dict[str, Any]]:
    graphics = profile.get("graphics") or {}
    adapters = graphics.get("adapters") or []
    if not adapters:
        return [
            _decision(
                decision_id="graphics-driver",
                category="graphics",
                title="Graphics driver",
                status="skip",
                target="graphics.driver",
                value=None,
                current_value=None,
                rationale="No PCI display device was detected, so no graphics decision is made.",
                evidence=["graphics.adapter_count=0"],
            )
        ]
    decisions = [
        _decision(
            decision_id="graphics-driver",
            category="graphics",
            title="Graphics driver and hybrid strategy",
            status="keep",
            target="graphics.driver",
            value=graphics.get("primary_driver"),
            current_value=graphics.get("primary_driver"),
            rationale=(
                "The kernel already binds "
                f"{', '.join(graphics.get('drivers') or []) or 'no driver'}. "
                + (
                    "Two vendors are present: the integrated adapter stays the "
                    "primary render device and the discrete adapter is used on demand."
                    if graphics.get("hybrid")
                    else "No hybrid switching is required."
                )
            ),
            evidence=[
                f"graphics.vendor_ids={graphics.get('vendor_ids')}",
                f"graphics.drivers={graphics.get('drivers')}",
            ],
        )
    ]
    if graphics.get("requires_third_party_driver"):
        decisions.append(
            _decision(
                decision_id="graphics-proprietary-driver",
                category="graphics",
                title="Proprietary NVIDIA driver",
                status="manual",
                target="graphics.proprietary_driver",
                value="nvidia",
                current_value="nvidia",
                rationale=(
                    "The proprietary driver is not redistributable by OpenQOS and is "
                    "not installed automatically. Installing it requires enabling a "
                    "third-party repository and an explicit user decision."
                ),
                evidence=["graphics.drivers contains 'nvidia'"],
                rollback=None,
            )
        )
    return decisions


def _package_decisions(
    profile: dict[str, Any], selected: dict[str, Any], ruleset: RuleSet
) -> list[dict[str, Any]]:
    graphics = profile.get("graphics") or {}
    network = profile.get("network") or {}
    cpu = profile.get("cpu") or {}
    audio = profile.get("audio") or {}
    machine = profile.get("machine") or {}

    wanted: dict[str, str] = {}
    for driver in graphics.get("drivers") or []:
        package_set = _DRIVER_PACKAGE_SETS.get(driver)
        if package_set:
            wanted[package_set] = f"the {driver} graphics driver is bound"
    if network.get("wireless") and any(
        driver.startswith("iwlwifi") for driver in network.get("drivers") or []
    ):
        wanted["intel-wifi"] = "an Intel wireless adapter is present"
    if (
        cpu.get("vendor") == "intel"
        and machine.get("form_factor") == "laptop"
        and int(audio.get("card_count") or 0) > 0
    ):
        wanted["sof-audio"] = "an Intel laptop with an HDA/SOF audio device"
    for name in selected.get("package_sets") or []:
        wanted.setdefault(name, f"the {selected['profile_id']} profile requires it")

    decisions = []
    for name in sorted(wanted):
        entry = ruleset.package_sets.get(name)
        if entry is None:
            continue
        decisions.append(
            _decision(
                decision_id=f"packages-{name}",
                category="packages",
                title=f"Package set: {name}",
                status="plan",
                target=f"packages.{name}",
                value=entry["packages"],
                current_value=None,
                rationale=f"{entry['reason']} Needed because {wanted[name]}.",
                evidence=[f"profile matched package set {name}"],
                packages=list(entry["packages"]),
                source=entry["source"],
                rollback={"action": "remove_packages", "target": name, "value": entry["packages"]},
            )
        )
    return decisions


def _memory_decisions(
    profile: dict[str, Any], policy_document: dict[str, Any]
) -> list[dict[str, Any]]:
    memory = profile.get("memory") or {}
    policy_memory = policy_document.get("memory") or {}
    total_mib = int(memory.get("total_mib") or 0)
    if policy_memory.get("swap") != "zram":
        return [
            _decision(
                decision_id="memory-swap",
                category="memory",
                title="Swap strategy",
                status="skip",
                target="swap",
                value=policy_memory.get("swap"),
                current_value="disk swap" if memory.get("has_swap") else "none",
                rationale="The selected policy does not use compressed swap.",
                evidence=[f"memory.total_mib={total_mib}"],
            )
        ]
    if total_mib and total_mib < 1024:
        return [
            _decision(
                decision_id="memory-swap",
                category="memory",
                title="Swap strategy",
                status="skip",
                target="swap",
                value="zram",
                current_value="disk swap" if memory.get("has_swap") else "none",
                rationale="Less than 1 GiB of RAM was detected; zram is not worthwhile.",
                evidence=[f"memory.total_mib={total_mib}"],
            )
        ]
    percent = int(policy_memory.get("zram_percent_of_ram") or 50)
    return [
        _decision(
            decision_id="memory-swap",
            category="memory",
            title="Compressed RAM swap",
            status="plan",
            target="swap.zram",
            value={"device": "zram0", "percent_of_ram": percent},
            current_value="disk swap" if memory.get("has_swap") else "none",
            rationale=(
                f"zram provides {percent}% of RAM as compressed swap without "
                "touching the partition layout, and it is reversible at runtime."
            ),
            evidence=[f"memory.total_mib={total_mib}", f"memory.tier={memory.get('tier')}"],
            packages=["zram-generator"],
            rollback={"action": "remove_config", "target": "zram", "value": None},
            notes=[
                "Fedora ships the writeback/priority defaults in zram-generator-defaults."
            ],
        )
    ]


def _storage_decisions(
    profile: dict[str, Any], policy_document: dict[str, Any]
) -> list[dict[str, Any]]:
    storage = profile.get("storage") or {}
    policy_storage = policy_document.get("storage") or {}
    primary = storage.get("primary")
    if not policy_storage.get("trim"):
        return []
    if primary == "ssd":
        return [
            _decision(
                decision_id="storage-trim",
                category="storage",
                title="Scheduled TRIM",
                status="plan",
                target="services.fstrim.timer",
                value="enabled",
                current_value=None,
                rationale=(
                    "TRIM keeps write performance predictable on SSDs/NVMe and is "
                    "scheduled weekly so it does not compete with interactive use."
                ),
                evidence=[
                    f"storage.primary={primary}",
                    f"storage.transports={storage.get('transports')}",
                ],
                packages=[],
                rollback={
                    "action": "disable_service",
                    "target": "fstrim.timer",
                    "value": "enabled",
                },
            )
        ]
    return [
        _decision(
            decision_id="storage-trim",
            category="storage",
            title="Scheduled TRIM",
            status="skip",
            target="services.fstrim.timer",
            value=None,
            current_value=None,
            rationale=(
                "No solid-state device was identified as primary storage; "
                "fstrim on rotational media provides no benefit."
            ),
            evidence=[f"storage.primary={primary}"],
        )
    ]


def _notices(profile: dict[str, Any], selected: dict[str, Any]) -> list[str]:
    notices: list[str] = []
    machine = profile.get("machine") or {}
    if selected.get("fallback"):
        notices.append("No specific profile matched; the generic baseline is in use.")
    if machine.get("is_virtual_machine"):
        notices.append("This is a virtual machine; hardware-specific tuning is limited.")
    if (machine.get("firmware") or {}).get("secure_boot") == "disabled":
        notices.append("Secure Boot is disabled. OpenQOS does not change firmware settings.")
    unavailable = profile.get("unavailable") or []
    if unavailable:
        notices.append(
            "Some collectors could not read data: " + ", ".join(unavailable) + "."
        )
    if not (profile.get("graphics") or {}).get("adapter_count"):
        notices.append("No graphics adapter was detected; no graphics packages are planned.")
    return notices


def _summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {status: 0 for status in sorted(_STATUSES)}
    packages: set[str] = set()
    for decision in decisions:
        counts[decision["status"]] = counts.get(decision["status"], 0) + 1
        packages.update(decision.get("packages") or [])
    return {
        "total": len(decisions),
        "by_status": counts,
        "packages": sorted(packages),
        "all_reversible": all(
            decision["reversible"] for decision in decisions if decision["status"] == "plan"
        ),
    }


def _decision(
    *,
    decision_id: str,
    category: str,
    title: str,
    status: str,
    target: str,
    value: Any,
    current_value: Any,
    rationale: str,
    evidence: list[str],
    packages: list[str] | None = None,
    source: str = "fedora",
    rollback: dict[str, Any] | None = None,
    notes: list[str] | None = None,
    apply_stage: str = "runtime",
) -> dict[str, Any]:
    if status not in _STATUSES:
        raise OptimizationError(f"invalid decision status {status!r}")
    if not rationale:
        raise OptimizationError(f"decision {decision_id!r} has no rationale")
    return {
        "id": decision_id,
        "category": category,
        "title": title,
        "status": status,
        "target": target,
        "value": value,
        "current_value": current_value,
        "already_satisfied": status == "keep",
        "rationale": rationale,
        "evidence": list(evidence),
        "risk": "low" if status in {"plan", "keep"} else "medium",
        "reversible": rollback is not None or status != "plan",
        "rollback": rollback,
        "apply_stage": apply_stage,
        "packages": list(packages or []),
        "source": source,
        "notes": list(notes or []),
    }


def _ensure_unique_ids(decisions: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for decision in decisions:
        if decision["id"] in seen:
            raise OptimizationError(f"duplicate decision id {decision['id']!r}")
        seen.add(decision["id"])


def render_plan(plan: dict[str, Any]) -> str:
    """Render a plan as human readable text."""
    selected = plan["selected_profile"]
    lines = [
        f"OpenQOS optimisation plan (policy: {plan['policy']})",
        f"  profile     : {selected['profile_id']} "
        f"({'fallback' if selected['fallback'] else 'matched'}, "
        f"priority {selected['priority']})",
        f"  description : {selected['description']}",
        f"  rules       : revision {selected['rules_revision']}",
        "",
    ]
    if selected["matched_conditions"]:
        lines.append("matched conditions:")
        lines.extend(f"  - {condition}" for condition in selected["matched_conditions"])
        lines.append("")

    for decision in plan["decisions"]:
        marker = {
            "plan": "PLAN",
            "keep": "KEEP",
            "skip": "SKIP",
            "manual": "MANUAL",
        }[decision["status"]]
        lines.append(f"[{marker:6}] {decision['title']} ({decision['id']})")
        lines.append(f"         target : {decision['target']} -> {decision['value']!r}")
        if decision["current_value"] is not None:
            lines.append(f"         current: {decision['current_value']!r}")
        lines.append(f"         why    : {decision['rationale']}")
        if decision["packages"]:
            lines.append(f"         packages: {', '.join(decision['packages'])}")
        if decision["rollback"]:
            lines.append(f"         rollback: {decision['rollback']['action']} "
                         f"{decision['rollback']['target']}")
        lines.append("")

    if plan["notices"]:
        lines.append("notices:")
        lines.extend(f"  - {notice}" for notice in plan["notices"])
        lines.append("")

    summary = plan["summary"]
    counts = ", ".join(f"{status}={count}" for status, count in summary["by_status"].items())
    lines.append(f"summary: {summary['total']} decisions ({counts})")
    lines.append(f"packages: {', '.join(summary['packages']) or 'none'}")
    return "\n".join(lines) + "\n"
